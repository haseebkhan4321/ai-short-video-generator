from django.contrib import admin

from .models import ApiCallLog, Chapter, ChapterImage, GenerationStep, Video


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0


class GenerationStepInline(admin.TabularInline):
    model = GenerationStep
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("__str__", "profile", "status", "target_minutes", "total_cost_usd", "created_at")
    list_filter = ("status", "profile")
    search_fields = ("title", "premise")
    inlines = [ChapterInline, GenerationStepInline]


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("video", "chapter_number", "title", "word_count")
    list_filter = ("video",)


@admin.register(ChapterImage)
class ChapterImageAdmin(admin.ModelAdmin):
    list_display = ("chapter", "order", "image_path")


@admin.register(GenerationStep)
class GenerationStepAdmin(admin.ModelAdmin):
    list_display = ("video", "step_type", "provider", "status", "estimated_cost_usd", "actual_cost_usd")
    list_filter = ("step_type", "provider", "status")


@admin.register(ApiCallLog)
class ApiCallLogAdmin(admin.ModelAdmin):
    list_display = ("provider", "endpoint", "model", "cost_usd", "created_at")
    list_filter = ("provider",)
