from django import forms

from apps.templates.repositories import TemplateRepository


class VideoCreateForm(forms.Form):
    """Collects the inputs needed to start a video's pipeline."""

    template = forms.ModelChoiceField(queryset=None, label="Template")
    premise = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="What the story is about. The full 1-2 hour script is generated "
        "from this plus the template's style prompt.",
    )
    target_minutes = forms.IntegerField(
        min_value=5,
        max_value=240,
        help_text="Target narration length in minutes.",
    )

    def __init__(self, *args, account=None, default_minutes=90, **kwargs):
        super().__init__(*args, **kwargs)
        # Scoped queryset: the choices are also the validation, so a template id
        # from another account cannot be posted in.
        self.fields["template"].queryset = TemplateRepository.for_account(account)
        self.fields["target_minutes"].initial = default_minutes
