from __future__ import annotations

import re
from pathlib import Path

import yaml

from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.schemas import DocSearchResult

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SAFE_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _infer_client_doc_type(path: Path) -> str:
    stem = path.stem.lower()
    if stem.startswith("sow"):
        return "sow"
    if "discovery" in stem:
        return "discovery_notes"
    return "client_doc"


def _extract_title(content: str, fallback: str) -> str:
    fm_match = _FRONTMATTER_RE.match(content)
    if fm_match:
        try:
            meta = yaml.safe_load(fm_match.group(1)) or {}
            if isinstance(meta, dict):
                for key in ("title", "name"):
                    if meta.get(key):
                        return str(meta[key]).strip()
        except yaml.YAMLError:
            pass

    h1_match = _H1_RE.search(content)
    if h1_match:
        return h1_match.group(1).strip()

    return fallback


def sync_context_store(
    db: ContextDB,
    store_path: str | Path | None = None,
    *,
    actor_id: str = "system",
    actor_role: str = "presales_sa",
) -> list[DocSearchResult]:
    root = Path(store_path) if store_path is not None else get_settings().context_store_path
    if not root.exists():
        raise FileNotFoundError(f"context_store directory not found: {root}")

    indexed: list[DocSearchResult] = []

    clients_dir = root / "clients"
    if clients_dir.exists():
        for client_dir in sorted(p for p in clients_dir.iterdir() if p.is_dir()):
            client_id = client_dir.name
            for md_file in sorted(client_dir.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                doc_id = f"clients/{client_id}/{md_file.name}"
                doc_type = _infer_client_doc_type(md_file)
                title = _extract_title(content, fallback=md_file.stem.replace("_", " ").title())
                record = db.upsert_doc(
                    doc_id=doc_id,
                    client_id=client_id,
                    doc_type=doc_type,
                    title=title,
                    content=content,
                )
                indexed.append(record)

    skills_dir = root / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            skill_name = skill_dir.name
            content = skill_file.read_text(encoding="utf-8")
            doc_id = f"skills/{skill_name}/SKILL.md"
            title = _extract_title(content, fallback=skill_name)
            record = db.upsert_doc(
                doc_id=doc_id,
                client_id="_global",
                doc_type="skill",
                title=title,
                content=content,
            )
            indexed.append(record)

    db.log_audit_event(
        actor_id=actor_id,
        actor_role=actor_role,
        action="sync_context_store",
        target_entity="context_store",
        details={
            "store_path": str(root),
            "indexed_count": len(indexed),
            "doc_ids": [d.doc_id for d in indexed],
        },
    )
    return indexed


def load_skill_markdown(
    skill_name: str,
    store_path: str | Path | None = None,
    *,
    db: ContextDB | None = None,
    actor_id: str = "agent",
    actor_role: str = "system",
) -> str:
    if not _SAFE_SKILL_NAME_RE.match(skill_name):
        raise ValueError(f"Invalid skill name: '{skill_name}'")

    root = Path(store_path) if store_path is not None else get_settings().context_store_path
    skill_file = root / "skills" / skill_name / "SKILL.md"

    content: str | None = None
    if skill_file.exists():
        content = skill_file.read_text(encoding="utf-8")
    elif db is not None:
        doc = db.get_doc(f"skills/{skill_name}/SKILL.md")
        if doc is not None:
            content = doc.content

    if content is None:
        raise FileNotFoundError(f"Skill '{skill_name}' not found at {skill_file}")

    if db is not None:
        db.log_audit_event(
            actor_id=actor_id,
            actor_role=actor_role,
            action="load_skill",
            target_entity=f"skill:{skill_name}",
            details={"bytes": len(content.encode("utf-8"))},
        )
    return content
