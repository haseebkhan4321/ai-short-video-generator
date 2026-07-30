"""Pipeline orchestration and the approval framework.

Every paid step is created as ``pending_approval`` with an estimated cost. Nothing
calls a paid provider until ``approve_step`` runs it. Free/local steps (split,
render) need no approval and are auto-run when their executor is available.

Step executors are registered by the per-step service modules (milestones 4-8) via
``register_executor``. Each executor receives the GenerationStep and returns a
``StepResult``. This keeps the framework decoupled from provider specifics.
"""
import threading
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import (
    Provider,
    StepStatus,
    StepType,
    Video,
    VideoStatus,
)
from ..repositories import (
    ApiCallLogRepository,
    ChapterRepository,
    StepRepository,
    VideoRepository,
)
from .cost_estimator import CostEstimator
from .currency import format_usd_as_pkr


# --- Executor registry -------------------------------------------------------

STEP_EXECUTORS = {}


def register_executor(step_type, fn):
    """Register the callable that runs a given step type."""
    STEP_EXECUTORS[step_type] = fn


def has_executor(step_type):
    return step_type in STEP_EXECUTORS


@dataclass
class StepResult:
    """What an executor returns to the pipeline."""

    actual_cost_usd: Decimal = Decimal("0")
    response_metadata: dict = field(default_factory=dict)
    # Each api_call is a dict: provider, endpoint, model, units, cost_usd, duration_ms
    api_calls: list = field(default_factory=list)


# --- Errors ------------------------------------------------------------------


class PipelineError(Exception):
    pass


class BudgetExceededError(PipelineError):
    def __init__(self, projected, cap):
        self.projected = projected
        self.cap = cap
        super().__init__(
            f"Approving this would bring the video to {format_usd_as_pkr(projected)}, "
            f"over the {format_usd_as_pkr(cap)} per-video cap."
        )


class StepNotActionableError(PipelineError):
    pass


class StepTypeNotImplemented(PipelineError):
    def __init__(self, step_type):
        self.step_type = step_type
        super().__init__(f"No executor registered for step type '{step_type}' yet.")


# --- Free vs paid ------------------------------------------------------------

FREE_STEP_TYPES = {
    StepType.SPLIT, StepType.RENDER_PART, StepType.MERGE, StepType.RENDER,
    StepType.SUBTITLES,
}


def _run_steps_threaded(step_ids):
    """Run one or more steps sequentially in a background thread with a fresh DB
    connection (closed at the end to avoid leaking connections per thread)."""
    from django.db import connections

    try:
        for step_id in step_ids:
            step = StepRepository.get(step_id)
            PipelineService.run_step(step)
    finally:
        connections.close_all()


class PipelineService:
    # ---- Video creation ----

    @staticmethod
    def create_video(profile, premise, target_minutes):
        video = VideoRepository.create(
            profile=profile,
            premise=premise,
            target_minutes=target_minutes,
            status=VideoStatus.DRAFT,
        )
        PipelineService._create_script_step(video)
        return video

    @staticmethod
    def _create_script_step(video):
        estimate = CostEstimator.estimate_script(video.target_minutes)
        payload = {
            "model": settings.OPENAI_TEXT_MODEL,
            "target_minutes": video.target_minutes,
            "target_words": CostEstimator.target_words(video.target_minutes),
            "premise": video.premise,
            "style_prompt": video.profile.style_prompt,
        }
        return StepRepository.create(
            video=video,
            step_type=StepType.SCRIPT,
            provider=Provider.OPENAI,
            status=StepStatus.PENDING_APPROVAL,
            estimated_cost_usd=estimate,
            request_payload=payload,
        )

    # ---- Budget ----

    @staticmethod
    def budget_cap():
        return Decimal(settings.MAX_COST_PER_VIDEO_USD)

    @staticmethod
    def _check_budget(video, added_estimate, force):
        projected = Decimal(video.total_cost_usd) + Decimal(added_estimate)
        cap = PipelineService.budget_cap()
        if not force and projected > cap:
            raise BudgetExceededError(projected, cap)

    # ---- Approval / rejection ----

    @staticmethod
    def approve_step(step, force=False):
        if step.status != StepStatus.PENDING_APPROVAL:
            raise StepNotActionableError("Step is not pending approval.")
        if not has_executor(step.step_type):
            raise StepTypeNotImplemented(step.step_type)
        PipelineService._check_budget(step.video, step.estimated_cost_usd, force)
        return PipelineService._approve_and_run(step)

    @staticmethod
    def approve_step_background(step, force=False):
        """Validate + mark approved synchronously, then run in a background thread
        so the request returns immediately. Used by the web UI."""
        if step.status != StepStatus.PENDING_APPROVAL:
            raise StepNotActionableError("Step is not pending approval.")
        if not has_executor(step.step_type):
            raise StepTypeNotImplemented(step.step_type)
        PipelineService._check_budget(step.video, step.estimated_cost_usd, force)
        StepRepository.update(
            step, status=StepStatus.APPROVED, approved_at=timezone.now()
        )
        threading.Thread(
            target=_run_steps_threaded, args=([step.pk],), daemon=True
        ).start()
        return step

    @staticmethod
    def batch_approve_background(video, step_type, force=False):
        pending = list(
            StepRepository.for_video(video.pk).filter(
                step_type=step_type, status=StepStatus.PENDING_APPROVAL
            )
        )
        if not pending:
            return []
        total_estimate = sum((s.estimated_cost_usd for s in pending), Decimal("0"))
        PipelineService._check_budget(video, total_estimate, force)
        for step in pending:
            if not has_executor(step.step_type):
                raise StepTypeNotImplemented(step.step_type)
        ids = []
        for step in pending:
            StepRepository.update(
                step, status=StepStatus.APPROVED, approved_at=timezone.now()
            )
            ids.append(step.pk)
        threading.Thread(
            target=_run_steps_threaded, args=(ids,), daemon=True
        ).start()
        return ids

    @staticmethod
    def approve_chapter_background(video, chapter_id, force=False):
        """Approve and run all pending steps for one part (images + narration) so a
        part can be completed on its own."""
        pending = list(
            StepRepository.for_video(video.pk).filter(
                chapter_id=chapter_id, status=StepStatus.PENDING_APPROVAL
            )
        )
        if not pending:
            return []
        total_estimate = sum((s.estimated_cost_usd for s in pending), Decimal("0"))
        PipelineService._check_budget(video, total_estimate, force)
        for step in pending:
            if not has_executor(step.step_type):
                raise StepTypeNotImplemented(step.step_type)
        ids = []
        for step in pending:
            StepRepository.update(
                step, status=StepStatus.APPROVED, approved_at=timezone.now()
            )
            ids.append(step.pk)
        threading.Thread(
            target=_run_steps_threaded, args=(ids,), daemon=True
        ).start()
        return ids

    @staticmethod
    def reject_step(step):
        if step.status != StepStatus.PENDING_APPROVAL:
            raise StepNotActionableError("Step is not pending approval.")
        return StepRepository.update(step, status=StepStatus.REJECTED)

    @staticmethod
    def retry_step(step):
        """Reset a failed/rejected step back to pending approval, in place (no new
        row). Clears the video's failed state when appropriate."""
        if step.status not in (StepStatus.FAILED, StepStatus.REJECTED):
            raise StepNotActionableError("Only failed or rejected steps can be retried.")
        StepRepository.update(
            step,
            status=StepStatus.PENDING_APPROVAL,
            error_message="",
            actual_cost_usd=None,
            approved_at=None,
            started_at=None,
            finished_at=None,
            progress_current=0,
            progress_total=0,
            progress_message="",
        )
        video = step.video
        if video.status == VideoStatus.FAILED:
            # Reset to the stage just before this step type.
            prior = {
                StepType.SCRIPT: VideoStatus.DRAFT,
                StepType.IMAGES: VideoStatus.SPLIT,
                StepType.NARRATION: VideoStatus.IMAGES,
                StepType.MERGE: VideoStatus.NARRATION,
                StepType.RENDER: VideoStatus.NARRATION,
            }.get(step.step_type, VideoStatus.DRAFT)
            VideoRepository.update(video, status=prior, error_message="")
        return step

    @staticmethod
    def resume_waiting_steps(video):
        """Start any APPROVED steps whose executor is now available (e.g. a free
        step that was created before its executor existed, or a job orphaned by a
        server restart). Safe to call on every page load."""
        waiting = [
            s
            for s in StepRepository.for_video(video.pk).filter(
                status=StepStatus.APPROVED
            )
            if has_executor(s.step_type)
        ]
        ids = []
        for step in waiting:
            # Claim synchronously so a rapid second load won't double-start.
            StepRepository.update(
                step, status=StepStatus.RUNNING, started_at=timezone.now()
            )
            ids.append(step.pk)
        if ids:
            threading.Thread(
                target=_run_steps_threaded, args=(ids,), daemon=True
            ).start()
        return ids

    @staticmethod
    def update_progress(step, current=None, total=None, message=None):
        """Executors call this to publish live progress for the UI."""
        fields = {}
        if current is not None:
            fields["progress_current"] = current
        if total is not None:
            fields["progress_total"] = total
        if message is not None:
            fields["progress_message"] = message[:255]
        if fields:
            StepRepository.update(step, **fields)

    @staticmethod
    def batch_approve(video, step_type, force=False):
        pending = StepRepository.for_video(video.pk).filter(
            step_type=step_type, status=StepStatus.PENDING_APPROVAL
        )
        pending = list(pending)
        if not pending:
            return []
        total_estimate = sum((s.estimated_cost_usd for s in pending), Decimal("0"))
        PipelineService._check_budget(video, total_estimate, force)
        for step in pending:
            if not has_executor(step.step_type):
                raise StepTypeNotImplemented(step.step_type)
        return [PipelineService._approve_and_run(s) for s in pending]

    @staticmethod
    def _approve_and_run(step):
        StepRepository.update(
            step, status=StepStatus.APPROVED, approved_at=timezone.now()
        )
        return PipelineService.run_step(step)

    # ---- Execution ----

    @staticmethod
    def run_step(step):
        executor = STEP_EXECUTORS.get(step.step_type)
        if executor is None:
            raise StepTypeNotImplemented(step.step_type)

        StepRepository.update(
            step, status=StepStatus.RUNNING, started_at=timezone.now()
        )
        try:
            result = executor(step)
        except Exception as exc:  # executor failure is contained to the step
            StepRepository.update(
                step,
                status=StepStatus.FAILED,
                error_message=str(exc),
                finished_at=timezone.now(),
            )
            VideoRepository.update(step.video, status=VideoStatus.FAILED,
                                   error_message=str(exc))
            return step

        for call in result.api_calls:
            ApiCallLogRepository.create(step=step, **call)

        StepRepository.update(
            step,
            status=StepStatus.COMPLETED,
            actual_cost_usd=result.actual_cost_usd,
            response_metadata=result.response_metadata,
            finished_at=timezone.now(),
        )
        video = step.video
        VideoRepository.update(
            video,
            total_cost_usd=Decimal(video.total_cost_usd)
            + Decimal(result.actual_cost_usd),
            error_message="",
        )
        PipelineService._advance(step)
        return step

    # ---- Stage advancement ----

    @staticmethod
    def _advance(step):
        video = step.video
        step_type = step.step_type

        if step_type == StepType.SCRIPT:
            VideoRepository.update(video, status=VideoStatus.SCRIPT)
            PipelineService._create_and_maybe_run_free(video, StepType.SPLIT)

        elif step_type == StepType.SPLIT:
            VideoRepository.update(video, status=VideoStatus.SPLIT)
            # Images and narration both depend only on the split text, so create
            # both up front. The user can complete a part at a time or run a whole
            # stage in batch. Merge waits until every part has both.
            PipelineService._create_image_steps(video)
            PipelineService._create_narration_steps(video)

        elif step_type in (StepType.IMAGES, StepType.NARRATION):
            # Once a part has both its images and narration, render its preview
            # video (free/local) so parts can be watched before the whole video.
            PipelineService._maybe_render_part(video, step.chapter_id)
            # Parts may finish in concurrent threads; a row lock ensures exactly one
            # of them creates the merge step.
            PipelineService._trigger_singleton_free(
                video, StepType.MERGE,
                ready=lambda: PipelineService._assets_ready(video),
                on_create=lambda: VideoRepository.update(
                    video, status=VideoStatus.NARRATION),
            )

        elif step_type == StepType.RENDER_PART:
            pass  # per-part preview; does not advance the video-level pipeline

        elif step_type == StepType.MERGE:
            PipelineService._trigger_singleton_free(video, StepType.RENDER)

        elif step_type == StepType.RENDER:
            VideoRepository.update(video, status=VideoStatus.COMPLETED)

    @staticmethod
    def _all_completed(video, step_type):
        steps = StepRepository.for_video(video.pk).filter(step_type=step_type)
        steps = list(steps)
        if not steps:
            return False
        return all(s.status == StepStatus.COMPLETED for s in steps)

    @staticmethod
    def _has_step(video, step_type):
        return StepRepository.for_video(video.pk).filter(step_type=step_type).exists()

    @staticmethod
    def _assets_ready(video):
        """True when every part has both its images and narration completed."""
        return (
            PipelineService._all_completed(video, StepType.IMAGES)
            and PipelineService._all_completed(video, StepType.NARRATION)
        )

    @staticmethod
    def _chapters_with_step(video, step_type):
        return set(
            StepRepository.for_video(video.pk)
            .filter(step_type=step_type)
            .values_list("chapter_id", flat=True)
        )

    @staticmethod
    def _maybe_render_part(video, chapter_id):
        """Render a part's preview video once it has both images and narration.
        Idempotent and concurrency-safe: a video row lock ensures a single
        render_part step per chapter even when images/narration finish in
        parallel threads."""
        if chapter_id is None:
            return None
        step = None
        with transaction.atomic():
            Video.objects.select_for_update().get(pk=video.pk)
            chapter = ChapterRepository.get(chapter_id)
            has_images = chapter.images.exclude(image_path="").exists()
            has_narration = bool(chapter.narration_audio_path)
            exists = (
                StepRepository.for_video(video.pk)
                .filter(step_type=StepType.RENDER_PART, chapter_id=chapter_id)
                .exists()
            )
            if has_images and has_narration and not exists:
                step = StepRepository.create(
                    video=video,
                    chapter=chapter,
                    step_type=StepType.RENDER_PART,
                    provider=Provider.LOCAL,
                    status=StepStatus.APPROVED,
                    estimated_cost_usd=Decimal("0"),
                )
        if step is not None and has_executor(StepType.RENDER_PART):
            PipelineService.run_step(step)
        return step

    @staticmethod
    def ensure_asset_steps(video):
        """Idempotently create any missing per-part image/narration steps. Backfills
        videos split under the old flow and supports part-by-part completion."""
        if video.status not in (
            VideoStatus.SPLIT, VideoStatus.IMAGES, VideoStatus.NARRATION
        ):
            return
        if ChapterRepository.for_video(video.pk).exists():
            PipelineService._create_image_steps(video)
            PipelineService._create_narration_steps(video)

    @staticmethod
    def backfill_part_videos(video):
        """Create render_part steps (APPROVED, unrun) for parts that already have
        both assets but no preview video yet (e.g. parts completed before this
        feature). Does not run them itself — resume_waiting_steps, called right
        after this on each load, claims and runs APPROVED steps exactly once, which
        avoids a double-render race. Safe to call every load."""
        chapters = ChapterRepository.for_video(video.pk)
        with_step = PipelineService._chapters_with_step(video, StepType.RENDER_PART)
        created = []
        for chapter in chapters:
            if chapter.pk in with_step:
                continue
            if not chapter.narration_audio_path:
                continue
            if not chapter.images.exclude(image_path="").exists():
                continue
            step = StepRepository.create(
                video=video,
                chapter=chapter,
                step_type=StepType.RENDER_PART,
                provider=Provider.LOCAL,
                status=StepStatus.APPROVED,
            )
            created.append(step.pk)
        return created

    @staticmethod
    def _create_and_maybe_run_free(video, step_type):
        """Create a free/local step and run it immediately if its executor exists.
        If the executor isn't built yet, the step waits as APPROVED."""
        step = StepRepository.create(
            video=video,
            step_type=step_type,
            provider=Provider.LOCAL,
            status=StepStatus.APPROVED,
            estimated_cost_usd=Decimal("0"),
        )
        if has_executor(step_type):
            PipelineService.run_step(step)
        return step

    @staticmethod
    def _trigger_singleton_free(video, step_type, ready=None, on_create=None):
        """Create a one-off free step (merge/render) exactly once, even when called
        from concurrent part threads. A row lock on the video serializes the check.
        The step is run AFTER the lock is released so encoding doesn't hold it."""
        step = None
        with transaction.atomic():
            Video.objects.select_for_update().get(pk=video.pk)
            if (ready is None or ready()) and not PipelineService._has_step(
                video, step_type
            ):
                if on_create is not None:
                    on_create()
                step = StepRepository.create(
                    video=video,
                    step_type=step_type,
                    provider=Provider.LOCAL,
                    status=StepStatus.APPROVED,
                    estimated_cost_usd=Decimal("0"),
                )
        if step is not None and has_executor(step_type):
            PipelineService.run_step(step)
        return step

    @staticmethod
    def _create_image_steps(video):
        already = PipelineService._chapters_with_step(video, StepType.IMAGES)
        chapters = ChapterRepository.for_video(video.pk)
        for chapter in chapters:
            if chapter.pk in already:
                continue
            estimate = CostEstimator.estimate_images(settings.IMAGES_PER_PART)
            StepRepository.create(
                video=video,
                chapter=chapter,
                step_type=StepType.IMAGES,
                provider=Provider.OPENAI,
                status=StepStatus.PENDING_APPROVAL,
                estimated_cost_usd=estimate,
                request_payload={
                    "model": settings.OPENAI_IMAGE_MODEL,
                    "num_images": settings.IMAGES_PER_PART,
                    "chapter_number": chapter.chapter_number,
                },
            )

    @staticmethod
    def _create_narration_steps(video):
        # Narration uses Kokoro (local, free). Steps still wait for a manual start
        # since they are a long-running job.
        voice = video.profile.narrator_voice
        already = PipelineService._chapters_with_step(video, StepType.NARRATION)
        chapters = ChapterRepository.for_video(video.pk)
        for chapter in chapters:
            if chapter.pk in already:
                continue
            StepRepository.create(
                video=video,
                chapter=chapter,
                step_type=StepType.NARRATION,
                provider=Provider.LOCAL,
                status=StepStatus.PENDING_APPROVAL,
                estimated_cost_usd=Decimal("0"),
                request_payload={
                    "tts_provider": "kokoro",
                    "voice_id": voice,
                    "characters": len(chapter.body or ""),
                    "chapter_number": chapter.chapter_number,
                },
            )

    # ---- Regeneration ----

    @staticmethod
    def regenerate_step(old_step):
        """Create a fresh pending copy of a step (used after reject/failure)."""
        return StepRepository.create(
            video=old_step.video,
            chapter=old_step.chapter,
            step_type=old_step.step_type,
            provider=old_step.provider,
            status=StepStatus.PENDING_APPROVAL,
            estimated_cost_usd=old_step.estimated_cost_usd,
            request_payload=old_step.request_payload,
        )
