"""Kokoro local text-to-speech provider (free). Requires the kokoro-onnx package,
the model + voices files, and espeak-ng installed. The model is loaded once and
cached, since loading is expensive."""
import os

import numpy as np
from django.conf import settings

from .base import ProviderError, TTSProvider, TTSResult

_KOKORO = None  # cached model instance


def _get_kokoro():
    global _KOKORO
    if _KOKORO is not None:
        return _KOKORO
    model_path = settings.KOKORO_MODEL_PATH
    voices_path = settings.KOKORO_VOICES_PATH
    if not (os.path.exists(model_path) and os.path.exists(voices_path)):
        raise ProviderError(
            "Kokoro model files not found. Download kokoro-v1.0.onnx and "
            "voices-v1.0.bin and set KOKORO_MODEL_PATH / KOKORO_VOICES_PATH."
        )
    try:
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        raise ProviderError(
            "kokoro-onnx is not installed. Run: pip install kokoro-onnx soundfile"
        ) from exc
    _KOKORO = Kokoro(model_path, voices_path)
    return _KOKORO


class KokoroTTSProvider(TTSProvider):
    def __init__(self, voice=None, lang=None):
        self.default_voice = voice or settings.DEFAULT_KOKORO_VOICE
        self.lang = lang or "en-us"

    def synthesize(self, text, voice_id):
        kokoro = _get_kokoro()
        voice = voice_id or self.default_voice
        try:
            samples, sample_rate = kokoro.create(
                text, voice=voice, speed=1.0, lang=self.lang
            )
        except Exception as exc:
            raise ProviderError(f"Kokoro synthesis failed: {exc}") from exc
        return TTSResult(
            samples=np.asarray(samples, dtype=np.float32),
            sample_rate=int(sample_rate),
            model="kokoro-v1.0",
            characters=len(text or ""),
        )
