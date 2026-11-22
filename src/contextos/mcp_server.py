from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastmcp import FastMCP

from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.governance import GovernanceEngine, GovernedContextService
from contextos.loader import load_skill_markdown
from contextos.schemas import ChangeRequest


def create_mcp_server(
    db_path: str | Path | None = None,
    store_path: str | Path | None = None,
    policies_path: str | Path | None = None,
) -> FastMCP:
    settings = get_settings()
    resolved_db = Path(db_path) if db_path is not None else settings.db_path
    resolved_store = Path(store_path) if store_path is not None else settings.context_store_path
    resolved_policies = Path(policies_path) if policies_path is not None else settings.governance_policies_path

    mcp = FastMCP("ContextOS")

    def _service() -> tuple[ContextDB, GovernedContextService]:
        db = ContextDB(resolved_db)
        engine = GovernanceEngine(resolved_policies)
        return db, GovernedContextService(db=db, engine=engine)

    @mcp.tool
    def get_project_context(project_id: str, role: str) -> dict[str, Any]:
        db, svc = _service()
        try:
            return svc.get_project_context(project_id=project_id, role=role, actor_id="mcp_client")
        finally:
            db.close()

    @mcp.tool
    def search_client_docs(client_id: str, query: str, role: str) -> list[dict[str, Any]]:
        db, svc = _service()
        try:
            return svc.search_client_docs(
                client_id=client_id,
                query=query,
                role=role,
                actor_id="mcp_client",
            )
        finally:
            db.close()

    @mcp.tool
    def load_skill(skill_name: str) -> str:
        db, _ = _service()
        try:
            return load_skill_markdown(
                skill_name=skill_name,
                store_path=resolved_store,
                db=db,
                actor_id="mcp_client",
                actor_role="agent",
            )
        finally:
            db.close()

    @mcp.tool
    def submit_change_request(
        project_id: str,
        requested_by: str,
        description: str,
        role: str,
    ) -> dict[str, Any]:
        db, svc = _service()
        try:
            if db.get_project(project_id, audit=False) is None:
                raise KeyError(f"Project '{project_id}' not found.")
            cr = ChangeRequest(
                id=f"cr_{uuid4().hex[:8]}",
                project_id=project_id,
                requested_by=requested_by,
                description=description,
                scope_verdict="pending_review",
                approval_status="pending",
            )
            saved = svc.submit_change_request(cr, role=role, actor_id="mcp_client")
            return saved.model_dump()
        finally:
            db.close()

    @mcp.tool
    def get_audit_log(project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        db, _ = _service()
        try:
            prefix = None if project_id in ("*", "all", "") else f"project:{project_id}"
            events = db.get_audit_events(target_prefix=prefix, limit=limit)
            return [event.model_dump() for event in events]
        finally:
            db.close()

    @mcp.resource("skill://{skill_name}")
    def skill_resource(skill_name: str) -> str:
        return load_skill_markdown(skill_name=skill_name, store_path=resolved_store)

    return mcp


mcp = create_mcp_server()

if __name__ == "__main__":
    mcp.run()
