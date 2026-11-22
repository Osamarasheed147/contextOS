# FinBridge UK — Pre-Sales Discovery Notes

- **Client:** FinBridge UK Ltd. (London, United Kingdom)
- **Engagement:** FinBridge Core Payments MVP (`finbridge_mvp`)
- **Pre-Sales Lead:** Priya Nair (Principal Solutions Architect)
- **Client Stakeholders:** Marcus Vance (CTO), Eleanor Finch (Head of Risk & Compliance)
- **Date:** 2026-10-14
- **NDA Tier:** Mutual Strict NDA (Tier 1 — Regulated FinTech)

## 1. Business Context
FinBridge UK is an FCA-regulated B2B payment orchestration startup preparing for its Series A launch in London. They need an external delivery partner to build their **v1 Payment Ledger & Open Banking Orchestration MVP** within 12 weeks so they can onboard their first 15 UK SME treasury customers.

## 2. Regulatory & Data Residency Constraints
- **UK Data Residency (Non-Negotiable):** Eleanor Finch emphasized that all customer PII, payment ledger data, backups, and staging synthetic datasets **must remain strictly within the UK (`eu-west-2`, AWS London)**. Any deployment into US regions (`us-east-1`, `us-west-2`) or EU mainland regions (`eu-central-1`) violates FinBridge's FCA operational resilience filing and UK-GDPR client DPA.
- **Compliance Frameworks:** FCA Operational Resilience, UK-GDPR, SOC 2 Type II readiness.
- **Encryption:** All databases and S3 buckets must use KMS-managed encryption at rest and TLS 1.3 in transit.

## 3. Infrastructure Budget & FinOps Notes
- FinBridge is pre-Series A and closely scrutinizing cloud burn.
- **Staging Environment Budget Cap:** CTO Marcus Vance explicitly capped staging AWS spend at **$400/month** (e.g., `db.t4g.small` single-AZ PostgreSQL RDS + lightweight ECS Fargate tasks).
- Any staging architecture proposal exceeding $400/month requires formal CTO sign-off and cannot be provisioned autonomously by engineering.

## 4. Phase 1 vs. Phase 2 Feature Boundary (Captured in Discovery)
- **Must-Have for Phase 1 MVP:**
  - Core double-entry payment ledger API (FastAPI + PostgreSQL).
  - UK Open Banking (TrueLayer/Yapily) payment initiation connector.
  - Standard email/password authentication with TOTP MFA for operations users.
  - Single-region AWS `eu-west-2` Terraform infrastructure (staging + production) with automated daily snapshots.
- **Explicitly Deferred to Phase 2 (Post-Series A):**
  - **Okta SSO / SAML 2.0 Enterprise Federation:** Nice-to-have for enterprise banks later, NOT needed for initial 15 SME customers. Estimated separately as a 2-week paid Change Request if pulled forward.
  - **Multi-Region Active-Active Failover:** Deferred due to cost and UK residency constraints. Phase 1 relies on single-region multi-AZ production (`eu-west-2`) with automated backups (RPO <= 15 min, RTO <= 2 hours).
  - **Native iOS / Android Mobile Apps:** Out of scope; responsive web portal only.

## 5. Commercial Sensitivity (Internal Pre-Sales Note)
- Fixed-price MVP signed at **$185,000 USD** with a target blended gross margin of 38%.
- Scope discipline is critical: absorbing unpriced enterprise features (such as Okta SSO or multi-region active-active failover) into Sprint 3–5 would erode delivery margin below 25%.
