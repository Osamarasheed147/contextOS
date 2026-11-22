from __future__ import annotations

import random
import time
from typing import Any

import groq

from contextos.llm.base import LLMProvider, LLMProviderError


class GroqProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
        *,
        max_retries: int = 4,
        base_delay: float = 2.0,
        temperature: float = 0.1,
        client: Any | None = None,
    ) -> None:
        if not api_key and client is None:
            raise LLMProviderError("GROQ_API_KEY is required when LLM_PROVIDER=groq.")
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.temperature = temperature
        self.client = client or groq.Groq(api_key=api_key)

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if content is None:
                    raise LLMProviderError("Groq returned an empty message content.")
                return content
            except groq.RateLimitError as exc:
                if attempt >= self.max_retries:
                    raise LLMProviderError(
                        f"Groq rate limit exceeded after {self.max_retries + 1} attempts."
                    ) from exc
                retry_after = self._retry_after_seconds(exc)
                delay = retry_after if retry_after is not None else self.base_delay * (2**attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
            except groq.APIError as exc:
                raise LLMProviderError(f"Groq API error: {exc}") from exc

        raise LLMProviderError("Groq completion failed unexpectedly.")
