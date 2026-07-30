from decimal import Decimal, InvalidOperation

from django import template

from apps.videos.services.currency import format_usd_as_pkr

register = template.Library()


@register.filter
def pkr(value):
    """Format a USD amount as a PKR string, e.g. 0.55 -> 'Rs 154.00'."""
    return format_usd_as_pkr(value)


@register.filter
def percent_of(value, total):
    """``value`` as a whole-number percentage of ``total``, clamped to 0-100.

    Used for the budget meter, which needs a width and cannot do arithmetic in the
    template. Clamped because a forced over-cap approval can exceed 100%, and a bar
    wider than its track would overflow the panel.
    """
    try:
        value = Decimal(str(value or 0))
        total = Decimal(str(total or 0))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    return int(min(Decimal(100), max(Decimal(0), value / total * 100)))


@register.filter
def duration(seconds):
    """Seconds as ``1h 24m`` / ``3m 12s`` / ``24s``, for lengths shown in the UI."""
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

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
