"""Pipeline orchestration and the approval framework.

Every paid step is created as ``pending_approval`` with an estimated cost. Nothing
calls a paid provider until ``approve_step`` runs it. Free/local steps (split,
render) need no approval and are auto-run when their executor is available.

Step executors are registered by the per-step service modules (milestones 4-8) via
``register_executor``. Each executor receives the GenerationStep and returns a
``StepResult``. This keeps the framework decoupled from provider specifics.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from ..models import (
    Provider,
    StepStatus,
    StepType,
    VideoStatus,
)
from ..repositories import (
    ApiCallLogRepository,
    ChapterRepository,
    StepRepository,
    VideoRepository,
)
from .cost_estimator import CostEstimator


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
            f"Approving this would bring the video to ${projected}, over the "
            f"${cap} per-video cap."
        )


class StepNotActionableError(PipelineError):
    pass


class StepTypeNotImplemented(PipelineError):
    def __init__(self, step_type):
        self.step_type = step_type
        super().__init__(f"No executor registered for step type '{step_type}' yet.")


# --- Free vs paid ------------------------------------------------------------

FREE_STEP_TYPES = {StepType.SPLIT, StepType.RENDER, StepType.SUBTITLES}


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
    def reject_step(step):
        if step.status != StepStatus.PENDING_APPROVAL:
            raise StepNotActionableError("Step is not pending approval.")
        return StepRepository.update(step, status=StepStatus.REJECTED)

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
            PipelineService._create_image_steps(video)

        elif step_type == StepType.IMAGES:
            if PipelineService._all_completed(video, StepType.IMAGES):
                VideoRepository.update(video, status=VideoStatus.IMAGES)
                PipelineService._create_narration_steps(video)

        elif step_type == StepType.NARRATION:
            if PipelineService._all_completed(video, StepType.NARRATION):
                VideoRepository.update(video, status=VideoStatus.NARRATION)
                PipelineService._create_and_maybe_run_free(video, StepType.RENDER)

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
    def _create_image_steps(video):
        chapters = ChapterRepository.for_video(video.pk)
        for chapter in chapters:
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
        chapters = ChapterRepository.for_video(video.pk)
        for chapter in chapters:
            estimate = CostEstimator.estimate_narration_for_text(chapter.body)
            StepRepository.create(
                video=video,
                chapter=chapter,
                step_type=StepType.NARRATION,
                provider=Provider.ELEVENLABS,
                status=StepStatus.PENDING_APPROVAL,
                estimated_cost_usd=estimate,
                request_payload={
                    "voice_id": video.profile.elevenlabs_voice_id,
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
