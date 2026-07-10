"""OpenAI-backed text and image providers."""
import base64

from django.conf import settings

from .base import ImageProvider, LLMProvider, LLMResponse, ProviderError


def _make_client(api_key):
    if not api_key:
        raise ProviderError(
            "OPENAI_API_KEY is not set. Add it to your .env before approving this step."
        )
    # Imported lazily so the app runs without the key configured.
    from openai import OpenAI

    return OpenAI(api_key=api_key)


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_TEXT_MODEL

    def complete(self, system_prompt, user_prompt, json_mode=False, max_tokens=None):
        client = _make_client(self.api_key)
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class OpenAIImageProvider(ImageProvider):
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_IMAGE_MODEL

    def default_size(self):
        # Closest available landscape size per model (render crops to 16:9).
        if self.model.startswith("dall-e"):
            return "1792x1024"
        return "1536x1024"  # gpt-image-1

    def generate(self, prompt, size=None, n=1):
        client = _make_client(self.api_key)
        kwargs = {"model": self.model, "prompt": prompt,
                  "size": size or self.default_size(), "n": n}
        # dall-e-* need an explicit b64 request; gpt-image-1 returns b64 by default.
        if self.model.startswith("dall-e"):
            kwargs["response_format"] = "b64_json"

        try:
            resp = client.images.generate(**kwargs)
        except Exception as exc:
            raise ProviderError(f"OpenAI image request failed: {exc}") from exc

        images = []
        for item in resp.data:
            b64 = getattr(item, "b64_json", None)
            if b64:
                images.append(base64.b64decode(b64))
                continue
            url = getattr(item, "url", None)
            if url:
                import urllib.request

                with urllib.request.urlopen(url) as r:
                    images.append(r.read())
        return images
