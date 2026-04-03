# Phase 4A — Combined Auth + Pricing Remediation Packet

> Date: 2026-03-24
> Status: Planning artifact — no implementation changes.
> Scope: Single bundled remediation for the next backend-admin rebuild.
> Basis: Live code audit of gateway_approval.py, gateway_usage.py, handler.py, BedrockGateway.jsx.

---

## 1. Unauthenticated Approval Endpoints

Four routes in `gateway_approval.py` have no authentication:

| Route | Method | Function | Auth? |
|-------|--------|----------|-------|
| `/api/gateway/approvals` | GET | `list_approvals()` | **NONE** |
| `/api/gateway/approvals/<id>` | GET | `get_approval()` | **NONE** |
| `/api/gateway/approvals/<id>/approve` | POST | `approve_request()` | **NONE** |
| `/api/gateway/approvals/<id>/reject` | POST | `reject_request()` | **NONE** |

Evidence:
- `gateway_approval.py` imports: `os, time, uuid, json, logging, datetime, timezone, timedelta, Decimal, monthrange, boto3, Blueprint, request, jsonify`. No `jwt`, no `wraps`, no auth decorator.
- No `@admin_required` or equivalent appears anywhere in the file.
- By contrast, all 6 routes in `gateway_usage.py` correctly use `@admin_required`.

Impact: Anyone with network access to backend-admin (port 5000) can list, view, approve, or reject quota boost requests without authentication. This is a security gap — approve/reject are write operations that create DynamoDB records and send SES emails.

Mitigating factor: backend-admin is only accessible within the Docker network / host. Not internet-exposed. But still unacceptable for an admin-plane endpoint.

---

## 2. Minimum Safe Auth Fix

### Chosen approach: Import `admin_required` from `gateway_usage`

```python
# Add to gateway_approval.py imports:
from routes.gateway_usage import admin_required
```

Then add `@admin_required` decorator to all 4 routes, immediately below each `@gateway_approval_bp.route(...)` line.

### Why this approach

- `admin_required` in `gateway_usage.py` (line 74) is the only JWT auth decorator in the gateway domain.
- It uses the same `JWT_SECRET_KEY` (`mogam-portal-secret-key-2024`) and same `HS256` algorithm as `auth.py`.
- It checks `payload.get('role') != 'admin'` → 403. This is the correct authorization check for admin-plane endpoints.
- `auth.py` has no reusable decorator — it only has login/verify endpoints. The JWT decode logic is inline, not extracted.

### Alternatives considered and rejected

| Option | Why rejected |
|--------|-------------|
| Duplicate decorator into gateway_approval.py | Code duplication. Same JWT_SECRET_KEY, same logic. Two copies to maintain. |
| Extract to shared `utils/auth.py` | Over-engineering for 2 files. Can be done later if more blueprints need it. |
| Use auth.py's inline pattern | auth.py has no decorator. Would require refactoring auth.py first. |

### Exact changes required

File: `account-portal/backend-admin/routes/gateway_approval.py`

1. Add import after existing imports:
```python
from routes.gateway_usage import admin_required
```

2. Add `@admin_required` to each route (4 locations):
```python
@gateway_approval_bp.route('/api/gateway/approvals', methods=['GET'])
@admin_required          # ← ADD
def list_approvals():

@gateway_approval_bp.route('/api/gateway/approvals/<approval_id>', methods=['GET'])
@admin_required          # ← ADD
def get_approval(approval_id):

@gateway_approval_bp.route('/api/gateway/approvals/<approval_id>/approve', methods=['POST'])
@admin_required          # ← ADD
def approve_request(approval_id):

@gateway_approval_bp.route('/api/gateway/approvals/<approval_id>/reject', methods=['POST'])
@admin_required          # ← ADD
def reject_request(approval_id):
```

### Rebuild required: Yes

This is a Python code change. The running container has the old code. Must be included in the next Docker rebuild.

### Rollback

Revert the import line and 4 decorator additions. Rebuild. No data impact.

---

## 3. Current Pricing / Model-Coverage Gaps

### 3.1 Two separate pricing failure modes

**Mode A — Lambda gateway (managed users): fail-closed denial.**
`handler.py` `lookup_model_pricing()` does strict `model_id` match against `model_pricing` table cache. If no match → returns None → handler denies the request with `"no pricing defined for model {model_id}"`. The user gets a 403.

This means: managed users (cgjang, jwlee, sbkim) cannot invoke any model that lacks a pricing entry through the gateway. Currently 11 of 16 actually-used model IDs have no pricing. The gateway blocks them.

**Mode B — Exception-usage monitoring (shlee): silent cost omission.**
`gateway_usage.py` `_get_exception_usage_cached()` looks up pricing for each model returned by CloudWatch Logs Insights. If no match → sets `cost_source: 'unavailable'`, `estimated_cost_krw: None`, `has_unpriced: True`. The frontend shows "미등록" per model and "부분 추정" or "산정 불가" for the total.

This means: shlee's usage is visible (invocation counts, token counts) but cost estimation is incomplete. The operator sees partial or zero KRW totals for the heaviest user (27,225 invocations).

### 3.2 Specific models causing failures

Models actually invoked this month (30,167 total invocations) with pricing status:

| model_id | Invocations | Has pricing? | Failure mode |
|----------|-------------|-------------|--------------|
| `us.anthropic.claude-sonnet-4-6` | 22,748 | NO | A+B |
| `us.anthropic.claude-opus-4-6-v1` | 4,482 | NO | A+B |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 1,569 | NO | B only (shlee) |
| `us.amazon.nova-2-lite-v1:0` | 1,240 | NO | A+B |
| `global.anthropic.claude-opus-4-6-v1` | 103 | NO | B only (shlee) |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | 7 | NO | A+B |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 5 | YES | — |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | 2 | YES | — |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 1 | NO | A+B |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 1 | NO | A+B |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | 1 | YES | — |
| `anthropic.claude-3-haiku-20240307-v1:0` | 1 | YES | — |
| `us.anthropic.claude-opus-4-20250514-v1:0` | 1 | NO | A+B |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | 1 | NO | A+B |
| `us.anthropic.claude-3-5-sonnet-20240620-v1:0` | 1 | NO | A+B |
| `anthropic.claude-sonnet-4-20250514-v1:0` | 1 | YES | — |

Coverage: 5 of 16 model IDs have pricing. By invocation volume: 10 of 30,167 (0.03%) hit a priced model.

### 3.3 Root cause: inference profile IDs vs foundation model IDs

The `model_pricing` table was seeded with foundation model IDs (e.g., `anthropic.claude-sonnet-4-20250514-v1:0`). But actual usage is via:
- Cross-region inference profiles: `us.*`, `global.*` prefixes
- Newer model versions: `claude-sonnet-4-6`, `claude-opus-4-6-v1` (short-form IDs released after initial seed)

Both the Lambda handler and the admin-plane exception-usage code do strict `model_id` match. No normalization exists anywhere in the codebase.

### 3.4 Consequences of leaving pricing gaps unresolved

| Consequence | Severity |
|-------------|----------|
| Managed users cannot invoke `us.anthropic.claude-sonnet-4-6` through gateway | Critical — blocks primary model |
| Managed users cannot invoke `us.anthropic.claude-opus-4-6-v1` through gateway | Critical — blocks Opus |
| shlee exception-usage shows "미등록" for 99.97% of invocations | High — operator monitoring is useless |
| Monthly KRW totals for exception users are null or partial | High — cost visibility is broken |
| Frontend shows "산정 불가" instead of actual cost | High — operator cannot make budget decisions |

---

## 4. Minimum Safe Pricing Fix

### 4.1 Approach: Option A — add every variant as a separate pricing entry

This is data-only. No code change to handler.py or gateway_usage.py. No Lambda redeploy.

11 new `model_pricing` DynamoDB items. Exact CLI commands already prepared in `phase4-backend-remediation-analysis.md` §8.1.

### 4.2 Why not normalization (Option B)

A normalization function in handler.py (e.g., strip `us.`/`global.` prefix, map short-form to long-form) would reduce pricing table size but:
- Requires Lambda code change → Lambda redeploy → separate approval gate
- Normalization rules are fragile (new prefixes, new short-form names)
- Does not help the admin-plane exception-usage code (separate codebase)
- Would need to be implemented in TWO places: handler.py AND gateway_usage.py

Option A is boring, maintainable, immediately effective, and requires zero code changes. Option B is a v2 optimization.

### 4.3 Pricing tiers (3 tiers cover all 16 models)

| Tier | USD Input/1K | USD Output/1K | KRW Input/1K | KRW Output/1K | Models |
|------|-------------|---------------|-------------|---------------|--------|
| Haiku | $0.001 | $0.005 | 1.45 | 7.25 | All haiku variants (4 model IDs) |
| Sonnet | $0.003 | $0.015 | 4.35 | 21.75 | All sonnet variants (6 model IDs) |
| Opus | $0.015 | $0.075 | 21.75 | 108.75 | All opus variants (5 model IDs) |
| Nova Lite | $0.00006 | $0.00024 | 0.087 | 0.348 | `us.amazon.nova-2-lite-v1:0` (1 model ID) |

Exception: `anthropic.claude-3-haiku-20240307-v1:0` (already seeded at 0.36/1.81 KRW — older Haiku 3 pricing, different from Haiku 4.5). This entry is correct and should not be changed.

### 4.4 What becomes complete after this fix

After seeding all 11 items:
- All 16 actually-invoked model IDs have pricing entries.
- Lambda handler will allow managed users to invoke all models (no more fail-closed denials for missing pricing).
- Exception-usage endpoint will return `estimated_cost_krw` (not null) for all of shlee's models.
- Frontend will show actual KRW totals instead of "미등록" / "산정 불가".
- `has_unpriced_models` will be `false` for shlee's usage data.
- Monthly totals become trustworthy (complete, not partial).

### 4.5 What remains unresolved after this fix

- If a user invokes a NEW model ID not in the 16 known ones, it will still fail-closed (Lambda) or show "미등록" (admin-plane). This is correct behavior — new models should be explicitly priced before use.
- Daily usage (`daily_usage` table) is unreadable by backend-admin until IAM fix (Task 4A.1). This pricing fix does not address that.
- The Lambda pricing cache reloads on cold start. After seeding, the next Lambda cold start will pick up new pricing. No redeploy needed. Existing warm instances will reload on cache miss (the `lookup_model_pricing` function does one retry reload on miss).

### 4.6 Operator verification still required

The USD prices in §4.3 are based on publicly known Bedrock pricing as of early 2026. The operator must verify these against the current AWS Bedrock pricing page before executing the seed commands. Specifically:

- `us.anthropic.claude-sonnet-4-6`: Is it still $0.003/$0.015 per 1K tokens?
- `us.anthropic.claude-opus-4-6-v1`: Is it still $0.015/$0.075 per 1K tokens?
- `us.amazon.nova-2-lite-v1:0`: Is it still $0.00006/$0.00024 per 1K tokens?
- Exchange rate: Is 1,450 KRW/USD still acceptable?

If any USD rate has changed, the corresponding KRW values must be recalculated before seeding.

---

## 5. Work That Must Be Included In The Next Backend-Admin Rebuild

These are code changes. They take effect only after Docker rebuild. They should be bundled into a single rebuild to avoid multiple rebuild cycles.

| # | Change | File | Lines affected | Risk |
|---|--------|------|---------------|------|
| R1 | Add `from routes.gateway_usage import admin_required` | `gateway_approval.py` | 1 line (imports) | Low — import from same package |
| R2 | Add `@admin_required` to `list_approvals()` | `gateway_approval.py` | 1 line | Low — additive decorator |
| R3 | Add `@admin_required` to `get_approval()` | `gateway_approval.py` | 1 line | Low — additive decorator |
| R4 | Add `@admin_required` to `approve_request()` | `gateway_approval.py` | 1 line | Low — additive decorator |
| R5 | Add `@admin_required` to `reject_request()` | `gateway_approval.py` | 1 line | Low — additive decorator |

Total: 5 lines changed in 1 file. No other files modified.

No pricing code changes needed — pricing fix is data-only (DynamoDB PutItem).

### Rebuild command

```bash
cd account-portal
docker compose -f docker-compose-fixed.yml up -d --build
```

This rebuilds backend-admin only (other services are unaffected unless their Dockerfiles changed).

---

## 6. Work That Can Be Prepared Now But Applied Later

### 6.1 IAM policy update (Task 4A.1)

The `aws iam create-policy-version` command is fully prepared in `phase4-backend-remediation-analysis.md` §7. Can be executed at any time. Independent of the auth/pricing fix. Independent of Docker rebuild.

Adds read access for: request-ledger, daily-usage, approval-request, session-metadata.

### 6.2 Principal policy seed (Task 4A.3)

The `aws dynamodb put-item` commands for jwlee, sbkim, and the `update-item` for cgjang are fully prepared. Can be executed at any time. Independent of auth fix. Independent of pricing seed.

### 6.3 Ledger read endpoint (Task 4B.1)

Code can be written now. Cannot be runtime-tested until IAM fix (6.1) is applied. Not required for the immediate rebuild — can be added in a subsequent rebuild.

---

## 7. Work Still Blocked By Operator Decisions

| # | Decision | What it blocks | Can the rest proceed without it? |
|---|----------|---------------|----------------------------------|
| O1 | USD pricing verification (H2) | Model pricing seed (11 items) | Yes — auth fix and principal policy seed can proceed. But exception-usage cost estimation remains broken until pricing is seeded. |
| O2 | Exchange rate confirmation (H3) | Model pricing seed (11 items) | Same as O1. |
| O3 | Docker rebuild approval (H1) | All runtime validation | Auth fix code can be written and merged. Data seeds can be applied. But nothing is testable at HTTP level until rebuild. |
| O4 | hermee classification | hermee principal_policy seed | Yes — core pipeline works with 3 confirmed users. |
| O5 | shlee2 classification | shlee2 seed or EXCEPTION_USERS update | Yes — core pipeline works without shlee2. |

O1+O2 block pricing seed only. O3 blocks runtime validation only. O4+O5 block nothing in the core pipeline.

---

## 8. Correct Immediate Execution Order

```
Phase A: Preparation (no operator confirmation needed)
  A1. Write auth fix code (R1-R5)                    — can do now
  A2. getDiagnostics on gateway_approval.py           — validate syntax
  A3. Prepare smoke test script                       — can do now

Phase B: Operator confirmations (parallel, no ordering)
  B1. Operator verifies USD pricing for 11 models     — blocks Phase C pricing seed
  B2. Operator confirms exchange rate (1,450 KRW/USD)  — blocks Phase C pricing seed
  B3. Operator approves auth fix + Docker rebuild      — blocks Phase D

Phase C: Data seeds (can run as soon as B1+B2 confirmed, independent of B3)
  C1. IAM policy update (Task 4A.1)                   — no dependency on B1/B2
  C2. Model pricing seed (11 items)                    — requires B1+B2
  C3. Principal policy seed (jwlee, sbkim, cgjang)     — no dependency on B1/B2

  C1 and C3 can run immediately. C2 waits for B1+B2.
  All three are independent of each other.

Phase D: Rebuild + Validate (requires B3 + Phase A complete)
  D1. Docker rebuild backend-admin                     — picks up auth fix
  D2. HTTP smoke test: all 10 endpoints                — validates auth + data
  D3. Validate exception-usage for shlee               — validates pricing completeness
  D4. Validate managed user data (cgjang, jwlee, sbkim) — validates principal policy seed

Phase E: Deferred (no urgency)
  E1. Operator decides hermee classification
  E2. Operator decides shlee2 classification
  E3. Ledger read endpoint (Phase 4B.1, separate rebuild)
```

### Critical path

The shortest path to a fully validated system:
```
A1 (auth fix code) ──┐
B1+B2 (pricing OK) ──┤
B3 (rebuild OK) ─────┤
C1 (IAM) ────────────┤
C2 (pricing seed) ───┤
C3 (user seed) ──────┤
                      ▼
                D1 (rebuild) → D2-D4 (validate)
```

A1 can start immediately. C1 and C3 can start immediately. B1+B2+B3 are operator actions that can happen in parallel. C2 waits for B1+B2. D1 waits for A1+B3.

---

## 9. What Will Become Trustworthy After This Combined Fix

### Trustworthy (after auth fix + pricing seed + user seed + rebuild):

| Capability | Before fix | After fix |
|------------|-----------|-----------|
| Approval endpoint authentication | None — anyone on network can approve/reject | Admin JWT required on all 4 routes |
| Exception-usage cost for shlee | "미등록" on 99.97% of models, "산정 불가" total | Full KRW cost estimate for all 16 model IDs |
| Managed user visibility | Only cgjang (1 user) | cgjang + jwlee + sbkim (3 users) |
| Model pricing completeness | 5 of 16 model IDs priced | 16 of 16 model IDs priced |
| Lambda gateway model access | Blocks 11 of 16 models (fail-closed) | All 16 models accessible through gateway |
| Monthly KRW totals (exception) | Null or partial | Complete |
| Monthly KRW totals (managed) | Accurate but only for cgjang | Accurate for 3 confirmed users |
| Approval approve/reject safety | Unauthenticated write operations | JWT-protected admin-only operations |

### Still blocked after this fix (requires separate work):

| Capability | Why blocked | What unblocks it |
|------------|------------|-----------------|
| Daily usage visibility | `daily-usage` table unreadable by backend-admin (IAM gap) | Task 4A.1 (IAM policy update) |
| Request ledger / audit trail | `request-ledger` table unreadable by backend-admin (IAM gap) | Task 4A.1 (IAM policy update) |
| Unfiltered approval list | `approval-request` Scan not in IAM policy | Task 4A.1 (IAM policy update) |
| hermee visibility | Not in principal_policy or EXCEPTION_USERS | Operator decision (O4) |
| shlee2 visibility | Not in principal_policy or EXCEPTION_USERS | Operator decision (O5) |
| Ledger read endpoint | Code not written, IAM not fixed | Task 4A.1 + Task 4B.1 |
| Frontend improvements | Not in scope for this packet | Phase 5 (separate) |

---

## 10. Final Immediate Priority

The single next action is: **operator approval for the combined auth + pricing remediation packet**.

What the operator is approving:
1. Code change: 5 lines in `gateway_approval.py` (add `@admin_required` to 4 routes + 1 import)
2. Data change: 11 DynamoDB PutItem to `model_pricing` (after USD price verification)
3. Data change: 2 DynamoDB PutItem + 1 UpdateItem to `principal_policy` (confirmed users only)
4. Docker rebuild: backend-admin container only

What the operator must verify before the pricing seed:
- USD pricing for `claude-sonnet-4-6`, `claude-opus-4-6-v1`, `nova-2-lite` against current AWS pricing page
- Exchange rate: 1,450 KRW/USD still acceptable?

What is NOT included in this packet:
- No IAM policy changes (Task 4A.1 — separate, can run in parallel)
- No Lambda changes (no handler.py modification)
- No Terraform changes
- No frontend changes
- No hermee/shlee2 decisions
- No nginx/docker-compose topology changes

Blast radius: backend-admin container only. Other services unaffected. Rollback: revert 5 lines, rebuild. Data seeds are additive (new items only, no overwrites of existing items except cgjang allowed_models update which is also safe to revert).
