# Phase 2 Operator Smoke Test Runbook

> Generated: 2026-03-19
> Purpose: Exact operator steps to complete C5-C9 verification for Phase 2.
> Prerequisite: C1-C4 already verified (2026-03-18). Seed data applied.
> Blocked by: Agent environment lacks BedrockUser-cgjang credentials.

---

## 0. Overview

Phase 2 is DEPLOYED TO DEV with seed data applied. C1-C4 are verified.
Verification model upgraded to 4.5+ ACTIVE (2026-03-19): primary target `anthropic.claude-haiku-4-5-20251001-v1:0`, fallback `anthropic.claude-sonnet-4-5-20250929-v1:0`. Legacy models retained in allowlist but are non-primary.
C5-C9 require two roles:
- **cgjang side** (BedrockUser-cgjang): Run smoke test script → produces C5 evidence
- **admin side** (`--profile bedrock-gw`): Verify DynamoDB writes + Lambda logs → produces C6-C9 evidence

---

## 1. cgjang-Side: Run Smoke Test (C5)

### 1.1 Setup

```bash
# On FSx as cgjang (default profile = BedrockUser-cgjang)
mkdir -p /fsx/home/cgjang/phase2-verify
cp docs/ai/phase2-smoke-test.py /fsx/home/cgjang/phase2-verify/
cd /fsx/home/cgjang/phase2-verify
```

### 1.2 Verify Identity

```bash
aws sts get-caller-identity
# MUST show: arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/<session>
# If not → STOP. Wrong credentials.
```

### 1.3 Run Smoke Test

```bash
python3 phase2-smoke-test.py
# Script will:
#   1. Verify caller identity
#   2. Send SigV4-signed POST to https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1/converse
#   3. Print HTTP status + response body
#   4. Save evidence to ./phase2-smoke-response.json
#   5. Exit 0 if C5 passes, exit 1 if fails
```

### 1.4 Expected Output (C5 PASS)

```
[Step 4] Verdict:
  [PASS] decision == ALLOW
  [PASS] estimated_cost_krw present and > 0
  [PASS] remaining_quota.cost_krw present
  [PASS] usage.inputTokens > 0
  [PASS] usage.outputTokens > 0

  >>> C5 PASSED: Smoke test successful.
```

### 1.5 If Smoke Test Fails

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| HTTP 403 | Missing `execute-api:Invoke` on BedrockUser-cgjang for dev API | Add ARN `arn:aws:execute-api:us-west-2:107650139384:5l764dh7y9/*` to role policy |
| `"no pricing defined for model ..."` | model_id mismatch between request and `model_pricing` seed | Compare exact model_id strings |
| `"pricing lookup failed"` | Lambda can't read `model_pricing` table | Check Lambda IAM + env var `TABLE_MODEL_PRICING` |
| `"no policy defined for principal"` | `principal_policy` record missing for `107650139384#BedrockUser-cgjang` | Re-seed with `--profile bedrock-gw` |
| `"monthly cost quota exceeded"` | `monthly_cost_limit_krw` = 0 or missing | Check `principal_policy` KRW fields |
| `"model ... not in allowed list"` | Model not in `allowed_models` | Check `principal_policy` allowed_models list |
| HTTP 500 | Lambda crash | Check CloudWatch logs (§2.4) |

### 1.6 Save Evidence

```bash
# Copy evidence file for record
cat phase2-smoke-response.json
# Share this file with admin for C6-C9 verification
```

---

## 2. Admin-Side: Post-Smoke Verification (C6-C9)

All commands below use `--profile bedrock-gw` (SSO admin).

### 2.0 Prerequisite

```bash
# Ensure SSO session is active
aws sts get-caller-identity --profile bedrock-gw
# Must show SSO admin role, NOT mg-infra-admin
```

### 2.1 C6: Verify `monthly_usage` Received Writes

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --region us-west-2 \
  --profile bedrock-gw
```

**Expected:** At least 1 item with:
- `principal_id_month`: `"107650139384#BedrockUser-cgjang#2026-03"`
- `model_id`: `"anthropic.claude-haiku-4-5-20251001-v1:0"`
- `cost_krw`: positive number (> 0)
- `input_tokens`: positive number
- `output_tokens`: positive number
- `ttl`: Unix epoch ~35 days from now

**C6 PASS** if item exists with `cost_krw > 0`.
**C6 FAIL** if table is empty after successful C5.

### 2.2 C7: Verify `daily_usage` Received NO New Writes

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-daily-usage \
  --region us-west-2 \
  --filter-expression "contains(#pk, :today)" \
  --expression-attribute-names '{"#pk": "principal_id_date"}' \
  --expression-attribute-values '{":today": {"S": "2026-03-19"}}' \
  --select COUNT \
  --profile bedrock-gw
```

> Adjust date to the actual smoke test date (YYYY-MM-DD).

**C7 PASS** if `Count = 0` (no new writes from Phase 2 code).
**C7 FAIL** if `Count > 0` with today's date — old Lambda code may still be running.

If C7 fails, verify Lambda alias:
```bash
aws lambda get-alias \
  --function-name bedrock-gw-dev-gateway \
  --name live \
  --region us-west-2 \
  --profile bedrock-gw
```

### 2.3 C8: Verify `request-ledger` Includes `estimated_cost_krw`

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --region us-west-2 \
  --limit 5 \
  --profile bedrock-gw
```

**Expected:** Most recent entry contains:
- `estimated_cost_krw`: positive number (> 0)
- `decision`: `"ALLOW"`
- `principal_id`: `"107650139384#BedrockUser-cgjang"`
- `model_id`: `"anthropic.claude-haiku-4-5-20251001-v1:0"`
- `input_tokens`: positive number
- `output_tokens`: positive number

**C8 PASS** if `estimated_cost_krw` field is present and > 0 on the ALLOW entry.
**C8 FAIL** if field is missing or 0.

### 2.4 C9: Verify Lambda Logs — No Pricing/Quota Errors

```bash
# Check for errors in last 30 minutes
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 1800) * 1000))") \
  --filter-pattern "?pricing_lookup_failed ?no_pricing ?quota_check_failed ?monthly_usage_update_failed" \
  --limit 10 \
  --profile bedrock-gw
```

**C9 PASS** if no results (no pricing or quota errors).
**C9 FAIL** if any of these error patterns appear.

Optional positive signal check:
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 1800) * 1000))") \
  --filter-pattern "estimated_cost_krw" \
  --limit 5 \
  --profile bedrock-gw
# Expected: log entries showing estimated_cost_krw values from the smoke test
```

---

## 3. Evidence Checklist

| # | Criterion | Evidence Source | Pass Condition |
|---|-----------|---------------|----------------|
| C5 | Smoke test ALLOW + cost_krw | `phase2-smoke-response.json` | `decision=ALLOW`, `estimated_cost_krw > 0` |
| C6 | monthly_usage write | DynamoDB scan (§2.1) | Item with `cost_krw > 0` for cgjang 2026-03 |
| C7 | daily_usage no new writes | DynamoDB scan (§2.2) | `Count = 0` for smoke test date |
| C8 | request-ledger cost_krw | DynamoDB scan (§2.3) | `estimated_cost_krw > 0` on ALLOW entry |
| C9 | No Lambda pricing errors | CloudWatch logs (§2.4) | Zero matches for error patterns |

---

## 4. Red Flags — Stop Conditions

| Condition | Severity | Action |
|-----------|----------|--------|
| C5 returns DENY on valid request | Blocker | Diagnose per §1.5 table. Do not proceed to C6-C9. |
| C6: monthly_usage empty after C5 PASS | Critical | Lambda code path broken. Check env vars, Lambda version. |
| C7: daily_usage has NEW writes | Critical | Old code running. Check Lambda alias/version. |
| C8: estimated_cost_krw missing or 0 | Critical | Cost estimation pipeline broken. Check handler.py deployment. |
| C9: pricing_lookup_failed in logs | Critical | DynamoDB read failure. Check IAM for model_pricing table. |

---

## 5. After All C5-C9 Pass

Report the following to the agent:
1. `phase2-smoke-response.json` content (or key fields: decision, estimated_cost_krw, remaining_quota, usage)
2. `monthly_usage` scan output (item count, cost_krw value)
3. `daily_usage` scan count for smoke test date
4. `request-ledger` scan output (estimated_cost_krw value)
5. Lambda logs error check result (zero matches or specific errors)

The agent will then update status markers in governance docs to "VERIFIED IN DEV".

---

## 6. After Any C5-C9 Fail

Report the exact failure:
- Which criterion failed (C5/C6/C7/C8/C9)
- Exact error message or unexpected output
- Lambda log excerpts if relevant

Phase 2 status remains "DEPLOYED TO DEV — NOT YET VERIFIED" until all C5-C9 pass.

---

## 7. Boundary Statement

This runbook covers C5-C9 verification ONLY. No Phase 3, Phase 4, daily_usage removal, or new feature work.
