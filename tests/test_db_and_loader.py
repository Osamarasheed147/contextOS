from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from contextos.db import ContextDB
from contextos.loader import load_skill_markdown, sync_context_store
from contextos.schemas import ChangeRequest, Client, Guardrail, Project, ScopeItem

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_STORE = REPO_ROOT / "context_store"


def _seed_sample_entities(db: ContextDB) -> tuple[Client, Project]:
    client = Client(
        id="finbridge_uk",
        name="FinBridge UK Ltd.",
        region="UK",
        nda_tier="tier_1_strict",
        compliance_standards=["FCA", "UK-GDPR", "SOC2"],
    )
    project = Project(
        id="finbridge_mvp",
        client_id="finbridge_uk",
        name="FinBridge Core Payments MVP",
        status="active",
        contract_value_usd=185000.0,
        margin_notes="Target 38% blended gross margin; avoid unpriced SSO work.",
        cloud_budget_monthly_usd=400.0,
        approved_cloud_regions=["eu-west-2"],
    )
    db.upsert_client(client, actor_id="sa_priya", actor_role="presales_sa")
    db.upsert_project(project, actor_id="sa_priya", actor_role="presales_sa")
    return client, project


def test_sqlite_wal_mode_and_foreign_key_enforcement(tmp_path: Path) -> None:
    db_file = tmp_path / "test_contextos.db"
    with ContextDB(db_file) as db:
        journal_mode = db.conn.execute("PRAGMA journal_mode;").fetchone()[0]
        foreign_keys = db.conn.execute("PRAGMA foreign_keys;").fetchone()[0]

        assert str(journal_mode).lower() == "wal"
        assert foreign_keys == 1

        orphan_project = Project(
            id="orphan_proj",
            client_id="does_not_exist",
            name="Orphan Project",
            status="draft",
            contract_value_usd=10000.0,
            margin_notes="",
            cloud_budget_monthly_usd=200.0,
            approved_cloud_regions=["eu-west-2"],
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert_project(orphan_project)


def test_schema_validation_enforces_literals() -> None:
    with pytest.raises(ValidationError):
        ScopeItem(
            id="s1",
            project_id="p1",
            title="Bad classification",
            classification="maybe_scope",  # type: ignore[arg-type]
            source_doc_ref="sow_v1.md",
        )

    with pytest.raises(ValidationError):
        Guardrail(
            id="g1",
            project_id="p1",
            category="cloud",
            rule_text="Must stay in UK",
            severity="critical",  # type: ignore[arg-type]
        )


def test_crud_hierarchy_and_immutable_audit_log(tmp_path: Path) -> None:
    with ContextDB(tmp_path / "crud.db") as db:
        client, project = _seed_sample_entities(db)

        scope_item = ScopeItem(
            id="scope_okta_sso",
            project_id=project.id,
            title="Okta SSO / SAML 2.0 Enterprise Federation",
            classification="out_of_scope",
            source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-2.1",
        )
        guardrail = Guardrail(
            id="gr_uk_residency",
            project_id=project.id,
            category="cloud",
            rule_text="All AWS resources must reside exclusively in eu-west-2 (London).",
            severity="hard_block",
        )
        cr = ChangeRequest(
            id="cr_001",
            project_id=project.id,
            requested_by="Marcus Vance (CTO)",
            description="Add Okta SSO and multi-region failover this sprint.",
            scope_verdict="OUT_OF_SCOPE_BILLABLE",
            approval_status="pending",
        )

        db.upsert_scope_item(scope_item, actor_id="sa_priya", actor_role="presales_sa")
        db.upsert_guardrail(guardrail, actor_id="sa_priya", actor_role="presales_sa")
        db.upsert_change_request(cr, actor_id="pm_alex", actor_role="pm")

        assert db.get_client(client.id, actor_id="pm_alex", actor_role="pm") == client
        assert db.get_project(project.id, actor_id="pm_alex", actor_role="pm") == project
        assert db.list_scope_items(project.id, actor_id="pm_alex", actor_role="pm") == [scope_item]
        assert db.list_guardrails(project.id, actor_id="pm_alex", actor_role="pm") == [guardrail]
        assert db.list_change_requests(project.id, actor_id="pm_alex", actor_role="pm") == [cr]

        events = db.get_audit_events(limit=50)
        assert len(events) >= 10
        actions = {e.action for e in events}
        assert {"write_client", "write_project", "read_project", "write_change_request"}.issubset(actions)

        first_event_id = events[-1].id
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.conn.execute("UPDATE audit_events SET action = 'tampered' WHERE id = ?", (first_event_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.conn.execute("DELETE FROM audit_events WHERE id = ?", (first_event_id,))


def test_loader_syncs_context_store_and_fts5_search(tmp_path: Path) -> None:
    with ContextDB(tmp_path / "loader.db") as db:
        synced = sync_context_store(db, CONTEXT_STORE)
        doc_ids = {d.doc_id for d in synced}

        assert "clients/finbridge_uk/discovery_notes.md" in doc_ids
        assert "clients/finbridge_uk/sow_v1.md" in doc_ids
        assert "skills/scope_creep_check/SKILL.md" in doc_ids
        assert "skills/cloud_guardrail_check/SKILL.md" in doc_ids

        sync_context_store(db, CONTEXT_STORE)
        assert len(db.list_docs()) == len(synced)

        sso_hits = db.search_docs("Okta SSO multi-region failover", client_id="finbridge_uk")
        assert len(sso_hits) >= 1
        assert any(hit.doc_id == "clients/finbridge_uk/sow_v1.md" for hit in sso_hits)

        budget_hits = db.search_docs("$400/mo staging eu-west-2", client_id="finbridge_uk")
        assert len(budget_hits) >= 1
        assert any("eu-west-2" in hit.content for hit in budget_hits)

        scope_skill = load_skill_markdown("scope_creep_check", CONTEXT_STORE, db=db, actor_role="pm")
        cloud_skill = load_skill_markdown("cloud_guardrail_check", CONTEXT_STORE, db=db, actor_role="delivery_dev")
        assert "OUT_OF_SCOPE_BILLABLE" in scope_skill
        assert "hard_block" in cloud_skill

        with pytest.raises(ValueError):
            load_skill_markdown("../governance_policies", CONTEXT_STORE)
