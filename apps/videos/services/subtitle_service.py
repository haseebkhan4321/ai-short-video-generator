"""Subtitles: transcribe the merged narration locally and write an SRT.

Free and local (faster-whisper), and off unless ``SUBTITLES_ENABLED``. It runs after
merge and before render, because the render can optionally burn the captions in and
needs the SRT to exist first.

Transcribing rather than reusing the script is deliberate. The script is what was
*sent* to the narrator; the audio is what came out, and only the audio has timings.
A caption track built from the script would need alignment anyway, and would drift
wherever the TTS chunked a sentence differently.
"""
import textwrap
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from ..integrations.whisper_local import get_transcription_provider
from ..models import StepType
from ..repositories import VideoRepository
from .pipeline import PipelineService, StepResult, register_executor


def format_timestamp(seconds):
    """``SS.mmm`` seconds as SRT's ``HH:MM:SS,mmm``."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_ms = int(round(float(seconds) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def wrap_cue(text, width=None, max_lines=2):
    """Wrap a cue to at most ``max_lines`` lines.

    Long single-line captions run off the frame, and a caption that is three or four
    lines tall covers the image it is captioning. Anything past the limit is dropped
    into the last line rather than truncated — losing words is worse than a slightly
    long line.
    """
    width = width or settings.SUBTITLE_LINE_WIDTH
    lines = textwrap.wrap(" ".join((text or "").split()), width=width) or [""]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])])


def to_srt(cues):
    """SRT text for a list of cues. Indexes are 1-based and contiguous."""
    blocks = []
    for index, cue in enumerate(cues, start=1):
        # A zero-length or reversed cue is invalid SRT and some players drop the rest
        # of the file, so give it a minimum on-screen time.
        end = max(float(cue.end), float(cue.start) + 0.2)
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(cue.start)} --> {format_timestamp(end)}\n"
            f"{wrap_cue(cue.text)}\n"
        )
    return "\n".join(blocks)


def run_subtitles_step(step):
    video = step.video
    if not video.narration_audio_path:
        raise ValueError("No merged narration track; run narration + merge first.")

    audio = Path(settings.MEDIA_ROOT) / video.narration_audio_path
    if not audio.is_file():
        raise ValueError(f"Narration track is missing from disk: {audio}")

    total = int(video.duration_seconds or 0) or 1
    PipelineService.update_progress(
        step, current=0, total=total, message="Transcribing narration..."
    )

    def on_progress(seconds_done):
        # Progress is measured in seconds of audio, so the bar tracks the track rather
        # than an unknown number of segments.
        PipelineService.update_progress(step, current=min(int(seconds_done), total))

    provider = get_transcription_provider()
    result = provider.transcribe(
        audio, language=video.template.language or None, on_progress=on_progress
    )

    if not result.cues:
        raise ValueError(
            "Transcription produced no cues. The narration track may be silent."
        )

    PipelineService.update_progress(step, current=total, message="Writing SRT...")
    rel_path = f"videos/{video.pk}/subtitles.srt"
    out = Path(settings.MEDIA_ROOT) / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_srt(result.cues), encoding="utf-8")

    VideoRepository.update(video, subtitles_path=rel_path)

    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={
            "cues": len(result.cues),
            "language": result.language,
            "model": result.model,
            "seconds": round(result.duration or 0, 2),
        },
    )


register_executor(StepType.SUBTITLES, run_subtitles_step)
