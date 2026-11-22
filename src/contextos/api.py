from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.governance import GovernanceEngine, GovernanceError, GovernedContextService
from contextos.loader import load_skill_markdown
from contextos.schemas import ChangeRequest


class ChangeRequestCreateBody(BaseModel):
    requested_by: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    scope_verdict: str = Field(default="pending_review")


class ChangeRequestApproveBody(BaseModel):
    role: str = Field(..., min_length=1)
    scope_verdict: str | None = None


def create_app(
    db_path: str | Path | None = None,
    store_path: str | Path | None = None,
    policies_path: str | Path | None = None,
) -> FastAPI:
    settings = get_settings()
    resolved_db = Path(db_path) if db_path is not None else settings.db_path
    resolved_store = Path(store_path) if store_path is not None else settings.context_store_path
    resolved_policies = Path(policies_path) if policies_path is not None else settings.governance_policies_path

    app = FastAPI(title="ContextOS API", version="0.1.0")

    def _service() -> tuple[ContextDB, GovernedContextService]:
        db = ContextDB(resolved_db)
        engine = GovernanceEngine(resolved_policies)
        return db, GovernedContextService(db=db, engine=engine)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/projects/{project_id}/context")
    def get_project_context(
        project_id: str,
        role: str = Query(..., description="Caller role (presales_sa, pm, delivery_dev)"),
    ) -> dict[str, Any]:
        db, svc = _service()
        try:
            return svc.get_project_context(project_id=project_id, role=role, actor_id="rest_api")
        except GovernanceError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            db.close()

    @app.get("/clients/{client_id}/docs/search")
    def search_client_docs(
        client_id: str,
        query: str = Query(..., min_length=1),
        role: str = Query(...),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> list[dict[str, Any]]:
        db, svc = _service()
        try:
            return svc.search_client_docs(
                client_id=client_id,
                query=query,
                role=role,
                actor_id="rest_api",
                limit=limit,
            )
        except GovernanceError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        finally:
            db.close()

    @app.get("/skills/{skill_name}")
    def load_skill(skill_name: str) -> dict[str, str]:
        db, _ = _service()
        try:
            content = load_skill_markdown(
                skill_name=skill_name,
                store_path=resolved_store,
                db=db,
                actor_id="rest_api",
                actor_role="agent",
            )
            return {"skill_name": skill_name, "content": content}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            db.close()

    @app.post("/projects/{project_id}/change-requests", status_code=201)
    def submit_change_request(project_id: str, body: ChangeRequestCreateBody) -> dict[str, Any]:
        db, svc = _service()
        try:
            if db.get_project(project_id, audit=False) is None:
                raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
            cr = ChangeRequest(
                id=f"cr_{uuid4().hex[:8]}",
                project_id=project_id,
                requested_by=body.requested_by,
                description=body.description,
                scope_verdict=body.scope_verdict,
                approval_status="pending",
            )
            saved = svc.submit_change_request(cr, role=body.role, actor_id="rest_api")
            return saved.model_dump()
        except GovernanceError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        finally:
            db.close()

    @app.post("/change-requests/{cr_id}/approve")
    def approve_change_request(cr_id: str, body: ChangeRequestApproveBody) -> dict[str, Any]:
        db, svc = _service()
        try:
            approved = svc.approve_change_request(
                cr_id=cr_id,
                role=body.role,
                actor_id="rest_api",
                scope_verdict=body.scope_verdict,
            )
            return approved.model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GovernanceError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        finally:
            db.close()

    @app.get("/projects/{project_id}/audit-log")
    def get_audit_log(
        project_id: str,
        limit: int = Query(default=20, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        db, _ = _service()
        try:
            prefix = None if project_id in ("*", "all") else f"project:{project_id}"
            events = db.get_audit_events(target_prefix=prefix, limit=limit)
            return [event.model_dump() for event in events]
        finally:
            db.close()

    return app


app = create_app()
