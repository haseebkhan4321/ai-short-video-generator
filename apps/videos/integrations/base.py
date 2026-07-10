"""Provider-agnostic interfaces. Services depend on these, not on concrete SDKs,
so a provider can be swapped without touching business logic."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TTSResult:
    # samples: a numpy float32 mono array in [-1, 1]
    samples: object
    sample_rate: int
    model: str = ""
    characters: int = 0


class LLMProvider(ABC):
    """Text generation (chat completion)."""

    @abstractmethod
    def complete(self, system_prompt, user_prompt, json_mode=False, max_tokens=None):
        """Return an LLMResponse. If json_mode, the model is asked to return JSON."""
        raise NotImplementedError


class ImageProvider(ABC):
    """Image generation (used by the images step, milestone 6)."""

    @abstractmethod
    def generate(self, prompt, size, n=1):
        raise NotImplementedError


class TTSProvider(ABC):
    """Text-to-speech (used by the narration step, milestone 7).

    Implementations return a TTSResult with mono float32 samples so parts can be
    concatenated with numpy (no ffmpeg needed for the merge)."""

    @abstractmethod
    def synthesize(self, text, voice_id):
        raise NotImplementedError


class ProviderError(Exception):
    """Raised by providers on configuration or API failure."""
