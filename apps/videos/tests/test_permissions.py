"""Which role may do what, and the two spend gates in particular."""
from decimal import Decimal
from unittest import mock

from django.test import TestCase
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
from apps.videos.models import StepStatus, StepType
from apps.videos.services.pipeline import BudgetExceededError, PipelineService


def _no_background(step, *args, **kwargs):
    """Approve without spawning the executor thread, so tests stay deterministic."""
    return step


class TemplatePermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.template = make_template(self.account)
        self.viewer = make_user("viewer@example.com")
        add_member(self.account, self.viewer, VIEWER_ROLE)

    def test_a_viewer_can_read_but_not_manage(self):
        self.client.force_login(self.viewer)

        self.assertEqual(self.client.get(reverse("templates:list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("templates:detail", args=[self.template.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("templates:create")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("templates:edit", args=[self.template.pk])).status_code,
            403,
        )

    def test_a_viewer_cannot_delete_a_template(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("templates:delete", args=[self.template.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.account.content_templates.filter(pk=self.template.pk).exists())

    def test_a_viewer_sees_no_manage_links(self):
        self.client.force_login(self.viewer)

        html = self.client.get(reverse("templates:list")).content.decode()

        self.assertNotIn("New template", html)
        self.assertNotIn(reverse("templates:create"), html)


class VideoPermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.template = make_template(self.account)
        self.video = make_video(self.template, actor=self.owner)
        self.script_step = self.video.steps.get(step_type=StepType.SCRIPT)

        self.viewer = make_user("viewer@example.com")
        add_member(self.account, self.viewer, VIEWER_ROLE)

    def test_a_viewer_cannot_create_or_delete(self):
        self.client.force_login(self.viewer)

        self.assertEqual(self.client.get(reverse("videos:create")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("videos:delete", args=[self.video.pk])).status_code,
            403,
        )

    def test_a_viewer_cannot_approve_a_paid_step(self):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.script_step.refresh_from_db()
        self.assertEqual(self.script_step.status, StepStatus.PENDING_APPROVAL)

    def test_a_viewer_cannot_reject_or_regenerate(self):
        self.client.force_login(self.viewer)

        for name in ("step_reject", "step_regenerate"):
            with self.subTest(view=name):
                response = self.client.post(
                    reverse(f"videos:{name}", args=[self.video.pk, self.script_step.pk])
                )
                self.assertEqual(response.status_code, 403)

    def test_opening_the_detail_page_as_a_viewer_does_not_run_the_pipeline(self):
        """``video_detail`` mutates state and can start a thread, so a read-only role
        must not trigger it just by looking at the page."""
        self.client.force_login(self.viewer)

        with mock.patch.object(PipelineService, "resume_waiting_steps") as resume, \
                mock.patch.object(PipelineService, "ensure_asset_steps") as ensure, \
                mock.patch.object(PipelineService, "backfill_part_videos") as backfill:
            response = self.client.get(reverse("videos:detail", args=[self.video.pk]))

        self.assertEqual(response.status_code, 200)
        resume.assert_not_called()
        ensure.assert_not_called()
        backfill.assert_not_called()

    def test_opening_the_detail_page_as_a_producer_does_run_the_pipeline(self):
        producer = make_user("producer@example.com")
        add_member(self.account, producer, PRODUCER_ROLE)
        self.client.force_login(producer)

        with mock.patch.object(PipelineService, "resume_waiting_steps") as resume:
            self.client.get(reverse("videos:detail", args=[self.video.pk]))

        resume.assert_called_once()

    def test_a_viewer_sees_no_approve_buttons(self):
        self.client.force_login(self.viewer)

        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertNotIn(
            reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk]),
            html,
        )
        self.assertIn("Awaiting approval", html)


class SpendGateTests(TestCase):
    """``step.approve_paid`` and ``step.override_budget`` are deliberately separate."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.template = make_template(self.account)
        self.video = make_video(self.template, actor=self.owner)
        self.script_step = self.video.steps.get(step_type=StepType.SCRIPT)

        self.producer = make_user("producer@example.com")
        add_member(self.account, self.producer, PRODUCER_ROLE)

    def test_a_producer_may_approve_a_paid_step(self):
        self.client.force_login(self.producer)

        with mock.patch.object(
            PipelineService, "approve_step_background", side_effect=_no_background
        ) as approve:
            response = self.client.post(
                reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk])
            )

        self.assertEqual(response.status_code, 302)
        approve.assert_called_once()
        self.assertEqual(approve.call_args.kwargs["actor"], self.producer)

    def test_a_producer_cannot_force_past_the_budget_cap(self):
        """``force=1`` in POST data is a request, not a fact."""
        self.client.force_login(self.producer)

        with mock.patch.object(
            PipelineService, "approve_step_background", side_effect=_no_background
        ) as approve:
            self.client.post(
                reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk]),
                {"force": "1"},
            )

        self.assertIs(approve.call_args.kwargs["force"], False)

    def test_an_owner_can_force_past_the_budget_cap(self):
        self.client.force_login(self.owner)

        with mock.patch.object(
            PipelineService, "approve_step_background", side_effect=_no_background
        ) as approve:
            self.client.post(
                reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk]),
                {"force": "1"},
            )

        self.assertIs(approve.call_args.kwargs["force"], True)

    def test_the_cap_still_bites_a_producer_who_sends_force(self):
        """End to end: without the override permission the projected spend is
        refused even with ``force=1``, and the step stays pending."""
        self.video.total_cost_usd = PipelineService.budget_cap()
        self.video.save()
        self.client.force_login(self.producer)

        response = self.client.post(
            reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk]),
            {"force": "1"},
            follow=True,
        )

        self.script_step.refresh_from_db()
        self.assertEqual(self.script_step.status, StepStatus.PENDING_APPROVAL)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("budget" in m.lower() for m in messages), messages)
        self.assertTrue(
            any("Ask someone who can override" in m for m in messages), messages
        )

    def test_the_override_button_is_hidden_from_a_producer(self):
        self.client.force_login(self.producer)

        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertIn("Approve</button>", html)
        self.assertNotIn("Approve anyway", html)

    def test_the_override_button_is_shown_to_an_owner(self):
        self.client.force_login(self.owner)

        html = self.client.get(
            reverse("videos:detail", args=[self.video.pk])
        ).content.decode()

        self.assertIn("Approve anyway", html)

    def test_a_free_only_role_cannot_approve_a_paid_step(self):
        free_hand = make_user("free@example.com")
        role = make_role(
            self.account,
            "Narrator",
            [Perm.VIDEO_VIEW, Perm.TEMPLATE_VIEW, Perm.STEP_RUN_FREE],
        )
        add_member(self.account, free_hand, VIEWER_ROLE)
        membership = free_hand.memberships.get(account=self.account)
        membership.role = role
        membership.save()
        self.client.force_login(free_hand)

        response = self.client.post(
            reverse("videos:step_approve", args=[self.video.pk, self.script_step.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_a_free_only_role_may_batch_approve_free_steps(self):
        """Narration is local and free, so ``step.run_free`` is enough for it."""
        free_hand = make_user("free@example.com")
        role = make_role(
            self.account,
            "Narrator",
            [Perm.VIDEO_VIEW, Perm.TEMPLATE_VIEW, Perm.STEP_RUN_FREE],
        )
        add_member(self.account, free_hand, VIEWER_ROLE)
        membership = free_hand.memberships.get(account=self.account)
        membership.role = role
        membership.save()
        self.client.force_login(free_hand)

        with mock.patch.object(
            PipelineService, "batch_approve_background", return_value=[]
        ) as batch:
            response = self.client.post(
                reverse("videos:batch_approve", args=[self.video.pk]),
                {"step_type": StepType.NARRATION},
            )

        self.assertEqual(response.status_code, 302)
        batch.assert_called_once()

    def test_batch_approving_a_paid_type_needs_the_paid_permission(self):
        """A pending paid step in the batch makes the whole batch a spend."""
        RoleRepository.update(
            RoleRepository.get_by_name(self.account, PRODUCER_ROLE),
            permissions=[Perm.VIDEO_VIEW, Perm.TEMPLATE_VIEW, Perm.STEP_RUN_FREE],
        )
        self.client.force_login(self.producer)

        response = self.client.post(
            reverse("videos:batch_approve", args=[self.video.pk]),
            {"step_type": StepType.SCRIPT},
        )

        self.assertEqual(response.status_code, 403)


class SpendAuditTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.script_step = self.video.steps.get(step_type=StepType.SCRIPT)

    def test_the_creator_is_recorded_on_the_video(self):
        self.assertEqual(self.video.created_by_id, self.owner.pk)

    def test_the_approver_is_recorded_on_the_step(self):
        with mock.patch.object(PipelineService, "enqueue"):
            PipelineService.approve_step_background(self.script_step, actor=self.owner)

        self.script_step.refresh_from_db()
        self.assertEqual(self.script_step.approved_by_id, self.owner.pk)
        self.assertEqual(self.script_step.status, StepStatus.APPROVED)

    def test_a_retry_clears_the_previous_approver(self):
        with mock.patch.object(PipelineService, "enqueue"):
            PipelineService.approve_step_background(self.script_step, actor=self.owner)
        self.script_step.refresh_from_db()
        self.script_step.status = StepStatus.FAILED
        self.script_step.save()

        PipelineService.retry_step(self.script_step)

        self.script_step.refresh_from_db()
        self.assertIsNone(self.script_step.approved_by_id)

    def test_the_budget_cap_is_enforced_in_the_service_itself(self):
        self.video.total_cost_usd = PipelineService.budget_cap() + Decimal("1")
        self.video.save()
        self.script_step.refresh_from_db()

        with self.assertRaises(BudgetExceededError):
            PipelineService.approve_step_background(
                self.script_step, force=False, actor=self.owner
            )
