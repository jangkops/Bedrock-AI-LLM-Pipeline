# Phase 2: Current-State Reconciliation & cgjang Live-Usage Validation Plan

> Generated: 2026-03-20. **VERIFIED: 2026-03-20.**
> Purpose: (A) Reconcile exact current state of all Phase 2 components, (B) provide operator-ready validation plan for cgjang live-usage test
> Canonical validation principal: **cgjang** (only)
> shlee is excluded from ALL validation — deliberate exception, uses direct Bedrock
>
> **SMOKE TEST RESULT (2026-03-20):** HTTP 200, `decision: ALLOW`, `estimated_cost_krw: 0.0551`, `remaining_quota.cost_krw: 499999.7796`, `inputTokens: 13`, `outputTokens: 5`. Model: `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Request ID: `d01542b3-61dc-4e96-a423-583954d031b4`.
>
> **PHASE 2 DEV VALIDATION: COMPLETE (2026-03-20).** All C5-C9 PASS. Final report: `docs/ai/phase2-dev-validation-report.md`.

---

## Part 1: Current-State Reconciliation

### 1.1 Infrastructure State

| Component | State | Evidence |
|-----------|-------|----------|
| API Gateway | DEPLOYED, API ID `5l764dh7y9`, stage `v1` | terraform output |
| Lambda | DEPLOYED, `bedrock-gw-dev-gateway` | terraform output |
| DynamoDB (10 tables) | ALL ACTIVE | Phase 1 + Phase 2 apply |
| IAM Lambda exec role | `bedrock-gw-dev-lambda-exec` — `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` | iam.tf, IAM fix applied 2026-03-19 |
| CloudWatch log group | `/aws/lambda/bedrock-gw-dev-gateway` | terraform |

### 1.2 Seed Data State

| Table | State | Details |
|-------|-------|---------|
| `model_pricing` | SEEDED (5 items) | 2 ACTIVE `us.` prefix (Haiku 4.5, Sonnet 4.5) + 3 legacy |
| `principal_policy` (cgjang) | SEEDED | `monthly_cost_limit_krw`=500000, `max_monthly_cost_limit_krw`=2000000, 5 `allowed_models` including `us.` prefix models |

### 1.3 Code State (handler.py)

| Fix | State | Details |
|-----|-------|---------|
| KRW cost-based quota rewrite | DEPLOYED (2026-03-18) | Full pipeline: pricing → cost estimation → monthly usage → ledger |
| Inference profile fix | DEPLOYED (2026-03-19) | `model_pricing` + `principal_policy` keys use `us.` prefix IDs |
| Cost precision fix (`float()`) | DEPLOYED AND VERIFIED (2026-03-20) | `int()` → `float()` at 5 locations. Prevents sub-1 KRW truncation to 0. **DynamoDB Decimal-vs-float ledger defect FIXED (2026-03-20):** ledger_entry `estimated_cost_krw` changed from `float(estimated_cost_krw)` to raw `Decimal` — DynamoDB rejects Python `float`, requires `Decimal`. Response body retains `float()` for JSON serialization (correct). **Smoke test confirmed: `estimated_cost_krw: 0.0551`.** |

### 1.4 Bypass Prevention State

| Role | DenyDirectBedrockInference | Status |
|------|---------------------------|--------|
| BedrockUser-cgjang | ✅ Applied | Enforced |
| BedrockUser-hermee | ✅ Applied | Enforced |
| BedrockUser-jwlee | ✅ Applied | Enforced |
| BedrockUser-sbkim | ✅ Applied | Enforced |
| BedrockUser-shlee | ❌ Removed (2026-03-19) | Exception — uses direct Bedrock |
| BedrockUser-shlee2 | ✅ Applied | Enforced |

### 1.5 Pending Items

| # | Item | Blocker | Priority |
|---|------|---------|----------|
| P1 | Deploy cost-precision + Decimal ledger fix to Lambda | — | **DONE (2026-03-20)** |
| P2 | Run cgjang live-usage validation test | — | **DONE (2026-03-20) — ALL PASS. C5-C9 verified.** |
| P3 | Collect C5-C9 evidence per `phase2-post-deploy-verification.md` | — | **DONE (2026-03-20) — ALL PASS. See `docs/ai/phase2-dev-validation-report.md`. Phase 2 dev validation COMPLETE.** |

---

## Part 2: Cost-Precision Deploy Path

### 2.0 Credential Normalization (run first, every session)

```bash
unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN; unset AWS_SECURITY_TOKEN
export AWS_PROFILE=bedrock-gw; export AWS_REGION=us-west-2; export AWS_DEFAULT_REGION=us-west-2; export AWS_PAGER=""
aws sts get-caller-identity
# Expected: arn:aws:sts::107650139384:assumed-role/AWSReservedSSO_AdministratorAccess_2aad224aa92c3bbe/changgeun.jang@mogam.re.kr
```

If SSO expired:
```bash
aws sso login --profile bedrock-gw
```

### 2.1 Terraform Plan

```bash
cd infra/bedrock-gateway
terraform workspace select dev
terraform plan -var-file=env/dev.tfvars
```

**Expected plan output:**
```
~ aws_lambda_function.gateway    (update — source_code_hash changed)
~ aws_lambda_alias.live          (update — function_version changed)
```

**Red flags — STOP if:**
- Any DynamoDB table changes
- Any API Gateway changes
- Any IAM changes
- Any destroy actions
- More than 2 resource updates

### 2.2 Terraform Apply

```bash
terraform apply -var-file=env/dev.tfvars
```

### 2.3 Post-Apply Quick Check

```bash
# Verify Lambda was updated (check last modified timestamp)
aws lambda get-function-configuration \
  --function-name bedrock-gw-dev-gateway \
  --region us-west-2 \
  --query '{Version: Version, LastModified: LastModified, CodeSha256: CodeSha256}'
```

---

## Part 3: cgjang Live-Usage Validation Test

> **Prerequisites**: Part 2 (cost-precision deploy) MUST be complete before running this test.
> All commands in this section run as **BedrockUser-cgjang** from FSx.

### 3.0 Test Design

| Parameter | Value |
|-----------|-------|
| Principal | `107650139384#BedrockUser-cgjang` |
| Primary model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` (cheapest, fastest) |
| Number of requests | 3 sequential |
| Time window | ~2-3 minutes |
| Expected per-request cost | ~0.01-0.10 KRW (Haiku 4.5, short prompt) |
| Pass criteria | All 3 return `decision: ALLOW`, `estimated_cost_krw > 0`, cumulative usage visible in `monthly_usage` |

### 3.1 Step 0: Verify Identity (as cgjang)

```bash
aws sts get-caller-identity
# MUST show: arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/<session>
# STOP if not cgjang.
```

### 3.2 Step 1: Baseline — Capture Pre-Test State

Switch to admin SSO for DynamoDB reads:
```bash
unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN; unset AWS_SECURITY_TOKEN
export AWS_PROFILE=bedrock-gw; export AWS_REGION=us-west-2; export AWS_DEFAULT_REGION=us-west-2; export AWS_PAGER=""
aws sts get-caller-identity
```

```bash
# Baseline: monthly_usage for cgjang in current month
aws dynamodb query \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --key-condition-expression "principal_id_month = :pk" \
  --expression-attribute-values '{":pk": {"S": "107650139384#BedrockUser-cgjang#2026-03"}}' \
  --region us-west-2 \
  | tee /tmp/validation-baseline-monthly-usage.json

# Baseline: request_ledger count for cgjang
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --filter-expression "principal_id = :pid" \
  --expression-attribute-values '{":pid": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --select COUNT \
  --region us-west-2 \
  | tee /tmp/validation-baseline-ledger-count.json

echo "Baseline captured at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### 3.3 Step 2: Run 3 Sequential Gateway Requests (as cgjang)

Switch back to cgjang credentials, then run:

```bash
cat > /tmp/phase2-validation-test.py << 'PYEOF'
#!/usr/bin/env python3
"""
Phase 2 cgjang Live-Usage Validation — 3 sequential requests.
Run as BedrockUser-cgjang from FSx.
"""
import boto3, json, sys, time, uuid
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.request, urllib.error

API_URL = "https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1/converse"
REGION = "us-west-2"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

PROMPTS = [
    "What is 2+2? Answer in one word.",
    "Name one color. One word only.",
    "Say yes or no: is the sky blue?",
]

session = boto3.Session()
credentials = session.get_credentials().get_frozen_credentials()

# Verify identity
sts = session.client("sts", region_name=REGION)
identity = sts.get_caller_identity()
arn = identity["Arn"]
print(f"Caller: {arn}")
if "BedrockUser-cgjang" not in arn:
    print("FATAL: Not running as BedrockUser-cgjang. Aborting.")
    sys.exit(1)

results = []
cumulative_cost = 0.0

for i, prompt in enumerate(PROMPTS, 1):
    request_id = f"validation-{int(time.time())}-{i}-{uuid.uuid4().hex[:8]}"
    body = json.dumps({
        "modelId": MODEL,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
    }).encode()

    aws_req = AWSRequest(
        method="POST", url=API_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "Host": "5l764dh7y9.execute-api.us-west-2.amazonaws.com",
        },
    )
    SigV4Auth(credentials, "execute-api", REGION).add_auth(aws_req)

    req = urllib.request.Request(API_URL, data=body, method="POST")
    for k, v in aws_req.headers.items():
        req.add_header(k, v)

    print(f"\n--- Request {i}/3 (ID: {request_id}) ---")
    print(f"  Prompt: {prompt}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            resp_body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        status = e.code
        resp_body = json.loads(e.read().decode())
    except Exception as e:
        print(f"  FATAL: {e}")
        results.append({"request": i, "error": str(e)})
        continue

    decision = resp_body.get("decision", "unknown")
    cost = resp_body.get("estimated_cost_krw", 0)
    remaining = resp_body.get("remaining_quota", {}).get("cost_krw", "N/A")
    usage = resp_body.get("usage", {})
    cumulative_cost += cost if isinstance(cost, (int, float)) else 0

    print(f"  HTTP: {status}")
    print(f"  Decision: {decision}")
    print(f"  estimated_cost_krw: {cost}")
    print(f"  remaining_quota.cost_krw: {remaining}")
    print(f"  inputTokens: {usage.get('inputTokens', 'N/A')}")
    print(f"  outputTokens: {usage.get('outputTokens', 'N/A')}")

    result = {
        "request": i,
        "request_id": request_id,
        "http_status": status,
        "decision": decision,
        "estimated_cost_krw": cost,
        "remaining_quota_cost_krw": remaining,
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
    }
    results.append(result)

    # Brief pause between requests
    if i < len(PROMPTS):
        time.sleep(2)

# --- Summary ---
print("\n" + "=" * 60)
print("VALIDATION SUMMARY")
print("=" * 60)

all_allow = all(r.get("decision") == "ALLOW" for r in results if "error" not in r)
all_cost_positive = all(
    isinstance(r.get("estimated_cost_krw"), (int, float)) and r["estimated_cost_krw"] > 0
    for r in results if "error" not in r
)
remaining_decreased = True
if len(results) >= 2 and "error" not in results[0] and "error" not in results[-1]:
    first_remaining = results[0].get("remaining_quota_cost_krw", 0)
    last_remaining = results[-1].get("remaining_quota_cost_krw", 0)
    if isinstance(first_remaining, (int, float)) and isinstance(last_remaining, (int, float)):
        remaining_decreased = last_remaining < first_remaining

checks = {
    "All 3 requests returned ALLOW": all_allow,
    "All estimated_cost_krw > 0": all_cost_positive,
    "remaining_quota decreased across requests": remaining_decreased,
    "Cumulative cost > 0": cumulative_cost > 0,
}

all_pass = True
for name, passed in checks.items():
    tag = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{tag}] {name}")

print(f"\n  Cumulative estimated cost: {cumulative_cost:.4f} KRW")

# Save evidence
evidence = {
    "test_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "caller_arn": arn,
    "model": MODEL,
    "results": results,
    "cumulative_cost_krw": cumulative_cost,
    "checks": {k: v for k, v in checks.items()},
    "verdict": "PASS" if all_pass else "FAIL",
}
with open("/tmp/phase2-validation-results.json", "w") as f:
    json.dump(evidence, f, indent=2, default=str)
print(f"\n  Evidence saved: /tmp/phase2-validation-results.json")

if all_pass:
    print("\n  >>> VALIDATION PASSED — proceed to admin-side verification (Step 3)")
    sys.exit(0)
else:
    print("\n  >>> VALIDATION FAILED — review results and Lambda logs")
    sys.exit(1)
PYEOF

python3 /tmp/phase2-validation-test.py
```

### 3.4 Step 3: Admin-Side Evidence Collection (as admin SSO)

Switch to admin SSO credentials:
```bash
unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN; unset AWS_SECURITY_TOKEN
export AWS_PROFILE=bedrock-gw; export AWS_REGION=us-west-2; export AWS_DEFAULT_REGION=us-west-2; export AWS_PAGER=""
aws sts get-caller-identity
```

#### 3.4.1 monthly_usage — Verify Cost Accumulated

```bash
aws dynamodb query \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --key-condition-expression "principal_id_month = :pk" \
  --expression-attribute-values '{":pk": {"S": "107650139384#BedrockUser-cgjang#2026-03"}}' \
  --region us-west-2 \
  | tee /tmp/validation-post-monthly-usage.json

# Compare with baseline:
echo "--- BASELINE ---"
cat /tmp/validation-baseline-monthly-usage.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('Items', [])
if not items:
    print('  (no baseline records)')
else:
    for item in items:
        mid = item.get('model_id', {}).get('S', '?')
        cost = item.get('cost_krw', {}).get('N', '0')
        inp = item.get('input_tokens', {}).get('N', '0')
        out = item.get('output_tokens', {}).get('N', '0')
        print(f'  {mid}: cost_krw={cost}, input={inp}, output={out}')
"

echo "--- POST-TEST ---"
cat /tmp/validation-post-monthly-usage.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('Items', [])
if not items:
    print('  ERROR: no records found after test')
else:
    for item in items:
        mid = item.get('model_id', {}).get('S', '?')
        cost = item.get('cost_krw', {}).get('N', '0')
        inp = item.get('input_tokens', {}).get('N', '0')
        out = item.get('output_tokens', {}).get('N', '0')
        print(f'  {mid}: cost_krw={cost}, input={inp}, output={out}')
"
```

**Pass criteria**: `cost_krw` for `us.anthropic.claude-haiku-4-5-20251001-v1:0` is > 0 and increased from baseline.

#### 3.4.2 request_ledger — Verify Entries Written

```bash
# Get the 3 most recent ledger entries for cgjang
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --filter-expression "principal_id = :pid AND begins_with(request_id, :prefix)" \
  --expression-attribute-values '{
    ":pid": {"S": "107650139384#BedrockUser-cgjang"},
    ":prefix": {"S": "validation-"}
  }' \
  --region us-west-2 \
  | tee /tmp/validation-post-ledger.json

# Quick summary
cat /tmp/validation-post-ledger.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('Items', [])
print(f'Validation ledger entries: {len(items)}')
for item in items:
    rid = item.get('request_id', {}).get('S', '?')
    decision = item.get('decision', {}).get('S', '?')
    cost = item.get('estimated_cost_krw', {}).get('N', '0')
    print(f'  {rid}: decision={decision}, estimated_cost_krw={cost}')
"
```

**Pass criteria**: 3 entries found, all `decision=ALLOW`, all `estimated_cost_krw > 0`.

#### 3.4.3 daily_usage — Verify NO New Writes

```bash
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-daily-usage \
  --filter-expression "contains(principal_id_date, :today)" \
  --expression-attribute-values '{":today": {"S": "2026-03-20"}}' \
  --select COUNT \
  --region us-west-2
# Expected: Count = 0
# If Count > 0, old Lambda code is running — check alias/version.
```

**Pass criteria**: Count = 0 for today's date.

#### 3.4.4 Lambda Logs — No Errors

```bash
# Check for errors in last 10 minutes
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 600) * 1000))") \
  --filter-pattern "ERROR" \
  --limit 20 \
  | tee /tmp/validation-lambda-errors.json

# Check for validation request flow
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --region us-west-2 \
  --start-time $(python3 -c "import time; print(int((time.time() - 600) * 1000))") \
  --filter-pattern '"validation-"' \
  --limit 20 \
  | tee /tmp/validation-lambda-flow.json
```

**Pass criteria**: No ERROR entries related to validation requests. Flow logs show 3 request cycles.

---

## Part 4: Pass/Fail Criteria Summary

| # | Criterion | Source | Required |
|---|-----------|--------|----------|
| V1 | Cost-precision fix deployed (terraform apply success) | Part 2 | YES |
| V2 | All 3 requests return `decision: ALLOW` | Step 2 script output | YES |
| V3 | All 3 `estimated_cost_krw > 0` (not truncated to 0) | Step 2 script output | YES — this is the cost-precision fix validation |
| V4 | `remaining_quota.cost_krw` decreases across requests | Step 2 script output | YES |
| V5 | `monthly_usage` shows accumulated `cost_krw > 0` | Step 3.4.1 | YES |
| V6 | `request_ledger` has 3 entries with `estimated_cost_krw > 0` | Step 3.4.2 | YES |
| V7 | `daily_usage` has 0 new writes for today | Step 3.4.3 | YES |
| V8 | Lambda logs show no ERROR for validation requests | Step 3.4.4 | YES |

**All 8 criteria must pass for Phase 2 to be marked VERIFIED.**

---

## Part 5: After Validation Passes

When all V1-V8 pass:

1. Update `docs/ai/todo.md` — Phase 2 line: "DEPLOYED AND VERIFIED"
2. Update `docs/ai/runbook.md` — Remove "COST-PRECISION FIX PENDING DEPLOY" note
3. Update `docs/ai/phase2-post-deploy-verification.md` — Mark C5-C9 as verified
4. Save all `/tmp/validation-*.json` files as evidence

Phase 2 is then COMPLETE. Phase 3 (approval ladder) requires separate approval.

---

## Part 6: Failure Triage

| Failure | Likely Cause | Fix |
|---------|-------------|-----|
| `estimated_cost_krw = 0` | Cost-precision fix not deployed (still using `int()`) | Confirm terraform apply completed, check Lambda version |
| `decision: DENY` with "audit ledger write failed" | DynamoDB Decimal-vs-float defect — `float()` in ledger_entry | Confirm Decimal ledger fix deployed (2026-03-20). Check Lambda version matches latest code hash. |
| `decision: DENY` with "no pricing" | `model_pricing` seed missing for `us.` prefix model | Re-seed per `phase2-post-deploy-verification.md` §1.1 |
| `decision: DENY` with "model not in allowed list" | `principal_policy` `allowed_models` missing `us.` prefix | Update allowed_models |
| `decision: DENY` with "quota exceeded" | Previous test runs consumed quota | Reset monthly_usage or wait for month rollover |
| HTTP 403 (no Lambda fields) | `execute-api:Invoke` permission missing on cgjang role | Check `AllowDevGatewayConverse` inline policy |
| SSO expired during terraform | Session timeout | `aws sso login --profile bedrock-gw` and retry |

---

## Boundary Statement

This document covers Phase 2 cost-precision deploy + cgjang validation ONLY.
- No Phase 3 (approval ladder) work
- No Phase 4 (admin API/frontend) work
- No `daily_usage` table removal
- No shlee validation (deliberate exception)
- No existing infrastructure modifications
