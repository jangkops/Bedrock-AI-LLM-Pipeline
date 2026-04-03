# Phase 4 Backend MVP — Execution Package

> ⚠️ SUPERSEDED by `docs/ai/phase4-execution-readiness-master.md` (2026-03-23). This document is retained as a historical artifact. Do not use for Phase 4 execution decisions.
>
> Date: 2026-03-23
> Status: HISTORICAL — superseded by phase4-execution-readiness-master.md
> Scope: Phase 4 backend MVP for gateway operator menu (backend-admin endpoints only)
> Prerequisites: Phase 2 COMPLETE. Phase 3 COMPLETE (2026-03-23).
> API contract: `docs/ai/account-portal-mvp-api-data-contract.md` (v2)
> This document does NOT modify runtime code, IaC, or deployment configs.

---

## 1. Scope

Phase 4 Backend MVP delivers the minimum backend-admin API surface needed for an operator to monitor gateway-managed user usage, quotas, and policies through the account-portal. It does NOT include frontend views (Phase 5), direct-use exception user visibility (post-MVP), or approval ladder corrections (Phase 3).

---

## 2. Objectives

1. Expose per-user monthly KRW usage and per-model breakdown via API
2. Expose per-user request history with date-range filtering via API
3. Expose per-user policy/quota/boost state via API
4. Expose model pricing reference data via API
5. Enforce admin-only authorization on all new operator endpoints
6. Structurally separate gateway-managed users from direct-use exception users in API responses
7. Enable the `request_ledger` GSI that makes per-user request queries efficient

---

## 3. Included MVP Backlog Items

| # | Backlog Item | Source | Type |
|---|-------------|--------|------|
| M1 | Admin authorization enforcement for operator endpoints | R26 | backend-admin middleware |
| M2 | BL-1: GSI on `request_ledger` (`principal_id` HK + `timestamp` RK, projection ALL) | BL-1 | Terraform additive |
| M3 | `gateway_usage.py` blueprint + `app.py` registration | New | backend-admin route file |
| M4 | `GET /api/gateway/users` (V1: User Overview) | Endpoint 4.1 | Flask route |
| M5 | `GET /api/gateway/users/<pid>/usage` (V2: Monthly Usage) | Endpoint 4.2 | Flask route |
| M6 | `GET /api/gateway/users/<pid>/requests` (V3: Request History) | Endpoint 4.3 | Flask route |
| M7 | `GET /api/gateway/users/<pid>/policy` (Policy Detail) | Endpoint 4.4 | Flask route |
| M8 | `GET /api/gateway/pricing` (Pricing Reference) | Endpoint 4.5 | Flask route |

---

## 4. Excluded Items

| Item | Reason | Deferred To |
|------|--------|-------------|
| Direct-use exception user usage endpoint (shlee CW Insights) | Not needed for gateway operator dashboard; manual CW queries sufficient | Post-MVP / separate future work |
| Frontend React views for V1–V4 | Phase 5 scope | Phase 5 |
| Approval ladder rewrite (UTC→KST TTL, reason validation) | Phase 3 scope; V4 endpoints already exist and function | Phase 3 |
| Admin-action-log table | Nice-to-have audit trail; not blocking for core queries | Post-Phase-4 |
| Bypass/anomaly detection endpoint | Security enhancement, not core | Separate future work |
| `daily_usage` table removal | Post-Phase-3 cleanup | Post-Phase-3 |
| Policy CRUD endpoints (create/update/delete `principal_policy`) | Admin currently manages via DynamoDB console; API CRUD is a separate scope | Post-MVP |
| SES notification integration for usage alerts | Depends on SES domain verification (R23); non-blocking for query endpoints | Post-MVP |

---

## 5. Authoritative Data Sources

### Gateway-Managed Users (MVP scope)

| Data Need | Table | Key Pattern |
|-----------|-------|-------------|
| User enumeration | `principal_policy` | Scan (≤10 items) |
| Monthly KRW total + per-model breakdown | `monthly_usage` | Query PK `<pid>#YYYY-MM` |
| Per-request audit trail | `request_ledger` | GSI: `principal_id` (HK) + `timestamp` (RK) |
| Policy state (base limit, hard cap, allowed models) | `principal_policy` | GetItem by `principal_id` |
| Active boosts / approval band | `temporary_quota_boost` | Query by `principal_id`, filter TTL > now |
| Pending approval check | `approval_pending_lock` | GetItem by `principal_id` |
| Model pricing rates | `model_pricing` | Scan (≤10 items) |

### Direct-Use Exception Users (NOT in MVP)

| Data Need | Source | Notes |
|-----------|--------|-------|
| Per-request usage (tokens, model) | `/aws/bedrock/modelinvocations` | CW Logs Insights query |
| KRW cost estimation | CW tokens × `model_pricing` rates | Derived, not pre-computed |

Exception users appear in MVP API responses as metadata-only entries in the `exception_users` array — no usage data, no gateway metrics. See API contract §2.2.

---

## 6. Required Backend Endpoints

All endpoints in `routes/gateway_usage.py`, registered as `gateway_usage_bp`.

| # | Method | Path | View | GSI Required |
|---|--------|------|------|-------------|
| 4.1 | GET | `/api/gateway/users` | V1: User Overview | No |
| 4.2 | GET | `/api/gateway/users/<pid>/usage` | V2: Monthly Usage | No |
| 4.3 | GET | `/api/gateway/users/<pid>/requests` | V3: Request History | **Yes (BL-1)** |
| 4.4 | GET | `/api/gateway/users/<pid>/policy` | Policy Detail | No |
| 4.5 | GET | `/api/gateway/pricing` | Pricing Reference | No |

Request/response schemas: see API contract §4.1–4.5.

All endpoints require admin authorization enforcement (see §7.1).

---

## 7. Required Dependency Changes

### 7.1 Admin Authorization Enforcement (M1)

**Current state**: JWT-based authentication exists in `routes/auth.py`. Login returns a JWT token with `username`, `account_id`, `role`, `exp`. Verify endpoint decodes and validates. No reusable middleware enforces admin-only access on arbitrary routes.

**Required**: An explicit admin authorization boundary for all `gateway_usage_bp` endpoints. Unauthenticated or non-admin requests must be rejected with `401` (no token / expired) or `403` (insufficient role).

**Implementation options** (design decision, not prescribed):
- (A) `@admin_required` decorator extracting and verifying JWT from `Authorization` header, checking `role == "admin"`
- (B) `before_request` hook on the `gateway_usage_bp` blueprint
- (C) Flask middleware class

The binding requirement is the authorization boundary, not the specific mechanism. Option A is the simplest and most explicit.

**Risk reference**: R26 in `risk_register.md`.

### 7.2 GSI on `request_ledger` (M2 / BL-1)

**Current state**: `request_ledger` has PK `request_id` only. No GSI. Per-user queries require full table scan.

**Required**: Global Secondary Index added to `request_ledger` in `infra/bedrock-gateway/dynamodb.tf`:
- Hash key: `principal_id` (S)
- Range key: `timestamp` (S)
- Projection: ALL

**Terraform change**: One `global_secondary_index` block + two `attribute` blocks added to the existing `aws_dynamodb_table.request_ledger` resource. In-place update — no table recreation. GSI backfill is automatic for existing items.

**Blast radius**: None. Additive change. No existing queries, Lambda code, or IAM policies affected. The Lambda IAM policy already has `dynamodb:Query` on `request_ledger` (needed for the GSI query from backend-admin, which uses its own IAM context via the container's mounted credentials).

**Blocks**: Endpoint 4.3 (request history). Endpoints 4.1, 4.2, 4.4, 4.5 are NOT blocked by this GSI.

### 7.3 Blueprint File + Registration (M3)

**Required**:
- Create `account-portal/backend-admin/routes/gateway_usage.py` with `gateway_usage_bp` Blueprint
- Add `app.register_blueprint(gateway_usage_bp)` to `account-portal/backend-admin/app.py`

---

## 8. Implementation Order

```
Step 1: M1 — Admin authorization enforcement
  - Establish reusable admin auth boundary (decorator or hook)
  - Verify: unauthenticated requests → 401, non-admin → 403

Step 2: M2 — GSI on request_ledger (Terraform)
  - Add GSI definition to dynamodb.tf
  - terraform plan → review (expect 1 in-place update)
  - terraform apply (requires explicit approval)
  - Wait for GSI backfill to complete (check via AWS console or CLI)

Step 3: M3 + M4 + M5 + M8 — Blueprint + non-GSI endpoints
  - Create gateway_usage.py
  - Implement endpoints 4.1 (users), 4.2 (usage), 4.5 (pricing)
  - Register blueprint in app.py
  - Validate: correct data returned for cgjang

Step 4: M7 — Policy detail endpoint
  - Implement endpoint 4.4 (policy)
  - Validate: effective limit, band, boosts correct for cgjang

Step 5: M6 — Request history endpoint (depends on Step 2 GSI)
  - Implement endpoint 4.3 (requests)
  - Validate: per-user request history with date-range filter for cgjang

Step 6: Integration validation
  - All 5 endpoints return correct data
  - Exception users appear in 4.1 response as metadata-only
  - Auth enforcement verified on all endpoints
  - Docker rebuild + redeploy backend-admin container
```

---

## 9. Acceptance Criteria

| # | Criterion | Endpoint | Validation Method |
|---|-----------|----------|-------------------|
| AC1 | `GET /api/gateway/users` returns all gateway-managed users with correct monthly KRW totals | 4.1 | Compare response `current_month_cost_krw` against direct `monthly_usage` DynamoDB query for cgjang |
| AC2 | `GET /api/gateway/users` returns exception users in separate `exception_users` array with no gateway metrics | 4.1 | Verify shlee appears with `gateway_managed: false`, no cost/token fields |
| AC3 | `GET /api/gateway/users/<pid>/usage` returns per-model breakdown matching `monthly_usage` data | 4.2 | Cross-check model-level cost/tokens against DynamoDB |
| AC4 | `GET /api/gateway/users/<pid>/requests` returns paginated request history sorted by timestamp descending | 4.3 | Verify pagination with `limit=1`, check `next_token` works |
| AC5 | `GET /api/gateway/users/<pid>/requests` supports date-range filtering | 4.3 | Query with `start_date`/`end_date`, verify only matching records returned |
| AC6 | `GET /api/gateway/users/<pid>/policy` returns correct effective limit and approval band | 4.4 | Compare against `_get_effective_limit()` result for cgjang |
| AC7 | `GET /api/gateway/pricing` returns all models from `model_pricing` table | 4.5 | Compare count and fields against DynamoDB scan |
| AC8 | All endpoints reject unauthenticated requests with 401 | All | curl without Authorization header |
| AC9 | All endpoints reject non-admin requests with 403 | All | curl with valid non-admin JWT |
| AC10 | Exception user principal_id on usage/requests/policy endpoints returns 404 | 4.2–4.4 | Request shlee's principal_id, expect 404 |

---

## 10. Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | GSI backfill time for `request_ledger` may delay endpoint 4.3 | Low | Current table has minimal items (dev environment). Backfill should complete in seconds-to-minutes. |
| R2 | `principal_policy` scan returns exception users (if shlee has a policy record) | Medium | Check: does shlee have a `principal_policy` record? If yes, filter by exception-user list. If no, scan naturally excludes shlee. |
| R3 | JWT secret key is hardcoded default in `auth.py` (`mogam-portal-secret-key-2024`) | Medium | Existing issue, not introduced by Phase 4. Should be addressed separately (env var or secrets manager). |
| R4 | `Decimal` serialization in DynamoDB responses | Low | Known issue — `gateway_approval.py` already handles this with `int()` conversion. New endpoints must apply same pattern. Use `float()` for KRW cost fields. |
| R5 | Phase 3 not complete — approval TTL uses UTC not KST | ~~Low~~ Closed | ✅ Phase 3 COMPLETE (2026-03-23). TTL KST fix deployed and verified. |

---

## 11. Blockers / Prerequisites

| Blocker | Status | Blocks | Resolution Path |
|---------|--------|--------|----------------|
| Phase 4 implementation approval | ❌ NOT GRANTED | All implementation | Operator must explicitly approve Phase 4 start |
| Phase 3 complete | ✅ COMPLETE (2026-03-23) | — | Phase 3 deployed and verified. TTL KST fix operational. |
| GSI deployment (BL-1) | ❌ NOT DEPLOYED | Endpoint 4.3 only | Terraform apply in Step 2. Endpoints 4.1, 4.2, 4.4, 4.5 are NOT blocked. |
| Admin auth enforcement | ⚠️ NOT IMPLEMENTED | All new endpoints | Step 1 of implementation order. |
| Docker rebuild/redeploy of backend-admin | Required after code changes | All new endpoints going live | Standard `docker compose up -d --build` for backend-admin. |

---

## 12. Boundary Statement

This document is a Phase 4 backend MVP planning artifact only. No runtime code, IaC, deployment configs, or infrastructure were modified in this step. No implementation is performed or authorized by this document.

Constraints preserved:
- shlee remains a direct-use exception — excluded from gateway enforcement and MVP usage views
- Phase 2 validation conclusions are not reopened
- Phase 3 approval ladder rewrite is not started or modified
- Existing `gateway_approval.py` is not modified
- No frontend implementation is included
- Each implementation step requires separate explicit approval
