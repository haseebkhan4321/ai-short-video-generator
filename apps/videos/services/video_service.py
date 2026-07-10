"""Read/CRUD business logic for videos. Views call these; these call repositories
(and the pipeline for creation)."""
from ..repositories import (
    ApiCallLogRepository,
    ChapterRepository,
    StepRepository,
    VideoRepository,
)


class VideoService:
    @staticmethod
    def list_videos():
        return VideoRepository.all()

    @staticmethod
    def get_video(video_id):
        return VideoRepository.get_or_none(video_id)

    @staticmethod
    def delete_video(video):
        VideoRepository.delete(video)

    @staticmethod
    def chapters_for(video_id):
        return ChapterRepository.for_video(video_id)

    @staticmethod
    def steps_for(video_id):
        return StepRepository.for_video(video_id).select_related("chapter")

    @staticmethod
    def get_step(step_id):
        return StepRepository.get(step_id)
