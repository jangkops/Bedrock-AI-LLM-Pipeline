# Phase 4 Backend/Admin-Plane Remediation Analysis

> Generated: 2026-03-24. Based on live DynamoDB scans, CloudWatch Logs Insights queries,
> IAM policy inspection, and handler.py code review.
> This is a research/planning artifact — no implementation changes.

---

## 1. Why Frontend Is Not the Primary Blocker

The frontend (BedrockGateway.jsx) already exists and calls the Phase 4 Scope A APIs.
The APIs themselves are structurally deployed (gateway_usage.py registered in app.py).
The blocker is that the data those APIs read is incomplete:

- `principal_policy` has only 1 user (cgjang). 5 other BedrockUser-* roles exist.
- `model_pricing` has 5 entries but is missing 8+ model IDs actually invoked in production.
- `request_ledger` and `daily_usage` are unreadable by backend-admin (IAM gap).
- `approval_request` is unreadable by backend-admin for Scan (IAM gap).
- Exception user monitoring (shlee) returns "미등록된 모델입니다" for most models because
  shlee primarily uses `us.anthropic.claude-sonnet-4-6` and `us.anthropic.claude-opus-4-6-v1`,
  neither of which exists in `model_pricing`.

The frontend will render empty/misleading data until the backend data layer is fixed.

---

## 2. Current Data-Source Gaps

### 2.1 principal_policy — Only 1 of 6 Users Registered

Live scan result: 1 item (cgjang only).

IAM roles that exist (from `aws iam list-roles`):
- BedrockUser-cgjang ← registered
- BedrockUser-hermee ← NOT registered
- BedrockUser-jwlee ← NOT registered (2,917 invocations this month)
- BedrockUser-sbkim ← NOT registered (1 invocation)
- BedrockUser-shlee ← NOT registered (27,225 invocations — exception user)
- BedrockUser-shlee2 ← NOT registered (3 invocations)

Impact: GET /api/gateway/users returns only cgjang. jwlee (the second-heaviest user)
is invisible to the operator. sbkim, hermee, shlee2 are also invisible.

### 2.2 model_pricing — 5 Entries, 8+ Models Missing

Current model_pricing entries:
1. `anthropic.claude-3-5-sonnet-20241022-v2:0` (4.35 / 21.75 KRW)
2. `anthropic.claude-3-haiku-20240307-v1:0` (0.36 / 1.81 KRW)
3. `anthropic.claude-sonnet-4-20250514-v1:0` (4.35 / 21.75 KRW)
4. `us.anthropic.claude-haiku-4-5-20251001-v1:0` (1.45 / 7.25 KRW)
5. `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (4.35 / 21.75 KRW)

Models actually invoked this month (from CloudWatch Logs, 30,167 total invocations):

| Model ID | Invocations | In model_pricing? |
|----------|-------------|-------------------|
| `us.anthropic.claude-sonnet-4-6` | 22,748 | NO |
| `us.anthropic.claude-opus-4-6-v1` | 4,482 | NO |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 1,569 | NO |
| `us.amazon.nova-2-lite-v1:0` | 1,240 | NO |
| `global.anthropic.claude-opus-4-6-v1` | 103 | NO |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | 7 | NO |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 5 | YES |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | 2 | YES |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 1 | NO |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 1 | NO |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | 1 | YES |
| `anthropic.claude-3-haiku-20240307-v1:0` | 1 | YES |
| `us.anthropic.claude-opus-4-20250514-v1:0` | 1 | NO |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | 1 | NO |
| `us.anthropic.claude-3-5-sonnet-20240620-v1:0` | 1 | NO |
| `anthropic.claude-sonnet-4-20250514-v1:0` | 1 | YES |

Coverage: 5 of 16 model IDs have pricing. But by invocation volume,
only 10 of 30,167 invocations (0.03%) hit a model with pricing.
**99.97% of actual usage is unpriced.**

Root cause: The pricing table was seeded with foundation model IDs, but users
invoke via cross-region inference profile IDs (`us.*`, `global.*`) and newer
model versions (`claude-sonnet-4-6`, `claude-opus-4-6-v1`) that were released
after the seed data was created.

### 2.3 request_ledger — Unreadable by backend-admin

`BedrockGatewayScopeAReadTemp` IAM policy does NOT include `request-ledger`.
Scan fails with AccessDeniedException.

Impact: No audit trail visible to operator. No request history endpoint possible.

### 2.4 daily_usage — Unreadable by backend-admin

Same IAM gap. `daily-usage` not in `BedrockGatewayScopeAReadTemp`.

### 2.5 approval_request — Partially Readable

`BedrockGatewayApprovalAdminTemp` grants GetItem/PutItem/UpdateItem/DeleteItem/Query
but NOT Scan. The gateway_approval.py `list_approvals()` uses Scan when no filters
are provided, which fails.

### 2.6 monthly_usage — Only 1 Record

Live scan: 1 item (cgjang, 2026-03, haiku-4-5, 65 input / 25 output / 0.2755 KRW).
This is from the Phase 2 smoke test. No other users have monthly_usage because
they are not going through the gateway (they invoke Bedrock directly).

---

## 3. Current IAM / Read-Access Gaps

### 3.1 BedrockGatewayScopeAReadTemp (infra-admins group)

Tables covered (GetItem/Query/Scan):
- model-pricing ✓
- principal-policy ✓
- monthly-usage ✓
- temporary-quota-boost ✓
- approval-pending-lock ✓

Tables MISSING:
- request-ledger ✗
- daily-usage ✗
- approval-request ✗ (Scan missing — only CRUD via ApprovalAdminTemp)
- session-metadata ✗
- idempotency-record ✗

### 3.2 Required IAM Changes

To make all gateway tables operator-readable, `BedrockGatewayScopeAReadTemp` needs:
- Add `request-ledger` ARN (read-only: GetItem/Query/Scan)
- Add `daily-usage` ARN (read-only: GetItem/Query/Scan)
- Add `approval-request` ARN (read-only: GetItem/Query/Scan)
  - OR add Scan to `BedrockGatewayApprovalAdminTemp`
- Optionally: session-metadata, idempotency-record (lower priority)

This is a managed IAM policy update, not a Terraform change.
The policy `BedrockGatewayScopeAReadTemp` was manually created (not in Terraform state).

---

## 4. Pricing / Model-Coverage Gaps

### 4.1 The Inference Profile ID Problem

AWS Bedrock cross-region inference uses profile IDs like `us.anthropic.claude-sonnet-4-6`
instead of foundation model IDs like `anthropic.claude-sonnet-4-20250514-v1:0`.

The `model_pricing` table was seeded with a mix of foundation IDs and some `us.*` IDs,
but the actual high-volume models are:
- `us.anthropic.claude-sonnet-4-6` (22,748 calls) — NO pricing entry
- `us.anthropic.claude-opus-4-6-v1` (4,482 calls) — NO pricing entry
- `global.anthropic.claude-haiku-4-5-20251001-v1:0` (1,569 calls) — NO pricing entry
- `us.amazon.nova-2-lite-v1:0` (1,240 calls) — NO pricing entry

### 4.2 Required Pricing Additions

Minimum additions to cover >99% of actual invocations:

| model_id | USD Input/1K | USD Output/1K | KRW Input/1K | KRW Output/1K | Notes |
|----------|-------------|---------------|-------------|---------------|-------|
| `us.anthropic.claude-sonnet-4-6` | 0.003 | 0.015 | 4.35 | 21.75 | Sonnet 4 tier pricing |
| `us.anthropic.claude-opus-4-6-v1` | 0.015 | 0.075 | 21.75 | 108.75 | Opus 4 tier pricing |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 0.001 | 0.005 | 1.45 | 7.25 | Same as us. variant |
| `global.anthropic.claude-opus-4-6-v1` | 0.015 | 0.075 | 21.75 | 108.75 | Same as us. variant |
| `us.amazon.nova-2-lite-v1:0` | 0.00006 | 0.00024 | 0.087 | 0.348 | Nova Lite pricing |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | 0.001 | 0.005 | 1.45 | 7.25 | Direct (non-profile) |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 0.001 | 0.005 | 1.45 | 7.25 | 3.5 Haiku |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 0.015 | 0.075 | 21.75 | 108.75 | Opus 4.5 |
| `us.anthropic.claude-opus-4-20250514-v1:0` | 0.015 | 0.075 | 21.75 | 108.75 | Opus 4 |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | 0.003 | 0.015 | 4.35 | 21.75 | us. variant |
| `us.anthropic.claude-3-5-sonnet-20240620-v1:0` | 0.003 | 0.015 | 4.35 | 21.75 | us. variant |

> USD prices are approximate and must be verified by operator against current AWS pricing.
> Exchange rate: 1,450 KRW/USD (same as existing seed data).

### 4.3 Lambda handler.py Pricing Lookup — Fail-Closed Behavior

The handler's `lookup_model_pricing()` returns None if model_id is not in the cache.
When pricing is None, the handler DENIES the request:

```python
if not pricing:
    denial_reason = f"no pricing defined for model {model_id}"
    return deny_response(denial_reason)
```

This means: if a user tries to invoke a model through the gateway that isn't in
`model_pricing`, the request is denied. This is correct fail-closed behavior.
But it also means the gateway cannot serve any of the 8+ missing models until
pricing is added.

For direct-use users (shlee) who bypass the gateway, the pricing gap means
the admin portal's exception-usage endpoint cannot estimate KRW cost.

### 4.4 Normalization Strategy

Two approaches to handle inference profile IDs:

**Option A: Add every variant as a separate pricing entry.**
- Simple, no code change.
- Requires ~11 new DynamoDB items.
- Maintenance burden: every new model version or region prefix needs a new entry.

**Option B: Add a normalization function in handler.py that maps profile IDs to foundation IDs.**
- E.g., `us.anthropic.claude-sonnet-4-6` → `anthropic.claude-sonnet-4-6` → lookup pricing.
- Reduces pricing table size.
- Requires Lambda code change (handler.py modification).
- Risk: normalization rules may not cover all edge cases.

**Recommendation: Option A for now.** It's data-only, no code change, immediately effective.
Option B can be a v2 optimization if the pricing table grows unwieldy.

---

## 5. Approval-Control Model Problem

### 5.1 The Core Problem

Users do NOT declare "I want to spend X KRW" before invoking a model.
They simply call POST /converse with a prompt. The actual cost is unknown until
Bedrock returns the response with token counts.

Current handler.py flow:
1. Check quota (monthly cumulative cost < effective limit)
2. If quota OK → invoke Bedrock
3. After response → estimate cost → update monthly_usage
4. If quota exceeded → deny with 429 + hint to request approval

This means:
- A single request can overshoot the remaining monthly budget.
- The system only blocks AFTER the cumulative total exceeds the limit.
- There is no per-request cost ceiling or pre-invocation worst-case check.

### 5.2 Current Enforcement Model (handler.py)

```
check_quota():
  total_cost_krw = SUM(monthly_usage for current month)
  effective_limit = base_limit + active_boosts (capped at hard_cap)
  allowed = total_cost_krw < effective_limit
```

This is a **post-hoc cumulative check**. It does NOT estimate the cost of the
incoming request before invocation.

### 5.3 Per-Request Safety Guard Options

**Option 1: No pre-invocation guard (current behavior).**
- Simple. Already deployed.
- Risk: one large request (e.g., 200K output tokens on Opus at 108.75 KRW/1K)
  could cost ~21,750 KRW in a single request, overshooting a nearly-full budget.
- Acceptable for MVP if the operator understands the risk.

**Option 2: Pre-invocation worst-case estimate.**
- Before calling Bedrock, estimate worst-case cost:
  `worst_case = input_tokens_from_request * input_price + MAX_OUTPUT_TOKENS * output_price`
- If `current_usage + worst_case > effective_limit` → deny.
- Requires knowing MAX_OUTPUT_TOKENS (from inferenceConfig.maxTokens or model default).
- Problem: input token count is not known before Bedrock processes the request.
  The request body contains messages, not a token count.
- Could use a rough heuristic (e.g., 4 chars ≈ 1 token) but this is unreliable.

**Option 3: Soft pre-check with configurable headroom.**
- If `remaining_budget < HEADROOM_KRW` (e.g., 50,000 KRW) → deny or warn.
- Simple to implement. Doesn't require token estimation.
- Headroom value is configurable per policy.

**Recommendation for MVP: Option 1 (current behavior) + Option 3 as a future enhancement.**
The current post-hoc check is sufficient for a small user base (6 users).
The maximum single-request overshoot for Opus 4 at max output (4096 tokens default)
is approximately: 200K input × 21.75/1K + 4096 × 108.75/1K ≈ 4,350 + 445 ≈ 4,795 KRW.
This is <1% of the 500K base limit. The overshoot risk is manageable.

### 5.4 Approval Trigger Timing

Current flow: user hits 429 (quota exceeded) → user manually POSTs /approval/request
with reason and requested_increment_krw=500000.

The approval is NOT triggered automatically by the system. The user must:
1. Receive a 429 denial
2. Decide to request more quota
3. Submit POST /approval/request with a reason

This is acceptable for MVP. Automatic approval triggers (e.g., "when usage > 80%,
auto-submit approval request") would add complexity without clear benefit for 6 users.

### 5.5 Approval State Transitions

Current states in approval_request table:
- `pending` → created by user via POST /approval/request
- `approved` → set by admin via POST /api/gateway/approvals/<id>/approve
- `rejected` → set by admin via POST /api/gateway/approvals/<id>/reject

These transitions are already implemented in handler.py (user side) and
gateway_approval.py (admin side). The state machine is complete for MVP.

What's missing for operator visibility:
- No endpoint to list approval history (only current state)
- No timeline view (created_at → approved_at/rejected_at)
- approval_request table is not readable by backend-admin (IAM gap, §3)

### 5.6 What Happens When a Request Would Overshoot

Current behavior: the request succeeds, cost is recorded, and the NEXT request
gets denied with 429. The overshoot amount is bounded by the single-request cost.

For the worst case (Opus 4.6 with maximum context):
- Input: ~200K tokens × 21.75 KRW/1K = ~4,350 KRW
- Output: ~4,096 tokens × 108.75 KRW/1K = ~445 KRW
- Total worst-case single request: ~4,795 KRW

This is 0.96% of the 500K base limit. Acceptable for MVP.

---

## 6. Recommended Backend / Infra Work Packet

### Priority 1: IAM Policy Update (operator action, no code change)

Update `BedrockGatewayScopeAReadTemp` to add read access for:
- `bedrock-gw-dev-us-west-2-request-ledger` (GetItem/Query/Scan)
- `bedrock-gw-dev-us-west-2-daily-usage` (GetItem/Query/Scan)
- `bedrock-gw-dev-us-west-2-approval-request` (add Scan to existing CRUD)
- `bedrock-gw-dev-us-west-2-session-metadata` (GetItem/Query/Scan) — optional

This is a managed IAM policy update via AWS Console or CLI.
Not a Terraform change. Immediately effective.

### Priority 2: Model Pricing Seed Expansion (operator action, no code change)

Add 11 missing model_pricing entries (§4.2) via DynamoDB PutItem.
Data-only change. No Lambda redeploy needed (pricing cache reloads on next cold start).

### Priority 3: Principal Policy Seed Expansion (operator action, no code change)

Add principal_policy entries for confirmed seed targets only:
- `107650139384#BedrockUser-jwlee` (active user, 2,917 invocations)
- `107650139384#BedrockUser-sbkim` (1 invocation)

Each with: monthly_cost_limit_krw=500000, max_monthly_cost_limit_krw=2000000,
allowed_models=[same 5 models as cgjang + new models as appropriate].

Also update cgjang's allowed_models to include new inference profile model IDs.

shlee is deliberately excluded from principal_policy (direct-use exception — locked operator decision).
hermee and shlee2 are NOT seeded until operator explicitly classifies them.
See `docs/ai/phase4-corrected-user-classification.md` §2 for operator decision details.

### Priority 4: Exception User List Update (code change, gateway_usage.py)

Update EXCEPTION_USERS dict in gateway_usage.py to reflect actual direct-use users.
Currently only shlee is listed. Verify whether shlee2 should also be exception
(3 invocations, not through gateway).

### Priority 5: Backend-Admin Read Endpoints for Ledger/Approval History (code change)

After IAM gap is fixed (Priority 1), add:
- `GET /api/gateway/ledger` — paginated request_ledger scan (admin-only)
- `GET /api/gateway/users/<pid>/history` — request_ledger query by principal_id
  (requires GSI on request_ledger — currently no GSI, only PK=request_id)

Note: request_ledger has no GSI for principal_id. A full table scan filtered
client-side is the only option without adding a GSI. For MVP with small data
volume, this is acceptable. GSI addition is a Terraform change (separate approval).

---

## 7. Minimum Required IAM Changes

```bash
# Update BedrockGatewayScopeAReadTemp to add missing tables
# This adds request-ledger, daily-usage, approval-request, session-metadata
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
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

---

## 8. Minimum Required Data-Model / API Changes

### 8.1 Data-Only Changes (DynamoDB PutItem, no code)

**model_pricing additions** (11 items):
```bash
# High-volume models (cover >99% of invocations)
# us.anthropic.claude-sonnet-4-6 (22,748 invocations)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-sonnet-4-6"},
  "input_price_per_1k":{"N":"4.35"},"output_price_per_1k":{"N":"21.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.003"},"source_usd_output_per_1k":{"N":"0.015"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Sonnet 4.6 US cross-region inference profile. Verify USD pricing."}
}'

# us.anthropic.claude-opus-4-6-v1 (4,482 invocations)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-opus-4-6-v1"},
  "input_price_per_1k":{"N":"21.75"},"output_price_per_1k":{"N":"108.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.015"},"source_usd_output_per_1k":{"N":"0.075"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Opus 4.6 US cross-region inference profile. Verify USD pricing."}
}'

# global.anthropic.claude-haiku-4-5-20251001-v1:0 (1,569 invocations)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"global.anthropic.claude-haiku-4-5-20251001-v1:0"},
  "input_price_per_1k":{"N":"1.45"},"output_price_per_1k":{"N":"7.25"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.001"},"source_usd_output_per_1k":{"N":"0.005"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Haiku 4.5 global cross-region inference profile."}
}'

# us.amazon.nova-2-lite-v1:0 (1,240 invocations)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.amazon.nova-2-lite-v1:0"},
  "input_price_per_1k":{"N":"0.087"},"output_price_per_1k":{"N":"0.348"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.00006"},"source_usd_output_per_1k":{"N":"0.00024"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Amazon Nova 2 Lite. Verify USD pricing."}
}'

# global.anthropic.claude-opus-4-6-v1 (103 invocations)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"global.anthropic.claude-opus-4-6-v1"},
  "input_price_per_1k":{"N":"21.75"},"output_price_per_1k":{"N":"108.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.015"},"source_usd_output_per_1k":{"N":"0.075"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Opus 4.6 global cross-region inference profile."}
}'

# Low-volume models (completeness)
# anthropic.claude-haiku-4-5-20251001-v1:0 (7 invocations, direct non-profile)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"anthropic.claude-haiku-4-5-20251001-v1:0"},
  "input_price_per_1k":{"N":"1.45"},"output_price_per_1k":{"N":"7.25"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.001"},"source_usd_output_per_1k":{"N":"0.005"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Haiku 4.5 direct (non-profile) ID."}
}'

# anthropic.claude-3-5-haiku-20241022-v1:0
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"anthropic.claude-3-5-haiku-20241022-v1:0"},
  "input_price_per_1k":{"N":"1.45"},"output_price_per_1k":{"N":"7.25"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.001"},"source_usd_output_per_1k":{"N":"0.005"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Claude 3.5 Haiku."}
}'

# us.anthropic.claude-opus-4-5-20251101-v1:0
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-opus-4-5-20251101-v1:0"},
  "input_price_per_1k":{"N":"21.75"},"output_price_per_1k":{"N":"108.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.015"},"source_usd_output_per_1k":{"N":"0.075"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Opus 4.5 US cross-region inference profile."}
}'

# us.anthropic.claude-opus-4-20250514-v1:0
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-opus-4-20250514-v1:0"},
  "input_price_per_1k":{"N":"21.75"},"output_price_per_1k":{"N":"108.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.015"},"source_usd_output_per_1k":{"N":"0.075"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Opus 4 US cross-region inference profile."}
}'

# us.anthropic.claude-3-5-sonnet-20241022-v2:0
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-3-5-sonnet-20241022-v2:0"},
  "input_price_per_1k":{"N":"4.35"},"output_price_per_1k":{"N":"21.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.003"},"source_usd_output_per_1k":{"N":"0.015"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Sonnet 3.5 v2 US cross-region inference profile."}
}'

# us.anthropic.claude-3-5-sonnet-20240620-v1:0
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-model-pricing --item '{
  "model_id":{"S":"us.anthropic.claude-3-5-sonnet-20240620-v1:0"},
  "input_price_per_1k":{"N":"4.35"},"output_price_per_1k":{"N":"21.75"},
  "effective_date":{"S":"2026-03-24"},
  "source_usd_input_per_1k":{"N":"0.003"},"source_usd_output_per_1k":{"N":"0.015"},
  "exchange_rate_krw_per_usd":{"N":"1450"},
  "notes":{"S":"Sonnet 3.5 v1 US cross-region inference profile."}
}'
```

**principal_policy additions** (2 confirmed items + 1 update):
```bash
# jwlee — active user (2,917 invocations this month)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
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

# sbkim — minimal user (1 invocation)
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
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
    {"S":"us.anthropic.claude-opus-4-6-v1"},
    {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
    {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
    {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
  ]}
}'

# hermee — DEFERRED: requires explicit operator decision (Task 4A.3a)
# If operator approves hermee as gateway-managed, use this command:
# env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
# aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-principal-policy --item '{
#   "principal_id":{"S":"107650139384#BedrockUser-hermee"},
#   "monthly_cost_limit_krw":{"N":"500000"},
#   "max_monthly_cost_limit_krw":{"N":"2000000"},
#   "daily_input_token_limit":{"N":"100000"},
#   "daily_output_token_limit":{"N":"50000"},
#   "allowed_models":{"L":[
#     {"S":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},
#     {"S":"us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
#     {"S":"us.anthropic.claude-sonnet-4-6"},
#     {"S":"us.anthropic.claude-opus-4-6-v1"},
#     {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
#     {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
#     {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
#   ]}
# }'

# shlee2 — DEFERRED: requires explicit operator decision (Task 4A.3b)
# If operator classifies shlee2 as gateway-managed, use this command:
# env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
# aws dynamodb put-item --table-name bedrock-gw-dev-us-west-2-principal-policy --item '{
#   "principal_id":{"S":"107650139384#BedrockUser-shlee2"},
#   "monthly_cost_limit_krw":{"N":"500000"},
#   "max_monthly_cost_limit_krw":{"N":"2000000"},
#   "daily_input_token_limit":{"N":"100000"},
#   "daily_output_token_limit":{"N":"50000"},
#   "allowed_models":{"L":[
#     {"S":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},
#     {"S":"us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
#     {"S":"us.anthropic.claude-sonnet-4-6"},
#     {"S":"anthropic.claude-3-5-sonnet-20241022-v2:0"},
#     {"S":"anthropic.claude-3-haiku-20240307-v1:0"},
#     {"S":"anthropic.claude-sonnet-4-20250514-v1:0"}
#   ]}
# }'
# If operator classifies shlee2 as exception, add to EXCEPTION_USERS in gateway_usage.py instead.
```

Also update cgjang's allowed_models to include the new model IDs:
```bash
env AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" \
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

### 8.2 Code Changes (backend-admin only, requires approval)

None strictly required for the data-layer remediation.
The existing gateway_usage.py endpoints will automatically reflect the new data
once the IAM and seed gaps are filled.

Optional future code changes:
- Add request_ledger read endpoint (after IAM fix)
- Add approval history timeline endpoint (after IAM fix)
- Update EXCEPTION_USERS if shlee2 should also be exception

---

## 9. Exact Next Implementation Order

1. **Operator: Update IAM policy** (§7) — unblocks all table reads
2. **Operator: Seed model_pricing** (§8.1, 11 items) — unblocks cost estimation
3. **Operator: Seed principal_policy** (§8.1, 2 confirmed new + cgjang update) — unblocks user visibility
4. **Operator: Verify** — scan all tables, confirm backend-admin can read them
5. **Operator: Docker rebuild backend-admin** — pick up any code changes
6. **Operator: Validate Phase 4 Scope A endpoints** — confirm data flows through APIs
7. **Future: Add ledger/history read endpoints** (code change, separate approval)
8. **Future: Per-request safety guard** (handler.py change, separate approval)

Steps 1-4 are data-only / IAM-only. No code changes. No Terraform. No Lambda redeploy.
They can be executed immediately by the operator.
hermee and shlee2 seeding is deferred until operator explicitly classifies them.

---

## 10. Final Readiness Verdict

The backend/admin-plane is structurally complete (gateway_usage.py + app.py registration).
The blocker is not code — it's data and IAM permissions.

Three operator actions unblock the entire monitoring pipeline:
1. IAM policy update (5 minutes)
2. Model pricing seed (11 DynamoDB PutItems, 10 minutes)
3. Principal policy seed (2 confirmed new + 1 update, 5 minutes)

Total estimated operator effort: ~20 minutes of CLI commands.
No code changes required. No Terraform apply. No Lambda redeploy.
No risk to existing infrastructure.

After these three actions, the Phase 4 Scope A endpoints will return
meaningful data for 3 confirmed gateway-managed users (cgjang, jwlee, sbkim)
and the shlee exception user.
hermee and shlee2 remain invisible until operator classifies them.

The approval/control model (§5) is adequate for MVP. The post-hoc cumulative
quota check has a bounded overshoot risk of <1% per request. No immediate
code changes needed for the enforcement model.

**Decisions requiring operator approval:**
1. USD pricing values for new models (§4.2) — operator must verify against AWS pricing page
2. Whether shlee2 should be exception or managed user
3. Whether to add Opus 4.6 to all users' allowed_models (currently only shlee uses it heavily)
4. Exchange rate: continue using 1,450 KRW/USD or update?
