from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import groq
import httpx
import pytest

from contextos.agents.bridge_agent import BridgeAgent
from contextos.api import create_app
from contextos.config import Settings
from contextos.db import ContextDB
from contextos.governance import REDACTION_MARKER, GovernanceEngine, GovernedContextService
from contextos.llm.base import LLMProvider, LLMProviderError
from contextos.llm.factory import create_llm_provider
from contextos.llm.gemini_provider import GeminiProvider
from contextos.llm.groq_provider import GroqProvider
from contextos.mcp_server import create_mcp_server
from examples.seed_demo import seed_finbridge_demo

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_STORE = REPO_ROOT / "context_store"
POLICIES_PATH = CONTEXT_STORE / "governance_policies.yaml"


class _CapturingLLM(LLMProvider):
    def __init__(self, response_payload: dict[str, Any]) -> None:
        self.response_payload = response_payload
        self.calls: list[dict[str, Any]] = []

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "json_mode": json_mode,
            }
        )
        return json.dumps(self.response_payload)


def test_llm_factory_switches_between_groq_and_gemini() -> None:
    groq_cfg = Settings(llm_provider="groq", groq_api_key="gsk_test", groq_model="openai/gpt-oss-120b")
    provider = create_llm_provider(groq_cfg)
    assert isinstance(provider, GroqProvider)
    assert provider.model == "openai/gpt-oss-120b"

    gemini_cfg = Settings(llm_provider="gemini", gemini_api_key="AIza_test", gemini_model="gemini-2.5-flash")
    gemini_provider = create_llm_provider(gemini_cfg)
    assert isinstance(gemini_provider, GeminiProvider)
    assert gemini_provider.model == "gemini-2.5-flash"

    with pytest.raises(LLMProviderError):
        create_llm_provider(Settings(llm_provider="unknown"))


def test_groq_provider_retries_on_429_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []
    monkeypatch.setattr("contextos.llm.groq_provider.time.sleep", lambda s: sleeps.append(s))

    def fake_create(**kwargs: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] == 1:
            req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            resp = httpx.Response(429, headers={"retry-after": "0.1"}, request=req)
            raise groq.RateLimitError("rate limited", response=resp, body=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    provider = GroqProvider(api_key="gsk_test", client=fake_client, max_retries=2)
    out = provider.complete("sys", "usr", json_mode=True)

    assert out == '{"ok": true}'
    assert attempts["count"] == 2
    assert sleeps == [0.1]


def test_gemini_provider_works_with_injected_client() -> None:
    captured: dict[str, Any] = {}

    def fake_generate_content(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(text='{"status": "APPROVED"}')

    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))
    provider = GeminiProvider(api_key="test", client=fake_client)
    out = provider.complete("sys prompt", "user prompt", json_mode=True)

    assert out == '{"status": "APPROVED"}'
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["config"]["response_mime_type"] == "application/json"


def test_bridge_agent_scope_creep_logs_draft_change_request(tmp_path: Path) -> None:
    db_file = tmp_path / "demo.db"
    seed_finbridge_demo(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)

    fake_llm = _CapturingLLM(
        {
            "verdict": "OUT_OF_SCOPE_BILLABLE",
            "summary": "Okta SSO and multi-region failover are excluded in SOW-2.1 and SOW-2.2.",
            "findings": [
                {
                    "requested_item": "Okta SSO",
                    "classification": "out_of_scope",
                    "sow_citation": "SOW-2.1",
                    "rationale": "Explicitly excluded from MVP Phase 1.",
                }
            ],
            "recommended_action": "Log billable CR",
            "should_create_change_request": True,
        }
    )

    with ContextDB(db_file) as db:
        service = GovernedContextService(db=db, engine=GovernanceEngine(POLICIES_PATH))
        agent = BridgeAgent(service=service, llm=fake_llm, store_path=CONTEXT_STORE)

        res = agent.check_scope_creep(
            project_id="finbridge_mvp",
            client_request="Can we add Okta SSO and multi-region failover this sprint?",
            requested_by="Marcus Vance",
            role="pm",
        )

        assert res["evaluation"]["verdict"] == "OUT_OF_SCOPE_BILLABLE"
        assert res["change_request"] is not None
        assert res["change_request"]["approval_status"] == "pending"
        assert len(db.list_change_requests("finbridge_mvp", audit=False)) == 1
        assert "scope_creep_check" in fake_llm.calls[0]["system_prompt"]
        assert "SOW-2.1" in fake_llm.calls[0]["user_prompt"]


def test_bridge_agent_cloud_check_redacts_commercial_fields_before_llm(tmp_path: Path) -> None:
    db_file = tmp_path / "cloud.db"
    seed_finbridge_demo(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)

    fake_llm = _CapturingLLM(
        {
            "status": "BLOCKED",
            "summary": "Violates eu-west-2 residency and $400/mo staging budget cap.",
            "violations": [
                {"guardrail_id": "gr_uk_residency", "severity": "hard_block"},
                {"guardrail_id": "gr_staging_budget", "severity": "hard_block"},
            ],
        }
    )

    with ContextDB(db_file) as db:
        service = GovernedContextService(db=db, engine=GovernanceEngine(POLICIES_PATH))
        agent = BridgeAgent(service=service, llm=fake_llm, store_path=CONTEXT_STORE)

        res = agent.check_cloud_guardrails(
            project_id="finbridge_mvp",
            proposal="Deploy staging PostgreSQL RDS in us-east-1 ($650/mo)",
            role="delivery_dev",
        )

        assert res["evaluation"]["status"] == "BLOCKED"
        assert len(res["evaluation"]["violations"]) == 2
        prompt_sent = fake_llm.calls[0]["user_prompt"]
        assert REDACTION_MARKER in prompt_sent
        assert "185000" not in prompt_sent
        assert "cloud_guardrail_check" in fake_llm.calls[0]["system_prompt"]


def test_fastapi_endpoints_enforce_governance_and_audit(tmp_path: Path) -> None:
    db_file = tmp_path / "api.db"
    seed_finbridge_demo(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)
    app = create_app(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            assert health.status_code == 200

            dev_resp = await client.get("/projects/finbridge_mvp/context", params={"role": "delivery_dev"})
            assert dev_resp.status_code == 200
            assert dev_resp.json()["project"]["contract_value_usd"] == REDACTION_MARKER

            pm_resp = await client.get("/projects/finbridge_mvp/context", params={"role": "pm"})
            assert pm_resp.status_code == 200
            assert pm_resp.json()["project"]["contract_value_usd"] == 185000.0

            search_resp = await client.get(
                "/clients/finbridge_uk/docs/search",
                params={"query": "Okta SSO", "role": "pm"},
            )
            assert search_resp.status_code == 200
            assert len(search_resp.json()) >= 1

            skill_resp = await client.get("/skills/scope_creep_check")
            assert skill_resp.status_code == 200
            assert "OUT_OF_SCOPE_BILLABLE" in skill_resp.json()["content"]

            cr_resp = await client.post(
                "/projects/finbridge_mvp/change-requests",
                json={
                    "requested_by": "Marcus Vance",
                    "description": "Add Okta SSO",
                    "role": "delivery_dev",
                },
            )
            assert cr_resp.status_code == 201
            cr_id = cr_resp.json()["id"]

            dev_approve = await client.post(f"/change-requests/{cr_id}/approve", json={"role": "delivery_dev"})
            assert dev_approve.status_code == 403

            pm_approve = await client.post(
                f"/change-requests/{cr_id}/approve",
                json={"role": "pm", "scope_verdict": "OUT_OF_SCOPE_BILLABLE"},
            )
            assert pm_approve.status_code == 200
            assert pm_approve.json()["approval_status"] == "approved"

            audit_resp = await client.get("/projects/finbridge_mvp/audit-log", params={"limit": 30})
            assert audit_resp.status_code == 200
            assert len(audit_resp.json()) >= 5

    asyncio.run(_run())


def test_mcp_server_registers_all_governed_tools(tmp_path: Path) -> None:
    db_file = tmp_path / "mcp.db"
    seed_finbridge_demo(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)
    mcp_server = create_mcp_server(db_path=db_file, store_path=CONTEXT_STORE, policies_path=POLICIES_PATH)

    async def _run() -> None:
        tools = await mcp_server.list_tools()
        tool_names = {t.name for t in tools}
        assert {
            "get_project_context",
            "search_client_docs",
            "load_skill",
            "submit_change_request",
            "get_audit_log",
        }.issubset(tool_names)

        dev_ctx = await mcp_server.call_tool(
            "get_project_context", {"project_id": "finbridge_mvp", "role": "delivery_dev"}
        )
        assert REDACTION_MARKER in str(dev_ctx)

        skill_out = await mcp_server.call_tool("load_skill", {"skill_name": "cloud_guardrail_check"})
        assert "hard_block" in str(skill_out)

    asyncio.run(_run())
