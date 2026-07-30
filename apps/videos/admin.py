from django.contrib import admin

from .models import ApiCallLog, Chapter, ChapterImage, GenerationStep, Video


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0


class GenerationStepInline(admin.TabularInline):
    model = GenerationStep
    extra = 0
    # status is read-only here on purpose: editing it directly would flip a paid
    # step to "approved" and bypass both the approval gate and the budget cap.
    readonly_fields = ("step_type", "provider", "status", "approved_by", "created_at")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = (
        "__str__", "template", "status", "target_minutes", "total_cost_usd", "created_at"
    )
    list_filter = ("status", "template__account", "template")
    search_fields = ("title", "premise")
    list_select_related = ("template",)
    raw_id_fields = ("template", "created_by")
    inlines = [ChapterInline, GenerationStepInline]


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("video", "chapter_number", "title", "word_count")
    list_filter = ("video",)
    raw_id_fields = ("video",)


@admin.register(ChapterImage)
class ChapterImageAdmin(admin.ModelAdmin):
    list_display = ("chapter", "order", "image_path")
    raw_id_fields = ("chapter",)


@admin.register(GenerationStep)
class GenerationStepAdmin(admin.ModelAdmin):
    list_display = (
        "video", "step_type", "provider", "status",
        "estimated_cost_usd", "actual_cost_usd", "approved_by",
    )
    list_filter = ("step_type", "provider", "status")
    list_select_related = ("video", "approved_by")
    raw_id_fields = ("video", "chapter", "approved_by")
    # Same reasoning as the inline: approval belongs to the pipeline service, which
    # is where the budget cap is enforced.
    readonly_fields = ("status", "approved_at", "approved_by", "created_at")


@admin.register(ApiCallLog)
class ApiCallLogAdmin(admin.ModelAdmin):
    list_display = ("provider", "endpoint", "model", "cost_usd", "created_at")
    list_filter = ("provider",)
    raw_id_fields = ("step",)
