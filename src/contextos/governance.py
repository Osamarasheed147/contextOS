from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.schemas import ChangeRequest, Client, Guardrail, Project, ScopeItem

REDACTION_MARKER = "[REDACTED_BY_POLICY]"


class GovernanceError(PermissionError):
    pass


class GovernanceEngine:
    def __init__(self, policies_path: str | Path | None = None) -> None:
        resolved = Path(policies_path) if policies_path is not None else get_settings().governance_policies_path
        self.policies_path = resolved
        if not self.policies_path.exists():
            raise FileNotFoundError(f"Governance policy file not found: {self.policies_path}")

        with self.policies_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        self.version: str = str(raw.get("version", "1.0"))
        self.redaction_marker: str = str(raw.get("redaction_marker", REDACTION_MARKER))
        self.roles: dict[str, dict[str, Any]] = raw.get("roles", {})

    def _get_entity_policy(self, role: str, entity_type: str) -> dict[str, Any] | None:
        role_cfg = self.roles.get(role)
        if not role_cfg:
            return None
        return role_cfg.get("entities", {}).get(entity_type)

    def list_roles(self) -> list[str]:
        return sorted(self.roles.keys())

    def get_redacted_fields(self, role: str, entity_type: str) -> list[str]:
        entity_policy = self._get_entity_policy(role, entity_type)
        if entity_policy is None:
            return []
        return list(entity_policy.get("redacted_fields", []))

    def check_read_permission(self, role: str, entity_type: str) -> bool:
        entity_policy = self._get_entity_policy(role, entity_type)
        if entity_policy is None:
            return False
        allowed = [str(a).lower() for a in entity_policy.get("allowed_actions", [])]
        return "read" in allowed

    def check_write_permission(self, role: str, entity_type: str, action: str) -> bool:
        normalized = action.strip().lower()
        if not normalized or normalized == "read":
            return False
        entity_policy = self._get_entity_policy(role, entity_type)
        if entity_policy is None:
            return False
        allowed = {str(a).lower() for a in entity_policy.get("allowed_actions", [])}
        return normalized in allowed

    def apply_read_policy(
        self,
        data: dict[str, Any],
        role: str,
        entity_type: str,
    ) -> dict[str, Any]:
        if role not in self.roles:
            raise GovernanceError(f"Unknown role '{role}' cannot read entity '{entity_type}'.")
        if not self.check_read_permission(role, entity_type):
            raise GovernanceError(f"Role '{role}' is not permitted to read entity '{entity_type}'.")

        sanitized = copy.deepcopy(data)
        for field_name in self.get_redacted_fields(role, entity_type):
            if field_name in sanitized:
                sanitized[field_name] = self.redaction_marker
        return sanitized


@lru_cache(maxsize=8)
def _load_cached_engine(policies_path_str: str) -> GovernanceEngine:
    return GovernanceEngine(Path(policies_path_str))


def get_governance_engine(policies_path: str | Path | None = None) -> GovernanceEngine:
    resolved = Path(policies_path) if policies_path is not None else get_settings().governance_policies_path
    return _load_cached_engine(str(resolved.resolve()))


def apply_read_policy(
    data: dict[str, Any],
    role: str,
    entity_type: str,
    *,
    policies_path: str | Path | None = None,
) -> dict[str, Any]:
    engine = get_governance_engine(policies_path)
    return engine.apply_read_policy(data=data, role=role, entity_type=entity_type)


def check_write_permission(
    role: str,
    entity_type: str,
    action: str,
    *,
    policies_path: str | Path | None = None,
) -> bool:
    engine = get_governance_engine(policies_path)
    return engine.check_write_permission(role=role, entity_type=entity_type, action=action)


class GovernedContextService:
    def __init__(
        self,
        db: ContextDB,
        engine: GovernanceEngine | None = None,
    ) -> None:
        self.db = db
        self.engine = engine or get_governance_engine()

    def _assert_write(
        self,
        *,
        actor_id: str,
        role: str,
        entity_type: str,
        action: str,
        target_entity: str,
    ) -> None:
        if not self.engine.check_write_permission(role, entity_type, action):
            self.db.log_audit_event(
                actor_id=actor_id,
                actor_role=role,
                action=f"denied_{action}_{entity_type.lower()}",
                target_entity=target_entity,
                details={"allowed": False, "entity_type": entity_type, "requested_action": action},
            )
            raise GovernanceError(
                f"Role '{role}' is not permitted to perform '{action}' on '{entity_type}'."
            )

    def get_project_context(
        self,
        project_id: str,
        role: str,
        *,
        actor_id: str = "agent",
    ) -> dict[str, Any]:
        if not self.engine.check_read_permission(role, "Project"):
            self.db.log_audit_event(
                actor_id=actor_id,
                actor_role=role,
                action="denied_read_project_context",
                target_entity=f"project:{project_id}",
                details={"allowed": False},
            )
            raise GovernanceError(f"Role '{role}' cannot read Project context.")

        project = self.db.get_project(project_id, actor_id=actor_id, actor_role=role, audit=False)
        if project is None:
            self.db.log_audit_event(
                actor_id=actor_id,
                actor_role=role,
                action="read_project_context",
                target_entity=f"project:{project_id}",
                details={"found": False},
            )
            raise KeyError(f"Project '{project_id}' not found.")

        client = self.db.get_client(project.client_id, actor_id=actor_id, actor_role=role, audit=False)
        scope_items = self.db.list_scope_items(project_id, actor_id=actor_id, actor_role=role, audit=False)
        guardrails = self.db.list_guardrails(project_id, actor_id=actor_id, actor_role=role, audit=False)
        change_requests = self.db.list_change_requests(project_id, actor_id=actor_id, actor_role=role, audit=False)

        redacted_project = self.engine.apply_read_policy(project.model_dump(), role, "Project")
        redacted_client = (
            self.engine.apply_read_policy(client.model_dump(), role, "Client") if client else None
        )
        redacted_scope = [
            self.engine.apply_read_policy(item.model_dump(), role, "ScopeItem")
            for item in scope_items
        ]
        redacted_guardrails = [
            self.engine.apply_read_policy(g.model_dump(), role, "Guardrail")
            for g in guardrails
        ]
        redacted_crs = [
            self.engine.apply_read_policy(cr.model_dump(), role, "ChangeRequest")
            for cr in change_requests
        ]

        redacted_fields = self.engine.get_redacted_fields(role, "Project")
        self.db.log_audit_event(
            actor_id=actor_id,
            actor_role=role,
            action="read_project_context",
            target_entity=f"project:{project_id}",
            details={
                "found": True,
                "redacted_fields": redacted_fields,
                "scope_item_count": len(redacted_scope),
                "guardrail_count": len(redacted_guardrails),
            },
        )

        return {
            "client": redacted_client,
            "project": redacted_project,
            "scope_items": redacted_scope,
            "guardrails": redacted_guardrails,
            "change_requests": redacted_crs,
            "governance_metadata": {
                "role": role,
                "redacted_project_fields": redacted_fields,
            },
        }

    def save_client(self, client: Client, role: str, *, actor_id: str = "agent") -> Client:
        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="Client",
            action="write",
            target_entity=f"client:{client.id}",
        )
        return self.db.upsert_client(client, actor_id=actor_id, actor_role=role, audit=True)

    def save_project(self, project: Project, role: str, *, actor_id: str = "agent") -> Project:
        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="Project",
            action="write",
            target_entity=f"project:{project.id}",
        )
        return self.db.upsert_project(project, actor_id=actor_id, actor_role=role, audit=True)

    def save_scope_item(self, item: ScopeItem, role: str, *, actor_id: str = "agent") -> ScopeItem:
        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="ScopeItem",
            action="write",
            target_entity=f"project:{item.project_id}/scope_item:{item.id}",
        )
        return self.db.upsert_scope_item(item, actor_id=actor_id, actor_role=role, audit=True)

    def save_guardrail(self, guardrail: Guardrail, role: str, *, actor_id: str = "agent") -> Guardrail:
        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="Guardrail",
            action="write",
            target_entity=f"project:{guardrail.project_id}/guardrail:{guardrail.id}",
        )
        return self.db.upsert_guardrail(guardrail, actor_id=actor_id, actor_role=role, audit=True)

    def submit_change_request(
        self,
        change_request: ChangeRequest,
        role: str,
        *,
        actor_id: str = "agent",
    ) -> ChangeRequest:
        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="ChangeRequest",
            action="submit",
            target_entity=f"project:{change_request.project_id}/change_request:{change_request.id}",
        )
        if change_request.approval_status == "approved":
            self._assert_write(
                actor_id=actor_id,
                role=role,
                entity_type="ChangeRequest",
                action="approve",
                target_entity=f"project:{change_request.project_id}/change_request:{change_request.id}",
            )
        return self.db.upsert_change_request(
            change_request,
            actor_id=actor_id,
            actor_role=role,
            audit=True,
        )

    def approve_change_request(
        self,
        cr_id: str,
        role: str,
        *,
        actor_id: str = "agent",
        scope_verdict: str | None = None,
    ) -> ChangeRequest:
        existing = self.db.get_change_request(cr_id, actor_id=actor_id, actor_role=role, audit=False)
        if existing is None:
            raise KeyError(f"ChangeRequest '{cr_id}' not found.")

        self._assert_write(
            actor_id=actor_id,
            role=role,
            entity_type="ChangeRequest",
            action="approve",
            target_entity=f"project:{existing.project_id}/change_request:{cr_id}",
        )
        updated = existing.model_copy(
            update={
                "approval_status": "approved",
                "scope_verdict": scope_verdict or existing.scope_verdict,
            }
        )
        return self.db.upsert_change_request(updated, actor_id=actor_id, actor_role=role, audit=True)

    def search_client_docs(
        self,
        client_id: str,
        query: str,
        role: str,
        *,
        actor_id: str = "agent",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not self.engine.check_read_permission(role, "Document"):
            self.db.log_audit_event(
                actor_id=actor_id,
                actor_role=role,
                action="denied_search_docs",
                target_entity=f"client:{client_id}",
                details={"allowed": False, "query": query},
            )
            raise GovernanceError(f"Role '{role}' is not permitted to search client documents.")

        hits = self.db.search_docs(
            query=query,
            client_id=client_id,
            limit=limit,
            actor_id=actor_id,
            actor_role=role,
            audit=True,
        )
        return [
            self.engine.apply_read_policy(hit.model_dump(), role, "Document")
            for hit in hits
        ]
