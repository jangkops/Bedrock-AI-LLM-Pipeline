# Phase 2 Operator Execution Package

> Generated: 2026-03-18. Updated: 2026-03-19.
> Purpose: Exact copy-paste commands for completing Phase 2 deployment.
> Current state: Phase 2 Lambda DEPLOYED TO DEV (2026-03-18). Seed data applied. Smoke test pending.
> Prerequisite: Phase 1 APPLIED TO DEV (2026-03-18) — `monthly_usage` + `model_pricing` tables exist.
> Smoke test: See `docs/ai/phase2-smoke-test.py` (Python, no awscurl dependency) and `docs/ai/phase2-operator-smoke-test-runbook.md` for C5-C9 operator steps.

---

## 0. True Phase 2 Status

| Milestone | Status |
|-----------|--------|
| Phase 2 code in repo (`handler.py`, `lambda.tf`) | ✅ Done (2026-03-18) |
| Syntax/validate checks | ✅ Pass |
| `model_pricing` table seeded | ✅ Done (2026-03-18) — 3 models, Count=3 verified |
| `principal_policy` KRW fields added | ✅ Done (2026-03-18) — cgjang: 500000/2000000, 3 allowed_models |
| `terraform apply` (deploy Lambda) | ✅ Done (2026-03-18) — API `5l764dh7y9`, env vars confirmed |
| Lambda env vars verified (C3) | ✅ Done — all 5 critical vars correct, 14 total |
| DynamoDB tables verified (C4) | ✅ Done — all 10 ACTIVE |
| Post-deploy smoke test | ❌ Pending — use `docs/ai/phase2-smoke-test.py` (Python SigV4, no awscurl). See `docs/ai/phase2-operator-smoke-test-runbook.md` |
| Phase 2 COMPLETE | ❌ Not until smoke test (C5-C9) passes |

---

## 1. Credential Setup — SSO Admin (NOT mg-infra-admin)

`mg-infra-admin` lacks DynamoDB DescribeTable permissions. All commands below must use the SSO admin role.

```bash
# Clear any conflicting env credentials
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN

# SSO login
aws sso login --profile bedrock-gw

# Verify identity — MUST show SSO admin role, NOT mg-infra-admin
aws sts get-caller-identity --profile bedrock-gw
# Expected output pattern:
# {
#   "UserId": "...",
#   "Account": "107650139384",
#   "Arn": "arn:aws:sts::107650139384:assumed-role/<SSO-admin-role>/..."
# }
# RED FLAG: If Arn contains "mg-infra-admin" → STOP. Wrong credentials.

export AWS_PROFILE=bedrock-gw
```

---

## 2. Seed Data (BEFORE deploy)

Seed order matters. `model_pricing` first, then `principal_policy` KRW fields.

### 2.1 Seed `model_pricing` (3 models)

Models must match what can appear in `allowed_models` in `principal_policy`. Current known models:
- `anthropic.claude-3-5-sonnet-20241022-v2:0`
- `anthropic.claude-3-haiku-20240307-v1:0`
- `anthropic.claude-sonnet-4-20250514-v1:0`

> KRW rates below use 1 USD = 1,450 KRW. Adjust if exchange rate differs.
> Verify USD prices against current AWS Bedrock pricing page before seeding.

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

**Verify seed:**
```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --region us-west-2 \
  --select COUNT
# Expected: {"Count": 3, "ScannedCount": 3}

aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --region us-west-2
# Verify: all 3 model_id values present, input_price_per_1k and output_price_per_1k correct
```

### 2.2 Update `principal_policy` with KRW fields

```bash
# Add KRW fields to cgjang's existing policy record
# This is an UPDATE (adds new attributes), not a PUT (would overwrite)
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

**Verify update:**
```bash
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2
# Expected: item contains BOTH:
#   - Old fields: daily_input_token_limit, daily_output_token_limit, allowed_models
#   - New fields: monthly_cost_limit_krw = 500000, max_monthly_cost_limit_krw = 2000000
```

### 2.3 Model-list consistency check

The `allowed_models` in cgjang's `principal_policy` may currently contain only 2 models (Sonnet v2 + Haiku), while `model_pricing` has 3 (includes Claude Sonnet 4).

This is safe — pricing data for Claude Sonnet 4 exists but if cgjang's `allowed_models` doesn't include it, requests for that model are denied at the model allowlist check (Step 4 in handler), before pricing lookup.

**Optional: Add Claude Sonnet 4 to cgjang's allowed_models:**
```bash
# Only run this if you want cgjang to access Claude Sonnet 4
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

---

## 3. Deploy (terraform apply)

### 3.1 Plan

```bash
cd infra/bedrock-gateway
terraform workspace select dev
terraform plan -var-file=env/dev.tfvars
```

**Expected safe plan:**
```
~ aws_lambda_function.gateway    (update in-place — code hash + 2 new env vars)
~ aws_lambda_alias.live          (update in-place — new function version)
```

**Red flags — STOP if plan shows ANY of:**
- Any `destroy` action (especially DynamoDB tables)
- Any change to `aws_dynamodb_table.*` resources
- Any change to `aws_api_gateway_*` resources
- Any change to `aws_iam_role_policy.*` (IAM was already updated in Phase 1)
- Any change to `aws_cloudwatch_log_group.*`
- More than 2 resources changing (Lambda function + alias only)

### 3.2 Apply

```bash
terraform apply -var-file=env/dev.tfvars
```

Review the plan output one more time before typing `yes`.

---

## 4. Post-Deploy Verification

### 4.1 Lambda env vars check

```bash
aws lambda get-function-configuration \
  --function-name bedrock-gw-dev-gateway \
  --region us-west-2 \
  | python3 -c "
import sys, json
vars = json.load(sys.stdin)['Environment']['Variables']
checks = {
  'TABLE_MONTHLY_USAGE present': 'TABLE_MONTHLY_USAGE' in vars,
  'TABLE_MODEL_PRICING present': 'TABLE_MODEL_PRICING' in vars,
  'TABLE_DAILY_USAGE still present': 'TABLE_DAILY_USAGE' in vars,
  'MONTHLY_USAGE value': vars.get('TABLE_MONTHLY_USAGE', 'MISSING'),
  'MODEL_PRICING value': vars.get('TABLE_MODEL_PRICING', 'MISSING'),
}
for k, v in checks.items():
    print(f'{k}: {v}')
"
# Expected:
#   TABLE_MONTHLY_USAGE present: True
#   TABLE_MODEL_PRICING present: True
#   TABLE_DAILY_USAGE still present: True
#   MONTHLY_USAGE value: bedrock-gw-dev-us-west-2-monthly-usage
#   MODEL_PRICING value: bedrock-gw-dev-us-west-2-model-pricing
```

### 4.2 Smoke test (SigV4 POST)

**Option A: Python script (recommended — no awscurl dependency):**
```bash
# From FSx with BedrockUser-cgjang credentials:
mkdir -p /fsx/home/cgjang/phase2-verify
cp docs/ai/phase2-smoke-test.py /fsx/home/cgjang/phase2-verify/
cd /fsx/home/cgjang/phase2-verify
python3 phase2-smoke-test.py
# Saves evidence to ./phase2-smoke-response.json
# Exit 0 = C5 PASS, exit 1 = C5 FAIL
```

**Option B: awscurl (if available):**
```bash
# From FSx with BedrockUser-cgjang credentials:
aws sts get-caller-identity
# Must show: assumed-role/BedrockUser-cgjang/<session>

# Invoke gateway
DEV_INVOKE_URL=$(cd infra/bedrock-gateway && terraform output -raw api_gateway_invoke_url)

awscurl --service execute-api --region us-west-2 \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "modelId": "anthropic.claude-3-haiku-20240307-v1:0",
    "messages": [{"role": "user", "content": [{"text": "Say hello in one word."}]}]
  }' \
  "${DEV_INVOKE_URL}/converse"

# Expected: JSON response with:
#   "decision": "ALLOW"
#   "estimated_cost_krw": <small integer>
#   "remaining_quota": {"cost_krw": <number close to 500000>}
#   "output": { ... Bedrock response ... }
```

### 4.3 Verify `monthly_usage` received a write

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --region us-west-2
# Expected: at least 1 item with:
#   principal_id_month: "107650139384#BedrockUser-cgjang#2026-03"
#   model_id: "anthropic.claude-3-haiku-20240307-v1:0"
#   cost_krw: <positive number>
#   input_tokens: <positive number>
#   output_tokens: <positive number>
```

### 4.4 Verify `daily_usage` received NO new writes

```bash
# Check daily_usage for today's date — should have NO new entries from the smoke test
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-daily-usage \
  --region us-west-2 \
  --filter-expression "contains(#pk, :today)" \
  --expression-attribute-names '{"#pk": "principal_id_date"}' \
  --expression-attribute-values '{":today": {"S": "2026-03-18"}}' \
  --select COUNT
# Expected: Count = 0 (or same as before smoke test — no NEW writes)
# Note: old entries from before Phase 2 may exist. Only check for new writes.
```

### 4.5 Verify `RequestLedger` includes `estimated_cost_krw`

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --region us-west-2 \
  --limit 1
# Expected: most recent entry contains "estimated_cost_krw" field with a positive number
```

### 4.6 Verify `model_pricing` lookup works (Lambda logs)

```bash
# Check recent Lambda logs for pricing lookup
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 300) * 1000))") \
  --filter-pattern "pricing" \
  --limit 5
# Expected: no "pricing_lookup_failed" or "no_pricing" errors
# If you see these errors, check model_pricing seed data
```

---

## 5. Red Flags / Stop Conditions

| Condition | Action |
|-----------|--------|
| `terraform plan` shows destroys | STOP. Do not apply. Review plan output. |
| `terraform plan` shows >2 resource changes | STOP. Expected: Lambda function + alias only. |
| `terraform apply` fails | Check error. Do NOT retry blindly. |
| Smoke test returns `"pricing lookup failed"` | `model_pricing` seed is missing or model_id mismatch. Check seed. |
| Smoke test returns `"no pricing defined for model"` | model_id in request doesn't match any `model_pricing` entry. Check exact string. |
| Smoke test returns `"monthly cost quota exceeded"` on first call | `monthly_cost_limit_krw` not set in `principal_policy`, or set to 0. Check seed. |
| Smoke test returns `"policy not found"` | `principal_policy` record missing for this principal_id. Check seed. |
| `monthly_usage` has no writes after smoke test | Lambda may not have the new env vars. Check §4.1. |
| `daily_usage` has NEW writes after smoke test | Phase 2 code not deployed correctly. Lambda may be running old code. Check Lambda version. |

---

## 6. Rollback

If Phase 2 deploy causes issues:

```bash
cd infra/bedrock-gateway
git checkout lambda/handler.py lambda.tf
terraform apply -var-file=env/dev.tfvars
```

This reverts Lambda to the pre-Phase-2 code (token-count daily quota). `model_pricing` seed data and `principal_policy` KRW fields remain (harmless — old code ignores them).

---

## 7. Evidence to Capture

Save the following outputs for the Phase 2 completion record:

1. `aws sts get-caller-identity` output (proves SSO admin credentials used)
2. `terraform plan` output (proves expected 2-resource change)
3. `terraform apply` output (proves successful deploy)
4. Lambda env var check output (§4.1)
5. Smoke test response JSON (§4.2)
6. `monthly_usage` scan output (§4.3)
7. `daily_usage` scan output (§4.4)
8. `request-ledger` scan output (§4.5)

---

## 8. Boundary Statement

**Phase 2 is "implemented in repo" until ALL of the following are true:**
1. `model_pricing` table seeded with 3 models
2. `principal_policy` updated with `monthly_cost_limit_krw` and `max_monthly_cost_limit_krw`
3. `terraform apply` executed successfully with SSO admin credentials
4. Lambda env vars confirmed to include `TABLE_MONTHLY_USAGE` and `TABLE_MODEL_PRICING`
5. Smoke test returns `"decision": "ALLOW"` with `estimated_cost_krw` in response
6. `monthly_usage` table receives writes
7. `daily_usage` table receives no new writes

**Only after all 7 conditions are verified can Phase 2 be marked COMPLETE.**

**No Phase 3 (approval ladder) or Phase 4 (admin API/frontend) work is authorized in this step.**
