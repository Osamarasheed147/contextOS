from __future__ import annotations

from contextos.config import Settings, get_settings
from contextos.llm.base import LLMProvider, LLMProviderError
from contextos.llm.gemini_provider import GeminiProvider
from contextos.llm.groq_provider import GroqProvider


def create_llm_provider(settings: Settings | None = None) -> LLMProvider:
    cfg = settings or get_settings()
    provider_name = cfg.llm_provider.strip().lower()

    if provider_name == "groq":
        return GroqProvider(api_key=cfg.groq_api_key, model=cfg.groq_model)
    if provider_name == "gemini":
        return GeminiProvider(api_key=cfg.gemini_api_key, model=cfg.gemini_model)

    raise LLMProviderError(f"Unsupported LLM_PROVIDER '{cfg.llm_provider}'. Expected 'groq' or 'gemini'.")
