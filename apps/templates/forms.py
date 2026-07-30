from django import forms

from .models import Template


class TemplateForm(forms.ModelForm):
    """Validates template input. Persistence is done by TemplateService via the
    repository, so this form is used for validation only (never .save())."""

    class Meta:
        model = Template
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

    def __init__(self, *args, account=None, **kwargs):
        """``account`` scopes the uniqueness check, since the model's
        ``unique_together`` spans (account, name) and the field is not on the form."""
        self.account = account
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"]
        account = self.account or getattr(self.instance, "account", None)
        if account is None:
            return name
        clash = Template.objects.filter(account=account, name=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(
                "A template with this name already exists in this account."
            )
        return name
