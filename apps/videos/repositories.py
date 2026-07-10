"""Data-access layer for videos and related models. The only place these ORM
queries live."""
from .models import ApiCallLog, Chapter, ChapterImage, GenerationStep, Video


class VideoRepository:
    @staticmethod
    def all():
        return Video.objects.select_related("profile").all()

    @staticmethod
    def for_profile(profile_id):
        return Video.objects.filter(profile_id=profile_id)

    @staticmethod
    def get(video_id):
        return Video.objects.select_related("profile").get(pk=video_id)

    @staticmethod
    def get_or_none(video_id):
        return Video.objects.filter(pk=video_id).select_related("profile").first()

    @staticmethod
    def create(**fields):
        return Video.objects.create(**fields)

    @staticmethod
    def update(video, **fields):
        for key, value in fields.items():
            setattr(video, key, value)
        video.save()
        return video

    @staticmethod
    def delete(video):
        video.delete()


class ChapterRepository:
    @staticmethod
    def for_video(video_id):
        return Chapter.objects.filter(video_id=video_id).prefetch_related("images")

    @staticmethod
    def get(chapter_id):
        return Chapter.objects.get(pk=chapter_id)

    @staticmethod
    def create(**fields):
        return Chapter.objects.create(**fields)

    @staticmethod
    def bulk_create(chapters):
        return Chapter.objects.bulk_create(chapters)

    @staticmethod
    def update(chapter, **fields):
        for key, value in fields.items():
            setattr(chapter, key, value)
        chapter.save()
        return chapter

    @staticmethod
    def delete_for_video(video_id):
        Chapter.objects.filter(video_id=video_id).delete()


class ChapterImageRepository:
    @staticmethod
    def create(**fields):
        return ChapterImage.objects.create(**fields)

    @staticmethod
    def for_chapter(chapter_id):
        return ChapterImage.objects.filter(chapter_id=chapter_id)

    @staticmethod
    def delete_for_chapter(chapter_id):
        ChapterImage.objects.filter(chapter_id=chapter_id).delete()


class StepRepository:
    @staticmethod
    def for_video(video_id):
        return GenerationStep.objects.filter(video_id=video_id)

    @staticmethod
    def get(step_id):
        return GenerationStep.objects.select_related("video", "chapter").get(pk=step_id)

    @staticmethod
    def create(**fields):
        return GenerationStep.objects.create(**fields)

    @staticmethod
    def update(step, **fields):
        for key, value in fields.items():
            setattr(step, key, value)
        step.save()
        return step


class ApiCallLogRepository:
    @staticmethod
    def create(**fields):
        return ApiCallLog.objects.create(**fields)

    @staticmethod
    def for_step(step_id):
        return ApiCallLog.objects.filter(step_id=step_id)
