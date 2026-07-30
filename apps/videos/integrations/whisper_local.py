"""Local Whisper transcription via faster-whisper (free, no API).

Optional: the package is imported lazily and the step is off unless
``SUBTITLES_ENABLED`` is set, so an install without faster-whisper works normally and
simply cannot run the subtitles step.

The model is cached per (size, device, compute type) because loading it is slow and a
worker will transcribe many videos in one process. The first run also downloads the
weights, which is why the error messages below say so explicitly — an unexplained
several-minute pause looks like a hang.
"""
import threading

from django.conf import settings

from .base import Cue, ProviderError, TranscriptionProvider, TranscriptionResult

_MODELS = {}
_LOCK = threading.Lock()


def _get_model(size, device, compute_type):
    key = (size, device, compute_type)
    cached = _MODELS.get(key)
    if cached is not None:
        return cached

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ProviderError(
            "faster-whisper is not installed, so subtitles cannot be generated. "
            "Run: pip install faster-whisper — or set SUBTITLES_ENABLED=False."
        ) from exc

    # Locked: two steps starting together would otherwise each load a copy, and the
    # model is hundreds of megabytes.
    with _LOCK:
        cached = _MODELS.get(key)
        if cached is None:
            try:
                cached = WhisperModel(size, device=device, compute_type=compute_type)
            except Exception as exc:
                raise ProviderError(
                    f"Could not load the Whisper '{size}' model on {device} "
                    f"({compute_type}): {exc}. The first run downloads the weights, "
                    "so check the network, or try WHISPER_MODEL=tiny."
                ) from exc
            _MODELS[key] = cached
    return cached


class WhisperLocalProvider(TranscriptionProvider):
    def __init__(self, model=None, device=None, compute_type=None, beam_size=None):
        self.model_size = model or settings.WHISPER_MODEL
        self.device = device or settings.WHISPER_DEVICE
        self.compute_type = compute_type or settings.WHISPER_COMPUTE_TYPE
        self.beam_size = beam_size or settings.WHISPER_BEAM_SIZE

    def transcribe(self, audio_path, language=None, on_progress=None):
        model = _get_model(self.model_size, self.device, self.compute_type)
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=language or None,
                beam_size=self.beam_size,
                vad_filter=True,
            )
        except Exception as exc:
            raise ProviderError(f"Whisper transcription failed: {exc}") from exc

        cues = []
        # `segments` is a generator: nothing is transcribed until it is consumed, so
        # this loop is where the time goes and where progress comes from.
        for segment in segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            cues.append(Cue(start=float(segment.start), end=float(segment.end), text=text))
            if on_progress is not None:
                on_progress(float(segment.end))

        return TranscriptionResult(
            cues=cues,
            language=getattr(info, "language", "") or "",
            model=f"whisper-{self.model_size}",
            duration=float(getattr(info, "duration", 0.0) or 0.0),
        )


def get_transcription_provider():
    """The configured provider. A seam for tests and for a future paid provider."""
    return WhisperLocalProvider()
