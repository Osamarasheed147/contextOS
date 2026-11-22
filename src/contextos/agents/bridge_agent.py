from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from contextos.governance import GovernedContextService
from contextos.llm.base import LLMProvider
from contextos.loader import load_skill_markdown
from contextos.schemas import ChangeRequest

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"raw_response": raw_text}


def _format_docs_for_prompt(docs: list[dict[str, Any]], max_chars_per_doc: int = 3500) -> str:
    if not docs:
        return "No matching documents found."
    chunks: list[str] = []
    for doc in docs:
        content = str(doc.get("content", ""))[:max_chars_per_doc]
        chunks.append(f"### {doc.get('doc_id')} ({doc.get('doc_type')})\n{content}")
    return "\n\n".join(chunks)


class BridgeAgent:
    def __init__(
        self,
        service: GovernedContextService,
        llm: LLMProvider,
        store_path: str | Path | None = None,
    ) -> None:
        self.service = service
        self.llm = llm
        self.store_path = Path(store_path) if store_path is not None else None

    def check_scope_creep(
        self,
        project_id: str,
        client_request: str,
        *,
        requested_by: str = "Client Stakeholder",
        role: str = "pm",
        actor_id: str = "bridge_agent",
        auto_log_cr: bool = True,
    ) -> dict[str, Any]:
        context = self.service.get_project_context(project_id, role=role, actor_id=actor_id)
        client_id = context["project"]["client_id"]

        docs = self.service.search_client_docs(
            client_id=client_id,
            query=client_request,
            role=role,
            actor_id=actor_id,
            limit=5,
        )
        skill_md = load_skill_markdown(
            "scope_creep_check",
            store_path=self.store_path,
            db=self.service.db,
            actor_id=actor_id,
            actor_role=role,
        )

        system_prompt = (
            "You are the ContextOS Pre-Sales to Delivery Bridge Agent. "
            "Follow the loaded SKILL.md rubric strictly and return valid JSON only.\n\n"
            f"{skill_md}"
        )
        user_prompt = (
            f"## Structured Governed Context (role={role})\n"
            f"```json\n{json.dumps(context, indent=2)}\n```\n\n"
            f"## Retrieved Client Documents (SOW & Discovery Notes)\n"
            f"{_format_docs_for_prompt(docs)}\n\n"
            f"## Incoming Client Request\n"
            f"Requested by: {requested_by}\n"
            f"Message: {client_request}\n\n"
            "Return the JSON evaluation object specified by the skill rubric."
        )

        raw = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt, json_mode=True)
        result = _parse_json_response(raw)

        verdict = str(result.get("verdict", "")).upper()
        should_log = bool(result.get("should_create_change_request")) or verdict == "OUT_OF_SCOPE_BILLABLE"

        logged_cr: dict[str, Any] | None = None
        if auto_log_cr and should_log:
            cr = ChangeRequest(
                id=f"cr_{uuid4().hex[:8]}",
                project_id=project_id,
                requested_by=requested_by,
                description=client_request,
                scope_verdict=verdict or "OUT_OF_SCOPE_BILLABLE",
                approval_status="pending",
            )
            saved = self.service.submit_change_request(cr, role=role, actor_id=actor_id)
            logged_cr = saved.model_dump()

        return {
            "role": role,
            "project_id": project_id,
            "evaluation": result,
            "change_request": logged_cr,
            "governance_metadata": context["governance_metadata"],
        }

    def check_cloud_guardrails(
        self,
        project_id: str,
        proposal: str,
        *,
        role: str = "delivery_dev",
        actor_id: str = "bridge_agent",
    ) -> dict[str, Any]:
        context = self.service.get_project_context(project_id, role=role, actor_id=actor_id)
        client_id = context["project"]["client_id"]

        docs = self.service.search_client_docs(
            client_id=client_id,
            query=f"{proposal} cloud residency budget guardrail",
            role=role,
            actor_id=actor_id,
            limit=5,
        )
        skill_md = load_skill_markdown(
            "cloud_guardrail_check",
            store_path=self.store_path,
            db=self.service.db,
            actor_id=actor_id,
            actor_role=role,
        )

        system_prompt = (
            "You are the ContextOS Cloud Guardrail Review Agent. "
            "Follow the loaded SKILL.md rubric strictly and return valid JSON only.\n\n"
            f"{skill_md}"
        )
        user_prompt = (
            f"## Structured Governed Context (role={role})\n"
            f"```json\n{json.dumps(context, indent=2)}\n```\n\n"
            f"## Retrieved Client Documents (SOW & Discovery Notes)\n"
            f"{_format_docs_for_prompt(docs)}\n\n"
            f"## Proposed Cloud / DevOps Architecture\n"
            f"{proposal}\n\n"
            "Return the JSON compliance check object specified by the skill rubric."
        )

        raw = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt, json_mode=True)
        result = _parse_json_response(raw)

        return {
            "role": role,
            "project_id": project_id,
            "evaluation": result,
            "governance_metadata": context["governance_metadata"],
        }
