"""Celery tasks. One task per pipeline step.

One step per task rather than one task per video, so each gets its own timeout, its
own log line, and its own place in the queue — and a failed render does not take the
narration that preceded it down with it.

There is deliberately no automatic retry. A step that failed halfway through a paid
OpenAI call may already have been charged for, so retrying it without a human looking
risks paying twice for the same work. Failures land on the video detail page with the
provider's error, and the existing Retry button is how they are re-run.
"""
import logging

from celery import shared_task

from .repositories import StepRepository
from .services.pipeline import PipelineService

log = logging.getLogger(__name__)


@shared_task(name="videos.run_step", ignore_result=True)
def run_step_task(step_id):
    """Claim and run one approved step.

    The claim is a compare-and-swap on APPROVED -> RUNNING, so a step enqueued twice
    runs once. That matters: two page loads can both call ``resume_waiting_steps``,
    and running a paid step twice would charge twice.
    """
    step = StepRepository.claim(step_id)
    if step is None:
        # Already claimed, or no longer approved. Not an error — the guard working.
        log.info("step %s was not available to claim; skipping", step_id)
        return

    log.info(
        "running step %s (%s) for video %s", step.pk, step.step_type, step.video_id
    )
    PipelineService.run_step(step)
    step.refresh_from_db()
    log.info("step %s finished as %s", step.pk, step.status)
