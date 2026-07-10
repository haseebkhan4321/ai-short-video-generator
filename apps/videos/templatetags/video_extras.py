from django import template

from apps.videos.services.currency import format_usd_as_pkr

register = template.Library()


@register.filter
def pkr(value):
    """Format a USD amount as a PKR string, e.g. 0.55 -> 'Rs 154.00'."""
    return format_usd_as_pkr(value)

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
