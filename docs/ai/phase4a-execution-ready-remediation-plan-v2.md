# Phase 4A — Corrected Execution-Ready Remediation Plan (v2)

> Date: 2026-03-24
> Status: Planning artifact — no implementation changes.
> Supersedes: `phase4a-execution-ready-remediation-plan.md`, `phase4a-combined-auth-pricing-remediation.md`
> Basis: Live DynamoDB scans, CloudWatch Logs, IAM inspection, handler.py + gateway_approval.py + gateway_usage.py code audit.
> Corrections applied: sbkim identity confirmed, shlee locked as exception, hermee/shlee2 unresolved, gateway_approval.py auth gap confirmed as must-fix, per-request overshoot flagged as operator decision.

---

## 1. Must-Fix Code Changes

### 1.1 gateway_approval.py — Unauthenticated Admin Endpoints (Security Gap)

All 4 routes in `gateway_approval.py` lack `@admin_required`. This is a real security gap.

| Route | Method | Function | Current Auth |
|-------|--------|----------|-------------|
| `/api/gateway/approvals` | GET | `list_approvals()` | **NONE** |
| `/api/gateway/approvals/<id>` | GET | `get_approval()` | **NONE** |
| `/api/gateway/approvals/<id>/approve` | POST | `approve_request()` | **NONE** |
| `/api/gateway/approvals/<id>/reject` | POST | `reject_request()` | **NONE** |

Evidence: `gateway_approval.py` imports `os, time, uuid, json, logging, datetime, timezone, timedelta, Decimal, monthrange, boto3, Blueprint, request, jsonify`. No `jwt`, no `wraps`, no auth decorator anywhere in the file. By contrast, all 6 routes in `gateway_usage.py` correctly use `@admin_required`.

Impact: Anyone with network access to backend-admin (port 5000) can approve or reject quota boost requests without authentication. `approve_request()` creates DynamoDB records (TemporaryQuotaBoost) and sends SES emails. `reject_request()` modifies approval status and deletes locks.

Mitigating factor: backend-admin is not internet-exposed (Docker network / host only). Still unacceptable for admin-plane write operations.

Fix (5 lines, 1 file):
```python
# Add to gateway_approval.py imports:
from routes.gateway_usage import admin_required

# Add @admin_required decorator to all 4 routes (below each @gateway_approval_bp.route)
```

This is the only code change in this packet. It must be included in the next Docker rebuild.

### 1.2 No Other Code Changes Required

- `gateway_usage.py`: All 6 routes already have `@admin_required`. No changes needed.
- `handler.py`: No changes. Lambda enforcement plane is out of Phase 4 scope.
- `app.py`: Both blueprints already registered. No changes needed.

---

## 2. Must-Fix IAM / Read-Access Changes

### 2.1 Current State of `BedrockGatewayScopeAReadTemp`

Tables with read access (GetItem/Query/Scan):
- `model-pricing` ✓
- `principal-policy` ✓
- `monthly-usage` ✓
- `temporary-quota-boost` ✓
- `approval-pending-lock` ✓

Tables MISSING from policy:
- `request-ledger` ✗ — AccessDeniedException on Scan
- `daily-usage` ✗ — AccessDeniedException on Scan
- `approval-request` ✗ — Scan missing (only CRUD via `BedrockGatewayApprovalAdminTemp`)
- `session-metadata` ✗
- `idempotency-record` ✗

### 2.2 Current State of `BedrockGatewayApprovalAdminTemp`

Grants: GetItem, PutItem, UpdateItem, DeleteItem, Query on `approval-request`.
Missing: Scan. This means `list_approvals()` in `gateway_approval.py` fails when called without filters (it falls back to `table.scan()`).

### 2.3 Required Fix

Update `BedrockGatewayScopeAReadTemp` to add read access for all missing tables. This is a managed IAM policy update (not Terraform). Immediately effective. No code change, no Lambda redeploy, no Docker rebuild required.

```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws iam create-policy-version \
  --policy-arn arn:aws:iam::107650139384:policy/BedrockGatewayScopeAReadTemp \
  --set-as-default \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "ScopeAReadOnlyGatewayTables",
        "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        "Resource": [
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-model-pricing",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-model-pricing/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-principal-policy",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-principal-policy/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-monthly-usage",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-monthly-usage/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-temporary-quota-boost",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-temporary-quota-boost/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-approval-pending-lock",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-approval-pending-lock/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-request-ledger",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-request-ledger/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-daily-usage",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-daily-usage/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-approval-request",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-approval-request/index/*",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-session-metadata",
          "arn:aws:dynamodb:us-west-2:107650139384:table/bedrock-gw-dev-us-west-2-session-metadata/index/*"
        ]
      }
    ]
  }'
```

This also resolves the `list_approvals()` Scan issue — `approval-request` is now covered by ScopeAReadTemp, so Scan works regardless of ApprovalAdminTemp's limitations.

### 2.4 IAM Policy Version Limit Risk

AWS allows max 5 managed policy versions. If `BedrockGatewayScopeAReadTemp` already has 5 versions, the `create-policy-version` call will fail. Operator must check and delete old versions first if needed:

```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws iam list-policy-versions --policy-arn arn:aws:iam::107650139384:policy/BedrockGatewayScopeAReadTemp
```

---

## 3. Gateway-Managed Pricing Gaps

These affect users who invoke Bedrock through the gateway (cgjang, jwlee, sbkim). The Lambda handler denies requests for models without pricing entries (fail-closed).

### 3.1 Failure Mode

`handler.py` `lookup_model_pricing()` does strict `model_id` match. No match → returns None → handler returns 403 `"no pricing defined for model {model_id}"`. The user cannot invoke the model.

### 3.2 Models Blocked by Missing Pricing

These models are actually invoked but have no `model_pricing` entry. Any managed user attempting to use them through the gateway gets denied:

| model_id | Invocations (2026-03) | Pricing tier |
|----------|----------------------|-------------|
| `us.anthropic.claude-sonnet-4-6` | 22,748 | Sonnet |
| `us.anthropic.claude-opus-4-6-v1` | 4,482 | Opus |
| `us.amazon.nova-2-lite-v1:0` | 1,240 | Nova Lite |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | 7 | Haiku |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 1 | Opus |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 1 | Haiku |
| `us.anthropic.claude-opus-4-20250514-v1:0` | 1 | Opus |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | 1 | Sonnet |
| `us.anthropic.claude-3-5-sonnet-20240620-v1:0` | 1 | Sonnet |

### 3.3 Root Cause

The `model_pricing` table was seeded with foundation model IDs. Actual usage is via cross-region inference profile IDs (`us.*`, `global.*` prefixes) and newer short-form model versions (`claude-sonnet-4-6`, `claude-opus-4-6-v1`).

### 3.4 Fix Approach

Option A (chosen): Add every variant as a separate pricing entry. Data-only, no code change, no Lambda redeploy. 11 DynamoDB PutItem commands.

Option B (rejected for now): Normalization function in handler.py. Requires Lambda code change + redeploy + separate approval gate. Fragile normalization rules. Would need implementation in TWO places (handler.py AND gateway_usage.py). Deferred to v2.

### 3.5 Pricing Tiers (Operator Must Verify USD Rates)

| Tier | USD Input/1K | USD Output/1K | KRW Input/1K | KRW Output/1K | Exchange Rate |
|------|-------------|---------------|-------------|---------------|--------------|
| Haiku 4.5 | $0.001 | $0.005 | 1.45 | 7.25 | 1,450 |
| Sonnet 4.x | $0.003 | $0.015 | 4.35 | 21.75 | 1,450 |
| Opus 4.x | $0.015 | $0.075 | 21.75 | 108.75 | 1,450 |
| Nova 2 Lite | $0.00006 | $0.00024 | 0.087 | 0.348 | 1,450 |

**Operator verification required before execution**: USD rates must be checked against current AWS Bedrock pricing page. Exchange rate (1,450 KRW/USD) must be confirmed as still acceptable.

### 3.6 Seed Commands (9 gateway-relevant models)

Commands are in `phase4-backend-remediation-analysis.md` §8.1. All use the pattern:
```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{...}'
```

After seeding: Lambda pricing cache reloads on next cold start. Existing warm instances reload on cache miss (one retry in `lookup_model_pricing()`). No Lambda redeploy needed.

---

## 4. Direct-Use Exception Pricing Gaps

These affect exception user monitoring only (shlee). The Lambda gateway is not involved — shlee bypasses it entirely.

### 4.1 Failure Mode

`gateway_usage.py` `_get_exception_usage_cached()` looks up pricing for each model returned by CloudWatch Logs Insights. No match → `cost_source: 'unavailable'`, `estimated_cost_krw: None`, `has_unpriced_models: True`. Frontend shows "미등록" per model and "산정 불가" for total.

### 4.2 Models Causing Silent Cost Omission for shlee

| model_id | Invocations (shlee, 2026-03) | Has pricing? |
|----------|------------------------------|-------------|
| `us.anthropic.claude-sonnet-4-6` | ~22,000+ | NO |
| `us.anthropic.claude-opus-4-6-v1` | ~4,400+ | NO |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | ~1,500+ | NO |
| `global.anthropic.claude-opus-4-6-v1` | ~100+ | NO |

These are the same models as §3.2 plus the `global.*` variants. The pricing seed in §3.6 covers the `us.*` models. Two additional `global.*` entries are needed:

```bash
# global.anthropic.claude-haiku-4-5-20251001-v1:0
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"global.anthropic.claude-haiku-4-5-20251001-v1:0"},
  "input_price_per_1k":{"N":"1.45"},"output_price_per_1k":{"N":"7.25"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.001"},"source_usd_output_per_1k":{"N":"0.005"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Haiku 4.5 global cross-region inference profile."}
}'

# global.anthropic.claude-opus-4-6-v1
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"global.anthropic.claude-opus-4-6-v1"},
  "input_price_per_1k":{"N":"21.75"},"output_price_per_1k":{"N":"108.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.015"},"source_usd_output_per_1k":{"N":"0.075"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Opus 4.6 global cross-region inference profile."}
}'
```

### 4.3 After Fix

After all 11 pricing entries are seeded, `_get_exception_usage_cached()` will return `estimated_cost_krw` (not null) for all of shlee's models. `has_unpriced_models` becomes `false`. Frontend shows actual KRW totals instead of "산정 불가".

### 4.4 Separation from Gateway-Managed Pricing

The pricing seed is shared — the same `model_pricing` table serves both the Lambda handler (gateway-managed) and the admin-plane exception-usage code. But the failure modes are different:
- Gateway-managed: missing pricing → request denied (fail-closed, blocks user)
- Exception monitoring: missing pricing → cost shown as null (silent omission, does not block user)

Both are fixed by the same data seed. No code change needed in either path.

---

## 5. Work That Can Be Applied Without Docker Rebuild

These are operator actions that take effect immediately. No code change, no container restart.

| # | Action | Type | Dependency | Time |
|---|--------|------|-----------|------|
| 5.1 | IAM policy update (§2.3) | `aws iam create-policy-version` | None | ~2 min |
| 5.2 | Model pricing seed (11 items, §3.6 + §4.2) | `aws dynamodb put-item` × 11 | Operator verifies USD rates (§3.5) | ~5 min |
| 5.3 | Principal policy seed — jwlee | `aws dynamodb put-item` | None | ~1 min |
| 5.4 | Principal policy seed — sbkim | `aws dynamodb put-item` | None | ~1 min |
| 5.5 | Principal policy update — cgjang allowed_models | `aws dynamodb update-item` | None | ~1 min |

5.1 is independent of everything. Can run first.
5.2 is blocked only by operator USD price verification.
5.3–5.5 are independent of 5.1 and 5.2. Can run in parallel.

All commands are in `phase4-backend-remediation-analysis.md` §7 (IAM) and §8.1 (DynamoDB seeds).

### 5.3–5.5 Principal Policy Seed Details

Confirmed targets only. No operator identity decision needed.

**jwlee** (2,917 invocations this month):
```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-principal-policy --item '{
  "principal_id":{"S":"107650139384#BedrockUser-jwlee"},
  "monthly_cost_limit_krw":{"N":"500000"},
  "max_monthly_cost_limit_krw":{"N":"2000000"},
  "daily_input_token_limit":{"N":"100000"},
  "daily_output_token_limit":{"N":"50000"},
  "allowed_models":{"L":[
    {"S":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},
    {"S":"us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"S":"us.anthropic.claude-sonnet-4-6"},
    {"S":"us.anthropic.claude-opus-4-6-v1"},
    {"S":"global.anthropic.claude-haiku-4-5-20251001-v1:0"},
    {"S":"global.anthropic.claude-opus-4-6-v1"},
    {"S":"us.amazon.nova-2-lite-v1:0"},
    {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
    {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
    {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
  ]}
}'
```

**sbkim** (1 invocation — no Opus in allowed_models per current proposal):
```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-principal-policy --item '{
  "principal_id":{"S":"107650139384#BedrockUser-sbkim"},
  "monthly_cost_limit_krw":{"N":"500000"},
  "max_monthly_cost_limit_krw":{"N":"2000000"},
  "daily_input_token_limit":{"N":"100000"},
  "daily_output_token_limit":{"N":"50000"},
  "allowed_models":{"L":[
    {"S":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},
    {"S":"us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"S":"us.anthropic.claude-sonnet-4-6"},
    {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
    {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
    {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
  ]}
}'
```

**cgjang** (update allowed_models to include new inference profile IDs):
```bash
env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb update-item --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id":{"S":"107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET allowed_models = :models' \
  --expression-attribute-values '{
    ":models":{"L":[
      {"S":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},
      {"S":"us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
      {"S":"us.anthropic.claude-sonnet-4-6"},
      {"S":"us.anthropic.claude-opus-4-6-v1"},
      {"S":"global.anthropic.claude-haiku-4-5-20251001-v1:0"},
      {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
      {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
      {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
    ]}
  }'
```

---

## 6. Work That Must Be Included In The Next Backend-Admin Rebuild

Only the auth fix from §1.1. Total: 5 lines changed in 1 file.

| # | Change | File | Lines |
|---|--------|------|-------|
| R1 | `from routes.gateway_usage import admin_required` | `gateway_approval.py` | 1 (imports) |
| R2 | `@admin_required` on `list_approvals()` | `gateway_approval.py` | 1 |
| R3 | `@admin_required` on `get_approval()` | `gateway_approval.py` | 1 |
| R4 | `@admin_required` on `approve_request()` | `gateway_approval.py` | 1 |
| R5 | `@admin_required` on `reject_request()` | `gateway_approval.py` | 1 |

No other code changes in this packet. No pricing code changes (data-only fix). No handler.py changes.

Rebuild command:
```bash
cd account-portal
docker compose -f docker-compose-fixed.yml up -d --build
```

This also picks up `gateway_usage.py` and `gateway_approval.py` which were added after the last rebuild (Phase 3, 2026-03-23). The running container currently does not serve any Phase 4 Scope A endpoints.

Rollback: revert 5 lines in `gateway_approval.py`, rebuild. Data seeds are additive (new items only, no destructive overwrites).

---

## 7. Work Still Requiring Operator Decision

| # | Decision | Options | Impact of Deferring | Urgency |
|---|----------|---------|---------------------|---------|
| D1 | hermee classification | (a) gateway-managed → seed principal_policy (b) deferred → no action | hermee invisible in admin portal. 1 invocation total. Zero operational risk. | None |
| D2 | shlee2 classification | (a) gateway-managed → seed principal_policy (b) exception → add to EXCEPTION_USERS dict (code change + rebuild) (c) deferred → no action | shlee2 invisible everywhere. 3 invocations total. Zero operational risk. | None |
| D3 | Opus 4.6 in sbkim's allowed_models | (a) include → add to sbkim seed command (b) exclude (current proposal) | sbkim cannot use Opus through gateway. Can be updated later via single DynamoDB UpdateItem. | None |
| D4 | Per-request overshoot risk acceptance | (a) accept current behavior (post-hoc check only) (b) implement pre-invocation headroom guard (code change to handler.py — out of Phase 4 scope) | See §7.1 below | Operator must acknowledge |
| D5 | USD pricing verification | Operator verifies rates against AWS pricing page | Blocks model_pricing seed (§3.6, §4.2) | Blocks pricing seed |
| D6 | Exchange rate confirmation | 1,450 KRW/USD still acceptable? | Blocks model_pricing seed | Blocks pricing seed |
| D7 | Docker rebuild approval | Approve backend-admin rebuild | Blocks all runtime validation | Blocks validation |

### 7.1 Per-Request Overshoot Risk (D4) — Operator Decision Required

Current handler.py behavior: post-hoc cumulative check only. A single request can overshoot the remaining monthly budget. The system blocks the NEXT request, not the current one.

Worst-case single-request cost (Opus 4.6, maximum context):
- Input: ~200K tokens × 21.75 KRW/1K = ~4,350 KRW
- Output: ~4,096 tokens (default max) × 108.75 KRW/1K = ~445 KRW
- Total: ~4,795 KRW (0.96% of 500K base limit)

This is NOT declared acceptable by this document. It is flagged as an operator decision because:
- The overshoot amount depends on model choice and context size
- For Opus with very large contexts, the overshoot could be higher
- The operator must decide whether this risk profile is acceptable for their user base
- If not acceptable, a pre-invocation headroom guard requires handler.py changes (Lambda code, out of Phase 4 scope)

Options:
- (a) Accept: no code change. Current behavior continues. Overshoot bounded by single-request cost.
- (b) Implement headroom guard: requires handler.py modification + Lambda redeploy. Separate approval gate. Phase 5 scope.

D1–D3 do not block the core pipeline. D4 is an acknowledgment, not a blocker. D5–D7 block specific execution steps.

---

## 8. Correct Immediate Execution Order

```
Phase A: Code Preparation (no operator confirmation needed, pre-approval artifact)
  A1. Prepare auth fix code for gateway_approval.py (§1.1)
  A2. Validate syntax via getDiagnostics

Phase B: Operator Confirmations (parallel, no ordering between them)
  B1. Verify USD pricing for 11 models against AWS Bedrock pricing page (§3.5)
  B2. Confirm exchange rate: 1,450 KRW/USD still acceptable? (§3.5)
  B3. Approve auth fix code change (§1.1)
  B4. Approve Docker rebuild (§6)
  B5. Acknowledge per-request overshoot risk (§7.1) — not a blocker, but must be recorded

Phase C: Data Seeds (can run as confirmations arrive, independent of each other)
  C1. IAM policy update (§2.3)                        — no dependency, run immediately
  C2. Principal policy seed: jwlee + sbkim + cgjang    — no dependency, run immediately
  C3. Model pricing seed: 11 items                     — requires B1 + B2

  C1 and C2 can run NOW. C3 waits for B1 + B2.
  All three are independent of each other and of B3/B4.

Phase D: Code + Rebuild (requires B3 + B4)
  D1. Apply auth fix to gateway_approval.py
  D2. Docker rebuild backend-admin
  D3. HTTP smoke test: all 10 endpoints
  D4. Validate exception-usage for shlee (pricing completeness)
  D5. Validate managed user data (cgjang, jwlee, sbkim visible in /api/gateway/users)

Phase E: Deferred (no urgency, no blocking)
  E1. Operator decides hermee classification
  E2. Operator decides shlee2 classification
  E3. Ledger read endpoint (Phase 4B, separate rebuild, requires C1 first)
```

### Critical Path

```
C1 (IAM) ────────────────────────────────────┐
C2 (user seed) ──────────────────────────────┤
B1+B2 (pricing OK) → C3 (pricing seed) ─────┤
B3+B4 (approvals) → D1 (auth fix) ──────────┤
                                              ▼
                                    D2 (rebuild) → D3-D5 (validate)
```

C1 and C2 can start immediately with no approvals. B1+B2 are verification-only (no system changes). B3+B4 are approval gates. D1 is the only code change.

---

## 9. What Becomes Trustworthy After This Packet

### Trustworthy (after full execution of Phases A–D):

| Capability | Before | After |
|------------|--------|-------|
| Approval endpoint authentication | None — unauthenticated write ops | Admin JWT required on all 4 routes |
| Exception-usage cost for shlee | "미등록" on 99.97% of models | Full KRW estimate for all 16 model IDs |
| Managed user visibility | cgjang only (1 user) | cgjang + jwlee + sbkim (3 users) |
| Model pricing completeness | 5 of 16 model IDs | 16 of 16 model IDs |
| Lambda gateway model access | Blocks 11 of 16 models (fail-closed) | All 16 models accessible |
| Monthly KRW totals (exception) | Null or partial | Complete |
| Monthly KRW totals (managed) | Accurate but cgjang only | Accurate for 3 confirmed users |
| Approval approve/reject safety | Unauthenticated | JWT-protected admin-only |
| DynamoDB table read access | 5 of 10 tables readable | 8 of 10 tables readable (+ session-metadata) |
| Unfiltered approval list | Scan fails (IAM gap) | Scan works via ScopeAReadTemp |

### Partially trustworthy (improved but not complete):

| Capability | Status | What's missing |
|------------|--------|---------------|
| Audit trail / request history | Tables now readable (IAM fixed) | No read endpoint yet (Phase 4B) |
| Daily usage drill-down | Table now readable (IAM fixed) | No read endpoint yet (Phase 4B) |
| User coverage | 3 of 6 users visible | hermee, shlee2 pending operator decision |

---

## 10. What Still Remains Unsafe or Unresolved

| # | Item | Risk Level | Resolution Path |
|---|------|-----------|----------------|
| 10.1 | Per-request overshoot (§7.1) | Medium — bounded by single-request cost (~4,795 KRW worst case) | Operator decision D4. If unacceptable → handler.py headroom guard (Phase 5) |
| 10.2 | hermee invisible | Low — 1 invocation total | Operator decision D1 |
| 10.3 | shlee2 invisible | Low — 3 invocations total | Operator decision D2 |
| 10.4 | No request ledger read endpoint | Medium — audit data exists but no API to surface it | Phase 4B: add `GET /api/gateway/ledger` after IAM fix |
| 10.5 | No daily usage read endpoint | Low — monthly aggregates available | Phase 4B: add endpoint if needed |
| 10.6 | request_ledger has no GSI for principal_id | Low — full scan with client-side filter works for MVP volume | GSI addition requires Terraform change (separate approval) |
| 10.7 | New model IDs not in pricing table | Low — fail-closed (gateway denies) or silent omission (exception monitoring) | Operator adds pricing entry when new models are adopted |
| 10.8 | Lambda pricing cache staleness | Low — reloads on cold start + one retry on miss | No action needed for MVP |
| 10.9 | SES notification best-effort | Low — approval request saved even if email fails | Accepted risk (R7 from Phase 3) |
| 10.10 | Frontend improvements | Low — functional but basic | Phase 5 scope |

### Summary of Unresolved Operator Decisions

| Decision | Impact of Not Deciding | Can Core Pipeline Proceed? |
|----------|----------------------|---------------------------|
| hermee classification | Invisible. Zero operational risk. | Yes |
| shlee2 classification | Invisible. Zero operational risk. | Yes |
| Per-request overshoot | Current behavior continues. Bounded risk. | Yes — but operator must acknowledge |
| Opus for sbkim | sbkim can't use Opus. Trivial to add later. | Yes |
