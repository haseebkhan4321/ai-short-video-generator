from django import template

register = template.Library()

_VIDEO_STATUS_CLASS = {
    "draft": "",
    "script": "accent",
    "split": "accent",
    "images": "accent",
    "narration": "accent",
    "rendering": "accent",
    "completed": "green",
    "failed": "red",
}

_STEP_STATUS_CLASS = {
    "pending_approval": "amber",
    "approved": "accent",
    "running": "accent",
    "completed": "green",
    "failed": "red",
    "rejected": "",
}


@register.filter
def status_class(value):
    """Badge CSS class for a Video status."""
    return _VIDEO_STATUS_CLASS.get(value, "")


@register.filter
def step_status_class(value):
    """Badge CSS class for a GenerationStep status."""
    return _STEP_STATUS_CLASS.get(value, "")
