# Account-Portal MVP Operator Menu — API & Data Contract

> Date: 2026-03-20 (revised)
> Status: DRAFT v2 — no implementation authorized
> Scope: MVP API endpoints, request/response schemas, data source mapping for gateway-managed operator views
> Prerequisites: Phase 2 COMPLETE. Phase 3 DEPLOYED AND VERIFIED (2026-03-23). Phase 4 awaiting approval.
> Source of truth: `phase4-execution-readiness-master.md` (execution-readiness), this document (API schemas)
> This document does NOT modify runtime code, IaC, or deployment configs.

---

## 1. MVP Scope

### 1.1 MVP Views (Phase 4 Backend)

The MVP operator menu provides 4 views, all served by `backend-admin` Flask routes. All views cover **gateway-managed users only**.

| # | View | Description |
|---|------|-------------|
| V1 | User Overview | All gateway-managed users with monthly KRW totals, effective limits, approval band |
| V2 | User Detail — Monthly Usage | Per-model KRW/token breakdown for a specific user-month |
| V3 | User Detail — Request History | Per-request audit trail for a specific user, with date-range filter |
| V4 | Approval Queue | Pending/recent approval requests with effective-limit context (exists: `gateway_approval.py`) |

### 1.2 Explicitly NOT in MVP

| Item | Reason | Deferred To |
|------|--------|-------------|
| Direct-use exception user visibility (shlee usage data) | Requires `/aws/bedrock/modelinvocations` CW Insights integration; manual CW queries are sufficient for v1 | Post-MVP / separate future work |
| shlee usage API endpoint | CloudWatch Logs Insights wrapper — not needed for gateway operator dashboard | Post-MVP |
| Frontend views (React pages for V1–V4) | Phase 5 scope | Phase 5 |
| Admin-action-log (policy change audit) | Nice-to-have, not blocking for core operator queries | Post-Phase-4 |
| Bypass/anomaly detection endpoint | Security enhancement, not core functionality | Separate future work |
| `daily_usage` table removal | Post-Phase-3 cleanup | Post-Phase-3 |

---

## 2. Gateway-Managed vs Direct-Use Exception Users

### 2.1 Classification

| Dimension | Gateway-managed (cgjang et al.) | Direct-use exception (shlee) |
|-----------|--------------------------------|------------------------------|
| Inference path | API Gateway → Lambda → Bedrock | boto3 → bedrock-runtime (direct) |
| DynamoDB records | Written to `monthly_usage`, `request_ledger`, etc. | Zero records in any gateway table |
| Usage data source | `monthly_usage`, `request_ledger` | `/aws/bedrock/modelinvocations` only |
| Cost tracking | `estimated_cost_krw` pre-computed per request | Derived: CW Insights tokens × `model_pricing` rates |
| Quota enforcement | Lambda `check_quota()` real-time | None — no gateway enforcement |
| Approval ladder | `temporary_quota_boost` + `approval_request` | N/A |
| `DenyDirectBedrockInference` | Applied | Removed (per operator approval, 2026-03-19) |

### 2.2 API Representation Contract

All MVP API responses that enumerate users MUST separate gateway-managed users from direct-use exception users. Exception users MUST NOT appear as ordinary zero-usage gateway users.

The canonical response shape uses two top-level arrays:

```
"managed_users": [ ... ]       ← gateway-managed, with full usage/quota/policy data
"exception_users": [ ... ]     ← direct-use exceptions, with status metadata only (no gateway metrics)
```

Each `exception_users` entry contains:
- `principal_id` — the normalized principal ID (e.g. `107650139384#BedrockUser-shlee`)
- `status` — fixed string `"direct-use exception"`
- `gateway_managed` — `false`
- `note` — human-readable explanation (e.g. `"Usage tracked via /aws/bedrock/modelinvocations only"`)

No gateway usage fields (`cost_krw`, `tokens`, `effective_limit`, `approval_band`, etc.) are included for exception users. These fields would be zero/null and misleading.

### 2.3 How to Identify Exception Users

For v1: hardcoded list in backend-admin config (env var or config dict). shlee is the only exception user. If the exception user set grows, migrate to a `principal_policy` attribute (`gateway_managed: false`) or a separate config table.

### 2.4 Post-MVP Exception User Visibility

When direct-use exception visibility is implemented (post-MVP):
- shlee's usage data will come from `/aws/bedrock/modelinvocations` CloudWatch Logs Insights queries
- KRW cost estimation will require joining CW token counts with `model_pricing` rates
- The `exception_users` response shape will be extended with usage fields
- This is a separate approval gate — not part of Phase 4 MVP

---

## 3. Authoritative Data Sources per MVP View

### V1: User Overview

| Field | Source Table | Query Pattern | Notes |
|-------|-------------|---------------|-------|
| `principal_id` | `principal_policy` | Scan (≤10 items) | Enumerate all managed users |
| `monthly_cost_limit_krw` (base) | `principal_policy` | Same scan | Default 500,000 |
| `max_monthly_cost_limit_krw` | `principal_policy` | Same scan | Hard cap 2,000,000 |
| `allowed_models` | `principal_policy` | Same scan | List of model IDs |
| `current_month_cost_krw` | `monthly_usage` | Query PK `<pid>#YYYY-MM`, sum `cost_krw` | Aggregated across models |
| `current_month_input_tokens` | `monthly_usage` | Same query, sum `input_tokens` | — |
| `current_month_output_tokens` | `monthly_usage` | Same query, sum `output_tokens` | — |
| `effective_limit_krw` | `principal_policy` + `temporary_quota_boost` | Derived: `base + sum(active boosts)`, capped | Same formula as `_get_effective_limit()` |
| `approval_band` | `temporary_quota_boost` | Query by `principal_id`, count active (TTL > now) | 0–3 |
| `has_pending_approval` | `approval_pending_lock` | GetItem by `principal_id` | Boolean: item exists and TTL > now |

### V2: User Detail — Monthly Usage

| Field | Source Table | Query Pattern |
|-------|-------------|---------------|
| `model_id` | `monthly_usage` | Query PK `<pid>#YYYY-MM` — each item is one model |
| `cost_krw` | `monthly_usage` | Per-item field |
| `input_tokens` | `monthly_usage` | Per-item field |
| `output_tokens` | `monthly_usage` | Per-item field |
| `price_per_1k_input_krw` | `model_pricing` | GetItem by `model_id` |
| `price_per_1k_output_krw` | `model_pricing` | GetItem by `model_id` |

### V3: User Detail — Request History

| Field | Source Table | Query Pattern | Notes |
|-------|-------------|---------------|-------|
| `request_id` | `request_ledger` | **GSI** `principal_id` (HK) + `timestamp` (RK) | **Requires BL-1 GSI** |
| `timestamp` | `request_ledger` | GSI range key | ISO 8601 UTC |
| `model_id` | `request_ledger` | Projected from GSI (ALL) | — |
| `decision` | `request_ledger` | Projected | `ALLOW` or `DENY` |
| `denial_reason` | `request_ledger` | Projected | Empty string if ALLOW |
| `input_tokens` | `request_ledger` | Projected | — |
| `output_tokens` | `request_ledger` | Projected | — |
| `estimated_cost_krw` | `request_ledger` | Projected | KRW float |
| `duration_ms` | `request_ledger` | Projected | Lambda execution time |

### V4: Approval Queue (existing)

Already served by `gateway_approval.py`. Current endpoints:
- `GET /api/gateway/approvals` — list (with status/principal_id filters)
- `GET /api/gateway/approvals/<id>` — detail
- `POST /api/gateway/approvals/<id>/approve` — approve
- `POST /api/gateway/approvals/<id>/reject` — reject

Data sources: `approval_request` (GSI `principal-status-index`), `principal_policy`, `temporary_quota_boost`.

No new endpoints needed for V4 in MVP. Phase 3 will add reason/increment validation to the Lambda-side `handle_approval_request()`.

---

## 4. MVP API Endpoints

All new endpoints are in `backend-admin` under a new blueprint `gateway_usage_bp` (file: `routes/gateway_usage.py`).

### 4.1 `GET /api/gateway/users`

Serves V1 (User Overview).

**Query parameters**: `month` (optional, format `YYYY-MM`, default: current KST month)

**Response** `200 OK`:
```json
{
  "month": "2026-03",
  "managed_users": [
    {
      "principal_id": "107650139384#BedrockUser-cgjang",
      "monthly_cost_limit_krw": 500000,
      "max_monthly_cost_limit_krw": 2000000,
      "effective_limit_krw": 1000000,
      "approval_band": 1,
      "has_pending_approval": false,
      "current_month_cost_krw": 1234.56,
      "current_month_input_tokens": 50000,
      "current_month_output_tokens": 12000,
      "allowed_models": ["us.anthropic.claude-haiku-4-5-20251001-v1:0"]
    }
  ],
  "exception_users": [
    {
      "principal_id": "107650139384#BedrockUser-shlee",
      "status": "direct-use exception",
      "gateway_managed": false,
      "note": "Usage tracked via /aws/bedrock/modelinvocations only"
    }
  ]
}
```

**Data flow**:
1. Scan `principal_policy` → enumerate all managed users
2. For each user: Query `monthly_usage` PK `<pid>#<month>` → sum cost/tokens
3. For each user: Query `temporary_quota_boost` → count active boosts → derive effective limit + band
4. For each user: GetItem `approval_pending_lock` → pending flag
5. Append hardcoded exception users to `exception_users` array (no DynamoDB query for these)

### 4.2 `GET /api/gateway/users/<principal_id>/usage`

Serves V2 (User Detail — Monthly Usage).

**Path parameter**: `principal_id` (URL-encoded, e.g. `107650139384%23BedrockUser-cgjang`)

**Query parameters**: `month` (optional, format `YYYY-MM`, default: current KST month)

**Response** `200 OK`:
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "month": "2026-03",
  "effective_limit_krw": 1000000,
  "total_cost_krw": 1234.56,
  "total_input_tokens": 50000,
  "total_output_tokens": 12000,
  "models": [
    {
      "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
      "cost_krw": 1100.00,
      "input_tokens": 40000,
      "output_tokens": 10000,
      "price_per_1k_input_krw": 0.143,
      "price_per_1k_output_krw": 0.715
    }
  ]
}
```

**Data flow**:
1. Query `monthly_usage` PK `<pid>#<month>` → all model items
2. For each model: GetItem `model_pricing` → pricing rates
3. Compute totals server-side

**Validation**: Return `404` if `principal_id` is an exception user or not found in `principal_policy`.

### 4.3 `GET /api/gateway/users/<principal_id>/requests`

Serves V3 (User Detail — Request History). **Blocked by BL-1 GSI.**

**Path parameter**: `principal_id` (URL-encoded)

**Query parameters**:
- `start_date` (optional, ISO 8601 date, e.g. `2026-03-15`)
- `end_date` (optional, ISO 8601 date)
- `limit` (optional, default 50, max 200)
- `next_token` (optional, pagination token from previous response)

**Response** `200 OK`:
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "requests": [
    {
      "request_id": "uuid-...",
      "timestamp": "2026-03-20T05:30:00Z",
      "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
      "decision": "ALLOW",
      "denial_reason": "",
      "input_tokens": 1500,
      "output_tokens": 300,
      "estimated_cost_krw": 0.0551,
      "duration_ms": 1200
    }
  ],
  "next_token": "...",
  "count": 1
}
```

**Data flow**:
1. Query `request_ledger` GSI (`principal_id` HK, `timestamp` RK)
2. Apply `start_date`/`end_date` as KeyConditionExpression range on `timestamp`
3. Apply `limit` as DynamoDB `Limit` parameter
4. Return `LastEvaluatedKey` as `next_token` for pagination

**Dependency**: BL-1 GSI on `request_ledger` must be deployed and backfill complete before this endpoint can be implemented.

### 4.4 `GET /api/gateway/users/<principal_id>/policy`

Serves policy detail for a specific gateway-managed user.

**Response** `200 OK`:
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "monthly_cost_limit_krw": 500000,
  "max_monthly_cost_limit_krw": 2000000,
  "allowed_models": ["us.anthropic.claude-haiku-4-5-20251001-v1:0"],
  "effective_limit_krw": 1000000,
  "approval_band": 1,
  "active_boosts": [
    {
      "boost_id": "uuid-...",
      "extra_cost_krw": 500000,
      "approved_by": "changgeun.jang@mogam.er.kr",
      "approved_at": "2026-03-18T10:00:00Z",
      "ttl": 1743465599
    }
  ],
  "has_pending_approval": false
}
```

**Data flow**:
1. GetItem `principal_policy` by `principal_id`
2. Query `temporary_quota_boost` by `principal_id`, filter active
3. GetItem `approval_pending_lock` by `principal_id`
4. Derive `effective_limit_krw` and `approval_band`

**Validation**: Return `404` if `principal_id` is an exception user or not found.

### 4.5 `GET /api/gateway/pricing`

Serves model pricing reference data.

**Response** `200 OK`:
```json
{
  "models": [
    {
      "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
      "price_per_1k_input_krw": 0.143,
      "price_per_1k_output_krw": 0.715
    }
  ]
}
```

**Data flow**: Scan `model_pricing` (≤10 items).

### Authorization Requirement (All Endpoints)

All new endpoints require admin-only authorization enforcement. The design requirement is an authorization boundary that ensures only authenticated admin users can access operator data.

Current state:
- JWT-based authentication exists in `routes/auth.py` (`/api/auth/login`, `/api/auth/verify`)
- JWT encode/decode with `HS256` is implemented
- No reusable authorization middleware or decorator exists

The implementation must establish an explicit admin authorization contract for all `gateway_usage_bp` endpoints. A `@admin_required` decorator is one implementation option, but the binding requirement is the authorization boundary itself — all operator endpoints must reject unauthenticated or non-admin requests with `401`/`403`. This is tracked as R26 in the risk register.

---

## 5. Field-to-Table Reference

| Field | Table | Attribute | Written By |
|-------|-------|-----------|------------|
| `principal_id` | `principal_policy` | PK | Admin (manual/API) |
| `monthly_cost_limit_krw` | `principal_policy` | Attribute | Admin |
| `max_monthly_cost_limit_krw` | `principal_policy` | Attribute | Admin |
| `allowed_models` | `principal_policy` | Attribute (list) | Admin |
| `cost_krw` (monthly per-model) | `monthly_usage` | Attribute | Lambda (atomic ADD) |
| `input_tokens` (monthly per-model) | `monthly_usage` | Attribute | Lambda (atomic ADD) |
| `output_tokens` (monthly per-model) | `monthly_usage` | Attribute | Lambda (atomic ADD) |
| `request_id` | `request_ledger` | PK | Lambda (PutItem, immutable) |
| `timestamp` | `request_ledger` | Attribute | Lambda |
| `model_id` (per-request) | `request_ledger` | Attribute | Lambda |
| `decision` | `request_ledger` | Attribute | Lambda (`ALLOW`/`DENY`) |
| `denial_reason` | `request_ledger` | Attribute | Lambda |
| `estimated_cost_krw` (per-request) | `request_ledger` | Attribute | Lambda |
| `duration_ms` | `request_ledger` | Attribute | Lambda |
| `extra_cost_krw` | `temporary_quota_boost` | Attribute | Admin API (`gateway_approval.py`) |
| `boost_id` | `temporary_quota_boost` | SK | Admin API |
| `ttl` (boost) | `temporary_quota_boost` | Attribute | Admin API |
| `request_id` (approval) | `approval_request` | PK | Lambda |
| `status` (approval) | `approval_request` | Attribute + GSI RK | Lambda (create) / Admin API (update) |
| `model_id` (pricing) | `model_pricing` | PK | Admin (manual/API) |
| `price_per_1k_input_krw` | `model_pricing` | Attribute | Admin |
| `price_per_1k_output_krw` | `model_pricing` | Attribute | Admin |

---

## 6. Dependencies

| Dependency | Status | Blocks | Notes |
|------------|--------|--------|-------|
| BL-1: GSI on `request_ledger` (`principal_id` HK + `timestamp` RK, projection ALL) | ❌ NOT DEPLOYED | Endpoint 4.3 (request history) | Single highest-value Terraform addition. In-place DynamoDB update, no table recreation. GSI backfill is automatic. |
| Admin authorization enforcement for operator endpoints | ⚠️ NOT IMPLEMENTED | All new endpoints (4.1–4.5) | JWT auth logic exists in `auth.py`. Reusable admin authorization boundary must be established. R26. |
| Phase 3 complete (approval ladder rewrite) | ✅ DEPLOYED AND VERIFIED (2026-03-23) | ~~V4 correctness~~ | KST TTL fix, reason validation deployed. See `docs/ai/phase3-dev-validation-report.md`. |
| `gateway_usage.py` blueprint | ❌ NOT CREATED | V1–V3, 4.4, 4.5 | New file in `account-portal/backend-admin/routes/` |
| Blueprint registration in `app.py` | ❌ NOT DONE | All new endpoints | `app.register_blueprint(gateway_usage_bp)` |

---

## 7. Backlog Priority & Phase Ownership

### MVP (Phase 4 Backend)

| Priority | Item | Dependency |
|----------|------|------------|
| P0 | Admin authorization enforcement | JWT auth in `auth.py` |
| P1 | BL-1: GSI on `request_ledger` | None (Terraform additive) |
| P1 | `gateway_usage.py` blueprint + registration | None |
| P1 | Endpoint 4.1 `GET /api/gateway/users` | Authorization + blueprint |
| P1 | Endpoint 4.2 `GET /api/gateway/users/<pid>/usage` | Authorization + blueprint |
| P2 | Endpoint 4.3 `GET /api/gateway/users/<pid>/requests` | BL-1 GSI deployed + backfill |
| P2 | Endpoint 4.4 `GET /api/gateway/users/<pid>/policy` | Authorization + blueprint |
| P3 | Endpoint 4.5 `GET /api/gateway/pricing` | Authorization + blueprint |

### Post-MVP

| Item | Phase | Notes |
|------|-------|-------|
| Direct-use exception user usage endpoint (shlee CW Insights) | Post-MVP / separate future work | Manual CW queries sufficient for v1 |
| Frontend views (React pages for V1–V4) | Phase 5 | Depends on all Phase 4 endpoints |
| Admin-action-log table | Post-Phase-4 | Policy change audit trail |
| Bypass/anomaly detection | Separate future work | Security enhancement |
| `daily_usage` table removal | Post-Phase-3 | Cleanup |

---

## 8. Boundary Statement

This document is a governance/planning artifact only. No runtime code, IaC, deployment configs, or infrastructure were modified. No Phase 2 conclusions were changed. No implementation is authorized by this document. Each endpoint and infrastructure change requires separate explicit approval before implementation.

Key constraints preserved:
- shlee remains a direct-use exception — not included in gateway enforcement or MVP usage views
- Exception users are structurally separated from managed users in all API responses
- Direct-use exception visibility is explicitly post-MVP scope
