# Phase 2 Inference Profile Fix — Root Cause & Minimum-Change Recommendation

> Generated: 2026-03-19
> Scope: Phase 2 unblock ONLY. No Phase 3/4 work. No v2 refactoring.
> Prerequisite: Task 2 LIVE VERIFIED / COMPLETE. Phase 2 DEPLOYED TO DEV, BLOCKED BY INFERENCE PROFILE REQUIREMENT.

---

## 1. Root Cause

Claude 4.5+ models have `inferenceTypesSupported: ["INFERENCE_PROFILE"]` only. They do NOT support `ON_DEMAND` direct invocation.

| Model | Base Model ID | inferenceTypesSupported | Direct `converse(modelId=base_id)` |
|-------|--------------|------------------------|-------------------------------------|
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | `["INFERENCE_PROFILE"]` | **FAILS** |
| Claude Sonnet 4.5 | `anthropic.claude-sonnet-4-5-20250929-v1:0` | `["INFERENCE_PROFILE"]` | **FAILS** |
| Claude 3.5 Sonnet v2 | `anthropic.claude-3-5-sonnet-20241022-v2:0` | `["ON_DEMAND"]` | Works |
| Claude 3 Haiku | `anthropic.claude-3-haiku-20240307-v1:0` | `["ON_DEMAND"]` | Works |
| Claude Sonnet 4 | `anthropic.claude-sonnet-4-20250514-v1:0` | `["ON_DEMAND"]` | Works |

Claude 4.5+ models require cross-region inference profile IDs:
- `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0`

These `us.` prefix IDs are valid `modelId` values for `bedrock_runtime.converse()`. They also work as plain string keys for DynamoDB lookups.

### Live Evidence

Task 2 Test B returned:
```json
{"decision": "ERROR", "error": "bedrock invocation failed: ... inference profile ..."}
```
This confirms the Lambda reached `invoke_bedrock()` and `converse()` rejected the base model ID.

---

## 2. Options Analysis

### Option A: Unified Key Switch to Inference Profile IDs (Recommended)

Switch all keys — `allowed_models`, `model_pricing`, and user-facing `modelId` — to inference profile IDs for 4.5+ models. The `us.` prefix IDs work in all three roles:

| Role | Before (broken) | After (fixed) |
|------|-----------------|---------------|
| Policy allowlist key | `anthropic.claude-haiku-4-5-20251001-v1:0` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Pricing lookup key | `anthropic.claude-haiku-4-5-20251001-v1:0` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Bedrock invocation target | `anthropic.claude-haiku-4-5-20251001-v1:0` ❌ | `us.anthropic.claude-haiku-4-5-20251001-v1:0` ✅ |

**Pros:**
- Zero runtime code change — `handler.py` passes `modelId` as-is to `converse()`, and the `us.` prefix ID is valid
- Same triple-role pattern (v1 known limitation, documented in design.md) — just with correct ID format
- Minimal blast radius — only DynamoDB seed data changes
- Legacy models (`ON_DEMAND`) keep their base model IDs unchanged

**Cons:**
- Users must send `us.anthropic.claude-haiku-4-5-20251001-v1:0` in requests (not the base model ID)
- If a user sends the base model ID, it will be denied at `check_model_access()` (fail-closed, correct behavior)

### Option B: Mapping Layer (policy key → invocation target)

Introduce a resolution function that maps a canonical policy key to the actual invocation target.

**Pros:**
- Users can send base model IDs; Lambda resolves to inference profile IDs internally
- Cleaner separation of concerns

**Cons:**
- Runtime code change required (`handler.py`)
- New mapping data structure needed (DynamoDB or in-code)
- More complex, more risk, more testing
- v2 territory — the design.md already documents this as the v2 separation plan

### Recommendation: Option A

Option A is the minimum safe change. No code change. No new data structures. No new failure modes. The `us.` prefix inference profile IDs are the correct invocation targets AND work as policy/pricing keys. Legacy models are unaffected.

Option B is the correct long-term architecture (documented in design.md "v2 분리 계획") but is over-engineering for the current unblock.

---

## 3. Is Runtime Code Change Needed?

**No.** `handler.py` `invoke_bedrock()` passes `model_id` directly to `bedrock_runtime.converse(modelId=model_id)`. If `model_id` is `us.anthropic.claude-haiku-4-5-20251001-v1:0`, `converse()` will accept it and route to the correct model via the US cross-region inference profile.

Similarly:
- `check_model_access()` does exact string match against `allowed_models` — works with any string
- `lookup_model_pricing()` does exact key lookup in `model_pricing` — works with any string
- `update_monthly_usage()` stores `model_id` as SK — works with any string

No function in `handler.py` parses, validates, or transforms the model ID format. It's opaque throughout the pipeline.

---

## 4. Is IAM Change Needed?

**No.** The Lambda execution role's Bedrock policy is:
```hcl
Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
Resource = ["*"]
```

`Resource: ["*"]` covers both base model ARNs and inference profile ARNs. No IAM change needed.

---

## 5. Exact Changes Required

### 5.1 DynamoDB: `model_pricing` Table

**Delete old 4.5+ entries, insert new ones with `us.` prefix keys.** Legacy models unchanged.

| Action | model_id (PK) | Pricing | Notes |
|--------|--------------|---------|-------|
| DELETE | `anthropic.claude-haiku-4-5-20251001-v1:0` | — | Old base model ID key |
| DELETE | `anthropic.claude-sonnet-4-5-20250929-v1:0` | — | Old base model ID key |
| PUT | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | input: 1.45, output: 7.25 | New inference profile ID key |
| PUT | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | input: 4.35, output: 21.75 | New inference profile ID key |
| — | `anthropic.claude-3-5-sonnet-20241022-v2:0` | unchanged | Legacy ON_DEMAND, no change |
| — | `anthropic.claude-3-haiku-20240307-v1:0` | unchanged | Legacy ON_DEMAND, no change |
| — | `anthropic.claude-sonnet-4-20250514-v1:0` | unchanged | Legacy ON_DEMAND, no change |

After: 5 items total (2 inference profile + 3 legacy base model).

### 5.2 DynamoDB: `principal_policy` Table (cgjang)

**Update `allowed_models` list:** replace 4.5+ base model IDs with inference profile IDs. Legacy models unchanged.

Before:
```
allowed_models: [
  "anthropic.claude-haiku-4-5-20251001-v1:0",
  "anthropic.claude-sonnet-4-5-20250929-v1:0",
  "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "anthropic.claude-3-haiku-20240307-v1:0",
  "anthropic.claude-sonnet-4-20250514-v1:0"
]
```

After:
```
allowed_models: [
  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "anthropic.claude-3-haiku-20240307-v1:0",
  "anthropic.claude-sonnet-4-20250514-v1:0"
]
```

### 5.3 Smoke Test Script Update

`docs/ai/phase2-smoke-test.py` — change `REQUEST_BODY["modelId"]` from base model ID to inference profile ID:

Before: `"modelId": "anthropic.claude-haiku-4-5-20251001-v1:0"`
After: `"modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0"`

### 5.4 No Other File Changes

| File | Change Needed? | Reason |
|------|---------------|--------|
| `handler.py` | **NO** | Passes `modelId` as-is; inference profile IDs work |
| `iam.tf` | **NO** | `Resource: ["*"]` covers inference profiles |
| `dynamodb.tf` | **NO** | Schema unchanged |
| `lambda.tf` | **NO** | Env vars unchanged |
| `main.tf` | **NO** | No change |

---

## 6. Operator Execution Commands

### Credential Normalization (run first)

```bash
unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN; unset AWS_SECURITY_TOKEN
export AWS_PROFILE=bedrock-gw; export AWS_REGION=us-west-2; export AWS_DEFAULT_REGION=us-west-2; export AWS_PAGER=""
aws sts get-caller-identity
# Expected: arn:aws:sts::107650139384:assumed-role/AWSReservedSSO_AdministratorAccess_*/changgeun.jang@mogam.re.kr
```

### 6.1 Delete Old model_pricing Entries (4.5+ base model IDs)

```bash
# Delete old Haiku 4.5 base model ID entry
aws dynamodb delete-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-haiku-4-5-20251001-v1:0"}}' \
  --region us-west-2

# Delete old Sonnet 4.5 base model ID entry
aws dynamodb delete-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-sonnet-4-5-20250929-v1:0"}}' \
  --region us-west-2
```

### 6.2 Insert New model_pricing Entries (inference profile IDs)

```bash
# Claude Haiku 4.5 — inference profile ID
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "us.anthropic.claude-haiku-4-5-20251001-v1:0"},
    "input_price_per_1k": {"N": "1.45"},
    "output_price_per_1k": {"N": "7.25"},
    "effective_date": {"S": "2026-03-19"},
    "source_usd_input_per_1k": {"N": "0.001"},
    "source_usd_output_per_1k": {"N": "0.005"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "ACTIVE 4.5+. US cross-region inference profile ID. Required for INFERENCE_PROFILE-only models."}
  }' \
  --region us-west-2

# Claude Sonnet 4.5 — inference profile ID
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-19"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "ACTIVE 4.5+. US cross-region inference profile ID. Required for INFERENCE_PROFILE-only models."}
  }' \
  --region us-west-2
```

### 6.3 Update principal_policy allowed_models (cgjang)

```bash
# Replace allowed_models list with inference profile IDs for 4.5+ models
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET allowed_models = :models' \
  --expression-attribute-values '{
    ":models": {"L": [
      {"S": "us.anthropic.claude-haiku-4-5-20251001-v1:0"},
      {"S": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
      {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
      {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
      {"S": "anthropic.claude-sonnet-4-20250514-v1:0"}
    ]}
  }' \
  --region us-west-2
```

### 6.4 Verification

```bash
# Verify model_pricing: 5 items, 2 with us. prefix, 3 legacy
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --region us-west-2 \
  --projection-expression "model_id" \
  --query 'Items[*].model_id.S' \
  --output text
# Expected (5 items, order may vary):
#   us.anthropic.claude-haiku-4-5-20251001-v1:0
#   us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   anthropic.claude-3-5-sonnet-20241022-v2:0
#   anthropic.claude-3-haiku-20240307-v1:0
#   anthropic.claude-sonnet-4-20250514-v1:0

# Verify NO old base model ID entries remain
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-haiku-4-5-20251001-v1:0"}}' \
  --region us-west-2
# Expected: empty (no Item)

aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-sonnet-4-5-20250929-v1:0"}}' \
  --region us-west-2
# Expected: empty (no Item)

# Verify principal_policy allowed_models
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2 \
  --projection-expression "allowed_models"
# Expected: list with 5 items, first 2 have us. prefix
```

---

## 7. Post-Fix Smoke Test

After seed data update, re-run the smoke test as `BedrockUser-cgjang`:

```bash
# From FSx:
python3 docs/ai/phase2-smoke-test.py
```

The smoke test script must be updated first (§5.3) to use `us.anthropic.claude-haiku-4-5-20251001-v1:0`.

Expected result: HTTP 200, `decision: ALLOW`, `estimated_cost_krw > 0`.

If this succeeds, Phase 2 C5 criterion is met. Proceed to C6-C9 verification per `docs/ai/phase2-post-deploy-verification.md`.

---

## 8. Rollback

If the inference profile ID fix causes unexpected issues:

```bash
# Restore old model_pricing entries (base model IDs)
# (copy commands from docs/ai/phase2-seed-data-preparation.md §1)

# Delete new inference profile ID entries
aws dynamodb delete-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "us.anthropic.claude-haiku-4-5-20251001-v1:0"}}' \
  --region us-west-2

aws dynamodb delete-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"}}' \
  --region us-west-2

# Restore allowed_models with base model IDs
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET allowed_models = :models' \
  --expression-attribute-values '{
    ":models": {"L": [
      {"S": "anthropic.claude-haiku-4-5-20251001-v1:0"},
      {"S": "anthropic.claude-sonnet-4-5-20250929-v1:0"},
      {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
      {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
      {"S": "anthropic.claude-sonnet-4-20250514-v1:0"}
    ]}
  }' \
  --region us-west-2
```

Note: rollback restores the broken state (4.5+ models won't invoke). This is only for reverting if the `us.` prefix IDs cause a different unexpected problem.

---

## 9. Impact on Other Documents

After operator applies the fix and smoke test passes, the following docs should be updated:

| Document | Update |
|----------|--------|
| `docs/ai/todo.md` | Phase 2 status: remove "BLOCKED BY INFERENCE PROFILE REQUIREMENT", update to verification status |
| `docs/ai/phase2-seed-data-preparation.md` | Update 4.5+ model IDs to `us.` prefix format |
| `docs/ai/phase2-post-deploy-verification.md` | Update expected model IDs in verification commands |
| `docs/ai/phase2-generalized-model-and-bypass-analysis.md` | Update §4.2, §7.1 to reflect that inference profile IDs ARE required for 4.5+ |
| `.kiro/specs/bedrock-access-gateway/design.md` | Update "Model ID Triple-Role Conflation" section — note that `us.` prefix IDs are used for 4.5+ |
| `docs/ai/runbook.md` | Update seed data commands and model references |

These doc updates should happen AFTER the fix is verified, not before.

---

## 10. Summary

- Root cause: Claude 4.5+ requires inference profile IDs, not base model IDs
- Fix: seed data only — switch `model_pricing` keys and `allowed_models` entries to `us.` prefix IDs
- No runtime code change (`handler.py` unchanged)
- No IAM change (`iam.tf` unchanged)
- No Terraform change (no `terraform apply` needed)
- Smoke test script needs `modelId` update
- Blast radius: DynamoDB seed data for 2 tables + 1 Python test script
- Rollback: restore old seed data (reverts to broken state for 4.5+ models)
