from django import forms

from .models import Profile


class ProfileForm(forms.ModelForm):
    """Validates profile input. Persistence is done by ProfileService via the
    repository, so this form is used for validation only (never .save())."""

    class Meta:
        model = Profile
        fields = [
            "name",
            "niche",
            "description",
            "style_prompt",
            "narrator_voice",
            "language",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "style_prompt": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "style_prompt": "Tone/style guidance injected into script and image "
            "prompts (e.g. 'slow, atmospheric horror narration in second person').",
            "narrator_voice": "Narrator voice for the active TTS provider (an "
            "ElevenLabs voice ID, or a Kokoro voice like 'af_heart'). Blank uses "
            "the default.",
        }
