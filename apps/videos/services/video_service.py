"""Read/CRUD business logic for videos. Views call these; these call repositories
(and the pipeline for creation).

Every lookup here takes the caller's active account. Returning ``None`` for a video
in another account (rather than the row) is what makes the view's 404 correct: a
video's existence must not leak across accounts.
"""
from ..models import StepStatus
from ..repositories import (
    ChapterRepository,
    StepRepository,
    VideoRepository,
)


class VideoService:
    @staticmethod
    def list_videos(account):
        return VideoRepository.for_account(account)

    @staticmethod
    def get_video(video_id, account):
        return VideoRepository.get_in_account(video_id, account)

    @staticmethod
    def delete_video(video):
        VideoRepository.delete(video)

    @staticmethod
    def chapters_for(video_id):
        return ChapterRepository.for_video(video_id)

    @staticmethod
    def steps_for(video_id):
        return StepRepository.for_video(video_id).select_related(
            "chapter", "approved_by"
        )

    @staticmethod
    def get_step(step_id, video_id):
        """Scoped to its video, so the ``video_id`` in a step URL is load-bearing."""
        return StepRepository.get_in_video(step_id, video_id)

    @staticmethod
    def pending_steps(video_id, step_type=None, chapter_id=None):
        """Steps awaiting approval, so a view can tell whether a batch spends money
        before deciding which permission to demand."""
        qs = StepRepository.for_video(video_id).filter(
            status=StepStatus.PENDING_APPROVAL
        )
        if step_type is not None:
            qs = qs.filter(step_type=step_type)
        if chapter_id is not None:
            qs = qs.filter(chapter_id=chapter_id)
        return qs
