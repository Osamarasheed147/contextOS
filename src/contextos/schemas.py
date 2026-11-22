from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScopeClassification = Literal["in_scope", "out_of_scope", "assumption"]
GuardrailCategory = Literal["cloud", "security", "sla", "architecture"]
GuardrailSeverity = Literal["hard_block", "warning"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Client(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    region: str = Field(..., min_length=1)
    nda_tier: str = Field(..., min_length=1)
    compliance_standards: list[str] = Field(default_factory=list)


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    contract_value_usd: float = Field(..., ge=0)
    margin_notes: str = Field(default="")
    cloud_budget_monthly_usd: float = Field(..., ge=0)
    approved_cloud_regions: list[str] = Field(default_factory=list)


class ScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    classification: ScopeClassification
    source_doc_ref: str = Field(..., min_length=1)


class Guardrail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    category: GuardrailCategory
    rule_text: str = Field(..., min_length=1)
    severity: GuardrailSeverity


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    requested_by: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    scope_verdict: str = Field(default="pending_review")
    approval_status: str = Field(default="pending")


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    timestamp: str = Field(default_factory=utc_now_iso)
    actor_id: str = Field(..., min_length=1)
    actor_role: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    target_entity: str = Field(..., min_length=1)
    details_json: str = Field(default="{}")


class DocSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    client_id: str
    doc_type: str
    title: str
    content: str
    snippet: str | None = None
    rank: float | None = None
