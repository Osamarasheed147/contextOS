from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from contextos.schemas import (
    AuditEvent,
    ChangeRequest,
    Client,
    DocSearchResult,
    Guardrail,
    Project,
    ScopeItem,
    utc_now_iso,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    nda_tier TEXT NOT NULL,
    compliance_standards_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    contract_value_usd REAL NOT NULL,
    margin_notes TEXT NOT NULL,
    cloud_budget_monthly_usd REAL NOT NULL,
    approved_cloud_regions_json TEXT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scope_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('in_scope', 'out_of_scope', 'assumption')),
    source_doc_ref TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guardrails (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('cloud', 'security', 'sla', 'architecture')),
    rule_text TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('hard_block', 'warning')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS change_requests (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    description TEXT NOT NULL,
    scope_verdict TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS prevent_audit_events_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events table is append-only and cannot be updated');
END;

CREATE TRIGGER IF NOT EXISTS prevent_audit_events_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events table is append-only and cannot be deleted');
END;

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    doc_id UNINDEXED,
    client_id UNINDEXED,
    doc_type UNINDEXED,
    title,
    content,
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_projects_client_id ON projects(client_id);
CREATE INDEX IF NOT EXISTS idx_scope_items_project_id ON scope_items(project_id);
CREATE INDEX IF NOT EXISTS idx_guardrails_project_id ON guardrails(project_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_project_id ON change_requests(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_target ON audit_events(target_entity);
"""

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _build_fts_query(raw_query: str) -> str:
    tokens = _TOKEN_RE.findall(raw_query)
    if not tokens:
        return ""
    unique_tokens = list(dict.fromkeys(tokens))
    return " OR ".join(f'"{token}"' for token in unique_tokens)


class ContextDB:
    def __init__(self, db_path: str | Path = "./contextos.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._configure_connection()
        self.init_schema()

    def _configure_connection(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ContextDB:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def log_audit_event(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        target_entity: str,
        details: dict[str, Any] | str | None = None,
    ) -> AuditEvent:
        if details is None:
            details_json = "{}"
        elif isinstance(details, str):
            details_json = details
        else:
            details_json = json.dumps(details, sort_keys=True)

        timestamp = utc_now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO audit_events (timestamp, actor_id, actor_role, action, target_entity, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, actor_id, actor_role, action, target_entity, details_json),
        )
        self.conn.commit()
        return AuditEvent(
            id=int(cur.lastrowid) if cur.lastrowid is not None else None,
            timestamp=timestamp,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_entity=target_entity,
            details_json=details_json,
        )

    def get_audit_events(
        self,
        target_entity: str | None = None,
        target_prefix: str | None = None,
        actor_role: str | None = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        params: list[Any] = []

        if target_entity is not None:
            clauses.append("target_entity = ?")
            params.append(target_entity)
        if target_prefix is not None:
            clauses.append("target_entity LIKE ?")
            params.append(f"{target_prefix}%")
        if actor_role is not None:
            clauses.append("actor_role = ?")
            params.append(actor_role)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT id, timestamp, actor_id, actor_role, action, target_entity, details_json
            FROM audit_events
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [AuditEvent(**dict(row)) for row in rows]

    def upsert_client(
        self,
        client: Client,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> Client:
        self.conn.execute(
            """
            INSERT INTO clients (id, name, region, nda_tier, compliance_standards_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                region = excluded.region,
                nda_tier = excluded.nda_tier,
                compliance_standards_json = excluded.compliance_standards_json
            """,
            (
                client.id,
                client.name,
                client.region,
                client.nda_tier,
                json.dumps(client.compliance_standards),
            ),
        )
        self.conn.commit()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="write_client",
                target_entity=f"client:{client.id}",
                details={"name": client.name, "region": client.region},
            )
        return client

    def get_client(
        self,
        client_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> Client | None:
        row = self.conn.execute(
            "SELECT id, name, region, nda_tier, compliance_standards_json FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_client",
                target_entity=f"client:{client_id}",
                details={"found": row is not None},
            )
        if row is None:
            return None
        return Client(
            id=row["id"],
            name=row["name"],
            region=row["region"],
            nda_tier=row["nda_tier"],
            compliance_standards=json.loads(row["compliance_standards_json"]),
        )

    def list_clients(
        self,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[Client]:
        rows = self.conn.execute(
            "SELECT id, name, region, nda_tier, compliance_standards_json FROM clients ORDER BY id"
        ).fetchall()
        clients = [
            Client(
                id=row["id"],
                name=row["name"],
                region=row["region"],
                nda_tier=row["nda_tier"],
                compliance_standards=json.loads(row["compliance_standards_json"]),
            )
            for row in rows
        ]
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="list_clients",
                target_entity="client:*",
                details={"count": len(clients)},
            )
        return clients

    def upsert_project(
        self,
        project: Project,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> Project:
        self.conn.execute(
            """
            INSERT INTO projects (
                id, client_id, name, status, contract_value_usd,
                margin_notes, cloud_budget_monthly_usd, approved_cloud_regions_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                client_id = excluded.client_id,
                name = excluded.name,
                status = excluded.status,
                contract_value_usd = excluded.contract_value_usd,
                margin_notes = excluded.margin_notes,
                cloud_budget_monthly_usd = excluded.cloud_budget_monthly_usd,
                approved_cloud_regions_json = excluded.approved_cloud_regions_json
            """,
            (
                project.id,
                project.client_id,
                project.name,
                project.status,
                project.contract_value_usd,
                project.margin_notes,
                project.cloud_budget_monthly_usd,
                json.dumps(project.approved_cloud_regions),
            ),
        )
        self.conn.commit()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="write_project",
                target_entity=f"project:{project.id}",
                details={"client_id": project.client_id, "status": project.status},
            )
        return project

    def get_project(
        self,
        project_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> Project | None:
        row = self.conn.execute(
            """
            SELECT id, client_id, name, status, contract_value_usd,
                   margin_notes, cloud_budget_monthly_usd, approved_cloud_regions_json
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_project",
                target_entity=f"project:{project_id}",
                details={"found": row is not None},
            )
        if row is None:
            return None
        return Project(
            id=row["id"],
            client_id=row["client_id"],
            name=row["name"],
            status=row["status"],
            contract_value_usd=row["contract_value_usd"],
            margin_notes=row["margin_notes"],
            cloud_budget_monthly_usd=row["cloud_budget_monthly_usd"],
            approved_cloud_regions=json.loads(row["approved_cloud_regions_json"]),
        )

    def list_projects(
        self,
        client_id: str | None = None,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[Project]:
        if client_id is not None:
            rows = self.conn.execute(
                """
                SELECT id, client_id, name, status, contract_value_usd,
                       margin_notes, cloud_budget_monthly_usd, approved_cloud_regions_json
                FROM projects
                WHERE client_id = ?
                ORDER BY id
                """,
                (client_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT id, client_id, name, status, contract_value_usd,
                       margin_notes, cloud_budget_monthly_usd, approved_cloud_regions_json
                FROM projects
                ORDER BY id
                """
            ).fetchall()

        projects = [
            Project(
                id=row["id"],
                client_id=row["client_id"],
                name=row["name"],
                status=row["status"],
                contract_value_usd=row["contract_value_usd"],
                margin_notes=row["margin_notes"],
                cloud_budget_monthly_usd=row["cloud_budget_monthly_usd"],
                approved_cloud_regions=json.loads(row["approved_cloud_regions_json"]),
            )
            for row in rows
        ]
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="list_projects",
                target_entity=f"client:{client_id}" if client_id else "project:*",
                details={"count": len(projects)},
            )
        return projects

    def upsert_scope_item(
        self,
        item: ScopeItem,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> ScopeItem:
        self.conn.execute(
            """
            INSERT INTO scope_items (id, project_id, title, classification, source_doc_ref)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                title = excluded.title,
                classification = excluded.classification,
                source_doc_ref = excluded.source_doc_ref
            """,
            (item.id, item.project_id, item.title, item.classification, item.source_doc_ref),
        )
        self.conn.commit()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="write_scope_item",
                target_entity=f"project:{item.project_id}/scope_item:{item.id}",
                details={"classification": item.classification, "title": item.title},
            )
        return item

    def list_scope_items(
        self,
        project_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[ScopeItem]:
        rows = self.conn.execute(
            """
            SELECT id, project_id, title, classification, source_doc_ref
            FROM scope_items
            WHERE project_id = ?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        items = [ScopeItem(**dict(row)) for row in rows]
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_scope_items",
                target_entity=f"project:{project_id}",
                details={"count": len(items)},
            )
        return items

    def upsert_guardrail(
        self,
        guardrail: Guardrail,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> Guardrail:
        self.conn.execute(
            """
            INSERT INTO guardrails (id, project_id, category, rule_text, severity)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                category = excluded.category,
                rule_text = excluded.rule_text,
                severity = excluded.severity
            """,
            (
                guardrail.id,
                guardrail.project_id,
                guardrail.category,
                guardrail.rule_text,
                guardrail.severity,
            ),
        )
        self.conn.commit()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="write_guardrail",
                target_entity=f"project:{guardrail.project_id}/guardrail:{guardrail.id}",
                details={"category": guardrail.category, "severity": guardrail.severity},
            )
        return guardrail

    def list_guardrails(
        self,
        project_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[Guardrail]:
        rows = self.conn.execute(
            """
            SELECT id, project_id, category, rule_text, severity
            FROM guardrails
            WHERE project_id = ?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        guardrails = [Guardrail(**dict(row)) for row in rows]
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_guardrails",
                target_entity=f"project:{project_id}",
                details={"count": len(guardrails)},
            )
        return guardrails

    def upsert_change_request(
        self,
        change_request: ChangeRequest,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> ChangeRequest:
        self.conn.execute(
            """
            INSERT INTO change_requests (
                id, project_id, requested_by, description, scope_verdict, approval_status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                requested_by = excluded.requested_by,
                description = excluded.description,
                scope_verdict = excluded.scope_verdict,
                approval_status = excluded.approval_status
            """,
            (
                change_request.id,
                change_request.project_id,
                change_request.requested_by,
                change_request.description,
                change_request.scope_verdict,
                change_request.approval_status,
            ),
        )
        self.conn.commit()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="write_change_request",
                target_entity=f"project:{change_request.project_id}/change_request:{change_request.id}",
                details={
                    "scope_verdict": change_request.scope_verdict,
                    "approval_status": change_request.approval_status,
                },
            )
        return change_request

    def get_change_request(
        self,
        cr_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> ChangeRequest | None:
        row = self.conn.execute(
            """
            SELECT id, project_id, requested_by, description, scope_verdict, approval_status
            FROM change_requests
            WHERE id = ?
            """,
            (cr_id,),
        ).fetchone()
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_change_request",
                target_entity=f"change_request:{cr_id}",
                details={"found": row is not None},
            )
        if row is None:
            return None
        return ChangeRequest(**dict(row))

    def list_change_requests(
        self,
        project_id: str,
        *,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[ChangeRequest]:
        rows = self.conn.execute(
            """
            SELECT id, project_id, requested_by, description, scope_verdict, approval_status
            FROM change_requests
            WHERE project_id = ?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        items = [ChangeRequest(**dict(row)) for row in rows]
        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="read_change_requests",
                target_entity=f"project:{project_id}",
                details={"count": len(items)},
            )
        return items

    def upsert_doc(
        self,
        doc_id: str,
        client_id: str,
        doc_type: str,
        title: str,
        content: str,
    ) -> DocSearchResult:
        with self.conn:
            self.conn.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
            self.conn.execute(
                """
                INSERT INTO docs_fts (doc_id, client_id, doc_type, title, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (doc_id, client_id, doc_type, title, content),
            )
        return DocSearchResult(
            doc_id=doc_id,
            client_id=client_id,
            doc_type=doc_type,
            title=title,
            content=content,
        )

    def get_doc(self, doc_id: str) -> DocSearchResult | None:
        row = self.conn.execute(
            """
            SELECT doc_id, client_id, doc_type, title, content
            FROM docs_fts
            WHERE doc_id = ?
            LIMIT 1
            """,
            (doc_id,),
        ).fetchone()
        if row is None:
            return None
        return DocSearchResult(**dict(row))

    def list_docs(
        self,
        client_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[DocSearchResult]:
        clauses: list[str] = []
        params: list[Any] = []
        if client_id is not None:
            clauses.append("client_id = ?")
            params.append(client_id)
        if doc_type is not None:
            clauses.append("doc_type = ?")
            params.append(doc_type)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT doc_id, client_id, doc_type, title, content FROM docs_fts {where_sql} ORDER BY doc_id",
            params,
        ).fetchall()
        return [DocSearchResult(**dict(row)) for row in rows]

    def search_docs(
        self,
        query: str,
        *,
        client_id: str | None = None,
        doc_type: str | None = None,
        limit: int = 10,
        actor_id: str = "system",
        actor_role: str = "system",
        audit: bool = True,
    ) -> list[DocSearchResult]:
        fts_query = _build_fts_query(query)
        results: list[DocSearchResult] = []

        if fts_query:
            clauses = ["docs_fts MATCH ?"]
            params: list[Any] = [fts_query]

            if client_id is not None:
                clauses.append("client_id = ?")
                params.append(client_id)
            if doc_type is not None:
                clauses.append("doc_type = ?")
                params.append(doc_type)

            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT
                    doc_id,
                    client_id,
                    doc_type,
                    title,
                    content,
                    snippet(docs_fts, 4, '[', ']', '...', 24) AS snippet,
                    bm25(docs_fts) AS rank
                FROM docs_fts
                WHERE {' AND '.join(clauses)}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
            results = [DocSearchResult(**dict(row)) for row in rows]

        if audit:
            self.log_audit_event(
                actor_id=actor_id,
                actor_role=actor_role,
                action="search_docs",
                target_entity=f"client:{client_id}" if client_id else "docs_fts:*",
                details={"query": query, "doc_type": doc_type, "hit_count": len(results)},
            )
        return results
