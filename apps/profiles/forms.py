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
            "elevenlabs_voice_id",
            "language",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "style_prompt": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "style_prompt": "Tone/style guidance injected into script and image "
            "prompts (e.g. 'slow, atmospheric horror narration in second person').",
            "elevenlabs_voice_id": "ElevenLabs voice ID used for narration. Can be "
            "left blank for now and set before the narration step.",
        }
