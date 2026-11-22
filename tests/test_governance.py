from __future__ import annotations

from pathlib import Path

import pytest

from contextos.db import ContextDB
from contextos.governance import (
    REDACTION_MARKER,
    GovernanceEngine,
    GovernanceError,
    GovernedContextService,
    apply_read_policy,
    check_write_permission,
)
from contextos.loader import sync_context_store
from contextos.schemas import ChangeRequest, Client, Guardrail, Project, ScopeItem

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICIES_PATH = REPO_ROOT / "context_store" / "governance_policies.yaml"
CONTEXT_STORE = REPO_ROOT / "context_store"


def _sample_project_dict() -> dict:
    return {
        "id": "finbridge_mvp",
        "client_id": "finbridge_uk",
        "name": "FinBridge Core Payments MVP",
        "status": "active",
        "contract_value_usd": 185000.0,
        "margin_notes": "Target 38% blended gross margin.",
        "cloud_budget_monthly_usd": 400.0,
        "approved_cloud_regions": ["eu-west-2"],
    }


def test_delivery_dev_redacts_commercial_fields_without_mutating_input() -> None:
    original = _sample_project_dict()
    redacted = apply_read_policy(original, role="delivery_dev", entity_type="Project", policies_path=POLICIES_PATH)

    assert redacted["contract_value_usd"] == REDACTION_MARKER
    assert redacted["margin_notes"] == REDACTION_MARKER
    assert redacted["cloud_budget_monthly_usd"] == 400.0
    assert redacted["approved_cloud_regions"] == ["eu-west-2"]

    assert original["contract_value_usd"] == 185000.0
    assert original["margin_notes"] == "Target 38% blended gross margin."


def test_pm_and_presales_see_unredacted_project_fields() -> None:
    original = _sample_project_dict()
    for role in ("pm", "presales_sa"):
        visible = apply_read_policy(original, role=role, entity_type="Project", policies_path=POLICIES_PATH)
        assert visible["contract_value_usd"] == 185000.0
        assert visible["margin_notes"] == "Target 38% blended gross margin."


def test_unknown_role_is_denied() -> None:
    with pytest.raises(GovernanceError):
        apply_read_policy(_sample_project_dict(), role="external_contractor", entity_type="Project", policies_path=POLICIES_PATH)
    assert check_write_permission("external_contractor", "Project", "write", policies_path=POLICIES_PATH) is False


def test_write_permissions_matrix_matches_policy() -> None:
    for entity in ("Client", "Project", "ScopeItem", "Guardrail"):
        assert check_write_permission("presales_sa", entity, "write", policies_path=POLICIES_PATH) is True
        assert check_write_permission("presales_sa", entity, "create", policies_path=POLICIES_PATH) is True
    assert check_write_permission("presales_sa", "ChangeRequest", "approve", policies_path=POLICIES_PATH) is False

    assert check_write_permission("pm", "Project", "write", policies_path=POLICIES_PATH) is True
    assert check_write_permission("pm", "ChangeRequest", "write", policies_path=POLICIES_PATH) is True
    assert check_write_permission("pm", "ChangeRequest", "approve", policies_path=POLICIES_PATH) is True
    assert check_write_permission("pm", "Guardrail", "write", policies_path=POLICIES_PATH) is False
    assert check_write_permission("pm", "Guardrail", "delete", policies_path=POLICIES_PATH) is False

    for entity in ("Project", "ScopeItem", "Guardrail"):
        assert check_write_permission("delivery_dev", entity, "write", policies_path=POLICIES_PATH) is False
        assert check_write_permission("delivery_dev", entity, "update", policies_path=POLICIES_PATH) is False
    assert check_write_permission("delivery_dev", "ChangeRequest", "approve", policies_path=POLICIES_PATH) is False
    assert check_write_permission("delivery_dev", "ChangeRequest", "submit", policies_path=POLICIES_PATH) is True


def test_governed_service_enforces_redaction_write_gates_and_audit_trail(tmp_path: Path) -> None:
    engine = GovernanceEngine(POLICIES_PATH)
    with ContextDB(tmp_path / "governed.db") as db:
        service = GovernedContextService(db=db, engine=engine)

        client = Client(
            id="finbridge_uk",
            name="FinBridge UK Ltd.",
            region="UK",
            nda_tier="tier_1_strict",
            compliance_standards=["FCA", "UK-GDPR"],
        )
        project = Project(
            id="finbridge_mvp",
            client_id="finbridge_uk",
            name="FinBridge Core Payments MVP",
            status="active",
            contract_value_usd=185000.0,
            margin_notes="38% target margin",
            cloud_budget_monthly_usd=400.0,
            approved_cloud_regions=["eu-west-2"],
        )
        scope_item = ScopeItem(
            id="s_okta",
            project_id="finbridge_mvp",
            title="Okta SSO",
            classification="out_of_scope",
            source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-2.1",
        )
        guardrail = Guardrail(
            id="g_residency",
            project_id="finbridge_mvp",
            category="cloud",
            rule_text="UK data residency eu-west-2 only",
            severity="hard_block",
        )

        service.save_client(client, role="presales_sa", actor_id="sa_priya")
        service.save_project(project, role="presales_sa", actor_id="sa_priya")
        service.save_scope_item(scope_item, role="presales_sa", actor_id="sa_priya")
        service.save_guardrail(guardrail, role="presales_sa", actor_id="sa_priya")
        sync_context_store(db, CONTEXT_STORE)

        with pytest.raises(GovernanceError):
            service.save_guardrail(guardrail, role="pm", actor_id="pm_alex")

        dev_ctx = service.get_project_context("finbridge_mvp", role="delivery_dev", actor_id="dev_sam")
        assert dev_ctx["project"]["contract_value_usd"] == REDACTION_MARKER
        assert dev_ctx["project"]["margin_notes"] == REDACTION_MARKER
        assert dev_ctx["project"]["cloud_budget_monthly_usd"] == 400.0
        assert len(dev_ctx["guardrails"]) == 1

        pm_ctx = service.get_project_context("finbridge_mvp", role="pm", actor_id="pm_alex")
        assert pm_ctx["project"]["contract_value_usd"] == 185000.0
        assert pm_ctx["project"]["margin_notes"] == "38% target margin"

        cr = ChangeRequest(
            id="cr_001",
            project_id="finbridge_mvp",
            requested_by="Marcus Vance",
            description="Add Okta SSO",
        )
        service.submit_change_request(cr, role="delivery_dev", actor_id="dev_sam")
        with pytest.raises(GovernanceError):
            service.approve_change_request("cr_001", role="delivery_dev", actor_id="dev_sam")

        approved = service.approve_change_request(
            "cr_001",
            role="pm",
            actor_id="pm_alex",
            scope_verdict="OUT_OF_SCOPE_BILLABLE",
        )
        assert approved.approval_status == "approved"
        assert approved.scope_verdict == "OUT_OF_SCOPE_BILLABLE"

        docs = service.search_client_docs("finbridge_uk", "Okta SSO", role="pm", actor_id="pm_alex")
        assert len(docs) >= 1

        events = db.get_audit_events(limit=100)
        actions = [e.action for e in events]
        assert "read_project_context" in actions
        assert "denied_write_guardrail" in actions
        assert "denied_approve_changerequest" in actions
        assert "search_docs" in actions
        dev_read_events = [
            e for e in events if e.action == "read_project_context" and e.actor_role == "delivery_dev"
        ]
        assert len(dev_read_events) == 1
        assert "contract_value_usd" in dev_read_events[0].details_json
