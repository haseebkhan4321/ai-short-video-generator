"""Cost estimation for paid pipeline steps.

Estimates are shown to the user BEFORE approval. Actual costs are recorded from
provider responses after each call (see ApiCallLog). Prices are approximate USD
and centralized here so they are easy to update.
"""
import math
from decimal import Decimal

from django.conf import settings

# --- Pricing (approximate, USD). Update as provider pricing changes. ---

# Text models: USD per 1,000,000 tokens (input, output).
TEXT_PRICING = {
    "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
    "gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
    "gpt-4.1-mini": {"input": Decimal("0.40"), "output": Decimal("1.60")},
}
TEXT_PRICING_FALLBACK = {"input": Decimal("0.50"), "output": Decimal("1.50")}

# Image models: USD per generated image (standard size/quality).
IMAGE_PRICING = {
    "gpt-image-1": Decimal("0.04"),
    "dall-e-3": Decimal("0.04"),
}
IMAGE_PRICING_FALLBACK = Decimal("0.05")

# ElevenLabs: USD per 1,000 characters (varies by plan; conservative default).
ELEVENLABS_PER_1K_CHARS = Decimal("0.30")

# Rough token/word ratios for pre-call estimation.
TOKENS_PER_WORD = Decimal("1.35")
CHARS_PER_WORD = Decimal("6")  # incl. spaces


def _q(value):
    """Round a Decimal to 4 places (matches model field precision)."""
    return Decimal(value).quantize(Decimal("0.0001"))


class CostEstimator:
    @staticmethod
    def target_words(target_minutes):
        return int(target_minutes) * settings.WORDS_PER_MINUTE

    @staticmethod
    def estimate_script(target_minutes, model=None):
        """Estimate the full script generation cost for the target length."""
        model = model or settings.OPENAI_TEXT_MODEL
        pricing = TEXT_PRICING.get(model, TEXT_PRICING_FALLBACK)
        words = Decimal(CostEstimator.target_words(target_minutes))
        output_tokens = words * TOKENS_PER_WORD
        # Input across continuation calls: prompt + rolling context. Approximate
        # as ~40% of output tokens in aggregate.
        input_tokens = output_tokens * Decimal("0.4")
        cost = (
            input_tokens / Decimal(1_000_000) * pricing["input"]
            + output_tokens / Decimal(1_000_000) * pricing["output"]
        )
        return _q(cost)

    @staticmethod
    def estimate_images(num_images, model=None):
        model = model or settings.OPENAI_IMAGE_MODEL
        per_image = IMAGE_PRICING.get(model, IMAGE_PRICING_FALLBACK)
        return _q(per_image * Decimal(num_images))

    @staticmethod
    def expected_parts(target_minutes):
        """How many parts the split step will produce for this target length.

        Mirrors split_service: it fills each part up to
        ``WORDS_PER_MINUTE * TARGET_MINUTES_PER_PART`` words, so the count follows from
        the target minutes. Kept as its own function precisely so a projection cannot
        drift from what the split actually does.
        """
        per_part = max(1, settings.TARGET_MINUTES_PER_PART)
        return max(1, math.ceil(int(target_minutes) / per_part))

    @staticmethod
    def estimate_video(target_minutes, text_model=None, image_model=None):
        """Projected cost of the whole pipeline, before any of it exists.

        Used by the up-front approval, so a person can authorize a video's spend once
        instead of clicking through every step. Narration, splitting, merging and
        rendering are all local, so images dominate and the script is a rounding error.

        Returns a breakdown rather than a single number: "Rs 780" invites a shrug, and
        "48 images at Rs 11.20 each" invites a decision.
        """
        parts = CostEstimator.expected_parts(target_minutes)
        images = parts * settings.IMAGES_PER_PART
        script_cost = CostEstimator.estimate_script(target_minutes, text_model)
        images_cost = CostEstimator.estimate_images(images, image_model)
        return {
            "parts": parts,
            "images": images,
            "images_per_part": settings.IMAGES_PER_PART,
            "script_usd": script_cost,
            "images_usd": images_cost,
            "per_image_usd": IMAGE_PRICING.get(
                image_model or settings.OPENAI_IMAGE_MODEL, IMAGE_PRICING_FALLBACK
            ),
            "total_usd": _q(script_cost + images_cost),
        }

    @staticmethod
    def estimate_narration_chars(num_chars):
        return _q(Decimal(num_chars) / Decimal(1000) * ELEVENLABS_PER_1K_CHARS)

    @staticmethod
    def estimate_narration_for_text(text):
        return CostEstimator.estimate_narration_chars(len(text or ""))

    # --- Actual-cost helpers (called after a provider response) ---

    @staticmethod
    def actual_text_cost(model, input_tokens, output_tokens):
        pricing = TEXT_PRICING.get(model, TEXT_PRICING_FALLBACK)
        cost = (
            Decimal(input_tokens) / Decimal(1_000_000) * pricing["input"]
            + Decimal(output_tokens) / Decimal(1_000_000) * pricing["output"]
        )
        return _q(cost)

    @staticmethod
    def actual_image_cost(model, num_images):
        per_image = IMAGE_PRICING.get(model, IMAGE_PRICING_FALLBACK)
        return _q(per_image * Decimal(num_images))

    @staticmethod
    def actual_narration_cost(num_chars):
        return CostEstimator.estimate_narration_chars(num_chars)
