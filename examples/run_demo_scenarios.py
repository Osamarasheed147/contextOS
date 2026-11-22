from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from contextos.agents.bridge_agent import BridgeAgent
from contextos.config import get_settings
from contextos.db import ContextDB
from contextos.governance import GovernanceEngine, GovernedContextService
from contextos.llm.base import LLMProvider, LLMProviderError
from contextos.llm.factory import create_llm_provider

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.seed_demo import seed_finbridge_demo


class _OfflineDemoLLM(LLMProvider):
    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        if "scope_creep_check" in system_prompt:
            return json.dumps(
                {
                    "verdict": "OUT_OF_SCOPE_BILLABLE",
                    "summary": "Both Okta SSO and multi-region failover are explicitly excluded from SOW v1.0 MVP Phase 1.",
                    "findings": [
                        {
                            "requested_item": "Okta SSO",
                            "classification": "out_of_scope",
                            "sow_citation": "SOW-2.1 in clients/finbridge_uk/sow_v1.md",
                            "rationale": "Enterprise Identity Federation & Okta SSO (SAML 2.0) is excluded from MVP Phase 1.",
                        },
                        {
                            "requested_item": "Multi-region failover",
                            "classification": "out_of_scope",
                            "sow_citation": "SOW-2.2 in clients/finbridge_uk/sow_v1.md",
                            "rationale": "Multi-Region Active-Active Failover is deferred to Phase 2 and excluded from SOW v1.0.",
                        },
                    ],
                    "recommended_action": "Log a pending Change Request and quote under the $165/hr Change Order rate card (SOW-4.2).",
                    "should_create_change_request": True,
                    "suggested_client_reply": "Happy to help plan Okta SSO and multi-region failover. Both sit outside SOW v1.0 (SOW-2.1 and SOW-2.2), so I have drafted a Change Request with estimates for your sign-off before adding them to the sprint.",
                },
                indent=2,
            )
        return json.dumps(
            {
                "status": "BLOCKED",
                "summary": "Proposal triggers two hard_block violations: non-UK region (us-east-1) and monthly cost ($650/mo > $400/mo cap).",
                "violations": [
                    {
                        "guardrail_id": "gr_uk_residency",
                        "category": "cloud",
                        "severity": "hard_block",
                        "rule_violated": "All AWS resources must reside exclusively in eu-west-2 (London).",
                        "proposal_conflict": "Proposed deployment targets us-east-1.",
                        "remediation": "Move staging PostgreSQL RDS deployment to eu-west-2.",
                    },
                    {
                        "guardrail_id": "gr_staging_budget",
                        "category": "cloud",
                        "severity": "hard_block",
                        "rule_violated": "Monthly staging AWS spend MUST NOT exceed $400/month.",
                        "proposal_conflict": "Estimated $650/mo exceeds the $400/mo staging budget cap by $250/mo.",
                        "remediation": "Use single-AZ db.t4g.small in eu-west-2 with KMS encryption to keep staging under $400/mo.",
                    },
                ],
                "recommended_compliant_architecture": "Deploy single-AZ db.t4g.small PostgreSQL RDS in eu-west-2 with KMS encryption enabled (~$120-$180/mo).",
            },
            indent=2,
        )


def _banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def run_scenarios(use_mock: bool = False) -> None:
    settings = get_settings()
    seed_finbridge_demo(
        db_path=settings.db_path,
        store_path=settings.context_store_path,
        policies_path=settings.governance_policies_path,
    )

    if use_mock:
        llm: LLMProvider = _OfflineDemoLLM()
        print("[Mode] Running with offline mock LLM (--mock)")
    else:
        try:
            llm = create_llm_provider(settings)
            print(f"[Mode] Running live LLM provider={settings.llm_provider} model={settings.groq_model if settings.llm_provider == 'groq' else settings.gemini_model}")
        except LLMProviderError as exc:
            print(f"Cannot initialize live LLM provider: {exc}")
            print("Set GROQ_API_KEY in .env (free at https://console.groq.com/keys) or pass --mock to preview offline.")
            sys.exit(1)

    with ContextDB(settings.db_path) as db:
        engine = GovernanceEngine(settings.governance_policies_path)
        service = GovernedContextService(db=db, engine=engine)
        agent = BridgeAgent(service=service, llm=llm, store_path=settings.context_store_path)

        _banner("SCENARIO 1: Scope Creep Check (role='pm')")
        s1_prompt = "Can we add Okta SSO and multi-region failover this sprint?"
        print(f"Client asks: {s1_prompt}\n")
        s1 = agent.check_scope_creep(
            project_id="finbridge_mvp",
            client_request=s1_prompt,
            requested_by="Marcus Vance (CTO, FinBridge UK)",
            role="pm",
            actor_id="pm_alex",
        )
        print(json.dumps(s1["evaluation"], indent=2))
        if s1["change_request"]:
            print("\nAuto-logged Draft ChangeRequest:")
            print(json.dumps(s1["change_request"], indent=2))

        _banner("SCENARIO 2: Cloud Silo Guardrail Check (role='delivery_dev')")
        s2_proposal = "Deploy staging PostgreSQL RDS in us-east-1 ($650/mo)"
        print(f"Engineer proposes: {s2_proposal}\n")
        s2 = agent.check_cloud_guardrails(
            project_id="finbridge_mvp",
            proposal=s2_proposal,
            role="delivery_dev",
            actor_id="dev_sam",
        )
        print(json.dumps(s2["evaluation"], indent=2))

        _banner("SCENARIO 3: Governance Redaction & Immutable Audit Proof")
        dev_view = service.get_project_context("finbridge_mvp", role="delivery_dev", actor_id="dev_sam")["project"]
        pm_view = service.get_project_context("finbridge_mvp", role="pm", actor_id="pm_alex")["project"]

        print("delivery_dev view of Project:")
        print(json.dumps(dev_view, indent=2))
        print("\npm view of Project:")
        print(json.dumps(pm_view, indent=2))

        print("\nLatest audit_events rows:")
        events = db.get_audit_events(limit=12)
        for ev in events:
            print(
                f"  #{ev.id:<3} | {ev.timestamp[:19]}Z | role={ev.actor_role:<12} "
                f"| action={ev.action:<24} | target={ev.target_entity}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ContextOS 3-scenario Pre-Sales to Delivery demo.")
    parser.add_argument("--mock", action="store_true", help="Run offline without calling Groq/Gemini APIs.")
    args = parser.parse_args()
    run_scenarios(use_mock=args.mock)


if __name__ == "__main__":
    main()
