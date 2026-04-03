# Shell Hook Quota Prompt — Implementation Plan

> Date: 2026-03-26
> Status: PLANNING — awaiting approval
> Scope: Shell hook for automatic quota status check + interactive approval request prompt

---

## 1. Current State Analysis

### Existing Gateway Capabilities (handler.py)

| Capability | Function | Endpoint | Status |
|-----------|----------|----------|--------|
| Principal identification | `extract_identity()` + `normalize_principal_id()` | Automatic from SigV4 | ✅ Exists |
| Policy lookup | `lookup_principal_policy()` | Internal | ✅ Exists |
| Usage aggregation | `check_quota()` | Internal | ✅ Exists |
| Effective limit calculation | Inside `check_quota()` | Internal | ✅ Exists |
| Pending approval check | Inside quota-exceeded response | Internal | ✅ Exists |
| Approval request creation | `handle_approval_request()` | `POST /approval/request` | ✅ Exists |
| **Quota status query endpoint** | — | — | ❌ Missing |

### Key Finding

The Lambda already has all the computation logic. What's missing is a **lightweight status query endpoint** that returns the user's current quota state without attempting inference. Currently the only way to get quota info is to attempt a Converse call and either succeed or get a 429 with quota details.

### API Gateway Routing

`{proxy+}` with `ANY` method → all paths go to Lambda. Adding a new path like `GET /quota/status` requires only a Lambda code change (new route in `lambda_handler`), no Terraform changes.

---

## 2. Design

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  User's interactive shell (bash/zsh)                │
│                                                      │
│  PROMPT_COMMAND / precmd hook                        │
│    └─ /fsx/shared/bedrock-gateway/quota-check.sh    │
│         ├─ Cooldown check (file timestamp, 5min)    │
│         ├─ Non-interactive? → skip                  │
│         ├─ SigV4 GET → API Gateway /quota/status    │
│         │   └─ Lambda check_quota() + pending check │
│         ├─ Response: usage/limit/pending/prompt flag │
│         ├─ should_prompt? → ask user y/N            │
│         │   └─ y → SigV4 POST /approval/request    │
│         └─ Update cooldown timestamp                │
└─────────────────────────────────────────────────────┘
```

### Server Side: New `/quota/status` endpoint (Lambda)

Add to `lambda_handler()` routing:

```python
if path.rstrip("/") == "/quota/status" and http_method == "GET":
    return handle_quota_status(principal_id, identity_fields)
```

New function `handle_quota_status()`:
- Reuses `lookup_principal_policy()`, `check_quota()`
- Checks `approval_pending_lock` for pending state
- Returns JSON with all fields the shell hook needs
- No mutation, read-only

Response schema:
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "month": "2026-03",
  "current_usage_krw": 450000.0,
  "effective_limit_krw": 500000,
  "approval_band": 0,
  "has_pending_approval": false,
  "at_hard_cap": false,
  "should_prompt_for_increase": true,
  "recommended_increment_krw": 500000,
  "message": ""
}
```

`should_prompt_for_increase` = true when:
- `current_usage_krw >= effective_limit_krw * 0.9` (90% threshold)
- AND `has_pending_approval == false`
- AND `at_hard_cap == false`

### Client Side: Shell hook script

Single file: `/fsx/shared/bedrock-gateway/quota-check.sh`

Sourced from user's `.bashrc` or `/etc/profile.d/`:
```bash
source /fsx/shared/bedrock-gateway/quota-check.sh
```

Behavior:
- Runs on `PROMPT_COMMAND` (bash) / `precmd` (zsh)
- Checks cooldown file (`~/.cache/bedrock-gw-quota-check-ts`)
- If < 5 minutes since last check → skip
- If non-interactive (`[[ ! -t 0 ]]`) → skip
- If suppressed (`~/.cache/bedrock-gw-quota-suppressed`) → skip until file expires
- Calls `GET /quota/status` via SigV4 (uses existing AWS credentials)
- If `should_prompt_for_increase`:
  - Shows prompt with usage/limit info
  - `y` → calls `POST /approval/request` via SigV4
  - `n` → creates suppress file (30min TTL)
- If `has_pending_approval`:
  - Shows one-line info: "한도 증액 요청 대기 중 (ID: xxx)"
  - No re-prompt

---

## 3. Files to Change — Precise Inventory

| # | File | Change | Type | Blast Radius |
|---|------|--------|------|-------------|
| 1 | `infra/bedrock-gateway/lambda/handler.py` | Add `handle_quota_status()` function (~40 lines) + add route in `lambda_handler()` (~5 lines) | Lambda code — **MUST CHANGE** | Inference pipeline untouched. New read-only route only. |
| 2 | `infra/bedrock-gateway/lambda.tf` | No change — no new env vars needed | — | — |
| 3 | `infra/bedrock-gateway/main.tf` | No change — `{proxy+}` proxy already routes all paths to Lambda | — | — |
| 4 | `infra/bedrock-gateway/iam.tf` | No change — Lambda already has GetItem/Query on all needed tables | — | — |
| 5 | `infra/bedrock-gateway/dynamodb.tf` | No change — no new tables or GSIs | — | — |
| 6 | `account-portal/backend-admin/data/bedrock-gw-quota-check.sh` | **New file** — shell hook script | New client-side | Zero server impact |
| 7 | `account-portal/backend-admin/data/bedrock-gw-request.sh` | No change — kept as manual fallback | — | — |

### handler.py Change Detail

**New function: `handle_quota_status()`** (inserted before `lambda_handler()`):
- Reuses existing `lookup_principal_policy()` (line 248)
- Reuses existing `check_quota()` (line 406) — which internally queries `monthly_usage` + `temporary_quota_boost`
- Queries `approval_pending_lock` table (same pattern as quota-exceeded block in `lambda_handler()` line ~1200)
- Read-only: zero DynamoDB writes, zero Bedrock calls
- Returns JSON with all fields shell hook needs

**Route addition in `lambda_handler()`** (after approval route, before inference pipeline):
```python
# --- Route: quota status query ---
if path.rstrip("/") == "/quota/status" and http_method == "GET":
    return handle_quota_status(principal_id, identity_fields)
```

**What is NOT changed in handler.py:**
- `lambda_handler()` inference pipeline (Steps 1-12) — untouched
- `handle_approval_request()` — untouched
- `check_quota()` — untouched (reused as-is)
- All existing functions — untouched

### Terraform Impact

`terraform apply` is required because `handler.py` changes → `source_code_hash` changes → Lambda function update. This is:
- `0 added, 1 changed, 0 destroyed` (Lambda code hash only)
- Same pattern as Phase 3 deployment
- No API Gateway, IAM, DynamoDB, or other resource changes

### IAM Verification

`handle_quota_status()` reads from:
- `principal_policy` — GetItem → covered by `DynamoDBReadWriteNonLedger` ✅
- `monthly_usage` — Query → covered by `DynamoDBReadWriteNonLedger` ✅
- `temporary_quota_boost` — Query → covered by `DynamoDBReadWriteNonLedger` ✅
- `approval_pending_lock` — GetItem → covered by `DynamoDBReadWriteNonLedger` ✅

No new IAM permissions needed.

---

## 4. Implementation Order

1. **handler.py**: Add `handle_quota_status()` function + route in `lambda_handler()`
2. **Terraform**: `terraform plan` → verify only Lambda code hash change → `terraform apply`
3. **Verify**: SigV4-signed `GET /quota/status` returns correct JSON for cgjang
4. **Shell hook**: Create `bedrock-gw-quota-check.sh`
5. **Deploy hook**: Place in `/fsx/shared/bedrock-gateway/` or equivalent shared path
6. **Test**: All 10 scenarios from requirements
7. **Cleanup**: Restore test user state

---

## 5. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Shell hook failure blocks user prompt | High | `set +e`, timeout on curl, all errors silently ignored |
| Excessive API Gateway calls | Medium | 5-minute cooldown, file-based timestamp |
| SigV4 signing in shell script | Low | Use `python3 -c` with boto3 (already available on FSx) |
| Non-interactive detection false positive | Low | Check `[[ -t 0 ]]` AND `$-` contains `i` |

---

## 6. Rollback

- Lambda: revert `handler.py` to remove `/quota/status` route, `terraform apply`
- Shell hook: remove source line from `.bashrc` or delete from `/etc/profile.d/`
- No DynamoDB changes, no IAM changes

---

## Boundary Statement

This is a planning artifact. No code changes made. Awaiting approval.
