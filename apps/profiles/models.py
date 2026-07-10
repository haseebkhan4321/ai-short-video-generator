from django.db import models


class Profile(models.Model):
    """A content identity (niche + style + narrator voice) that owns videos."""

    name = models.CharField(max_length=200)
    niche = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. horror, history, sci-fi, bedtime",
    )
    description = models.TextField(blank=True)
    style_prompt = models.TextField(
        blank=True,
        help_text="System/style prompt used when generating scripts and image prompts.",
    )
    narrator_voice = models.CharField(
        max_length=100,
        blank=True,
        help_text="Narrator voice for the active TTS provider (e.g. an ElevenLabs "
        "voice ID, or a Kokoro voice like 'af_heart'). Blank uses the default.",
    )
    elevenlabs_voice_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="(Deprecated) legacy ElevenLabs voice field.",
    )
    language = models.CharField(max_length=20, default="en")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
