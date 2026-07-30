"""The task queue: dispatch, the claim guard, and what happens when the broker is down.

The broker is never contacted here. ``PipelineService.enqueue`` is the single seam
where work leaves a request, so mocking it is enough to test everything around it, and
the tasks themselves are called directly.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import (
    make_account,
    make_template,
    make_user,
    make_video,
)
from apps.videos.models import Provider, StepStatus, StepType, VideoStatus
from apps.videos.repositories import StepRepository, VideoRepository
from apps.videos.services.pipeline import (
    PipelineService,
    QueueUnavailableError,
    StepResult,
    register_executor,
)
from apps.videos.tasks import run_step_task


class EnqueueTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)

    def test_it_dispatches_one_task_per_step(self):
        with mock.patch("apps.videos.tasks.run_step_task.delay") as delay:
            queued = PipelineService.enqueue([1, 2, 3])

        self.assertEqual(queued, [1, 2, 3])
        self.assertEqual([c.args[0] for c in delay.call_args_list], [1, 2, 3])

    def test_an_empty_list_touches_the_broker_at_all(self):
        with mock.patch("apps.videos.tasks.run_step_task.delay") as delay:
            self.assertEqual(PipelineService.enqueue([]), [])
        delay.assert_not_called()

    def test_a_dead_broker_raises_rather_than_silently_dropping_the_work(self):
        """A dropped task looks exactly like a step about to start, and the user would
        watch a spinner forever."""
        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("no route")
        ):
            with self.assertRaises(QueueUnavailableError) as caught:
                PipelineService.enqueue([self.step.pk])

        self.assertIn("Redis", str(caught.exception))
        self.assertIn("no route", str(caught.exception))

    def test_approving_leaves_the_step_approved_when_the_broker_is_down(self):
        """Approved-but-not-started is the truth, and it is what resume_waiting_steps
        needs in order to pick the step up later."""
        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            with self.assertRaises(QueueUnavailableError):
                PipelineService.approve_step_background(self.step, actor=self.owner)

        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.APPROVED)
        self.assertEqual(self.step.approved_by_id, self.owner.pk)

    def test_approving_queues_exactly_the_approved_step(self):
        with mock.patch.object(PipelineService, "enqueue") as enqueue:
            PipelineService.approve_step_background(self.step, actor=self.owner)

        enqueue.assert_called_once_with([self.step.pk])
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.APPROVED)


class ClaimTests(TestCase):
    """The compare-and-swap that stops a step running twice — and being paid for
    twice."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)
        StepRepository.update(self.step, status=StepStatus.APPROVED)

    def test_claiming_an_approved_step_takes_it(self):
        claimed = StepRepository.claim(self.step.pk)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, StepStatus.RUNNING)
        self.assertIsNotNone(claimed.started_at)

    def test_a_second_claim_gets_nothing(self):
        StepRepository.claim(self.step.pk)

        self.assertIsNone(StepRepository.claim(self.step.pk))

    def test_a_step_that_is_not_approved_cannot_be_claimed(self):
        for status in (
            StepStatus.PENDING_APPROVAL,
            StepStatus.RUNNING,
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.REJECTED,
        ):
            with self.subTest(status=status):
                StepRepository.update(self.step, status=status)
                self.assertIsNone(StepRepository.claim(self.step.pk))

    def test_an_unknown_step_claims_nothing(self):
        self.assertIsNone(StepRepository.claim(99_999))


class RunStepTaskTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)
        StepRepository.update(self.step, status=StepStatus.APPROVED)

    def test_it_claims_then_runs(self):
        with mock.patch.object(PipelineService, "run_step") as run:
            run_step_task(self.step.pk)

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0].pk, self.step.pk)
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.RUNNING)

    def test_a_duplicate_delivery_runs_nothing(self):
        """Two page loads can both queue the same approved step. Running a paid step
        twice would charge twice."""
        with mock.patch.object(PipelineService, "run_step") as run:
            run_step_task(self.step.pk)
            run_step_task(self.step.pk)

        self.assertEqual(run.call_count, 1)

    def test_a_step_no_longer_approved_is_skipped_quietly(self):
        StepRepository.update(self.step, status=StepStatus.REJECTED)

        with mock.patch.object(PipelineService, "run_step") as run:
            run_step_task(self.step.pk)  # must not raise

        run.assert_not_called()


class AdvanceQueuesFollowOnTests(TestCase):
    """Each step is its own task. Chaining them inline would hold one worker slot for
    the sum of the chain and hide the later steps' progress."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.script = self.video.steps.get(step_type=StepType.SCRIPT)
        StepRepository.update(self.script, status=StepStatus.COMPLETED)

    def test_a_finished_script_queues_the_split_rather_than_running_it(self):
        with mock.patch.object(PipelineService, "enqueue") as enqueue, \
                mock.patch.object(PipelineService, "run_step") as run:
            PipelineService._advance(self.script)

        split = StepRepository.for_video(self.video.pk).get(step_type=StepType.SPLIT)
        self.assertEqual(split.status, StepStatus.APPROVED)
        enqueue.assert_called_once_with([split.pk])
        run.assert_not_called()

    def test_a_dead_broker_leaves_the_follow_on_approved_and_does_not_fail_the_parent(self):
        """The predecessor genuinely succeeded, so failing it would be a lie."""
        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            PipelineService._advance(self.script)  # must not raise

        split = StepRepository.for_video(self.video.pk).get(step_type=StepType.SPLIT)
        self.assertEqual(split.status, StepStatus.APPROVED)


class ResumeWaitingTests(TestCase):
    def setUp(self):
        # make_account already gives the owner an Owner membership, which holds every
        # permission — adding another would break (user, account) uniqueness.
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)

    def test_it_requeues_approved_steps(self):
        StepRepository.update(self.step, status=StepStatus.APPROVED)

        with mock.patch.object(PipelineService, "enqueue", return_value=[self.step.pk]) as enqueue:
            resumed = PipelineService.resume_waiting_steps(self.video)

        self.assertEqual(resumed, [self.step.pk])
        enqueue.assert_called_once_with([self.step.pk])

    def test_it_leaves_pending_steps_alone(self):
        with mock.patch.object(PipelineService, "enqueue") as enqueue:
            self.assertEqual(PipelineService.resume_waiting_steps(self.video), [])
        enqueue.assert_not_called()

    def test_a_dead_broker_does_not_break_the_page(self):
        """This runs on an ordinary page view; failing the page over a background
        retry would be the wrong trade."""
        StepRepository.update(self.step, status=StepStatus.APPROVED)

        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            self.assertEqual(PipelineService.resume_waiting_steps(self.video), [])

    def test_the_detail_page_still_renders_with_the_broker_down(self):
        StepRepository.update(self.step, status=StepStatus.APPROVED)
        self.client.force_login(self.owner)

        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            response = self.client.get(reverse("videos:detail", args=[self.video.pk]))

        self.assertEqual(response.status_code, 200)


class BrokerDownMessageTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)
        self.client.force_login(self.owner)

    def test_approving_with_a_dead_broker_says_so(self):
        with mock.patch(
            "apps.videos.tasks.run_step_task.delay", side_effect=OSError("down")
        ):
            response = self.client.post(
                reverse("videos:step_approve", args=[self.video.pk, self.step.pk]),
                follow=True,
            )

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("task queue" in m for m in messages), messages)
        self.assertTrue(any("stays approved" in m for m in messages), messages)
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.APPROVED)


class UnstickStepsTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = self.video.steps.get(step_type=StepType.SCRIPT)

    def _make_running(self, minutes_ago):
        StepRepository.update(
            self.step,
            status=StepStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def _run(self, **options):
        out = StringIO()
        call_command("unstick_steps", stdout=out, **options)
        return out.getvalue()

    def test_it_fails_an_abandoned_step_so_it_can_be_retried(self):
        self._make_running(240)

        self._run(older_than=180)

        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.FAILED)
        self.assertIn("Abandoned", self.step.error_message)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, VideoStatus.FAILED)

    def test_it_never_re_approves(self):
        """Re-running a paid step automatically is the double charge this design
        exists to avoid, so the decision stays with a person."""
        self._make_running(240)

        self._run(older_than=180)

        self.step.refresh_from_db()
        self.assertNotEqual(self.step.status, StepStatus.APPROVED)

    def test_a_step_still_within_the_window_is_left_alone(self):
        self._make_running(30)

        self._run(older_than=180)

        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.RUNNING)

    def test_dry_run_changes_nothing(self):
        self._make_running(240)

        output = self._run(older_than=180, dry_run=True)

        self.assertIn("Dry run", output)
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.RUNNING)

    def test_it_reports_when_nothing_is_stuck(self):
        output = self._run(older_than=180)
        self.assertIn("nothing stuck", output)


class QueueStatusCommandTests(TestCase):
    def test_it_reports_an_unreachable_broker(self):
        out = StringIO()
        with mock.patch("config.celery.app.connection") as connection:
            connection.return_value.ensure_connection.side_effect = OSError("refused")
            call_command("queue_status", stdout=out)

        output = out.getvalue()
        self.assertIn("unreachable", output)
        self.assertIn("redis-server", output)

    def test_it_reports_a_broker_with_no_workers(self):
        out = StringIO()
        with mock.patch("config.celery.app.connection"), \
                mock.patch("config.celery.app.control.ping", return_value=[]):
            call_command("queue_status", stdout=out)

        output = out.getvalue()
        self.assertIn("no worker answered", output)
        self.assertIn("celery -A config worker", output)

    def test_it_reports_a_healthy_queue_and_the_backlog(self):
        out = StringIO()
        with mock.patch("config.celery.app.connection"), \
                mock.patch("config.celery.app.control.ping",
                           return_value=[{"celery@host": {"ok": "pong"}}]):
            call_command("queue_status", stdout=out)

        output = out.getvalue()
        self.assertIn("both up", output)
        self.assertIn("approved (waiting for a worker)", output)


class ExecutorFailureTests(TestCase):
    """A failing step must stay contained: no retry, and the video shows why."""

    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.video = make_video(make_template(self.account), actor=self.owner)
        self.step = StepRepository.create(
            video=self.video,
            step_type=StepType.SPLIT,
            provider=Provider.LOCAL,
            status=StepStatus.APPROVED,
            estimated_cost_usd=Decimal("0"),
        )
        self._original = None

    def test_a_raising_executor_fails_only_that_step(self):
        from apps.videos.services import pipeline

        previous = pipeline.STEP_EXECUTORS.get(StepType.SPLIT)

        def boom(step):
            raise RuntimeError("provider exploded")

        register_executor(StepType.SPLIT, boom)
        self.addCleanup(register_executor, StepType.SPLIT, previous)

        with mock.patch.object(PipelineService, "enqueue"):
            run_step_task(self.step.pk)

        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.FAILED)
        self.assertIn("provider exploded", self.step.error_message)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, VideoStatus.FAILED)

    def test_a_successful_executor_completes_and_advances(self):
        from apps.videos.services import pipeline

        previous = pipeline.STEP_EXECUTORS.get(StepType.SPLIT)
        register_executor(
            StepType.SPLIT,
            lambda step: StepResult(actual_cost_usd=Decimal("0"),
                                    response_metadata={"chapters": 0}),
        )
        self.addCleanup(register_executor, StepType.SPLIT, previous)

        with mock.patch.object(PipelineService, "enqueue"):
            run_step_task(self.step.pk)

        self.step.refresh_from_db()
        self.assertEqual(self.step.status, StepStatus.COMPLETED)
        self.assertEqual(self.step.response_metadata, {"chapters": 0})
