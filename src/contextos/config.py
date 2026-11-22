from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


def _default_repo_root() -> Path:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "context_store").exists():
        return candidate
    return Path.cwd()


class Settings(BaseModel):
    llm_provider: str = Field(default="groq")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="openai/gpt-oss-120b")
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    db_path: Path = Field(default_factory=lambda: Path("./contextos.db"))
    context_store_path: Path = Field(default_factory=lambda: _default_repo_root() / "context_store")
    governance_policies_path: Path = Field(
        default_factory=lambda: _default_repo_root() / "context_store" / "governance_policies.yaml"
    )


def get_settings(env_file: str | Path | None = None) -> Settings:
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(override=False)

    repo_root = _default_repo_root()
    default_store = repo_root / "context_store"
    store_path = Path(os.getenv("CONTEXTOS_STORE_PATH", str(default_store)))
    policies_path = Path(
        os.getenv(
            "CONTEXTOS_POLICIES_PATH",
            str(store_path / "governance_policies.yaml"),
        )
    )

    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "groq").strip().lower(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        db_path=Path(os.getenv("CONTEXTOS_DB_PATH", "./contextos.db")),
        context_store_path=store_path,
        governance_policies_path=policies_path,
    )
