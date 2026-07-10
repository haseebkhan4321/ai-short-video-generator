"""Narration step (per part) + merge step (video-level).

Narration: synthesize a part's text with the active TTS provider, saving a WAV
under media/. Long parts are chunked to stay within provider limits.

Merge: concatenate all part WAVs into one narration track, record each part's
start/end offset and the video's total duration. Both registered as executors.
"""
import re
from decimal import Decimal
from pathlib import Path

import numpy as np
import soundfile as sf
from django.conf import settings

from ..integrations.base import ProviderError
from ..integrations.kokoro_provider import KokoroTTSProvider
from ..models import StepType
from ..repositories import ChapterRepository, VideoRepository
from .pipeline import PipelineService, StepResult, register_executor


def get_tts_provider(name=None):
    """Return the TTS provider (Kokoro, local/free). Overridable in tests."""
    return KokoroTTSProvider()


def _chunk_text(text, max_chars):
    """Split text into <= max_chars chunks on sentence boundaries."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        elif len(sentence) > max_chars:
            # A single very long sentence: hard-split by words.
            words = sentence.split()
            buf = current
            for w in words:
                if len(buf) + len(w) + 1 > max_chars:
                    chunks.append(buf.strip())
                    buf = w
                else:
                    buf = f"{buf} {w}".strip()
            current = buf
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks


def run_narration_step(step):
    chapter = step.chapter
    if chapter is None:
        raise ValueError("Narration step has no associated part.")
    video = step.video
    payload = step.request_payload or {}
    voice = payload.get("voice_id") or ""

    text = chapter.body or ""
    if not text.strip():
        raise ValueError("Cannot narrate: the part has no text.")

    chunks = _chunk_text(text, settings.MAX_TTS_CHARS)
    provider = get_tts_provider()

    PipelineService.update_progress(
        step, current=0, total=len(chunks), message="Synthesizing narration..."
    )

    all_samples = []
    sample_rate = settings.TTS_SAMPLE_RATE
    for i, chunk in enumerate(chunks, start=1):
        PipelineService.update_progress(
            step, current=i, message=f"Synthesizing part audio {i}/{len(chunks)}"
        )
        result = provider.synthesize(chunk, voice)
        all_samples.append(np.asarray(result.samples, dtype=np.float32))
        sample_rate = result.sample_rate

    if not all_samples:
        raise ProviderError("TTS returned no audio.")
    samples = np.concatenate(all_samples)

    rel_dir = f"videos/{video.pk}/parts/{chapter.chapter_number:02d}"
    abs_dir = Path(settings.MEDIA_ROOT) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"{rel_dir}/narration.wav"
    sf.write(str(Path(settings.MEDIA_ROOT) / rel_path), samples, sample_rate)

    duration = len(samples) / float(sample_rate)
    ChapterRepository.update(
        chapter, narration_audio_path=rel_path, audio_end_seconds=duration
    )

    # Kokoro runs locally and is free.
    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={
            "provider": "kokoro", "chunks": len(chunks),
            "seconds": round(duration, 2),
        },
        api_calls=[],
    )


def run_merge_step(step):
    """Concatenate all part narration WAVs into one track and record offsets."""
    video = step.video
    chapters = list(ChapterRepository.for_video(video.pk))
    parts = [c for c in chapters if c.narration_audio_path]
    if not parts:
        raise ValueError("No narrated parts to merge.")

    PipelineService.update_progress(
        step, current=0, total=len(parts), message="Merging narration..."
    )

    merged = []
    sample_rate = settings.TTS_SAMPLE_RATE
    cursor = 0.0
    for i, chapter in enumerate(parts, start=1):
        path = Path(settings.MEDIA_ROOT) / chapter.narration_audio_path
        data, sr = sf.read(str(path), dtype="float32")
        if data.ndim > 1:  # force mono
            data = data.mean(axis=1)
        sample_rate = sr
        start = cursor
        end = cursor + len(data) / float(sr)
        ChapterRepository.update(
            chapter, audio_start_seconds=start, audio_end_seconds=end
        )
        merged.append(data)
        cursor = end
        PipelineService.update_progress(step, current=i)

    full = np.concatenate(merged)
    rel_path = f"videos/{video.pk}/narration.wav"
    sf.write(str(Path(settings.MEDIA_ROOT) / rel_path), full, sample_rate)

    total_seconds = len(full) / float(sample_rate)
    VideoRepository.update(
        video, narration_audio_path=rel_path, duration_seconds=total_seconds
    )

    return StepResult(
        actual_cost_usd=Decimal("0"),
        response_metadata={"parts": len(parts), "seconds": round(total_seconds, 2)},
    )


register_executor(StepType.NARRATION, run_narration_step)
register_executor(StepType.MERGE, run_merge_step)
