# Statement of Work (SOW v1.0) — FinBridge UK Core Payments MVP

- **Document ID:** `finbridge_uk/sow_v1.md`
- **Client:** FinBridge UK Ltd. (`finbridge_uk`)
- **Project ID:** `finbridge_mvp`
- **Effective Date:** 2026-10-20
- **Engagement Model:** Fixed-Price MVP Delivery (12 Weeks)
- **Contract Value:** $185,000 USD (Milestone-based billing)

---

## Section 1: In-Scope Deliverables (MVP Phase 1)
The Delivery Team will design, build, test, and deploy the following deliverables in AWS `eu-west-2` (London):

1. **SOW-1.1 — Core Payment Ledger API:** Double-entry ledger REST service backed by PostgreSQL with idempotent transaction processing and immutable audit trails.
2. **SOW-1.2 — UK Open Banking Connector:** Integration with a single UK Open Banking aggregator for GBP payment initiation and settlement webhook reconciliation.
3. **SOW-1.3 — Standard Operations Authentication:** Email/password login with TOTP-based multi-factor authentication (MFA) and role-based access control (Admin, Ops, Viewer).
4. **SOW-1.4 — Single-Region AWS Infrastructure (Terraform):** Provisioning of isolated `staging` and `production` environments strictly inside AWS `eu-west-2` (London), including VPC, private subnets, RDS PostgreSQL, and CI/CD pipelines.
5. **SOW-1.5 — Observability & Runbooks:** Structured logging, CloudWatch alarms, and operational handover runbooks.

---

## Section 2: Explicit Exclusions (Out of Scope)
The following capabilities are **explicitly excluded** from this SOW and require a formally approved, billable **Change Request (CR)** before any design or engineering work begins:

1. **SOW-2.1 — Enterprise Identity Federation & Okta SSO:** Integration with Okta SSO, Azure AD/Entra ID, SAML 2.0, or OIDC enterprise identity providers is **OUT OF SCOPE** for MVP Phase 1.
2. **SOW-2.2 — Multi-Region Active-Active Failover:** Cross-region database replication, multi-region active-active failover, and global traffic routing are **OUT OF SCOPE** for MVP Phase 1.
3. **SOW-2.3 — Native Mobile Applications:** iOS and Android applications are excluded; only the web interface is in scope.
4. **SOW-2.4 — External PCI-DSS Level 1 QSA Audit Remediation:** Advisory support beyond documented SOC 2 / UK-GDPR controls is excluded.

---

## Section 3: Technical, Cloud & Regulatory Guardrails
All engineering and DevOps implementations MUST comply with the following binding project guardrails:

1. **SOW-3.1 — UK Data Residency (`HARD_BLOCK`):** All cloud resources, databases, object storage, and backups MUST be provisioned exclusively in AWS region **`eu-west-2` (London)**. Provisioning in `us-east-1` or any non-UK region is strictly prohibited.
2. **SOW-3.2 — Staging Cloud Budget Cap (`HARD_BLOCK`):** Monthly AWS spend for the staging environment MUST NOT exceed **$400/month**. High-cost database tiers (e.g., multi-AZ large RDS instances exceeding budget) are blocked without written CTO and PM approval.
3. **SOW-3.3 — Security & Encryption (`HARD_BLOCK`):** All RDS instances and S3 buckets MUST enforce KMS encryption at rest, disable public internet access, and require TLS 1.2+ in transit.
4. **SOW-3.4 — Service Availability Target (`WARNING`):** Production environment targets 99.9% monthly uptime within single-region multi-AZ `eu-west-2`, with RPO <= 15 minutes and RTO <= 2 hours.

---

## Section 4: Assumptions & Change Control Procedure
- **SOW-4.1 — Client Dependencies:** FinBridge UK provides sandbox Open Banking credentials and AWS account access in `eu-west-2` by Week 1.
- **SOW-4.2 — Change Control:** Any client request falling under Section 2 (Explicit Exclusions) or altering Section 1 deliverables must be classified as `OUT_OF_SCOPE_BILLABLE`, logged as a formal `ChangeRequest`, estimated at the agreed Change Order rate card ($165/hr blended), and approved by the Project Manager and Client Sponsor prior to sprint inclusion.
