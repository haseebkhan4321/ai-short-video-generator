"""Split step (free/local): cut the completed script into ordered parts, creating
one Chapter per part. Registered as the 'split' executor."""
import math
import re
from decimal import Decimal

from django.conf import settings

from ..models import StepType
from ..repositories import ChapterRepository
from .pipeline import PipelineService, StepResult, register_executor


def _split_into_parts(script, words_per_part):
    paras = [p.strip() for p in re.split(r"\n\s*\n", script or "") if p.strip()]
    if not paras:
        return []

    parts, current, current_words = [], [], 0
    for para in paras:
        w = len(para.split())
        if current and current_words + w > words_per_part:
            parts.append("\n\n".join(current))
            current, current_words = [para], w
        else:
            current.append(para)
            current_words += w
    if current:
        parts.append("\n\n".join(current))

    # Fallback: a single giant paragraph -> split by word count.
    total_words = len((script or "").split())
    if len(parts) == 1 and total_words > words_per_part * 1.5:
        words = script.split()
        n = math.ceil(total_words / words_per_part)
        size = math.ceil(total_words / n)
        parts = [" ".join(words[i:i + size]) for i in range(0, total_words, size)]

    return parts


def run_split_step(step):
    video = step.video
    script = video.script or ""
    if not script.strip():
        raise ValueError("Cannot split: the script is empty.")

    words_per_part = settings.WORDS_PER_MINUTE * settings.TARGET_MINUTES_PER_PART
    part_texts = _split_into_parts(script, words_per_part)

    PipelineService.update_progress(
        step, current=0, total=len(part_texts), message="Splitting script into parts..."
    )

    # Re-splitting replaces any existing chapters.
    ChapterRepository.delete_for_video(video.pk)

    for index, text in enumerate(part_texts, start=1):
        ChapterRepository.create(
            video=video,
            chapter_number=index,
            title="",  # the part number is shown separately; no generic title
            body=text,
            word_count=len(text.split()),
        )
        PipelineService.update_progress(step, current=index)

    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={"parts": len(part_texts), "words_per_part": words_per_part},
    )


register_executor(StepType.SPLIT, run_split_step)
