"""Script step: generate the full 1-2 hour script via sequential continuation
calls, then store it on the video. Registered as the 'script' executor."""
import json
import math
from decimal import Decimal

from ..integrations.openai_provider import OpenAILLMProvider
from ..models import StepType
from ..repositories import VideoRepository
from .cost_estimator import CostEstimator
from .pipeline import PipelineService, StepResult, register_executor

# Approximate words to request per continuation call. Kept well within model
# output limits so each call completes reliably.
CHUNK_WORDS = 1800
TAIL_CONTEXT_WORDS = 800


def get_llm_provider(model=None):
    """Provider factory (overridable in tests to avoid real API calls)."""
    return OpenAILLMProvider(model=model)


def _word_count(text):
    return len((text or "").split())


def _last_words(text, n):
    words = (text or "").split()
    return " ".join(words[-n:])


def _system_prompt(style_prompt):
    base = (
        "You are a professional long-form storyteller writing narration to be read "
        "aloud by a single narrator over a 1 to 2 hour video. Write immersive, "
        "flowing prose in a consistent voice and tense. Do not include scene labels, "
        "headings, stage directions, markdown, or calls to action like 'subscribe'. "
        "Output only the narration text."
    )
    if style_prompt:
        base += "\n\nStyle guidance for this channel:\n" + style_prompt
    return base


def _first_user_prompt(premise, target_words):
    return (
        "Write the BEGINNING of a continuous story for narration.\n"
        f"Premise: {premise}\n\n"
        f"The complete story should run about {target_words} words in total. "
        f"For THIS response, write approximately {CHUNK_WORDS} words that open the "
        "story with a strong hook, establish the setting and characters, and then "
        "stop mid-story (do NOT conclude).\n\n"
        "Return a JSON object with exactly these keys:\n"
        '  "title": a compelling video title,\n'
        '  "description": a 2-3 sentence description,\n'
        '  "hashtags": an array of 5-8 short tags each starting with #,\n'
        '  "body": the opening narration text (the ~'
        f'{CHUNK_WORDS} words).'
    )


def _continuation_prompt(tail, remaining_words, is_final):
    if is_final:
        return (
            "Continue the following story and bring it to a satisfying conclusion in "
            f"approximately {remaining_words} more words. Keep the same voice and "
            "tense. Do NOT repeat earlier text or summarize.\n\n"
            f"...{tail}"
        )
    return (
        "Continue the following story naturally in the same voice and tense. Write "
        f"approximately {CHUNK_WORDS} more words. Do NOT repeat earlier text, do NOT "
        "summarize, and do NOT conclude the story yet.\n\n"
        f"...{tail}"
    )


def _record_call(response):
    cost = CostEstimator.actual_text_cost(
        response.model, response.input_tokens, response.output_tokens
    )
    return {
        "provider": "openai",
        "endpoint": "chat.completions",
        "model": response.model,
        "units": {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        },
        "cost_usd": cost,
        "duration_ms": None,
    }


def run_script_step(step):
    payload = step.request_payload or {}
    target_words = int(payload.get("target_words") or 0)
    premise = payload.get("premise", "")
    style_prompt = payload.get("style_prompt", "")
    model = payload.get("model")

    provider = get_llm_provider(model=model)
    system = _system_prompt(style_prompt)
    api_calls = []

    est_calls = math.ceil(max(target_words, 1) / CHUNK_WORDS)
    PipelineService.update_progress(
        step, current=0, total=est_calls, message="Writing opening..."
    )

    # --- First call: metadata + opening body (JSON) ---
    first = provider.complete(system, _first_user_prompt(premise, target_words),
                              json_mode=True)
    api_calls.append(_record_call(first))

    title, description, hashtags, body = "", "", [], ""
    try:
        data = json.loads(first.text)
        title = (data.get("title") or "").strip()
        description = (data.get("description") or "").strip()
        hashtags = data.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.split() if h.strip()]
        body = (data.get("body") or data.get("script") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        # Fall back to using the raw text as the opening body.
        body = (first.text or "").strip()

    script = body
    words = _word_count(script)
    PipelineService.update_progress(
        step, current=1, message=f"Opening written ({words} words)"
    )

    # --- Continuation calls until the target length is reached ---
    max_iterations = math.ceil(max(target_words, 1) / CHUNK_WORDS) + 4
    iterations = 1
    while words < target_words and iterations < max_iterations:
        remaining = target_words - words
        is_final = remaining <= CHUNK_WORDS
        tail = _last_words(script, TAIL_CONTEXT_WORDS)
        PipelineService.update_progress(
            step,
            current=iterations + 1,
            message=f"Writing part {iterations + 1} of ~{est_calls} ({words} words)",
        )
        cont = provider.complete(
            system, _continuation_prompt(tail, remaining, is_final), json_mode=False
        )
        api_calls.append(_record_call(cont))
        chunk_text = (cont.text or "").strip()
        if not chunk_text:
            break
        script += "\n\n" + chunk_text
        words = _word_count(script)
        iterations += 1

    PipelineService.update_progress(
        step, current=est_calls, message=f"Finalizing ({words} words)"
    )

    VideoRepository.update(
        step.video,
        title=title[:300] if title else (premise[:120]),
        script=script,
        description=description,
        hashtags=hashtags,
        total_words=words,
    )

    actual_cost = sum((c["cost_usd"] for c in api_calls), Decimal("0"))
    return StepResult(
        actual_cost_usd=actual_cost,
        response_metadata={
            "words": words,
            "calls": len(api_calls),
            "model": model,
            "reached_target": words >= target_words,
        },
        api_calls=api_calls,
    )


# Register with the pipeline.
register_executor(StepType.SCRIPT, run_script_step)
