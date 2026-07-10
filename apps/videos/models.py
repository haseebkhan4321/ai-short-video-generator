from django.db import models

from apps.profiles.models import Profile


class VideoStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SCRIPT = "script", "Script generated"
    SPLIT = "split", "Split into parts"
    IMAGES = "images", "Images generated"
    NARRATION = "narration", "Narration generated"
    RENDERING = "rendering", "Rendering"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class StepType(models.TextChoices):
    SCRIPT = "script", "Generate script"
    SPLIT = "split", "Split into parts"
    IMAGES = "images", "Generate images"
    NARRATION = "narration", "Generate narration"
    MERGE = "merge", "Merge narration"
    RENDER = "render", "Render video"
    SUBTITLES = "subtitles", "Generate subtitles"


class StepStatus(models.TextChoices):
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected"


class Provider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ELEVENLABS = "elevenlabs", "ElevenLabs"
    LOCAL = "local", "Local"


class Video(models.Model):
    """One long-form continuous story (1-2 hours), rendered to a single MP4."""

    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="videos"
    )
    premise = models.TextField(help_text="User-entered premise/topic for the story.")
    target_minutes = models.PositiveIntegerField(default=90)

    title = models.CharField(max_length=300, blank=True)
    script = models.TextField(blank=True, help_text="Full continuous script text.")
    description = models.TextField(blank=True)
    hashtags = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20, choices=VideoStatus.choices, default=VideoStatus.DRAFT
    )
    total_words = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    narration_audio_path = models.CharField(max_length=500, blank=True)
    final_video_path = models.CharField(max_length=500, blank=True)

    total_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Video #{self.pk} ({self.premise[:40]})"


class Chapter(models.Model):
    """An ordered part of the video's script (created by the split step)."""

    video = models.ForeignKey(
        Video, on_delete=models.CASCADE, related_name="chapters"
    )
    chapter_number = models.PositiveIntegerField()
    title = models.CharField(max_length=300, blank=True)
    body = models.TextField(help_text="This part's slice of the full script.")
    word_count = models.PositiveIntegerField(default=0)

    narration_audio_path = models.CharField(max_length=500, blank=True)
    audio_start_seconds = models.FloatField(null=True, blank=True)
    audio_end_seconds = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chapter_number"]
        unique_together = [("video", "chapter_number")]

    def __str__(self):
        return f"{self.video_id} - part {self.chapter_number}"


class ChapterImage(models.Model):
    """A generated image shown during a chapter, with a slow Ken Burns pan."""

    chapter = models.ForeignKey(
        Chapter, on_delete=models.CASCADE, related_name="images"
    )
    order = models.PositiveIntegerField(default=0)
    image_prompt = models.TextField()
    image_path = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"chapter {self.chapter_id} image {self.order}"


class GenerationStep(models.Model):
    """A single pipeline step. Paid steps wait in pending_approval until approved."""

    video = models.ForeignKey(
        Video, on_delete=models.CASCADE, related_name="steps"
    )
    chapter = models.ForeignKey(
        Chapter,
        on_delete=models.CASCADE,
        related_name="steps",
        null=True,
        blank=True,
        help_text="Null for video-level steps (script, split, render).",
    )
    step_type = models.CharField(max_length=20, choices=StepType.choices)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    status = models.CharField(
        max_length=20,
        choices=StepStatus.choices,
        default=StepStatus.PENDING_APPROVAL,
    )

    request_payload = models.JSONField(default=dict, blank=True)
    response_metadata = models.JSONField(default=dict, blank=True)

    # Live progress for background execution.
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    progress_message = models.CharField(max_length=255, blank=True)

    estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    actual_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    error_message = models.TextField(blank=True)

    approved_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_step_type_display()} ({self.status})"

    @property
    def is_paid(self):
        return self.provider != Provider.LOCAL

    @property
    def is_actionable(self):
        return self.status == StepStatus.PENDING_APPROVAL


class ApiCallLog(models.Model):
    """A record of every outbound provider call, for spend tracking."""

    step = models.ForeignKey(
        GenerationStep, on_delete=models.CASCADE, related_name="api_calls"
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    endpoint = models.CharField(max_length=200, blank=True)
    model = models.CharField(max_length=100, blank=True)
    units = models.JSONField(
        default=dict,
        blank=True,
        help_text="e.g. input_tokens, output_tokens, images, characters.",
    )
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.provider} {self.endpoint} ${self.cost_usd}"
