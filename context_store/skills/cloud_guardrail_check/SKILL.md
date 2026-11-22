---
name: cloud_guardrail_check
description: Step-by-step rubric for validating cloud, DevOps, and Terraform architecture proposals against client data residency, budget, security, and SLA guardrails.
version: "1.0"
---

# Skill: Cloud & Architecture Guardrail Validation (`cloud_guardrail_check`)

## Purpose
Bridge the Pre-Sales / Compliance to Delivery DevOps gap by catching regulatory, data residency, budget, and security violations *before* Terraform or cloud infrastructure is provisioned.

## Required Context Inputs
Before evaluating a proposal, ensure you have inspected:
1. Structured `Project` cloud fields (`approved_cloud_regions`, `cloud_budget_monthly_usd`).
2. Structured `Guardrail` records (`category`, `rule_text`, `severity`: `hard_block` | `warning`).
3. Client compliance metadata (`region`, `compliance_standards`) and relevant SOW / discovery documentation.

## Step-by-Step Validation Rubric
1. **Extract Proposal Parameters:** Identify every cloud region, service/instance type, estimated monthly cost, encryption/network posture, and environment (`staging` vs `production`) in the engineering proposal.
2. **Check Data Residency & Approved Regions:**
   - Compare every proposed cloud region against `approved_cloud_regions` and cloud/security guardrails.
   - Any region outside `approved_cloud_regions` (e.g., proposing `us-east-1` when only `eu-west-2` is approved) MUST be flagged as a `hard_block` violation.
3. **Check Monthly Cloud Budget Cap:**
   - Compare the proposed monthly cost against `cloud_budget_monthly_usd` and budget guardrails (e.g., `$650/mo` vs `$400/mo` staging cap).
   - Exceeding a hard budget cap MUST be flagged as a `hard_block` violation with the exact delta (`$650/mo` exceeds `$400/mo` by `$250/mo`).
4. **Check Security, Encryption & SLA Guardrails:**
   - Verify KMS encryption, private subnet isolation, TLS requirements, and SLA/RPO/RTO expectations.
   - Flag missing required controls as `hard_block` or `warning` matching the guardrail severity.
5. **Determine Overall Status:**
   - `BLOCKED`: One or more `hard_block` violations were detected. Deployment MUST NOT proceed.
   - `APPROVED_WITH_WARNINGS`: Zero `hard_block` violations, but one or more `warning` guardrails need attention.
   - `APPROVED`: Fully compliant with all project guardrails.
6. **Provide Compliant Remediation:** Recommend concrete Terraform / AWS changes that satisfy every violated guardrail (e.g., move RDS to `eu-west-2` and downsize staging instance class to stay under `$400/mo`).

## Expected JSON Output Format (when JSON mode is requested)
```json
{
  "status": "BLOCKED | APPROVED_WITH_WARNINGS | APPROVED",
  "summary": "One-sentence summary of the compliance check.",
  "violations": [
    {
      "guardrail_id": "Matching guardrail ID or rule identifier",
      "category": "cloud | security | sla | architecture",
      "severity": "hard_block | warning",
      "rule_violated": "Exact rule text or constraint violated",
      "proposal_conflict": "Specific part of the proposal that violates the rule",
      "remediation": "Actionable fix to make the proposal compliant"
    }
  ],
  "recommended_compliant_architecture": "Concrete revised configuration that passes all guardrails."
}
```
