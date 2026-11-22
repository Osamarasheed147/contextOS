from __future__ import annotations

import time
from typing import Any

from contextos.llm.base import LLMProvider, LLMProviderError


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        *,
        max_retries: int = 3,
        base_delay: float = 2.0,
        temperature: float = 0.1,
        client: Any | None = None,
    ) -> None:
        if not api_key and client is None:
            raise LLMProviderError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini.")
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.temperature = temperature
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> tuple[Any, Any]:
        if self._client is not None:
            return self._client, None
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMProviderError(
                "google-genai is not installed. Run: pip install 'contextos[gemini]' or pip install google-genai"
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client, types

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        client, types_mod = self._get_client()

        config: dict[str, Any] | Any
        if types_mod is not None:
            cfg_kwargs: dict[str, Any] = {
                "system_instruction": system_prompt,
                "temperature": self.temperature,
            }
            if json_mode:
                cfg_kwargs["response_mime_type"] = "application/json"
            config = types_mod.GenerateContentConfig(**cfg_kwargs)
        else:
            config = {
                "system_instruction": system_prompt,
                "temperature": self.temperature,
                **({"response_mime_type": "application/json"} if json_mode else {}),
            }

        for attempt in range(self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )
                text = getattr(response, "text", None)
                if not text:
                    raise LLMProviderError("Gemini returned an empty response.")
                return str(text)
            except LLMProviderError:
                raise
            except Exception as exc:
                is_rate_limit = getattr(exc, "code", None) == 429 or "429" in str(exc)
                if is_rate_limit and attempt < self.max_retries:
                    time.sleep(self.base_delay * (2**attempt))
                    continue
                raise LLMProviderError(f"Gemini API error: {exc}") from exc

        raise LLMProviderError("Gemini completion failed unexpectedly.")
