from django import forms

from apps.profiles.repositories import ProfileRepository


class VideoCreateForm(forms.Form):
    """Collects the inputs needed to start a video's pipeline."""

    profile = forms.ModelChoiceField(queryset=None)
    premise = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="What the story is about. The full 1-2 hour script is generated "
        "from this plus the profile's style prompt.",
    )
    target_minutes = forms.IntegerField(
        min_value=5,
        max_value=240,
        help_text="Target narration length in minutes.",
    )

    def __init__(self, *args, default_minutes=90, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile"].queryset = ProfileRepository.all()
        self.fields["target_minutes"].initial = default_minutes
