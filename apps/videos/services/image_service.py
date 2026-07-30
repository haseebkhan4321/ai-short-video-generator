"""Images step: for one part, generate image prompts from its text, then create
the images and save them under media/. Registered as the 'images' executor.

Each images step is per-chapter (step.chapter is set)."""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from ..integrations.openai_provider import OpenAILLMProvider, OpenAIImageProvider
from ..models import StepType
from ..repositories import ChapterImageRepository
from .cost_estimator import CostEstimator
from .pipeline import PipelineService, StepResult, register_executor

EXCERPT_WORDS = 500


def get_llm_provider(model=None):
    return OpenAILLMProvider(model=model)


def get_image_provider(model=None):
    return OpenAIImageProvider(model=model)


def _excerpt(text, n=EXCERPT_WORDS):
    return " ".join((text or "").split()[:n])


def _prompt_system(style_prompt):
    base = (
        "You write vivid, concrete prompts for an image model to produce cinematic "
        "16:9 still frames illustrating a passage of narration. Each prompt is one "
        "self-contained scene with concrete visual detail (setting, subject, lighting, "
        "mood, camera framing). No text, captions, watermarks, or logos in the image."
    )
    if style_prompt:
        base += "\n\nChannel visual style:\n" + style_prompt
    return base


def _prompt_user(excerpt, n):
    return (
        f"From the following passage, write {n} DISTINCT image prompts that together "
        "illustrate its key moments in order. Return a JSON object with a single key "
        '"prompts" whose value is an array of '
        f"{n} strings.\n\nPassage:\n{excerpt}"
    )


def _generate_prompts(llm, chapter, style_prompt, n):
    """Return a list of n image prompts (falls back to simple prompts on error)."""
    excerpt = _excerpt(chapter.body)
    resp = llm.complete(_prompt_system(style_prompt), _prompt_user(excerpt, n),
                        json_mode=True)
    prompts = []
    try:
        data = json.loads(resp.text)
        prompts = data.get("prompts") or []
        if isinstance(prompts, str):
            prompts = [prompts]
    except (json.JSONDecodeError, AttributeError):
        prompts = []
    # Normalize to exactly n prompts.
    prompts = [p for p in prompts if isinstance(p, str) and p.strip()]
    if not prompts:
        prompts = [f"Cinematic still: {_excerpt(chapter.body, 40)}"]
    # Pad to n by cycling through what we have.
    original = list(prompts)
    while len(prompts) < n:
        prompts.append(original[len(prompts) % len(original)])
    return prompts[:n], resp


def run_images_step(step):
    chapter = step.chapter
    if chapter is None:
        raise ValueError("Images step has no associated part.")

    video = step.video
    payload = step.request_payload or {}
    num_images = int(payload.get("num_images") or settings.IMAGES_PER_PART)
    image_model = payload.get("model") or settings.OPENAI_IMAGE_MODEL
    style_prompt = video.template.style_prompt

    api_calls = []
    PipelineService.update_progress(
        step, current=0, total=num_images + 1, message="Writing image prompts..."
    )

    # 1) Prompts (one cheap text call).
    llm = get_llm_provider()
    prompts, prompt_resp = _generate_prompts(llm, chapter, style_prompt, num_images)
    api_calls.append({
        "provider": "openai", "endpoint": "chat.completions",
        "model": prompt_resp.model,
        "units": {"input_tokens": prompt_resp.input_tokens,
                  "output_tokens": prompt_resp.output_tokens},
        "cost_usd": CostEstimator.actual_text_cost(
            prompt_resp.model, prompt_resp.input_tokens, prompt_resp.output_tokens),
        "duration_ms": None,
    })

    # 2) Images.
    provider = get_image_provider(model=image_model)
    rel_dir = f"videos/{video.pk}/parts/{chapter.chapter_number:02d}"
    abs_dir = Path(settings.MEDIA_ROOT) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    ChapterImageRepository.delete_for_chapter(chapter.pk)  # idempotent re-runs

    for i, prompt in enumerate(prompts, start=1):
        PipelineService.update_progress(
            step, current=i, message=f"Generating image {i} of {num_images}"
        )
        images = provider.generate(prompt, n=1)
        if not images:
            raise ValueError(f"Image model returned no image for prompt {i}.")
        fname = f"img_{i}.png"
        (abs_dir / fname).write_bytes(images[0])
        rel_path = f"{rel_dir}/{fname}"
        ChapterImageRepository.create(
            chapter=chapter, order=i, image_prompt=prompt, image_path=rel_path
        )
        api_calls.append({
            "provider": "openai", "endpoint": "images.generate",
            "model": image_model, "units": {"images": 1},
            "cost_usd": CostEstimator.actual_image_cost(image_model, 1),
            "duration_ms": None,
        })

    PipelineService.update_progress(
        step, current=num_images + 1, message="Done"
    )
    actual_cost = sum((c["cost_usd"] for c in api_calls), Decimal("0"))
    return StepResult(
        actual_cost_usd=actual_cost,
        response_metadata={"images": len(prompts), "model": image_model},
        api_calls=api_calls,
    )


register_executor(StepType.IMAGES, run_images_step)
