# Phase 2 Approval Readiness — Operator Execution Package

> Generated: 2026-03-18
> Purpose: Operator-executable package for post-apply validation, seed data, and Phase 2 approval boundary preparation.
> Scope: Governance/planning artifact only. No runtime code or IaC modified.

---

## 1. Current State Summary

| Component | Status |
|-----------|--------|
| Phase 0 (Q1-Q6 decisions) | COMPLETE (2026-03-18) |
| Phase 1 (DynamoDB tables) | APPLIED TO DEV (2026-03-18) |
| `monthly_usage` table | Deployed, empty, unused by runtime |
| `model_pricing` table | Deployed, empty, unused by runtime |
| `daily_usage` table | Active, used by current runtime |
| Lambda `handler.py` | Unchanged — daily token-count quota logic |
| Lambda env vars | Old-path only (`TABLE_DAILY_USAGE`), no `TABLE_MONTHLY_USAGE`/`TABLE_MODEL_PRICING` |
| IAM policy | Updated — `ModelPricingReadOnly` + `monthly-usage` in NonLedger |
| Post-apply validation | NOT YET RUN |
| Seed data (`model_pricing`) | NOT YET APPLIED |
| Seed data (`principal_policy` KRW fields) | NOT YET APPLIED |
| Phase 2 (Lambda rewrite) | NOT STARTED, NOT APPROVED |
| Phase 3 (Approval ladder) | NOT STARTED |
| Phase 4 (Admin API) | FROZEN |

---

## 2. Action Classification

| Action | Category | Can Execute Now? |
|--------|----------|-----------------|
| Post-apply validation (§3) | Verification | **YES** — read-only checks |
| `model_pricing` seed (§4) | Data-only | **YES** — table unused by runtime, data-only PutItem |
| `principal_policy` KRW field seed (§5) | Data-only | **YES** — DynamoDB schemaless, current handler ignores unknown attributes |
| `monthly_usage` seed | BLOCKED | **NO** — must remain empty until Phase 2 runtime writes to it |
| Phase 2 Lambda rewrite | BLOCKED | **NO** — requires separate explicit approval |
| Phase 2 `lambda.tf` env vars | BLOCKED | **NO** — requires separate explicit approval |

### Safety Justification: `model_pricing` Seed

- `model_pricing` table exists (Phase 1 deployed) but no runtime code references it.
- `handler.py` has no `TABLE_MODEL_PRICING` env var, no `lookup_model_pricing()` function.
- `lambda.tf` does not pass `TABLE_MODEL_PRICING` to Lambda.
- Seeding is a DynamoDB `put-item` — zero runtime impact.

### Safety Justification: `principal_policy` KRW Field Seed

- DynamoDB is schemaless for non-key attributes. Adding `monthly_cost_limit_krw` and `max_monthly_cost_limit_krw` does not affect existing attributes.
- Current `handler.py` reads specific fields: `daily_input_token_limit`, `daily_output_token_limit`, `allowed_models`. It uses `policy.get()` — unknown attributes are ignored.
- `check_quota()` reads `daily_input_token_limit`/`daily_output_token_limit` only. It will not see or be affected by `monthly_cost_limit_krw`.
- This is a DynamoDB `update-item` with `SET` — additive, non-destructive.

---

## 3. Operator Execution Sequence

Execute in this exact order. Stop at any red flag.

### Step 1: Post-Apply Validation

#### 1a. Terraform Convergence

```bash
cd infra/bedrock-gateway
terraform workspace select dev
terraform plan -var-file=env/dev.tfvars
```

**Expected:**
```
No changes. Your infrastructure matches the configuration.
```

**Red flag:** Any planned changes → STOP.

#### 1b. DynamoDB Table Existence

```bash
# New tables
aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2 \
  --query 'Table.{Status:TableStatus,KeySchema:KeySchema}'

aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 \
  --query 'Table.{Status:TableStatus,KeySchema:KeySchema}'

# Existing table (must still exist)
aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-daily-usage --region us-west-2 \
  --query 'Table.TableStatus'
```

**Expected — monthly_usage:**
```json
{
    "Status": "ACTIVE",
    "KeySchema": [
        { "AttributeName": "principal_id_month", "KeyType": "HASH" },
        { "AttributeName": "model_id", "KeyType": "RANGE" }
    ]
}
```

**Expected — model_pricing:**
```json
{
    "Status": "ACTIVE",
    "KeySchema": [
        { "AttributeName": "model_id", "KeyType": "HASH" }
    ]
}
```

**Expected — daily_usage:**
```
"ACTIVE"
```

**Red flag:** `ResourceNotFoundException` on any table → STOP. If `daily_usage` missing, something destroyed it.

#### 1c. Lambda Environment Variables Unchanged

```bash
aws lambda get-function-configuration --function-name bedrock-gw-dev-gateway --region us-west-2 \
  --query 'Environment.Variables' | python3 -c "
import sys, json
vars = json.load(sys.stdin)
print('TABLE_DAILY_USAGE present:', 'TABLE_DAILY_USAGE' in vars)
print('TABLE_MONTHLY_USAGE absent:', 'TABLE_MONTHLY_USAGE' not in vars)
print('TABLE_MODEL_PRICING absent:', 'TABLE_MODEL_PRICING' not in vars)
print('DISCOVERY_MODE:', vars.get('DISCOVERY_MODE', 'NOT SET'))
"
```

**Expected:**
```
TABLE_DAILY_USAGE present: True
TABLE_MONTHLY_USAGE absent: True
TABLE_MODEL_PRICING absent: True
DISCOVERY_MODE: false
```

**Red flag:** `TABLE_MONTHLY_USAGE` or `TABLE_MODEL_PRICING` present → premature runtime cutover. STOP.

#### 1d. IAM Policy Verification

```bash
aws iam get-role-policy --role-name bedrock-gw-dev-lambda-exec --policy-name bedrock-gw-dev-dynamodb \
  | python3 -c "
import sys, json
doc = json.load(sys.stdin)['PolicyDocument']
stmts = {s['Sid']: s for s in doc['Statement']}
print('ModelPricingReadOnly exists:', 'ModelPricingReadOnly' in stmts)
non_ledger = stmts.get('DynamoDBReadWriteNonLedger', {})
resources = str(non_ledger.get('Resource', ''))
print('monthly-usage in NonLedger:', 'monthly-usage' in resources)
print('daily-usage in NonLedger:', 'daily-usage' in resources)
"
```

**Expected:**
```
ModelPricingReadOnly exists: True
monthly-usage in NonLedger: True
daily-usage in NonLedger: True
```

**Red flag:** Missing statements or resources → IAM update failed.

#### 1e. New Tables Empty

```bash
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2 --select COUNT
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --select COUNT
```

**Expected:**
```json
{ "Count": 0, "ScannedCount": 0 }
```

#### 1f. Existing Runtime Smoke Test (Optional)

```bash
awscurl --service execute-api --region us-west-2 \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"modelId": "anthropic.claude-3-haiku-20240307-v1:0", "messages": [{"role": "user", "content": [{"text": "Hello"}]}]}' \
  "$(terraform output -raw api_gateway_invoke_url)/converse"
```

If PrincipalPolicy seeded → valid Bedrock response. If not seeded → deny (policy not found). Both are correct.


---

### Step 2: Seed `model_pricing` Table

> Prerequisite: Step 1 passes (all validations green).
> Operator must verify USD prices against current AWS Bedrock pricing page before executing.
> Exchange rate below uses 1 USD = 1,450 KRW. Adjust if needed.

```bash
# Claude 3.5 Sonnet v2
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# Claude 3 Haiku
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
    "input_price_per_1k": {"N": "0.36"},
    "output_price_per_1k": {"N": "1.81"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.00025"},
    "source_usd_output_per_1k": {"N": "0.00125"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# Claude Sonnet 4
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-sonnet-4-20250514-v1:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2
```

#### Verification

```bash
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --select COUNT
# Expected: {"Count": 3, "ScannedCount": 3}

aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 \
  --query 'Items[*].{model_id: model_id.S, input: input_price_per_1k.N, output: output_price_per_1k.N}'
# Expected: 3 items with correct model IDs and KRW prices
```

**Red flag:** Count ≠ 3, or any `put-item` returns error → check table name, region, IAM permissions.

#### Rollback (if needed)

```bash
aws dynamodb delete-item --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"}}' --region us-west-2
aws dynamodb delete-item --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-3-haiku-20240307-v1:0"}}' --region us-west-2
aws dynamodb delete-item --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --key '{"model_id": {"S": "anthropic.claude-sonnet-4-20250514-v1:0"}}' --region us-west-2
```

---

### Step 3: Add KRW Fields to `principal_policy`

> Prerequisite: Step 1 passes.
> This adds new attributes to existing items. Existing attributes are untouched.

```bash
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET monthly_cost_limit_krw = :limit, max_monthly_cost_limit_krw = :max_limit' \
  --expression-attribute-values '{
    ":limit": {"N": "500000"},
    ":max_limit": {"N": "2000000"}
  }' \
  --region us-west-2
```

> For additional users, repeat with their `principal_id`. Default: 500K KRW monthly, 2M KRW hard cap.

#### Verification

```bash
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2
```

**Expected:** Item contains both old fields (`daily_input_token_limit`, `daily_output_token_limit`, `allowed_models`) AND new fields (`monthly_cost_limit_krw`: 500000, `max_monthly_cost_limit_krw`: 2000000).

**Red flag:** Old fields missing → `update-item` accidentally overwrote. This should not happen with `SET` expression (additive), but verify.

#### Rollback (if needed)

```bash
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'REMOVE monthly_cost_limit_krw, max_monthly_cost_limit_krw' \
  --region us-west-2
```

---

### Step 4: Final Verification + Evidence Collection

```bash
# 1. model_pricing count
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --select COUNT

# 2. model_pricing full scan (save output)
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 > /tmp/model_pricing_seed_evidence.json

# 3. principal_policy cgjang (save output)
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2 > /tmp/principal_policy_krw_evidence.json

# 4. monthly_usage still empty
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2 --select COUNT

# 5. Lambda env vars still unchanged
aws lambda get-function-configuration --function-name bedrock-gw-dev-gateway --region us-west-2 \
  --query 'Environment.Variables' > /tmp/lambda_env_evidence.json

# 6. Terraform still converged
cd infra/bedrock-gateway
terraform plan -var-file=env/dev.tfvars 2>&1 | tail -5
```

**Save evidence files** (`/tmp/*_evidence.json`) for Phase 2 approval request.


---

## 4. Stop / Red-Flag Conditions (Summary)

| Step | Red Flag | Action |
|------|----------|--------|
| 1a | Terraform plan shows any changes | STOP — investigate drift |
| 1b | Any table returns `ResourceNotFoundException` | STOP — table missing |
| 1b | `daily_usage` missing | CRITICAL STOP — something destroyed it |
| 1c | `TABLE_MONTHLY_USAGE` or `TABLE_MODEL_PRICING` present in Lambda env | STOP — premature cutover |
| 1d | Missing IAM statements | STOP — IAM update failed |
| 1e | New tables not empty | STOP — unexpected data |
| 2 | `put-item` error | Check table name, region, IAM. Retry or rollback. |
| 2 | Count ≠ 3 after seed | Investigate missing items |
| 3 | Old fields missing after `update-item` | STOP — verify update expression |
| 4 | `monthly_usage` not empty | STOP — unexpected writes |
| 4 | Lambda env vars changed | STOP — something modified Lambda |

---

## 5. Inconsistency Flag: `allowed_models` in Seed Data

The `phase2-seed-data-preparation.md` "Current Allowed Models" section lists 3 models including `anthropic.claude-sonnet-4-20250514-v1:0`. However, the runbook Step 5 PrincipalPolicy seed (pre-Phase 1) only seeds 2 models:

```json
"allowed_models": ["anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic.claude-3-haiku-20240307-v1:0"]
```

**Impact:** If cgjang's `allowed_models` currently only contains 2 models, the `model_pricing` seed for Claude Sonnet 4 is harmless (pricing data exists but no user can request that model). When Phase 2 activates, requests for Claude Sonnet 4 will be denied at the model allowlist check (Step 4 in handler), not at pricing lookup.

**Operator action:** Decide whether to add `anthropic.claude-sonnet-4-20250514-v1:0` to cgjang's `allowed_models` now or defer. This is a separate `update-item` on `principal_policy`:

```bash
# Optional — add Sonnet 4 to allowed_models (only if operator wants to enable it)
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET allowed_models = :models' \
  --expression-attribute-values '{
    ":models": {"L": [
      {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
      {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
      {"S": "anthropic.claude-sonnet-4-20250514-v1:0"}
    ]}
  }' \
  --region us-west-2
```

> Note: This replaces the entire `allowed_models` list. Include all desired models.

---

## 6. Minor Doc Inaccuracy Note

`phase2-seed-data-preparation.md` §2 references `check_quota()` reading `daily_token_limit`. The actual handler.py reads `daily_input_token_limit` and `daily_output_token_limit` (two separate fields). This is a documentation shorthand, not a functional issue. The safety analysis conclusion is unchanged — current handler ignores `monthly_cost_limit_krw`.

---

## 7. Phase 2 Approval-Readiness Summary (Planning Only)

> This section documents what Phase 2 requires. No code changes are made or proposed.

### 7.1 Prerequisites Checklist

| # | Prerequisite | Status |
|---|-------------|--------|
| 1 | Phase 1 IaC applied to dev | ✅ DONE (2026-03-18) |
| 2 | Post-apply validation passed | ⬜ Pending operator execution (§3 Step 1) |
| 3 | `model_pricing` table seeded | ⬜ Pending operator execution (§3 Step 2) |
| 4 | `principal_policy` KRW fields added | ⬜ Pending operator execution (§3 Step 3) |
| 5 | Evidence collected | ⬜ Pending operator execution (§3 Step 4) |
| 6 | Phase 2 plan reviewed by operator | ⬜ Pending |
| 7 | Explicit Phase 2 approval granted | ⬜ BLOCKED — requires operator approval |

### 7.2 Files Phase 2 Will Touch

| File | Change Type | Description |
|------|-------------|-------------|
| `infra/bedrock-gateway/lambda/handler.py` | Rewrite | `check_quota()` → KRW monthly. `update_daily_usage()` → `update_monthly_usage()`. Add `lookup_model_pricing()`, `estimate_cost_krw()`, `current_month_kst()`, `end_of_month_ttl_kst()`. Wire pricing lookup into main handler (step 6). |
| `infra/bedrock-gateway/lambda.tf` | Add env vars | `TABLE_MONTHLY_USAGE`, `TABLE_MODEL_PRICING`. Keep `TABLE_DAILY_USAGE` (harmless, cleanup later). |

### 7.3 Files Phase 2 Will NOT Touch

- `dynamodb.tf` — Phase 1 already added tables
- `iam.tf` — Phase 1 already added permissions
- `outputs.tf` — Phase 1 already added entries
- `variables.tf`, `locals.tf`, `main.tf`, `logs.tf` — no changes
- `gateway_approval.py` — frozen until Phase 4
- All `account-portal/`, `ansible/`, `nginx/` — non-disruption policy

### 7.4 Phase 2 Cutover Model

1. Single `terraform apply` deploys both Lambda code changes and new env vars atomically.
2. After apply, Lambda uses `TABLE_MONTHLY_USAGE` and `TABLE_MODEL_PRICING` for all new requests.
3. `daily_usage` table still exists but receives no new writes.
4. Validation: confirm `monthly_usage` receives writes, `daily_usage` receives no new writes.
5. Post-validation cleanup (separate step): remove `daily_usage` table, `TABLE_DAILY_USAGE` env var.

### 7.5 Phase 2 Key Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Lambda deploy breaks inference | High | Atomic deploy (code + env vars together). Rollback: `terraform apply` with previous code. Lambda alias rollback as emergency. |
| Pricing cache stale at cold start | Low | Cache at init, periodic refresh. Missing pricing → fail-closed (deny). |
| KST boundary logic error | Medium | Unit test `current_month_kst()` and `end_of_month_ttl_kst()` before deploy. |
| `model_pricing` missing entries | High | Fail-closed: missing pricing → deny. Seed all allowed models before Phase 2 apply. |
| `monthly_cost_limit_krw` missing from policy | High | Phase 2 code must handle missing field gracefully (default 500K or deny). Seed KRW fields before Phase 2 apply. |

### 7.6 Phase 2 handler.py Change Summary

| Current Function | Phase 2 Action | New Function |
|-----------------|----------------|--------------|
| `check_quota()` (~lines 270-310) | Full rewrite | Query `MonthlyUsage` for `<principal_id>#YYYY-MM` (KST). Sum `cost_krw`. Compare against effective limit. |
| `update_daily_usage()` (~lines 340-360) | Replace | `update_monthly_usage()` — atomic ADD `cost_krw`, `input_tokens`, `output_tokens`. PK: `<principal_id>#YYYY-MM` (KST). |
| (new) | Add | `lookup_model_pricing(model_id)` — read `ModelPricing`, cache at cold start. |
| (new) | Add | `estimate_cost_krw(input_tokens, output_tokens, pricing)` — KRW cost formula. |
| (new) | Add | `current_month_kst()` — return `YYYY-MM` in KST (UTC+9). |
| (new) | Add | `end_of_month_ttl_kst()` — return Unix epoch for EOM KST. |
| `lambda_handler()` | Modify | Insert pricing lookup (step 6) between model check and quota check. Replace `update_daily_usage()` with `update_monthly_usage()`. Add `estimated_cost_krw` to ledger. |

---

## 8. Explicit Confirmation

- ✅ No Phase 2/3/4 implementation was performed.
- ✅ No modifications to `handler.py`, `lambda.tf`, or any runtime/IaC code.
- ✅ No `terraform apply` or `ansible-playbook` executed.
- ✅ Only `docs/ai/` governance artifact created (this file).
- ✅ All operator commands in §3 are read-only checks or data-only DynamoDB operations on tables unused by current runtime.
