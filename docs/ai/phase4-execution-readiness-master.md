# Phase 4 Execution-Readiness Master

> Date: 2026-03-23
> Status: PLANNING ONLY — Phase 4 implementation NOT STARTED, NOT APPROVED
> Authority: This is the single authoritative Phase 4 execution-readiness artifact.
> Prerequisites: Phase 2 COMPLETE (2026-03-20). Phase 3 DEPLOYED AND VERIFIED (2026-03-23).
> Scope: backend-admin operator API surface only. No frontend, no Lambda, no Terraform apply without approval.
> This document does NOT modify runtime code, IaC, or deployment configs.

---

## 1. Scope and Boundary

### What Phase 4 IS

Phase 4 delivers the minimum backend-admin API surface for an operator to monitor gateway-managed user usage, quotas, policies, and request history through the account-portal. All endpoints live in `backend-admin` (the admin/operations plane). The enforcement plane (`infra/bedrock-gateway/`) is NOT modified except for one additive GSI on `request_ledger`.

### What Phase 4 is NOT

- NOT frontend (Phase 5)
- NOT Lambda handler changes
- NOT inference proxy — backend-admin serves admin-plane queries only
- NOT shlee visibility (post-MVP; manual CW Insights queries are sufficient)
- NOT policy CRUD (admin manages via DynamoDB console for now)
- NOT SES alert integration (blocked by R23 domain verification)
- NOT `daily_usage` removal (post-Phase-3 cleanup, separate approval)
- NOT admin-action-log (post-Phase-4)
- NOT bypass/anomaly detection (separate future work)

### Non-Goals (explicitly excluded)

| Item | Reason | Deferred To |
|------|--------|-------------|
| shlee CW Insights endpoint | Manual CW queries sufficient; separate data source | Post-MVP |
| Frontend React views (V1–V4) | Phase 5 scope | Phase 5 |
| Policy CRUD endpoints (create/update/delete `principal_policy`) | Admin manages via DynamoDB console | Post-MVP |
| Admin-action-log table | Nice-to-have audit trail | Post-Phase-4 |
| Bypass/anomaly detection endpoint | Security enhancement | Separate future work |
| `daily_usage` table removal | Post-Phase-3 cleanup | Separate approval |
| SES usage alerts | Blocked by R23 (`mogam.er.kr` domain unverified) | Post-MVP |

---

## 2. Prerequisite Status

| Prerequisite | Status | Evidence |
|-------------|--------|---------|
| Phase 0 (Q1-Q6 decisions) | ✅ COMPLETE | `docs/ai/decision-resolution-q1-q6.md` |
| Phase 1 (data model migration) | ✅ COMPLETE | Tables deployed 2026-03-18 |
| Phase 2 (Lambda quota logic) | ✅ COMPLETE | All C1-C9 PASS, `docs/ai/phase2-dev-validation-report.md` |
| Task 2 (bypass prevention) | ✅ COMPLETE | Live verified 2026-03-19 |
| Phase 3 (approval ladder) | ✅ COMPLETE | Deployed and verified 2026-03-23, `docs/ai/phase3-dev-validation-report.md` |
| Phase 4 implementation approval | ❌ NOT GRANTED | Requires explicit operator approval |

All technical prerequisites are met. The only blocker is governance approval.

---

## 3. Exact MVP Boundary

### Included (M1–M8)

| # | Item | Type | Description |
|---|------|------|-------------|
| M1 | Admin auth enforcement | Middleware | `@admin_required` decorator or equivalent for all new endpoints |
| M2 | GSI on `request_ledger` | Terraform additive | `principal_id` (HK) + `timestamp` (RK), projection ALL |
| M3 | `gateway_usage.py` blueprint | New file | Blueprint + `app.py` registration |
| M4 | `GET /api/gateway/users` | Endpoint 4.1 | User overview: all managed users with monthly KRW totals |
| M5 | `GET /api/gateway/users/<pid>/usage` | Endpoint 4.2 | Per-model monthly breakdown for a user |
| M6 | `GET /api/gateway/users/<pid>/requests` | Endpoint 4.3 | Per-user request history (paginated, date-range) |
| M7 | `GET /api/gateway/users/<pid>/policy` | Endpoint 4.4 | Policy detail: effective limit, band, boosts |
| M8 | `GET /api/gateway/pricing` | Endpoint 4.5 | Model pricing reference |

### Exception user treatment in MVP

shlee appears in endpoint 4.1 response as a metadata-only entry in the `exception_users` array — no usage data, no gateway metrics. Endpoints 4.2–4.4 return `404` for exception user principal_ids.

---

## 4. Data Sources and Query Requirements

### Gateway-Managed Users (MVP scope)

| Data Need | Table | Key Pattern | Efficiency |
|-----------|-------|-------------|------------|
| User enumeration | `principal_policy` | Scan (≤10 items) | Good |
| Monthly KRW total + per-model | `monthly_usage` | Query PK `<pid>#YYYY-MM` | Good |
| Per-request audit trail | `request_ledger` | **GSI**: `principal_id` (HK) + `timestamp` (RK) | Good (after M2) |
| Policy state | `principal_policy` | GetItem by `principal_id` | Good |
| Active boosts / band | `temporary_quota_boost` | Query by `principal_id`, filter TTL > now | Good |
| Pending approval | `approval_pending_lock` | GetItem by `principal_id` | Good |
| Model pricing | `model_pricing` | Scan (≤10 items) | Good |

### Current gap

`request_ledger` PK is `request_id` only — no GSI on `principal_id`. Per-user queries require full table scan. M2 (GSI) resolves this. Without M2, endpoint 4.3 is impossible at acceptable performance.

---

## 5. Backend Responsibility Split

| Plane | Component | Phase 4 Role |
|-------|-----------|-------------|
| Enforcement plane | `infra/bedrock-gateway/` (API GW + Lambda + DynamoDB) | Read-only data source. One additive GSI (M2). No Lambda/handler changes. |
| Admin/operations plane | `account-portal/backend-admin/` | New `gateway_usage.py` blueprint with 5 GET endpoints. Auth enforcement. |
| Approval plane | `account-portal/backend-admin/routes/gateway_approval.py` | Already exists. NOT modified in Phase 4. |
| Frontend | `account-portal/frontend/` | NOT in Phase 4 scope. |

backend-admin reads DynamoDB tables using its own IAM context (container's mounted AWS credentials). It does NOT proxy through the Lambda or API Gateway.

---

## 6. Dependency Chain

```
M1 (admin auth) ─────────────────────────────────┐
                                                   ▼
M3 (blueprint) ──► M4 (users) ──► M5 (usage) ──► M8 (pricing) ──► M7 (policy)
                                                                        │
M2 (GSI terraform) ──────────────────────────────────────────────► M6 (requests)
```

- M1 must be first (all endpoints depend on auth)
- M3 must exist before any endpoint
- M4, M5, M7, M8 have no infrastructure dependency (can proceed immediately after M1+M3)
- M6 is blocked on M2 (GSI must be deployed and backfill complete)
- M2 can proceed in parallel with M1+M3 (independent Terraform change)

---

## 7. Ready vs Blocked Classification

### Ready now (after Phase 4 approval)

| Item | Dependencies | Notes |
|------|-------------|-------|
| M1: Admin auth enforcement | JWT auth in `auth.py` | Reusable decorator or hook |
| M3: Blueprint creation + registration | None | New file + `app.py` edit |
| M4: `GET /api/gateway/users` | M1 + M3 | Scans `principal_policy`, queries `monthly_usage` |
| M5: `GET /api/gateway/users/<pid>/usage` | M1 + M3 | Queries `monthly_usage` + `model_pricing` |
| M7: `GET /api/gateway/users/<pid>/policy` | M1 + M3 | GetItem `principal_policy` + query `temporary_quota_boost` |
| M8: `GET /api/gateway/pricing` | M1 + M3 | Scan `model_pricing` |

### Blocked on GSI deploy (M2)

| Item | Blocker | Resolution |
|------|---------|------------|
| M6: `GET /api/gateway/users/<pid>/requests` | M2 GSI not deployed | `terraform plan/apply` adds GSI to `request_ledger`. In-place update, no table recreation. Backfill automatic. |

### Blocked on governance

| Item | Blocker |
|------|---------|
| ALL (M1–M8) | Phase 4 implementation approval NOT GRANTED |

---

## 8. Recommended First Implementation Unit

**M1 + M3 + M4 + M5 + M7 + M8** — admin auth + blueprint + four non-GSI endpoints.

This is the approved first implementation scope. M7 is included (not deferred) because it queries the same tables already accessed by M4 (`principal_policy`, `temporary_quota_boost`, `approval_pending_lock`), the `_get_effective_limit()` helper already exists in `gateway_approval.py`, and excluding M7 would leave the operator unable to inspect a user's policy state after seeing the overview.

Rationale:
- Highest operator value: user overview (M4), monthly usage (M5), and policy detail (M7) answer the most frequent operator questions
- Zero infrastructure dependency: no Terraform, no GSI, no new tables
- Smallest blast radius: new Flask blueprint + decorator, no existing code modified
- Validates the full pattern: auth → DynamoDB read → JSON response
- M2 (GSI) + M6 (request history) follow as a second unit once Terraform is approved

### Implementation order within first unit

```
Step 1: M1 — @admin_required decorator in gateway_usage.py
  - Decode JWT from Authorization header (Bearer token)
  - Verify signature with SECRET_KEY from auth.py
  - Check payload role == "admin"
  - Return 401 if missing/expired/invalid token
  - Return 403 if role != "admin"
  - Verify: curl without token → 401, curl with non-admin token → 403

Step 2: M3 — Create routes/gateway_usage.py with gateway_usage_bp Blueprint
  - Add import + app.register_blueprint(gateway_usage_bp) in app.py
  - Verify: Flask app starts without errors

Step 3: M8 — GET /api/gateway/pricing
  - Scan model_pricing table, return all models
  - Verify: response matches DynamoDB scan

Step 4: M4 — GET /api/gateway/users
  - Scan principal_policy → managed users
  - For each: query monthly_usage, temporary_quota_boost, approval_pending_lock
  - Append hardcoded exception_users array (shlee)
  - Verify: cgjang in managed_users with correct KRW totals, shlee in exception_users

Step 5: M5 — GET /api/gateway/users/<pid>/usage
  - Query monthly_usage by principal_id + month
  - Join with model_pricing for rates
  - Return 404 for exception users
  - Verify: per-model breakdown matches DynamoDB for cgjang

Step 6: M7 — GET /api/gateway/users/<pid>/policy
  - GetItem principal_policy + query temporary_quota_boost + GetItem approval_pending_lock
  - Derive effective_limit_krw and approval_band
  - Return 404 for exception users
  - Verify: effective limit, band, boosts correct for cgjang
```

### Second implementation unit (requires separate Terraform approval)

```
Step 7: M2 — Add GSI to request_ledger (terraform plan → review → apply)
  - GSI: principal_id (HK) + timestamp (RK), projection ALL
  - Wait for GSI backfill (seconds-to-minutes on dev table)

Step 8: M6 — GET /api/gateway/users/<pid>/requests
  - Query request_ledger GSI with date-range filter and pagination
  - Verify: per-user request history with date-range filter for cgjang
```

---

## 9. Acceptance Criteria

### First Implementation Unit (M1 + M3 + M4 + M5 + M7 + M8)

| # | Criterion | Endpoint | Method |
|---|-----------|----------|--------|
| AC1 | Users endpoint returns all managed users with correct monthly KRW totals | 4.1 | Compare `current_month_cost_krw` vs direct DynamoDB query |
| AC2 | Exception users in separate `exception_users` array, no gateway metrics | 4.1 | Verify shlee: `gateway_managed: false` |
| AC3 | Per-model breakdown matches `monthly_usage` data | 4.2 | Cross-check model-level cost/tokens |
| AC6 | Policy detail returns correct effective limit and band | 4.4 | Compare vs `_get_effective_limit()` |
| AC7 | Pricing returns all models from `model_pricing` | 4.5 | Compare count/fields vs DynamoDB scan |
| AC8 | All endpoints reject unauthenticated with 401 | All | curl without Authorization |
| AC9 | All endpoints reject non-admin with 403 | All | curl with non-admin JWT |
| AC10 | Exception user pid on 4.2/4.4 returns 404 | 4.2, 4.4 | Request shlee's pid |

### Second Implementation Unit (M2 + M6)

| # | Criterion | Endpoint | Method |
|---|-----------|----------|--------|
| AC4 | Request history paginated, sorted by timestamp desc | 4.3 | `limit=1`, verify `next_token` |
| AC5 | Request history supports date-range filtering | 4.3 | `start_date`/`end_date` params |
| AC10b | Exception user pid on 4.3 returns 404 | 4.3 | Request shlee's pid |

---

## 10. Rollout Order

1. Code changes (M1, M3, M4, M5, M7, M8) → Docker rebuild backend-admin → validate endpoints
2. Terraform plan for M2 (GSI) → review → apply (separate approval gate)
3. Wait for GSI backfill → implement M6 → Docker rebuild → validate endpoint 4.3
4. Full integration validation (all 5 endpoints + auth)

### Rollback guidance

- Code rollback: revert `gateway_usage.py` + `app.py` registration, rebuild container
- GSI rollback: remove GSI block from `dynamodb.tf`, `terraform apply` (GSI deletion is non-destructive to base table)
- No existing endpoints, Lambda, or infrastructure are modified — rollback is purely subtractive

---

## 11. Open Decisions Needing Approval

| # | Decision | Options | Recommendation | Blocks |
|---|----------|---------|---------------|--------|
| D1 | Phase 4 implementation start | Approve / Defer | Approve — all prerequisites met | ALL |
| D2 | GSI Terraform apply | Approve / Defer | Approve with Phase 4 — additive, zero blast radius | M6 only |
| D3 | Auth mechanism | (A) `@admin_required` decorator (B) `before_request` hook (C) middleware | A — simplest, explicit, matches existing `gateway_approval.py` pattern | M1 |
| D4 | Exception user identification | (A) Hardcoded list (B) `principal_policy` attribute | A for MVP — only 1 exception user | M4 |

---

## 12. Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R-P4-1 | GSI backfill delay | Low | Dev table has minimal items; seconds-to-minutes |
| R-P4-2 | `principal_policy` scan returns shlee (if record exists) | Medium | Filter by exception-user list; verify shlee has no policy record |
| R-P4-3 | JWT secret hardcoded (`mogam-portal-secret-key-2024`) | Medium | Existing issue, not introduced by Phase 4; address separately |
| R-P4-4 | `Decimal` serialization from DynamoDB | Low | Known pattern — `gateway_approval.py` uses `int()`/`float()` conversion |
| R10 | backend-admin IAM role needs DynamoDB read on gateway tables | Medium | Container uses mounted AWS credentials; verify IAM permissions |
| R23 | Approver email domain unverified (`mogam.er.kr`) | Medium | Non-blocking for Phase 4 query endpoints |
| R26 | Admin auth enforcement gap | High→Mitigated | M1 establishes auth boundary before any endpoint goes live |

---

## 13. Document Authority Mapping

### Authoritative (active, maintained)

| Document | Role | Updated |
|----------|------|---------|
| `docs/ai/phase4-execution-readiness-master.md` (this file) | Single authoritative Phase 4 execution-readiness artifact | 2026-03-23 |
| `docs/ai/account-portal-mvp-api-data-contract.md` | Authoritative API schemas (request/response formats) — referenced, not duplicated | 2026-03-20 |
| `.kiro/specs/bedrock-access-gateway/tasks.md` | Phase task tracker (Phase 4 tasks listed) | 2026-03-20 |
| `.kiro/specs/bedrock-access-gateway/design.md` | Architecture and data model (locked decisions) | 2026-03-20 |
| `.kiro/specs/bedrock-access-gateway/requirements.md` | Requirements (Req 11, Req 12 cover Phase 4/5) | 2026-03-20 |
| `docs/ai/project-status-summary.md` | Project-wide status | 2026-03-23 |
| `docs/ai/todo.md` | Master TODO tracker | 2026-03-23 |
| `docs/ai/risk_register.md` | Risk register | 2026-03-23 |

### Superseded by this document (historical/reference only)

| Document | Original Role | Superseded Reason |
|----------|--------------|-------------------|
| `docs/ai/phase4-backend-mvp-execution-package.md` | Phase 4 execution package | Content consolidated into this master document |
| `docs/ai/account-portal-implementation-ready-backlog.md` | Implementation backlog (BL-1–BL-9) | Backlog items consolidated into §3 (MVP boundary) and §7 (ready/blocked) |
| `docs/ai/account-portal-operator-observability-future-work.md` | Comprehensive observability assessment | Assessment findings incorporated; future-work items remain valid reference for post-MVP |

These documents remain in the repo as historical artifacts. They are not deleted but should not be treated as authoritative for Phase 4 execution decisions. This master document is the single source of truth.

---

## 14. Stale Reference Corrections

The following stale references exist in superseded documents. They are noted here for completeness but do NOT require edits since those documents are now historical:

| Document | Stale Reference | Correct State |
|----------|----------------|---------------|
| `phase4-backend-mvp-execution-package.md` §4 | "Phase 3 NOT STARTED" in excluded items table | Phase 3 DEPLOYED AND VERIFIED (2026-03-23) |
| `account-portal-mvp-api-data-contract.md` §6 | "Phase 3 NOT STARTED" in dependencies | ✅ CORRECTED (2026-03-23) |
| `account-portal-mvp-api-data-contract.md` header | "Phase 3 NOT STARTED. Phase 4 FROZEN." | ✅ CORRECTED (2026-03-23) |
| `account-portal-operator-observability-future-work.md` header | "Phase 3 NOT STARTED" | Phase 3 COMPLETE |
| `.kiro/specs/bedrock-access-gateway/design.md` header | "Phase 3 NOT STARTED" | Phase 3 COMPLETE |
| `.kiro/specs/bedrock-access-gateway/requirements.md` header | "Phase 3 NOT STARTED" | Phase 3 COMPLETE |

---

## 15. Final Execution-Readiness Verdict

All technical prerequisites for Phase 4 are met:
- Phase 2 complete and verified (all C1-C9 PASS)
- Phase 3 deployed and verified (all critical AC PASS, KST TTL confirmed)
- DynamoDB tables with live data exist and are queryable
- `gateway_approval.py` exists as a working pattern for new blueprints
- JWT auth infrastructure exists in `auth.py` (SECRET_KEY, HS256, role claim)
- API schemas fully specified in `account-portal-mvp-api-data-contract.md`
- No infrastructure blockers for first unit (M1+M3+M4+M5+M7+M8)

**Verdict: EXECUTION-READY pending operator approval.**

### Approval Scope A — Code-Only Phase 4 MVP

> "Phase 4 code implementation approved. Scope: `@admin_required` decorator, `gateway_usage.py` blueprint with endpoints 4.1/4.2/4.4/4.5, `app.py` registration. No Terraform, no Lambda, no existing code modified. Docker rebuild of backend-admin required after implementation."

This unlocks: M1, M3, M4, M5, M7, M8.

### Approval Scope B — GSI Terraform (separate gate)

> "GSI Terraform apply approved. Scope: add one Global Secondary Index (`principal_id` HK + `timestamp` RK, projection ALL) to `request_ledger` table in `infra/bedrock-gateway/dynamodb.tf`. In-place DynamoDB update, no table recreation. Then implement endpoint 4.3 in `gateway_usage.py`."

This unlocks: M2, then M6.

Minimum approval to start: Scope A only. Scope B can follow independently.

---

## Boundary Statement

This document is a Phase 4 planning artifact only. No runtime code, IaC, deployment configs, or infrastructure were modified. No implementation is performed or authorized by this document. Each implementation step requires explicit operator approval.
