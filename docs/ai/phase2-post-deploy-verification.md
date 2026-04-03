# Phase 2 Post-Deploy Verification & Evidence Collection

> Generated: 2026-03-18. **ALL CRITERIA VERIFIED: 2026-03-20. CLOSEOUT COMPLETE.**
> Purpose: Verify Phase 2 Lambda deployment, seed state, and runtime behavior. Collect evidence for Phase 2 completion.
> Dev API: `https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1` (API ID: `5l764dh7y9`)
> Prerequisite: Phase 2 `terraform apply` COMPLETE (2026-03-18). Lambda env vars confirmed.
> **Final report: `docs/ai/phase2-dev-validation-report.md`**
> **Final cgjang evidence**: request_id `d01542b3-61dc-4e96-a423-583954d031b4`, model `us.anthropic.claude-haiku-4-5-20251001-v1:0`, HTTP 200, decision ALLOW, estimated_cost_krw 0.0551.

---

## 0. Completion Criteria

Phase 2 can be marked COMPLETE only when ALL of the following are verified:

| # | Criterion | Section |
|---|-----------|---------|
| C1 | `model_pricing` table seeded with ≥3 models | §1 |
| C2 | `principal_policy` has `monthly_cost_limit_krw` + `max_monthly_cost_limit_krw` | §2 |
| C3 | Lambda env vars include `TABLE_MONTHLY_USAGE` + `TABLE_MODEL_PRICING` | §3 |
| C4 | DynamoDB tables `monthly_usage` + `model_pricing` exist and ACTIVE | §4 |
| C5 | Smoke test returns `"decision": "ALLOW"` with `estimated_cost_krw` | §5 | **PASS (2026-03-20)** — HTTP 200, decision ALLOW, estimated_cost_krw 0.0551 |
| C6 | `monthly_usage` table receives writes after smoke test | §6 | **PASS (2026-03-20)** — remaining_quota.cost_krw=499999.7796 proves monthly_usage written (0.2204 KRW accumulated) |
| C7 | `daily_usage` table receives NO new writes after smoke test | §7 | **PASS (2026-03-20)** — Count=0, Items=[] |
| C8 | `request-ledger` entries include `estimated_cost_krw` field | §8 | **PASS (2026-03-20)** — request_id d01542b3, estimated_cost_krw=0.0551, input_tokens=13, output_tokens=5 |
| C9 | Lambda logs show no pricing/quota errors | §9 | **PASS (2026-03-20)** — request_received, principal_identified, normal END/REPORT, no errors |

---

## 1. Verify `model_pricing` Seed State

```bash
# Check item count
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --region us-west-2 \
  --select COUNT
# Expected: {"Count": 5, "ScannedCount": 5}
# (3 legacy + 2 ACTIVE 4.5+ models)
# If Count = 0 → seed is MISSING. Go to §1.1.
# If Count > 0 but < 5 → partial seed. Go to §1.1 for missing models.
```

```bash
# Full scan — verify all 3 models and pricing values
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --region us-west-2
# Expected: 5 items with model_id values:
#   PRIMARY (ACTIVE 4.5+, verification targets — inference profile IDs):
#   - us.anthropic.claude-haiku-4-5-20251001-v1:0
#   - us.anthropic.claude-sonnet-4-5-20250929-v1:0
#   LEGACY (retained for reference, non-primary):
#   - anthropic.claude-3-5-sonnet-20241022-v2:0
#   - anthropic.claude-3-haiku-20240307-v1:0
#   - anthropic.claude-sonnet-4-20250514-v1:0
# Each must have: input_price_per_1k (N), output_price_per_1k (N)
```

### 1.1 If Seed Missing — Apply It

If `model_pricing` is empty or incomplete, run the seed commands from `docs/ai/phase2-operator-execution-package.md` §2.1. Copy-pasted here for convenience:

```bash
# --- PRIMARY (ACTIVE 4.5+) ---

# Claude Haiku 4.5 (primary verification target, cheapest 4.5+, inference profile ID)
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
    "notes": {"S": "ACTIVE 4.5+ model. Primary verification target. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# Claude Sonnet 4.5 (fallback verification target, inference profile ID)
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
    "notes": {"S": "ACTIVE 4.5+ model. Fallback verification target. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# --- LEGACY (retained for reference, non-primary) ---

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
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
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
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
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
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2
```

Re-run the verification scan after seeding.

---

## 2. Verify `principal_policy` KRW Fields

```bash
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2
# Expected: item contains:
#   monthly_cost_limit_krw: {"N": "500000"}
#   max_monthly_cost_limit_krw: {"N": "2000000"}
#   allowed_models: (list with ≥2 models)
#   daily_input_token_limit, daily_output_token_limit: (legacy, still present)
```

### 2.1 If KRW Fields Missing — Apply Them

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

Re-run the get-item verification after update.

---

## 3. Verify Lambda Environment Variables

```bash
aws lambda get-function-configuration \
  --function-name bedrock-gw-dev-gateway \
  --region us-west-2 \
  | python3 -c "
import sys, json
vars = json.load(sys.stdin)['Environment']['Variables']
required = {
  'TABLE_MONTHLY_USAGE': 'bedrock-gw-dev-us-west-2-monthly-usage',
  'TABLE_MODEL_PRICING': 'bedrock-gw-dev-us-west-2-model-pricing',
  'TABLE_DAILY_USAGE': 'bedrock-gw-dev-us-west-2-daily-usage',
  'TABLE_PRINCIPAL_POLICY': 'bedrock-gw-dev-us-west-2-principal-policy',
  'TABLE_REQUEST_LEDGER': 'bedrock-gw-dev-us-west-2-request-ledger',
}
for key, expected in required.items():
    actual = vars.get(key, 'MISSING')
    status = '✅' if actual == expected else '❌'
    print(f'{status} {key}: {actual}')
print()
print(f'Total env vars: {len(vars)}')
"
# Expected: all ✅, TABLE_MONTHLY_USAGE and TABLE_MODEL_PRICING present with correct values
```

---

## 4. Verify DynamoDB Table Existence

```bash
for table in monthly-usage model-pricing daily-usage principal-policy request-ledger; do
  status=$(aws dynamodb describe-table \
    --table-name "bedrock-gw-dev-us-west-2-${table}" \
    --region us-west-2 \
    --query 'Table.TableStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")
  echo "${table}: ${status}"
done
# Expected: all ACTIVE
# Critical: monthly-usage and model-pricing must be ACTIVE (Phase 1 created them)
```

---

## 5. Smoke Test — SigV4 POST

### 5.1 Credential Verification

```bash
aws sts get-caller-identity
# Must show: arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/<session>
# If not → switch to BedrockUser-cgjang credentials before proceeding
```

### 5.2 Invoke Gateway

**Option A: Python script (recommended — no awscurl dependency):**
```bash
# From FSx with BedrockUser-cgjang credentials:
python3 docs/ai/phase2-smoke-test.py
# Saves evidence to ./phase2-smoke-response.json
# Exit 0 = C5 PASS, exit 1 = C5 FAIL
```

**Option B: awscurl (if available):**
```bash
DEV_INVOKE_URL="https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1"

awscurl --service execute-api --region us-west-2 \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "messages": [{"role": "user", "content": [{"text": "Say hello in one word."}]}]
  }' \
  "${DEV_INVOKE_URL}/converse"
```

### 5.3 Expected Response

```json
{
  "decision": "ALLOW",
  "output": { "message": { "role": "assistant", "content": [...] } },
  "stopReason": "end_turn",
  "usage": { "inputTokens": ..., "outputTokens": ... },
  "estimated_cost_krw": <positive integer>,
  "remaining_quota": {
    "cost_krw": <number close to 500000>
  },
  "request_id": "<uuid>"
}
```

Key fields to verify:
- `decision` = `"ALLOW"` (not `"DENY"`)
- `estimated_cost_krw` is present and > 0
- `remaining_quota.cost_krw` is present and < 500000 (reduced by estimated_cost_krw)
- `usage.inputTokens` and `usage.outputTokens` are present and > 0

### 5.4 If Smoke Test Fails

| Error | Cause | Fix |
|-------|-------|-----|
| `"pricing lookup failed"` | `model_pricing` table empty or Lambda can't read it | Check §1 seed, check IAM |
| `"no pricing defined for model ..."` | model_id string mismatch between request and seed | Compare exact model_id strings |
| `"monthly cost quota exceeded"` | `monthly_cost_limit_krw` = 0 or missing | Check §2 KRW fields |
| `"policy not found"` | `principal_policy` record missing | Check principal_id format |
| `"quota check failed"` | `monthly_usage` table inaccessible | Check Lambda env var `TABLE_MONTHLY_USAGE` |
| HTTP 403 | SigV4 auth failure or missing `execute-api:Invoke` | Check caller identity and IAM policy |
| HTTP 500 | Lambda crash | Check CloudWatch logs (§9) |

---

## 6. Verify `monthly_usage` Received Writes

Run this AFTER the smoke test in §5.

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --region us-west-2
# Expected: at least 1 item with:
#   principal_id_month: "107650139384#BedrockUser-cgjang#2026-03"
#   model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0"
#   cost_krw: <positive number matching estimated_cost_krw from smoke test>
#   input_tokens: <positive number>
#   output_tokens: <positive number>
#   ttl: <unix epoch ~35 days from now>
```

If no items found:
- Lambda may not have the `TABLE_MONTHLY_USAGE` env var → check §3
- Lambda may be running old code → check Lambda version/alias
- `update_monthly_usage()` may have failed silently → check CloudWatch logs (§9)

---

## 7. Verify `daily_usage` Received NO New Writes

Run this AFTER the smoke test in §5.

```bash
# Check for any writes with today's date
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-daily-usage \
  --region us-west-2 \
  --filter-expression "contains(#pk, :today)" \
  --expression-attribute-names '{"#pk": "principal_id_date"}' \
  --expression-attribute-values '{":today": {"S": "2026-03-18"}}' \
  --select COUNT
# Expected: Count = 0 (no new writes from Phase 2 code)
# Note: entries from BEFORE Phase 2 deploy may exist — that's fine.
# Only new writes (after deploy timestamp) indicate a problem.
```

If new writes found in `daily_usage`:
- Lambda may be running old code (pre-Phase-2) → check Lambda function version
- Check if `aws_lambda_alias.live` points to the latest version

```bash
# Verify Lambda alias points to latest version
aws lambda get-alias \
  --function-name bedrock-gw-dev-gateway \
  --name live \
  --region us-west-2
# Compare FunctionVersion with:
aws lambda get-function-configuration \
  --function-name bedrock-gw-dev-gateway \
  --region us-west-2 \
  --query 'Version'
# They should match (alias tracks latest published version)
```

---

## 8. Verify `request-ledger` Includes `estimated_cost_krw`

Run this AFTER the smoke test in §5.

```bash
# Get most recent ledger entry
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --region us-west-2 \
  --limit 5
# Expected: entries from the smoke test contain:
#   estimated_cost_krw: <positive number>
#   decision: "ALLOW"
#   input_tokens: <positive number>
#   output_tokens: <positive number>
#   principal_id: "107650139384#BedrockUser-cgjang"
#   model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0"
```

Verify `estimated_cost_krw` is present and > 0. If the field is missing or 0 on an ALLOW entry, the cost estimation pipeline is broken.

---

## 9. Verify Lambda Logs — No Pricing/Quota Errors

```bash
# Check last 10 minutes of logs for errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 600) * 1000))") \
  --filter-pattern "ERROR" \
  --limit 20

# Specifically check for pricing/quota failures
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 600) * 1000))") \
  --filter-pattern "?pricing_lookup_failed ?no_pricing ?quota_check_failed ?monthly_usage_update_failed" \
  --limit 10
# Expected: no results (no pricing or quota errors)
```

```bash
# Check for successful request flow (positive signal)
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 600) * 1000))") \
  --filter-pattern "estimated_cost_krw" \
  --limit 5
# Expected: log entries showing estimated_cost_krw values from the smoke test
```

---

## 10. Red Flags / Stop Conditions

| Condition | Severity | Action |
|-----------|----------|--------|
| `model_pricing` scan returns 0 items | Blocker | Seed required before any smoke test. See §1.1. |
| `principal_policy` missing KRW fields | Blocker | Update required before smoke test. See §2.1. |
| Lambda missing `TABLE_MONTHLY_USAGE` env var | Blocker | Redeploy required. `terraform apply` may not have completed. |
| Smoke test returns any DENY on valid request | Blocker | Diagnose per §5.4 table. Do not proceed until resolved. |
| `monthly_usage` empty after successful smoke test | Critical | Lambda code path broken. Check logs, env vars, Lambda version. |
| `daily_usage` has NEW writes after smoke test | Critical | Old code running. Check Lambda alias/version. |
| `request-ledger` missing `estimated_cost_krw` | Critical | Cost estimation pipeline broken. Check handler.py deployment. |
| Lambda logs show `pricing_lookup_failed` | Critical | DynamoDB read failure. Check IAM permissions for `model_pricing` table. |
| Lambda logs show `monthly_usage_update_failed` | Warning | Non-fatal (response still returned) but usage tracking broken. Check IAM. |
| `estimated_cost_krw` = 0 on ALLOW entry | Warning | Pricing values may be 0 in seed data. Check `model_pricing` values. |

---

## 11. Evidence Files to Capture

Save the following command outputs as evidence for Phase 2 completion record. Recommended location: `docs/ai/discovery/phase2-evidence/` or inline in a completion summary.

| # | Evidence | Command Section | Filename Suggestion |
|---|----------|-----------------|---------------------|
| E1 | `model_pricing` scan (full) | §1 | `model-pricing-scan.json` |
| E2 | `principal_policy` get-item (cgjang) | §2 | `principal-policy-cgjang.json` |
| E3 | Lambda env var check output | §3 | `lambda-env-vars.txt` |
| E4 | DynamoDB table status check | §4 | `table-status.txt` |
| E5 | Smoke test response JSON | §5.2 | `smoke-test-response.json` |
| E6 | `monthly_usage` scan (post-smoke) | §6 | `monthly-usage-scan.json` |
| E7 | `daily_usage` scan (post-smoke, count) | §7 | `daily-usage-count.txt` |
| E8 | `request-ledger` scan (post-smoke) | §8 | `request-ledger-scan.json` |
| E9 | Lambda logs (errors check) | §9 | `lambda-logs-errors.txt` |
| E10 | Lambda logs (positive signal) | §9 | `lambda-logs-cost.txt` |
| E11 | `aws sts get-caller-identity` | §5.1 | `caller-identity.json` |

---

## 12. Recommended Execution Order

1. **Credential setup** — SSO admin for DynamoDB checks, then BedrockUser-cgjang for smoke test
2. **§3** — Lambda env vars (quick sanity check, no seed dependency)
3. **§4** — DynamoDB table existence (quick sanity check)
4. **§1** — `model_pricing` seed verification → apply if missing (§1.1)
5. **§2** — `principal_policy` KRW fields verification → apply if missing (§2.1)
6. **§5** — Smoke test (requires seed data present)
7. **§6** — `monthly_usage` write verification (requires smoke test)
8. **§7** — `daily_usage` no-new-writes verification (requires smoke test)
9. **§8** — `request-ledger` `estimated_cost_krw` verification (requires smoke test)
10. **§9** — Lambda log inspection (requires smoke test)
11. **§11** — Save all evidence files

---

## 13. After All Criteria Pass

When all 9 criteria (C1-C9) are verified with evidence:

1. Update `docs/ai/todo.md` — Phase 2 line: change status to "VERIFIED"
2. Update `.kiro/specs/bedrock-access-gateway/tasks.md` — Phase 2 header: "DEPLOYED AND VERIFIED"
3. Update `docs/ai/runbook.md` — Remove "SEED STATUS UNKNOWN. RUNTIME VERIFICATION PENDING."
4. Update `docs/ai/validation_plan.md` — Same
5. Update `docs/ai/phase2-operator-execution-package.md` — Mark all milestones ✅

Phase 2 is then COMPLETE. Phase 3 (approval ladder) requires separate approval.

---

## 14. Boundary Statement

This document covers Phase 2 verification ONLY. No Phase 3 (approval ladder) or Phase 4 (admin API/frontend) work is authorized. No `daily_usage` table removal is authorized. No existing infrastructure modifications are authorized.
