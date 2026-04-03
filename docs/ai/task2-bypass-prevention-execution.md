# Task 2: Direct Bedrock Bypass Prevention — Execution Record

> Executed: 2026-03-19
> Scope: IAM deny policy on all `BedrockUser-*` roles to prevent direct Bedrock inference bypass.
> Method: Option A (IAM deny on user roles) per `research.md` §4, `design.md` "Bypass Prevention Architecture".

---

## Summary

Applied `DenyDirectBedrockInference` inline policy to all 6 `BedrockUser-*` roles. IAM policy simulation confirms `explicitDeny` for direct Bedrock inference on all user roles, and `allowed` for Lambda execution role and gateway invoke path.

**Status: IAM deny applied + simulation verified. Live operator verification pending.**

Task 2 cannot be marked fully complete until live evidence confirms:
1. Direct Bedrock call as `BedrockUser-cgjang` returns `AccessDeniedException`
2. Gateway-path smoke test as `BedrockUser-cgjang` succeeds end-to-end

See "Live Verification Package" section below for exact operator commands.

## Deny Policy Applied

Policy name: `DenyDirectBedrockInference`

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyDirectBedrockAccess",
    "Effect": "Deny",
    "Action": [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:Converse",
      "bedrock:ConverseStream"
    ],
    "Resource": "*"
  }]
}
```

### Why These 4 Actions

- `bedrock:InvokeModel` — IAM-level action for Converse API. Primary bypass surface.
- `bedrock:InvokeModelWithResponseStream` — IAM-level action for ConverseStream. Secondary bypass surface.
- `bedrock:Converse` / `bedrock:ConverseStream` — NOT currently valid IAM actions (AWS maps them to InvokeModel/InvokeModelWithResponseStream). Included for defense-in-depth in case AWS makes them valid IAM actions in the future. IAM silently ignores unrecognized actions in Deny statements.

### Why NOT Deny Other Actions

- `bedrock:ListFoundationModels`, `bedrock:GetFoundationModel`, `bedrock:ListInferenceProfiles`, `bedrock:GetInferenceProfile` — read-only discovery actions. No inference bypass risk. Users may need these for model discovery.
- `bedrock:InvokeAgent` — out of scope for v1. No agents configured. Can be added to deny if agents are deployed later.

## Roles Modified

| Role | Policy Applied | Simulation: InvokeModel | Simulation: InvokeModelWithResponseStream |
|------|---------------|------------------------|------------------------------------------|
| BedrockUser-cgjang | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |
| BedrockUser-hermee | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |
| BedrockUser-jwlee | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |
| BedrockUser-sbkim | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |
| BedrockUser-shlee | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |
| BedrockUser-shlee2 | ✅ DenyDirectBedrockInference | explicitDeny | explicitDeny |

## Unaffected Principals

| Principal | bedrock:InvokeModel | Reason |
|-----------|-------------------|--------|
| `bedrock-gw-dev-lambda-exec` | ✅ allowed | Separate IAM role. Deny is on user roles only. |

## Gateway Path Validation

| Check | Result |
|-------|--------|
| `BedrockUser-cgjang` execute-api:Invoke on gateway | ✅ allowed |
| `AllowDevGatewayConverse` policy intact | ✅ confirmed |

## Validation Method

All validations performed via `aws iam simulate-principal-policy` — IAM policy simulator evaluates the effective policy without requiring actual API calls. This is authoritative for IAM-level enforcement.

## What Still Requires Operator Confirmation

1. **Live gateway-path smoke test**: Operator must execute the Phase 2 smoke test as `BedrockUser-cgjang` to confirm the full gateway path (SigV4 → API Gateway → Lambda → Bedrock) still works end-to-end after the deny policy is applied. The IAM simulation confirms `execute-api:Invoke` is allowed and the Lambda role's `bedrock:InvokeModel` is allowed, but a live test provides full-stack confirmation.
   - Script: `docs/ai/phase2-smoke-test.py`
   - Runbook: `docs/ai/phase2-operator-smoke-test-runbook.md`

2. **Live direct-Bedrock-deny test**: Operator can optionally confirm that direct `boto3.client('bedrock-runtime').converse(...)` as `BedrockUser-cgjang` returns AccessDeniedException:
   ```bash
   # As BedrockUser-cgjang (from FSx):
   python3 -c "
   import boto3
   client = boto3.client('bedrock-runtime', region_name='us-west-2')
   try:
       resp = client.converse(
           modelId='anthropic.claude-haiku-4-5-20251001-v1:0',
           messages=[{'role': 'user', 'content': [{'text': 'Hello'}]}]
       )
       print('ERROR: Direct Bedrock call succeeded — bypass NOT blocked')
   except client.exceptions.ClientError as e:
       if 'AccessDeniedException' in str(e):
           print('PASS: Direct Bedrock call denied — bypass blocked')
       else:
           print(f'UNEXPECTED ERROR: {e}')
   "
   ```

## Rollback

To remove the deny policy from a single role:
```bash
aws iam delete-role-policy --role-name BedrockUser-<username> --policy-name DenyDirectBedrockInference
```

To remove from all 6 roles:
```bash
for ROLE in BedrockUser-cgjang BedrockUser-hermee BedrockUser-jwlee BedrockUser-sbkim BedrockUser-shlee BedrockUser-shlee2; do
  aws iam delete-role-policy --role-name "$ROLE" --policy-name DenyDirectBedrockInference
  echo "Removed DenyDirectBedrockInference from $ROLE"
done
```

## Future: SCP Migration

Per `research.md` §4, the long-term target is an Organization SCP that denies Bedrock inference for all principals except the gateway Lambda execution role. When SCP is approved:
1. Apply SCP with condition exempting `bedrock-gw-*-lambda-exec` role ARN
2. Verify SCP enforcement
3. Remove per-role `DenyDirectBedrockInference` inline policies
4. Track in `todo.md` Post-Implementation section


---

## Live Verification Package

### Why IAM Simulation Alone Is Not Enough

IAM policy simulation evaluates the policy documents attached to a principal. It does not exercise the actual AWS authorization path. Gaps can exist due to:
- Session policies passed during AssumeRole
- Resource-based policies on Bedrock model resources
- Permission boundaries not visible in simulation
- SCP evaluation differences between simulation and live calls
- Caching/propagation delays in IAM policy changes

Only a live API call proves the deny is enforced at the AWS service level.

### Prerequisites

All commands below must be run as `BedrockUser-cgjang` from FSx (using the existing `[default]` profile with `credential_source = Ec2InstanceMetadata`).

```bash
# Verify identity first — STOP if this does not show BedrockUser-cgjang
aws sts get-caller-identity
# Expected:
# {
#   "Account": "107650139384",
#   "Arn": "arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/<session>"
# }
```

---

### Test A: Direct Bedrock Bypass Test (MUST FAIL)

This test attempts a direct Bedrock runtime call, bypassing the gateway. It must be denied.

```bash
python3 -c "
import boto3, json, sys

client = boto3.client('bedrock-runtime', region_name='us-west-2')
print('Attempting direct Bedrock Converse call (bypassing gateway)...')
try:
    resp = client.converse(
        modelId='anthropic.claude-haiku-4-5-20251001-v1:0',
        messages=[{'role': 'user', 'content': [{'text': 'Hello'}]}]
    )
    print('FAIL: Direct Bedrock call SUCCEEDED — bypass NOT blocked')
    print(json.dumps({'status': 'BYPASS_NOT_BLOCKED', 'response_status': resp['ResponseMetadata']['HTTPStatusCode']}, indent=2))
    sys.exit(1)
except client.exceptions.ClientError as e:
    error_code = e.response['Error']['Code']
    error_msg = e.response['Error']['Message']
    http_status = e.response['ResponseMetadata']['HTTPStatusCode']
    if error_code == 'AccessDeniedException':
        print('PASS: Direct Bedrock call DENIED — bypass is blocked')
        print(json.dumps({'status': 'BYPASS_BLOCKED', 'error_code': error_code, 'http_status': http_status, 'message': error_msg}, indent=2))
        sys.exit(0)
    else:
        print(f'UNEXPECTED ERROR: {error_code} — {error_msg}')
        print(json.dumps({'status': 'UNEXPECTED_ERROR', 'error_code': error_code, 'http_status': http_status, 'message': error_msg}, indent=2))
        sys.exit(2)
except Exception as e:
    print(f'UNEXPECTED EXCEPTION: {type(e).__name__}: {e}')
    sys.exit(2)
" 2>&1 | tee /tmp/task2-test-a-direct-bypass.json
```

**Expected good output:**
```
PASS: Direct Bedrock call DENIED — bypass is blocked
{"status": "BYPASS_BLOCKED", "error_code": "AccessDeniedException", "http_status": 403, "message": "..."}
```

**Red flags — STOP and report:**
- `FAIL: Direct Bedrock call SUCCEEDED` → bypass is NOT blocked, deny policy is not effective
- `UNEXPECTED ERROR` with any code other than `AccessDeniedException` → investigate before proceeding
- `ThrottlingException` → retry after 30 seconds, not a deny issue

---

### Test B: Gateway Path Preservation Test (MUST SUCCEED)

This test invokes the gateway via the existing smoke-test path. It must succeed end-to-end.

**Option B1: Using the existing Python smoke test script**

```bash
# From FSx as BedrockUser-cgjang:
cd /path/to/repo/docs/ai
python3 phase2-smoke-test.py 2>&1 | tee /tmp/task2-test-b-gateway-path.json
```

**Option B2: Minimal inline gateway test (if smoke test script is not available on FSx)**

```bash
python3 -c "
import boto3, json, sys
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import urllib.request

session = boto3.Session(region_name='us-west-2')
credentials = session.get_credentials().get_frozen_credentials()

url = 'https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1/converse'
body = json.dumps({
    'modelId': 'anthropic.claude-haiku-4-5-20251001-v1:0',
    'messages': [{'role': 'user', 'content': [{'text': 'Say hello in one word.'}]}]
}).encode()

request = AWSRequest(method='POST', url=url, data=body, headers={
    'Content-Type': 'application/json',
    'X-Request-Id': 'task2-verify-gateway-' + str(int(__import__('time').time()))
})
SigV4Auth(credentials, 'execute-api', 'us-west-2').add_auth(request)

try:
    req = urllib.request.Request(url, data=body, headers=dict(request.headers), method='POST')
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        status = resp.status
        print('PASS: Gateway path works')
        print(json.dumps({'status': 'GATEWAY_PATH_OK', 'http_status': status, 'decision': result.get('decision', 'unknown')}, indent=2))
        sys.exit(0)
except urllib.error.HTTPError as e:
    error_body = e.read().decode()
    print(f'GATEWAY CALL FAILED: HTTP {e.code}')
    print(json.dumps({'status': 'GATEWAY_PATH_FAILED', 'http_status': e.code, 'body': error_body}, indent=2))
    sys.exit(1)
except Exception as e:
    print(f'UNEXPECTED EXCEPTION: {type(e).__name__}: {e}')
    sys.exit(2)
" 2>&1 | tee /tmp/task2-test-b-gateway-path.json
```

**Expected good output:**
```
PASS: Gateway path works
{"status": "GATEWAY_PATH_OK", "http_status": 200, "decision": "ALLOW"}
```

**Failure classification — if gateway test fails:**

| HTTP Status | Likely Cause | Classification |
|-------------|-------------|----------------|
| 403 Forbidden (from API Gateway) | `execute-api:Invoke` permission missing or deny applied | Gateway IAM problem — NOT related to Task 2 deny (Task 2 only denies `bedrock:*`, not `execute-api:*`) |
| 403 with `{"message": "...denied..."}` from Lambda | Lambda policy/model/quota deny | Runtime enforcement — gateway path is working, Lambda correctly denied the request. Check deny reason. |
| 500 Internal Server Error | Lambda runtime error | Runtime/config issue — check CloudWatch logs |
| 200 with `"decision": "DENY"` | Lambda quota/model/policy deny | Gateway path works, but request was denied by enforcement logic. Check `deny_reason` in response. |
| Connection refused / timeout | API Gateway or Lambda not reachable | Infrastructure issue — unrelated to Task 2 |

**Key distinction:** If Test B fails with HTTP 403 from API Gateway, that is NOT caused by the `DenyDirectBedrockInference` policy. That policy only denies `bedrock:*` actions, not `execute-api:Invoke`. If Test B fails, investigate the gateway/Lambda path independently.

---

### Admin-Side Verification (run as admin SSO role, not as cgjang)

After operator runs Tests A and B, admin can verify from the admin SSO session:

```bash
# Credential normalization
unset AWS_ACCESS_KEY_ID; unset AWS_SECRET_ACCESS_KEY; unset AWS_SESSION_TOKEN; unset AWS_SECURITY_TOKEN
export AWS_PROFILE=bedrock-gw; export AWS_REGION=us-west-2; export AWS_DEFAULT_REGION=us-west-2; export AWS_PAGER=""
aws sts get-caller-identity

# V1: Confirm deny policy still present on all roles
for ROLE in BedrockUser-cgjang BedrockUser-hermee BedrockUser-jwlee BedrockUser-sbkim BedrockUser-shlee BedrockUser-shlee2; do
  HAS=$(aws iam list-role-policies --role-name "$ROLE" --query "PolicyNames[?contains(@, 'DenyDirectBedrockInference')]" --output text)
  echo "$ROLE: $HAS"
done

# V2: Check CloudWatch logs for the gateway test request (Test B)
# Look for the request_id used in Test B
aws logs filter-log-events \
  --log-group-name /aws/lambda/bedrock-gw-dev-gateway \
  --start-time $(date -d '10 minutes ago' +%s000) \
  --filter-pattern '"task2-verify-gateway"' \
  --query 'events[*].message' --output text

# V3: Check RequestLedger for the gateway test entry
aws dynamodb scan \
  --table-name bedrock-gw-dev-us-west-2-request-ledger \
  --filter-expression "contains(request_id, :rid)" \
  --expression-attribute-values '{":rid": {"S": "task2-verify-gateway"}}' \
  --query 'Items[0].{request_id:request_id.S,principal_id:principal_id.S,decision:decision.S}' \
  --region us-west-2
```

---

### Evidence Checklist

After running Tests A and B, capture and save:

| # | Evidence | File | Required |
|---|----------|------|----------|
| E1 | Test A output (direct bypass denied) | `/tmp/task2-test-a-direct-bypass.json` | YES |
| E2 | Test B output (gateway path works) | `/tmp/task2-test-b-gateway-path.json` | YES |
| E3 | `aws sts get-caller-identity` output (proves tests ran as cgjang) | inline in E1/E2 | YES |
| E4 | CloudWatch log entry for Test B request | admin-side V2 output | RECOMMENDED |
| E5 | RequestLedger entry for Test B request | admin-side V3 output | RECOMMENDED |

---

### Completion Criteria

Task 2 may be upgraded from **"implemented / simulation-verified"** to **"live verified / complete"** when ALL of:

1. **E1 shows `BYPASS_BLOCKED`** — direct Bedrock call returned `AccessDeniedException`
2. **E2 shows `GATEWAY_PATH_OK`** — gateway call returned HTTP 200 with `decision: ALLOW`
3. **E3 confirms identity** — tests ran as `BedrockUser-cgjang` (not admin role)
4. **No rollback was needed** — deny policy remained in place throughout

If E1 passes but E2 fails, Task 2 deny is working but the gateway path has a separate issue. Investigate the gateway failure independently — do NOT roll back the deny policy unless the deny is proven to be the cause (it should not be — deny targets `bedrock:*`, not `execute-api:*`).

If E1 fails (direct call succeeds), the deny policy is not effective. Investigate immediately — check for permission boundaries, SCPs, or session policies that might override the inline deny.
