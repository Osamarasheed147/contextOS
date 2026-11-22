---
name: scope_creep_check
description: Step-by-step rubric for evaluating a client feature or sprint request against signed SOW scope items, explicit exclusions, and discovery context.
version: "1.0"
---

# Skill: Scope Creep & Change Request Evaluation (`scope_creep_check`)

## Purpose
Prevent unpriced scope creep during delivery by systematically checking every incoming client request against structured `ScopeItem` records and unstructured SOW / discovery documents stored in ContextOS.

## Required Context Inputs
Before rendering a verdict, ensure you have inspected:
1. Structured project context (`Project`, `ScopeItem` list with `in_scope` / `out_of_scope` / `assumption` classifications).
2. Relevant excerpts from the signed SOW (e.g., `sow_v1.md`) and pre-sales discovery notes (`discovery_notes.md`).

## Step-by-Step Evaluation Rubric
1. **Decompose the Request:** Break the client message into discrete requested capabilities (e.g., Request A: Okta SSO; Request B: multi-region failover).
2. **Match Against Structured Scope Items:** Compare each requested capability against every `in_scope`, `out_of_scope`, and `assumption` item on the project.
3. **Verify Against Signed SOW Text:** Cross-check the exact section numbers and clauses in the retrieved SOW document (e.g., `SOW-2.1`, `SOW-2.2`, `SOW-4.2`).
4. **Assign an Overall Verdict:**
   - `IN_SCOPE`: Every requested capability is explicitly covered under In-Scope Deliverables and violates no assumptions.
   - `OUT_OF_SCOPE_BILLABLE`: One or more requested capabilities match an Explicit Exclusion or add material new deliverables not covered in the SOW.
   - `NEEDS_CLARIFICATION`: The request is ambiguous or partially overlaps an assumption without clear SOW coverage.
5. **Cite Exact Evidence:** Quote or reference the specific SOW section IDs (`SOW-X.Y`) and document path (`source_doc_ref`) for each finding.
6. **Recommend Commercial Next Action:**
   - If `OUT_OF_SCOPE_BILLABLE`, instruct the PM to log a formal `ChangeRequest` before adding work to the sprint, and provide a concise, diplomatic client response framing the commercial Change Order process.
   - Never reveal internal `margin_notes` or confidential cost structures in client-facing wording.

## Expected JSON Output Format (when JSON mode is requested)
```json
{
  "verdict": "IN_SCOPE | OUT_OF_SCOPE_BILLABLE | NEEDS_CLARIFICATION",
  "summary": "One-sentence executive summary of the determination.",
  "findings": [
    {
      "requested_item": "Name of requested feature",
      "classification": "in_scope | out_of_scope | assumption",
      "sow_citation": "Exact SOW section reference (e.g., SOW-2.1 in sow_v1.md)",
      "rationale": "Why this item is in or out of scope."
    }
  ],
  "recommended_action": "Concrete next step for the PM (e.g., create billable Change Request).",
  "should_create_change_request": true,
  "suggested_client_reply": "Polite, professional response the PM can send to the client."
}
```
