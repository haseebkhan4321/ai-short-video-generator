"""Up-front budget approval: authorize a whole video's spend once.

The interesting parts are the accounting (budget against committed spend, not spend
already recorded) and that pre-authorizing is a separate, stronger permission than
approving one visible step.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.permissions import PRODUCER_ROLE, Perm
from apps.accounts.repositories import RoleRepository
from apps.accounts.tests.factories import (
    VIEWER_ROLE,
    add_member,
    make_account,
    make_role,
    make_template,
    make_user,
    make_video,
)
from apps.videos.models import Provider, StepStatus, StepType
from apps.videos.repositories import StepRepository, VideoRepository
from apps.videos.services.cost_estimator import CostEstimator
from apps.videos.services.currency import pkr_to_usd, usd_to_pkr
from apps.videos.services.pipeline import (
    BudgetExceededError,
    PipelineError,
    PipelineService,
)


class ProjectionTests(TestCase):
    @override_settings(TARGET_MINUTES_PER_PART=6, IMAGES_PER_PART=4)
    def test_parts_follow_the_target_length(self):
        self.assertEqual(CostEstimator.expected_parts(6), 1)
        self.assertEqual(CostEstimator.expected_parts(24), 4)
        self.assertEqual(CostEstimator.expected_parts(90), 15)

    @override_settings(TARGET_MINUTES_PER_PART=6)
    def test_a_very_short_video_still_has_one_part(self):
        self.assertEqual(CostEstimator.expected_parts(1), 1)

    @override_settings(TARGET_MINUTES_PER_PART=6, IMAGES_PER_PART=4)
    def test_the_projection_breaks_the_cost_down(self):
        projection = CostEstimator.estimate_video(24)

        self.assertEqual(projection["parts"], 4)
        self.assertEqual(projection["images"], 16)
        self.assertEqual(projection["images_per_part"], 4)
        self.assertEqual(
            projection["total_usd"],
            projection["script_usd"] + projection["images_usd"],
        )
        # Images dominate: everything but the script and images is local and free.
        self.assertGreater(projection["images_usd"], projection["script_usd"])

    @override_settings(TARGET_MINUTES_PER_PART=6, IMAGES_PER_PART=4)
    def test_it_matches_what_the_per_step_estimates_would_add_up_to(self):
        """A projection that disagreed with the steps it authorizes would be worse
        than no projection."""
        projection = CostEstimator.estimate_video(24)
        per_part = CostEstimator.estimate_images(4)

        self.assertEqual(projection["images_usd"], CostEstimator.estimate_images(16))
        self.assertEqual(projection["images_usd"], per_part * 4)


class CurrencyRoundTripTests(TestCase):
    @override_settings(USD_TO_PKR=280)
    def test_pkr_converts_back_to_usd(self):
        self.assertEqual(pkr_to_usd(280), Decimal("1.0000"))
        self.assertEqual(usd_to_pkr(pkr_to_usd(Decimal("560"))), Decimal("560.00"))

    @override_settings(USD_TO_PKR=280)
    def test_blank_is_zero_rather_than_an_error(self):
        self.assertEqual(pkr_to_usd(""), Decimal("0.0000"))
        self.assertEqual(pkr_to_usd(None), Decimal("0.0000"))


class AccountingTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.script = self.video.steps.get(step_type=StepType.SCRIPT)

    def test_no_approval_means_no_headroom(self):
        self.assertIsNone(PipelineService.budget_headroom(self.video))

    def test_committed_counts_queued_estimates_not_just_money_spent(self):
        """Budgeting on spend alone would authorize the same headroom once per step,
        because total_cost_usd stays put until a step finishes."""
        StepRepository.update(self.script, status=StepStatus.APPROVED)

        committed = PipelineService.budget_committed(self.video)

        self.assertEqual(committed, Decimal(self.script.estimated_cost_usd))
        self.assertEqual(self.video.total_cost_usd, Decimal("0"))

    def test_committed_counts_running_steps_too(self):
        StepRepository.update(self.script, status=StepStatus.RUNNING)
        self.assertEqual(
            PipelineService.budget_committed(self.video),
            Decimal(self.script.estimated_cost_usd),
        )

    def test_a_finished_step_is_counted_once_as_actual_spend(self):
        StepRepository.update(
            self.script, status=StepStatus.COMPLETED, actual_cost_usd=Decimal("0.5")
        )
        VideoRepository.update(self.video, total_cost_usd=Decimal("0.5"))
        self.video.refresh_from_db()

        self.assertEqual(PipelineService.budget_committed(self.video), Decimal("0.5"))

    def test_pending_steps_are_not_committed(self):
        self.assertEqual(PipelineService.budget_committed(self.video), Decimal("0"))


class ApproveBudgetTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.script = self.video.steps.get(step_type=StepType.SCRIPT)

    def _approve(self, amount, **kwargs):
        with mock.patch.object(PipelineService, "enqueue") as enqueue:
            released = PipelineService.approve_budget(
                self.video, amount, actor=self.owner, **kwargs
            )
        self.video.refresh_from_db()
        return released, enqueue

    def test_it_records_who_authorized_what(self):
        self._approve(Decimal("5"))

        self.assertEqual(self.video.budget_approved_usd, Decimal("5"))
        self.assertEqual(self.video.budget_approved_by_id, self.owner.pk)
        self.assertIsNotNone(self.video.budget_approved_at)
        self.assertTrue(self.video.has_budget_approval)

    def test_it_releases_and_queues_the_pending_script_step(self):
        released, enqueue = self._approve(Decimal("5"))

        self.assertEqual(released, [self.script.pk])
        enqueue.assert_called_once_with([self.script.pk])
        self.script.refresh_from_db()
        self.assertEqual(self.script.status, StepStatus.APPROVED)
        self.assertEqual(self.script.approved_by_id, self.owner.pk)

    def test_headroom_is_what_is_left_after_the_release(self):
        self._approve(Decimal("5"))

        self.assertEqual(
            PipelineService.budget_headroom(self.video),
            Decimal("5") - Decimal(self.script.estimated_cost_usd),
        )

    def test_it_stops_at_the_first_step_that_does_not_fit(self):
        """Reordering parts to squeeze under a budget would be a surprising thing to
        do unprompted."""
        estimate = Decimal("1")
        for _ in range(3):
            StepRepository.create(
                video=self.video,
                step_type=StepType.IMAGES,
                provider=Provider.OPENAI,
                status=StepStatus.PENDING_APPROVAL,
                estimated_cost_usd=estimate,
            )
        script_cost = Decimal(self.script.estimated_cost_usd)

        # Room for the script and two of the three image steps.
        released, _ = self._approve(script_cost + Decimal("2"))

        self.assertEqual(len(released), 3)  # script + 2 images
        still_pending = StepRepository.for_video(self.video.pk).filter(
            status=StepStatus.PENDING_APPROVAL
        )
        self.assertEqual(still_pending.count(), 1)

    def test_it_refuses_a_zero_or_negative_amount(self):
        for amount in (Decimal("0"), Decimal("-3")):
            with self.subTest(amount=amount):
                with self.assertRaises(PipelineError):
                    PipelineService.approve_budget(self.video, amount, actor=self.owner)

    def test_the_per_video_cap_still_applies(self):
        over = PipelineService.budget_cap() + Decimal("1")

        with self.assertRaises(BudgetExceededError):
            PipelineService.approve_budget(self.video, over, actor=self.owner)

        self.video.refresh_from_db()
        self.assertFalse(self.video.has_budget_approval)

    def test_force_authorizes_past_the_cap(self):
        over = PipelineService.budget_cap() + Decimal("1")

        self._approve(over, force=True)

        self.assertEqual(self.video.budget_approved_usd, over)

    def test_free_steps_are_released_too(self):
        """An up-front approval means 'run this video'. Narration waits for a click
        because it is slow, not because it costs anything."""
        narration = StepRepository.create(
            video=self.video,
            step_type=StepType.NARRATION,
            provider=Provider.LOCAL,
            status=StepStatus.PENDING_APPROVAL,
            estimated_cost_usd=Decimal("0"),
        )

        released, _ = self._approve(Decimal("5"))

        self.assertIn(narration.pk, released)

    def test_a_dead_broker_leaves_the_steps_approved(self):
        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            released = PipelineService.approve_budget(
                self.video, Decimal("5"), actor=self.owner
            )

        self.assertEqual(released, [self.script.pk])
        self.script.refresh_from_db()
        self.assertEqual(self.script.status, StepStatus.APPROVED)


class RevokeBudgetTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        with mock.patch.object(PipelineService, "enqueue"):
            PipelineService.approve_budget(self.video, Decimal("5"), actor=self.owner)
        self.video.refresh_from_db()

    def test_it_clears_the_approval(self):
        PipelineService.revoke_budget(self.video)
        self.video.refresh_from_db()

        self.assertFalse(self.video.has_budget_approval)
        self.assertIsNone(self.video.budget_approved_by_id)
        self.assertIsNone(PipelineService.budget_headroom(self.video))

    def test_already_queued_work_is_left_alone(self):
        """A task cannot be unsent, and pretending otherwise would be worse than
        saying so."""
        script = self.video.steps.get(step_type=StepType.SCRIPT)
        self.assertEqual(script.status, StepStatus.APPROVED)

        PipelineService.revoke_budget(self.video)

        script.refresh_from_db()
        self.assertEqual(script.status, StepStatus.APPROVED)

    def test_new_steps_go_back_to_waiting_for_approval(self):
        PipelineService.revoke_budget(self.video)
        self.video.refresh_from_db()
        StepRepository.create(
            video=self.video,
            step_type=StepType.IMAGES,
            provider=Provider.OPENAI,
            status=StepStatus.PENDING_APPROVAL,
            estimated_cost_usd=Decimal("1"),
        )

        self.assertEqual(PipelineService.release_pending_steps(self.video), [])


class SplitReleasesTests(TestCase):
    """After the split, image and narration steps should start on their own when the
    video was pre-authorized."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.split = StepRepository.create(
            video=self.video,
            step_type=StepType.SPLIT,
            provider=Provider.LOCAL,
            status=StepStatus.COMPLETED,
            estimated_cost_usd=Decimal("0"),
        )
        self.video.chapters.create(
            chapter_number=1, title="One", body="words here", word_count=2
        )

    def _advance_split(self):
        with mock.patch.object(PipelineService, "enqueue") as enqueue:
            PipelineService._advance(self.split)
        return enqueue

    def test_without_an_approval_the_image_step_waits(self):
        self._advance_split()

        images = StepRepository.for_video(self.video.pk).get(step_type=StepType.IMAGES)
        self.assertEqual(images.status, StepStatus.PENDING_APPROVAL)

    def test_with_an_approval_the_image_step_starts(self):
        VideoRepository.update(
            self.video,
            budget_approved_usd=Decimal("5"),
            budget_approved_by=self.owner,
        )
        self.video.refresh_from_db()

        self._advance_split()

        images = StepRepository.for_video(self.video.pk).get(step_type=StepType.IMAGES)
        self.assertEqual(images.status, StepStatus.APPROVED)
        self.assertEqual(images.approved_by_id, self.owner.pk)


class BudgetPermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)

    def test_a_producer_cannot_pre_authorize_a_whole_video(self):
        """Approving one step whose cost is on screen and pre-authorizing everything
        are different levels of trust."""
        producer = make_user("producer@example.com")
        add_member(self.account, producer, PRODUCER_ROLE)
        self.client.force_login(producer)

        response = self.client.post(
            reverse("videos:budget_approve", args=[self.video.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.video.refresh_from_db()
        self.assertFalse(self.video.has_budget_approval)

    def test_the_default_producer_role_does_not_hold_it(self):
        role = RoleRepository.get_by_name(self.account, PRODUCER_ROLE)
        self.assertNotIn(Perm.STEP_APPROVE_BUDGET, role.codenames)

    def test_the_owner_role_does(self):
        role = RoleRepository.get_by_name(self.account, "Owner")
        self.assertIn(Perm.STEP_APPROVE_BUDGET, role.codenames)

    def test_a_viewer_sees_no_approve_pipeline_form(self):
        viewer = make_user("viewer@example.com")
        add_member(self.account, viewer, VIEWER_ROLE)
        self.client.force_login(viewer)

        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertNotIn("Approve the pipeline", html)

    def test_a_role_with_the_permission_can_use_it(self):
        role = make_role(
            self.account,
            "Budgeter",
            [Perm.VIDEO_VIEW, Perm.TEMPLATE_VIEW, Perm.STEP_APPROVE_BUDGET],
        )
        user = make_user("budgeter@example.com")
        add_member(self.account, user, VIEWER_ROLE)
        membership = user.memberships.get(account=self.account)
        membership.role = role
        membership.save()
        self.client.force_login(user)

        with mock.patch.object(PipelineService, "enqueue"):
            response = self.client.post(
                reverse("videos:budget_approve", args=[self.video.pk]), follow=True
            )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertTrue(self.video.has_budget_approval)


class BudgetViewTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.client.force_login(self.owner)

    def test_a_blank_amount_authorizes_the_projected_total(self):
        projection = PipelineService.project_cost(self.video)

        with mock.patch.object(PipelineService, "enqueue"):
            self.client.post(reverse("videos:budget_approve", args=[self.video.pk]))

        self.video.refresh_from_db()
        self.assertEqual(self.video.budget_approved_usd, projection["total_usd"])

    @override_settings(USD_TO_PKR=280)
    def test_a_typed_amount_is_read_as_rupees(self):
        with mock.patch.object(PipelineService, "enqueue"):
            self.client.post(
                reverse("videos:budget_approve", args=[self.video.pk]),
                {"amount_pkr": "1,120"},
            )

        self.video.refresh_from_db()
        self.assertEqual(self.video.budget_approved_usd, Decimal("4.0000"))

    def test_nonsense_in_the_amount_falls_back_to_the_projection(self):
        projection = PipelineService.project_cost(self.video)

        with mock.patch.object(PipelineService, "enqueue"):
            self.client.post(
                reverse("videos:budget_approve", args=[self.video.pk]),
                {"amount_pkr": "not a number"},
            )

        self.video.refresh_from_db()
        self.assertEqual(self.video.budget_approved_usd, projection["total_usd"])

    def test_it_is_post_only(self):
        self.client.get(reverse("videos:budget_approve", args=[self.video.pk]))

        self.video.refresh_from_db()
        self.assertFalse(self.video.has_budget_approval)

    def test_the_page_shows_the_projection_before_approval(self):
        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertIn("Approve the pipeline", html)
        self.assertIn("Projected total", html)

    def test_the_page_shows_the_approval_afterwards(self):
        with mock.patch.object(PipelineService, "enqueue"):
            PipelineService.approve_budget(
                self.video, Decimal("5"), actor=self.owner
            )

        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertIn("Pipeline approved", html)
        self.assertIn("Withdraw approval", html)
        self.assertNotIn("Approve the pipeline", html)

    def test_revoking_from_the_page_works(self):
        with mock.patch.object(PipelineService, "enqueue"):
            PipelineService.approve_budget(self.video, Decimal("5"), actor=self.owner)

        self.client.post(reverse("videos:budget_revoke", args=[self.video.pk]))

        self.video.refresh_from_db()
        self.assertFalse(self.video.has_budget_approval)

    def test_a_foreign_video_is_a_404(self):
        outsider = make_user("outsider@example.com")
        other = make_video(
            make_template(make_account(outsider, "Theirs")), actor=outsider
        )

        response = self.client.post(
            reverse("videos:budget_approve", args=[other.pk])
        )

        self.assertEqual(response.status_code, 404)
