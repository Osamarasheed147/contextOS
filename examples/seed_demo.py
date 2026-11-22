from __future__ import annotations

from pathlib import Path
from typing import Any

from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.governance import GovernanceEngine, GovernedContextService
from contextos.loader import sync_context_store
from contextos.schemas import Client, Guardrail, Project, ScopeItem


def seed_finbridge_demo(
    db_path: str | Path | None = None,
    store_path: str | Path | None = None,
    policies_path: str | Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    resolved_db = Path(db_path) if db_path is not None else settings.db_path
    resolved_store = Path(store_path) if store_path is not None else settings.context_store_path
    resolved_policies = Path(policies_path) if policies_path is not None else settings.governance_policies_path

    with ContextDB(resolved_db) as db:
        engine = GovernanceEngine(resolved_policies)
        service = GovernedContextService(db=db, engine=engine)

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
            margin_notes="Fixed-price MVP at 38% target gross margin; enforce Change Order ($165/hr) for Phase 2 features.",
            cloud_budget_monthly_usd=400.0,
            approved_cloud_regions=["eu-west-2"],
        )

        scope_items = [
            ScopeItem(
                id="scope_ledger_api",
                project_id=project.id,
                title="Core Double-Entry Payment Ledger API",
                classification="in_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-1.1",
            ),
            ScopeItem(
                id="scope_open_banking",
                project_id=project.id,
                title="UK Open Banking Connector",
                classification="in_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-1.2",
            ),
            ScopeItem(
                id="scope_basic_auth",
                project_id=project.id,
                title="Standard Email/Password Auth with TOTP MFA",
                classification="in_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-1.3",
            ),
            ScopeItem(
                id="scope_aws_eu_west_2",
                project_id=project.id,
                title="Single-Region AWS eu-west-2 Terraform Setup",
                classification="in_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-1.4",
            ),
            ScopeItem(
                id="scope_okta_sso",
                project_id=project.id,
                title="Enterprise Identity Federation & Okta SSO (SAML 2.0)",
                classification="out_of_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-2.1",
            ),
            ScopeItem(
                id="scope_multi_region_failover",
                project_id=project.id,
                title="Multi-Region Active-Active Failover",
                classification="out_of_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-2.2",
            ),
            ScopeItem(
                id="scope_native_mobile",
                project_id=project.id,
                title="Native iOS and Android Mobile Apps",
                classification="out_of_scope",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-2.3",
            ),
            ScopeItem(
                id="scope_client_sandbox",
                project_id=project.id,
                title="Client provides Open Banking sandbox & AWS eu-west-2 access by Week 1",
                classification="assumption",
                source_doc_ref="clients/finbridge_uk/sow_v1.md#SOW-4.1",
            ),
        ]

        guardrails = [
            Guardrail(
                id="gr_uk_residency",
                project_id=project.id,
                category="cloud",
                rule_text="UK Data Residency: All AWS resources, databases, and backups MUST reside exclusively in eu-west-2 (London). Non-UK regions such as us-east-1 are strictly prohibited.",
                severity="hard_block",
            ),
            Guardrail(
                id="gr_staging_budget",
                project_id=project.id,
                category="cloud",
                rule_text="Staging Cloud Budget Cap: Monthly AWS spend for staging MUST NOT exceed $400/month.",
                severity="hard_block",
            ),
            Guardrail(
                id="gr_encryption_kms",
                project_id=project.id,
                category="security",
                rule_text="All RDS instances and S3 buckets MUST enforce KMS encryption at rest, disable public access, and require TLS 1.2+ in transit.",
                severity="hard_block",
            ),
            Guardrail(
                id="gr_prod_sla",
                project_id=project.id,
                category="sla",
                rule_text="Production targets 99.9% monthly uptime in single-region multi-AZ eu-west-2 (RPO <= 15 min, RTO <= 2 hours).",
                severity="warning",
            ),
        ]

        service.save_client(client, role="presales_sa", actor_id="sa_priya")
        service.save_project(project, role="presales_sa", actor_id="sa_priya")
        for item in scope_items:
            service.save_scope_item(item, role="presales_sa", actor_id="sa_priya")
        for gr in guardrails:
            service.save_guardrail(gr, role="presales_sa", actor_id="sa_priya")

        synced_docs = sync_context_store(db, store_path=resolved_store, actor_id="sa_priya", actor_role="presales_sa")

    return {
        "db_path": str(resolved_db),
        "client_id": client.id,
        "project_id": project.id,
        "scope_items": len(scope_items),
        "guardrails": len(guardrails),
        "indexed_docs": len(synced_docs),
    }


if __name__ == "__main__":
    summary = seed_finbridge_demo()
    print("Seeded FinBridge UK demo:")
    for key, val in summary.items():
        print(f"  {key}: {val}")
