# Shell Hook Quota Prompt — Full Design Review Document

> Date: 2026-03-26
> Status: DESIGN REVIEW — awaiting approval
> Author: Kiro (AI assistant)
> Scope: Automatic shell-based quota status check + interactive approval request prompt
> Prerequisites: Phase 4 Scope A COMPLETE. All existing gateway/approval/portal flows operational.

---

## A. Architecture Summary

### What exists today

| Component | Location | Role |
|-----------|----------|------|
| API Gateway | `infra/bedrock-gateway/main.tf` | SigV4-authenticated REST API, `{proxy+}` routes all paths to Lambda |
| Lambda gateway | `infra/bedrock-gateway/lambda/handler.py` | Inference pipeline, approval request creation, quota enforcement |
| DynamoDB tables | 10 tables (`principal_policy`, `monthly_usage`, `temporary_quota_boost`, `approval_pending_lock`, `approval_request`, etc.) | Source of truth for all quota/usage/approval state |
| Admin portal | `account-portal/backend-admin/` | Admin-plane read APIs, approval CRUD, email-action endpoint |
| Frontend | `account-portal/frontend/` | React SPA for operator monitoring |
| Admin email flow | Lambda SES + `gateway_approval.py` email-action | Approval notification + one-click approve/reject |
| Manual request script | `account-portal/backend-admin/data/bedrock-gw-request.sh` | User manually triggers approval request via SigV4 POST |

### What this design adds

One new read-only Lambda endpoint (`GET /quota/status`) and one new shell hook script.
The shell hook replaces the need for users to manually run `bedrock-gw-request.sh`.

### Why handler.py cannot directly control user shells

Lambda is a stateless serverless function invoked by API Gateway HTTP requests.
It has zero access to user shell processes, terminals, or stdin/stdout.
It cannot push notifications to a user's terminal.
The only way to surface information in a user's shell is for the shell itself to poll the server.
This is a fundamental architectural constraint, not a design choice.


## B. Server / Client / Manual Script Responsibility Matrix

| Responsibility | Owner | Implementation |
|---------------|-------|---------------|
| Principal identification | Server (Lambda) | `extract_identity()` + `normalize_principal_id()` from SigV4 context |
| Current month usage calculation | Server (Lambda) | `check_quota()` → queries `monthly_usage` table |
| Effective limit calculation (base + active boosts, capped at hard cap) | Server (Lambda) | `check_quota()` → queries `temporary_quota_boost` table |
| Approval band calculation | Server (Lambda) | Count active boosts in `temporary_quota_boost` |
| Pending approval detection | Server (Lambda) | GetItem on `approval_pending_lock`, check TTL |
| Hard cap detection | Server (Lambda) | Compare effective_limit against `max_monthly_cost_limit_krw` |
| **should_prompt_for_increase decision** | **Server (Lambda)** | New logic in `handle_quota_status()` |
| Interactive shell detection | Shell hook | `[[ -t 0 ]] && [[ $- == *i* ]]` |
| Cooldown/suppress management | Shell hook | Local file timestamps in `~/.cache/` |
| Display prompt to user | Shell hook | `read -p` in bash, `read "?..."` in zsh |
| Capture y/n input | Shell hook | Shell hook |
| Call `/approval/request` on y | Shell hook | SigV4-signed POST via python3+boto3 |
| Approval request creation | Server (Lambda) | Existing `handle_approval_request()` — **no change** |
| Pending lock acquisition | Server (Lambda) | Existing conditional PutItem — **no change** |
| Admin email notification | Server (Lambda) | Existing `_send_approval_email()` — **no change** |
| Admin approve/reject | Admin portal + email-action | Existing `gateway_approval.py` — **no change** |
| Manual fallback request | `bedrock-gw-request.sh` | Kept as-is, same `/approval/request` endpoint |

---

## C. What MUST Change vs What MUST NOT Change

### MUST change (required)

| # | File | Change | Reason |
|---|------|--------|--------|
| 1 | `infra/bedrock-gateway/lambda/handler.py` | Add `handle_quota_status()` function (~60 lines). Add route `GET /quota/status` in `lambda_handler()` (~3 lines). | No existing endpoint returns quota status without attempting inference. |
| 2 | `account-portal/backend-admin/data/bedrock-gw-quota-check.sh` | New file (~120 lines). Shell hook script. | Client-side thin client for prompt display. |

### SHOULD change (recommended for operational completeness)

| # | File | Change | Reason |
|---|------|--------|--------|
| 3 | Shell init integration (one of: `/etc/profile.d/bedrock-gw.sh`, or user `.bashrc`/`.zshrc`) | Add `source /fsx/shared/bedrock-gateway/quota-check.sh` | Hook must be loaded into user shells. |
| 4 | `docs/ai/runbook.md` | Add shell hook deployment/rollback section | Operational documentation. |
| 5 | `docs/ai/todo.md` | Update with shell hook task status | Task tracking. |

### MUST NOT change

| # | File/Component | Reason |
|---|---------------|--------|
| 1 | `handler.py` inference pipeline (Steps 1-12 in `lambda_handler()`) | Core inference path must remain untouched. |
| 2 | `handle_approval_request()` | Existing approval creation logic. Shell hook reuses it via POST. |
| 3 | `_send_approval_email()` | Admin email flow unchanged. |
| 4 | `_auto_create_approval_request()` | Existing auto-request on quota exhaustion during inference. |
| 5 | `_check_and_send_warning_email()` | Existing warning email thresholds. |
| 6 | `check_quota()` | Core quota calculation. Reused by new endpoint, not modified. |
| 7 | `gateway_approval.py` (all routes) | Admin portal approval CRUD + email-action. |
| 8 | `gateway_usage.py` (all routes) | Admin portal usage/policy/pricing read APIs. |
| 9 | `main.tf` | `{proxy+}` already routes all paths. No API Gateway changes. |
| 10 | `iam.tf` | Lambda already has GetItem/Query on all needed tables. |
| 11 | `dynamodb.tf` | No new tables or GSIs. |
| 12 | `lambda.tf` | No new environment variables. |
| 13 | `docker-compose-fixed.yml` | No container changes. |
| 14 | `bedrock-gw-request.sh` | Kept as manual fallback. |
| 15 | Frontend (`BedrockGateway.jsx`) | No frontend changes. |


## D. Terraform Impact Analysis

`handler.py` changes → `source_code_hash` changes → `terraform apply` required.

Expected plan output: `0 added, 1 changed, 0 destroyed` (Lambda function code hash update only).
Same deployment pattern as Phase 3 (2026-03-23).

No changes to: API Gateway resources, IAM policies, DynamoDB tables, Lambda env vars, CloudWatch log groups.

### IAM Verification for `/quota/status`

`handle_quota_status()` reads from:
- `principal_policy` → GetItem → `DynamoDBReadWriteNonLedger` statement ✅
- `monthly_usage` → Query → `DynamoDBReadWriteNonLedger` statement ✅
- `temporary_quota_boost` → Query → `DynamoDBReadWriteNonLedger` statement ✅
- `approval_pending_lock` → GetItem → `DynamoDBReadWriteNonLedger` statement ✅

Zero writes. No new IAM permissions needed.

### API Gateway Routing Verification

`main.tf` defines `{proxy+}` with `ANY` method → all paths route to Lambda.
`GET /quota/status` will be routed to Lambda automatically.
No Terraform resource changes needed for routing.

---

## E. Endpoint Specifications

### E.1 `GET /quota/status` (NEW — read-only)

**Authentication**: AWS_IAM (SigV4). Same as all existing gateway endpoints.
**Principal identification**: Automatic from `requestContext.identity` (same as inference/approval).
**Side effects**: None. Pure read-only. Zero DynamoDB writes.

**Implementation**: New `handle_quota_status()` function in `handler.py`.
Reuses existing functions:
- `lookup_principal_policy()` (line 248) — policy lookup
- `check_quota()` (line 406) — usage aggregation + effective limit calculation
- Pending lock check — same pattern as quota-exceeded block (line ~1200)

Does NOT call: `invoke_bedrock()`, `write_request_ledger()`, `update_monthly_usage()`, or any mutation function.

**Response JSON — status-specific examples**:

Case 1: Band not reached (no prompt needed)
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "month": "2026-03",
  "current_usage_krw": 123456.78,
  "effective_limit_krw": 500000,
  "base_limit_krw": 500000,
  "active_boost_krw": 0,
  "approval_band": 0,
  "has_pending_approval": false,
  "pending_approval_id": null,
  "should_prompt_for_increase": false,
  "can_request_increase": true,
  "recommended_increment_krw": 500000,
  "hard_cap_krw": 2000000,
  "at_hard_cap": false,
  "cooldown_seconds": 0,
  "suppress_reason": null,
  "message": "",
  "evaluated_at": "2026-03-26T10:00:00+00:00"
}
```

Case 2: Band threshold reached, prompt needed
```json
{
  "principal_id": "107650139384#BedrockUser-cgjang",
  "month": "2026-03",
  "current_usage_krw": 480000.0,
  "effective_limit_krw": 500000,
  "base_limit_krw": 500000,
  "active_boost_krw": 0,
  "approval_band": 0,
  "has_pending_approval": false,
  "pending_approval_id": null,
  "should_prompt_for_increase": true,
  "can_request_increase": true,
  "recommended_increment_krw": 500000,
  "hard_cap_krw": 2000000,
  "at_hard_cap": false,
  "cooldown_seconds": 0,
  "suppress_reason": null,
  "message": "이번 달 Bedrock Gateway 한도의 90%에 도달했습니다.",
  "evaluated_at": "2026-03-26T10:00:00+00:00"
}
```

Case 3: Pending approval exists
```json
{
  "should_prompt_for_increase": false,
  "has_pending_approval": true,
  "pending_approval_id": "73004e32-...",
  "suppress_reason": "pending_approval",
  "message": "한도 증액 요청이 관리자 승인 대기 중입니다."
}
```

Case 4: Hard cap reached
```json
{
  "should_prompt_for_increase": false,
  "at_hard_cap": true,
  "can_request_increase": false,
  "suppress_reason": "hard_cap",
  "message": "월간 최대 한도(KRW 2,000,000)에 도달하여 추가 증액이 불가합니다."
}
```

Case 5: No policy defined (exception user or unknown principal)
```json
{
  "error": "no policy defined for principal",
  "principal_id": "107650139384#BedrockUser-unknown"
}
```

**Server-side `should_prompt_for_increase` decision logic**:
```
should_prompt = (
    current_usage_krw >= effective_limit_krw * 0.9   # 90% threshold
    AND NOT has_pending_approval
    AND NOT at_hard_cap
    AND can_request_increase
)
```

The 90% threshold is chosen because:
- At 100% the user is already blocked from inference
- At 90% there's still room to use while the approval is pending
- Matches the existing 30%/10% warning email thresholds conceptually

### E.2 `POST /approval/request` (EXISTING — no change)

Shell hook calls this with the same body as `bedrock-gw-request.sh`:
```json
{
  "reason": "한도 소진 임박으로 증액 요청",
  "requested_increment_krw": 500000
}
```

Response on success (201):
```json
{
  "decision": "ACCEPTED",
  "approval_id": "uuid-...",
  "current_effective_limit_krw": 500000,
  "requested_new_limit_krw": 1000000,
  "message": "한도 증액 요청이 접수되었습니다. 관리자 승인 대기 중입니다."
}
```

Duplicate suppression: existing `ApprovalPendingLock` conditional PutItem handles this.
If lock exists: returns 409 with `"pending approval request already exists"`.


## F. Shell Hook Design

### F.1 File location and loading

Primary file: `/fsx/shared/bedrock-gateway/bedrock-gw-quota-check.sh`
(Also stored in repo at `account-portal/backend-admin/data/bedrock-gw-quota-check.sh`)

Loading options (in order of preference):
1. `/etc/profile.d/bedrock-gw.sh` — system-wide, applies to all login shells
2. Append to user's `~/.bashrc` / `~/.zshrc` — per-user
3. Source from shared FSx path in existing shell init

Content of `/etc/profile.d/bedrock-gw.sh`:
```bash
[ -f /fsx/shared/bedrock-gateway/bedrock-gw-quota-check.sh ] && \
  source /fsx/shared/bedrock-gateway/bedrock-gw-quota-check.sh
```

### F.2 Interactive detection

```bash
# Must pass ALL checks:
[[ -t 0 ]]           # stdin is a terminal
[[ -t 1 ]]           # stdout is a terminal
[[ $- == *i* ]]      # shell is interactive
[[ -z "$CI" ]]       # not in CI
[[ -z "$NONINTERACTIVE" ]]  # not explicitly non-interactive
```

### F.3 Cooldown/cache strategy

| Cache file | Purpose | TTL |
|-----------|---------|-----|
| `~/.cache/bedrock-gw/last-check` | Timestamp of last API call | 5 minutes |
| `~/.cache/bedrock-gw/suppressed` | User declined prompt (n) | 30 minutes |
| `~/.cache/bedrock-gw/session-done` | Already prompted this shell session | Until shell exit |
| `~/.cache/bedrock-gw/last-status.json` | Cached server response | 5 minutes (same as check) |

All files are per-user (`~/.cache/`), no cross-user contamination on shared FSx.

### F.4 Hook timing

**bash**: `PROMPT_COMMAND` — runs before each prompt display.
**zsh**: `precmd` hook — same timing.

The hook function checks cooldown first (file stat, no network call).
If cooldown not expired → return immediately (sub-millisecond).
If cooldown expired → background-capable API call with 3-second timeout.

### F.5 Complete flow

```
Shell prompt about to display
  → _bedrock_gw_check() called
    → Is interactive? No → return
    → Session already done? Yes → return
    → Cooldown file < 5 min old? Yes → return
    → Touch cooldown file (update timestamp)
    → Call GET /quota/status (SigV4, 3s timeout)
      → Timeout/error? → return silently
    → Parse JSON response
    → should_prompt_for_increase == false?
      → has_pending_approval? → print one-line info, mark session-done, return
      → else → return
    → should_prompt_for_increase == true?
      → Display prompt:
        ┌──────────────────────────────────────────────┐
        │ Bedrock Gateway 한도 알림                       │
        │ 현재 유효 한도: KRW 500,000                      │
        │ 현재 사용량:   KRW 480,000                      │
        │ KRW 500,000 증액 요청을 관리자에게 보낼까요?         │
        └──────────────────────────────────────────────┘
      → read y/N (5s timeout)
      → y → POST /approval/request (SigV4)
        → Success → print approval_id, mark session-done
        → 409 (already pending) → print info, mark session-done
        → Error → print error, mark session-done
      → n/timeout → create suppress file, mark session-done
```

### F.6 Performance budget

| Operation | Budget | Mechanism |
|-----------|--------|-----------|
| Cooldown check (no API call) | < 1ms | File stat only |
| API call (when needed) | < 3s hard timeout | `--max-time 3` or equivalent |
| Prompt display + input | User-driven | 5s read timeout |
| Total worst case per prompt | < 4s | Only when cooldown expired AND prompt needed |
| Typical case (cooldown active) | < 1ms | No network, no computation |

### F.7 SigV4 signing

Shell hook uses `python3 -c` with boto3 for SigV4 signing.
boto3 is already installed on all FSx hosts (used by existing `bedrock-gw-request.sh`).
AWS credentials come from existing `credential_source = Ec2InstanceMetadata` in user's `~/.aws/config`.

Alternative considered: `awscurl` — rejected because it's not installed by default.

### F.8 Multi-session / multi-terminal handling

- Each terminal has its own shell process → its own `session-done` marker
- `~/.cache/bedrock-gw/last-check` is shared across terminals → only one API call per 5 minutes regardless of terminal count
- `ApprovalPendingLock` in DynamoDB prevents duplicate request creation even if two terminals both prompt and both get `y` — second POST returns 409
- This is the same race-safe mechanism used by the existing manual script


## G. Failure Points — Critical Analysis

### G.1 Technical failure points

| # | Failure | Severity | Mitigation |
|---|---------|----------|------------|
| T1 | Shell hook runs in non-interactive context | High | 5-layer interactive check (tty, $-, $CI, $NONINTERACTIVE, $TERM) |
| T2 | API call adds latency to every prompt | High | 5-min cooldown. Typical case: file stat only (< 1ms). |
| T3 | API timeout blocks shell | High | 3s hard timeout. On timeout: silent return, no retry. |
| T4 | SigV4 signing fails (no credentials) | Medium | try/except in python3 call. On failure: silent return. |
| T5 | DynamoDB eventual consistency → stale usage data | Low | Same consistency model as existing inference pipeline. Acceptable. |
| T6 | Two terminals both prompt, both get y → duplicate request | Low | `ApprovalPendingLock` conditional PutItem. Second POST returns 409. Shell handles 409 gracefully. |
| T7 | Cache file permissions on shared FSx | Medium | Files in `~/.cache/` (user-owned home dir, 700 permissions). No cross-user access. |
| T8 | python3 not available | Low | All FSx hosts have python3 + boto3. Verified by existing `bedrock-gw-request.sh` usage. |
| T9 | tmux/screen reattach triggers re-check | Low | Session-done marker is per-shell-PID. Reattach creates new shell → new check is appropriate. |
| T10 | `PROMPT_COMMAND` already set by user | Medium | Append to existing `PROMPT_COMMAND`, don't overwrite. Use `PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND;}_bedrock_gw_check"` |

### G.2 Operational failure points

| # | Failure | Severity | Mitigation |
|---|---------|----------|------------|
| O1 | Hook deployed but user's shell doesn't source it | Medium | Use `/etc/profile.d/` for system-wide. Document manual source for edge cases. |
| O2 | bash/zsh incompatibility | Medium | Test both. Use POSIX-compatible constructs where possible. zsh `precmd` vs bash `PROMPT_COMMAND`. |
| O3 | Hook update requires user to restart shell | Low | Acceptable. Hook is sourced at shell start. |
| O4 | Rollback requires touching user shell init | Low | `/etc/profile.d/` file removal is instant system-wide rollback. |
| O5 | Lambda cold start adds latency to first check | Low | Cold start is ~1-2s. Within 3s timeout budget. Subsequent calls are warm. |

### G.3 UX failure points

| # | Failure | Severity | Mitigation |
|---|---------|----------|------------|
| U1 | Prompt too frequent | High | 5-min cooldown + 30-min suppress on decline + session-done marker |
| U2 | Prompt after admin already approved | Medium | Next check (5 min) will see updated effective_limit → no prompt |
| U3 | Prompt after admin rejected | Medium | Next check will see no pending + same band → prompt again. Suppress file (30 min) prevents immediate re-prompt. |
| U4 | Already pending but prompt shows | Low | Server returns `has_pending_approval=true` → shell shows info only, no prompt |
| U5 | Terminal output pollution | Medium | All output uses stderr. Prompt uses `read -p` (stderr). Normal stdout unaffected. |
| U6 | Batch job accidentally gets prompt | High | 5-layer interactive check. `read` with timeout → if no tty, read fails immediately. |

---

## H. Implementation Order (Safe Staged Rollout)

### Stage 1: Server — read-only endpoint (zero risk to existing flows)

1. Add `handle_quota_status()` to `handler.py`
2. Add route in `lambda_handler()`: `GET /quota/status`
3. `terraform plan` → verify only Lambda code hash change
4. `terraform apply`
5. Verify: SigV4 `GET /quota/status` returns correct JSON for cgjang
6. Verify: existing inference still works (regression test)
7. Verify: existing approval request still works

At this point: server is ready, no client changes, zero user impact.

### Stage 2: Shell hook — development + local test

8. Create `bedrock-gw-quota-check.sh`
9. Test locally: source in developer's interactive bash
10. Test: non-interactive detection
11. Test: cooldown behavior
12. Test: prompt display + y/n handling
13. Test: API call + response parsing

At this point: hook works in developer's shell, not deployed to other users.

### Stage 3: Pilot — single user

14. Deploy hook to `/fsx/shared/bedrock-gateway/`
15. Add source line to cgjang's `.bashrc` only
16. Test all 10 scenarios from requirements
17. Monitor for 1-2 days

### Stage 4: Gradual rollout

18. If pilot passes: add `/etc/profile.d/bedrock-gw.sh` for system-wide
19. Monitor for issues
20. Document in runbook

### Rollback at any stage

- Stage 1: `terraform apply` with reverted `handler.py` (removes `/quota/status` route)
- Stage 2: Delete hook file (no user impact)
- Stage 3: Remove source line from cgjang's `.bashrc`
- Stage 4: Delete `/etc/profile.d/bedrock-gw.sh` → instant system-wide removal


## I. Verification Plan

### I.1 Server logic verification

| # | Scenario | Method | Expected |
|---|----------|--------|----------|
| S1 | Band 0, usage < 90% | `GET /quota/status` | `should_prompt=false` |
| S2 | Band 0, usage >= 90% of 500K | `GET /quota/status` | `should_prompt=true` |
| S3 | Pending approval exists | `GET /quota/status` | `should_prompt=false`, `has_pending=true` |
| S4 | Hard cap reached (effective=2M) | `GET /quota/status` | `should_prompt=false`, `at_hard_cap=true` |
| S5 | Active boost exists (band 1) | `GET /quota/status` | `effective_limit=1000000`, `approval_band=1` |
| S6 | After approval: effective limit increased | `GET /quota/status` | Updated `effective_limit`, `should_prompt=false` |
| S7 | After rejection: same band, no pending | `GET /quota/status` | `should_prompt=true` (if still at threshold) |
| S8 | Exception user (shlee) | `GET /quota/status` | Error: no policy |
| S9 | Existing inference unaffected | `POST /converse` | Same behavior as before |
| S10 | Existing approval request unaffected | `POST /approval/request` | Same behavior as before |

### I.2 Shell verification

| # | Scenario | Method | Expected |
|---|----------|--------|----------|
| H1 | Interactive bash | Source hook, trigger check | Prompt appears when server says should_prompt=true |
| H2 | Interactive zsh | Source hook, trigger check | Same behavior |
| H3 | Non-interactive bash | `bash -c 'source hook; echo test'` | No prompt, no output |
| H4 | CI environment (`CI=true`) | Set CI=true, source hook | No prompt |
| H5 | tmux session | Open tmux, source hook | Works normally |
| H6 | Same session re-prompt | Trigger twice in same session | Second time: no prompt (session-done) |
| H7 | Decline suppress | Answer n, wait < 30 min | No re-prompt |
| H8 | Request success | Answer y | approval_id printed, session-done set |
| H9 | API timeout | Block API (iptables or similar) | Silent skip, no shell delay > 3s |
| H10 | Cooldown active | Check twice within 5 min | Second check: no API call |

### I.3 Operational verification

| # | Scenario | Method | Expected |
|---|----------|--------|----------|
| O1 | Existing `bedrock-gw-request.sh` still works | Run manually | Same behavior as before |
| O2 | Admin portal unaffected | Browse portal, check approvals | No change |
| O3 | Mail approval flow unaffected | Trigger approval, check email | No change |
| O4 | Inference pipeline unaffected | SigV4 POST /converse | Same response |
| O5 | Rollback: remove hook | Delete profile.d file | Shell returns to normal |
| O6 | Rollback: revert Lambda | terraform apply with old handler.py | /quota/status returns 405 |

---

## J. Self-Review — Defense Checklist

### 1. Requirements alignment

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| User doesn't need to run manual script | PASS | Shell hook auto-checks on prompt |
| Admin mail approve/reject unchanged | PASS | Zero changes to `gateway_approval.py`, `_send_approval_email()` |
| DynamoDB is source of truth | PASS | `handle_quota_status()` calls `check_quota()` which queries DynamoDB |
| Prompt only at band threshold | PASS | Server decides `should_prompt` based on 90% threshold |
| Server is single source for prompt decision | PASS | `should_prompt_for_increase` computed server-side only |
| Shell is thin client (display + input only) | PASS | Shell does zero business logic computation |
| Manual script kept as fallback | PASS | `bedrock-gw-request.sh` unchanged |

### 2. Architecture separation

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| handler.py doesn't assume shell access | PASS | New endpoint is HTTP request/response only |
| Server/shell responsibilities clearly separated | PASS | See responsibility matrix in §B |
| No business logic in shell | PASS | Shell only reads JSON fields and displays |
| Request creation reuses existing endpoint | PASS | Shell calls `POST /approval/request` — same as manual script |
| Status endpoint is read-only | PASS | Zero DynamoDB writes in `handle_quota_status()` |

### 3. Operational safety

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Inference path unaffected | PASS | New route is before inference check in `lambda_handler()`. Inference routing unchanged. |
| Admin portal unaffected | PASS | Zero changes to `gateway_approval.py`, `gateway_usage.py` |
| Mail flow unaffected | PASS | Zero changes to email-action endpoint or `_send_approval_email()` |
| IAM verified | PASS | All needed DynamoDB read permissions already in `DynamoDBReadWriteNonLedger` |
| API Gateway routing verified | PASS | `{proxy+}` routes all paths. No Terraform change needed. |
| Rollback path exists | PASS | 4-stage rollback plan in §H |
| Shell hook failure doesn't block user | PASS | All errors caught, silent return, 3s timeout |

### 4. Shell realism

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| bash supported | PASS | `PROMPT_COMMAND` hook |
| zsh supported | PASS | `precmd` hook |
| Interactive-only | PASS | 5-layer check |
| Non-interactive blocked | PASS | tty + $- + $CI + $NONINTERACTIVE + $TERM checks |
| tmux/screen considered | PASS | Per-PID session marker, reattach = new shell = new check |
| Multi-session duplicate prevention | PASS | `ApprovalPendingLock` + shared cooldown file |
| Cache designed realistically | PASS | Per-user `~/.cache/`, file timestamps, no cross-user contamination |
| Startup latency controlled | PASS | Cooldown check is file stat only (< 1ms). API call only every 5 min. |

### 5. Data accuracy

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Usage calculation same as enforcement | PASS | Both use `check_quota()` |
| Effective limit includes base + boosts | PASS | `check_quota()` sums active boosts, caps at hard cap |
| Pending approval accurately detected | PASS | GetItem on `approval_pending_lock`, TTL check |
| Hard cap reflected | PASS | `at_hard_cap` field in response |
| Race condition handled | PASS | `ApprovalPendingLock` conditional PutItem |
| Eventual consistency acknowledged | PASS | Same model as inference pipeline. Acceptable for 5-min polling. |

### 6. UX

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Not too frequent | PASS | 5-min cooldown + 30-min suppress + session-done |
| Not after rejection | PASS | 30-min suppress after decline. Server re-evaluates after suppress expires. |
| Not when pending | PASS | Server returns `should_prompt=false` when pending |
| Not after approval in same session | PASS | Session-done marker |
| Clean output | PASS | stderr only, no stdout pollution |
| Timeout/failure silent | PASS | All errors → silent return |

### 7. Change scope identification

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Required changes identified | PASS | 2 files: handler.py, new shell hook |
| Recommended changes identified | PASS | profile.d integration, runbook, todo |
| Unchanged files verified with evidence | PASS | 15 items in "MUST NOT change" list with reasons |
| Documentation needs identified | PASS | Runbook update, user guide |

### 8. Verification plan

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Server unit test scenarios | PASS | 10 scenarios in §I.1 |
| Shell test scenarios | PASS | 10 scenarios in §I.2 |
| Operational test scenarios | PASS | 6 scenarios in §I.3 |
| Partial failure scenarios | PASS | T1-T10 in §G.1 |
| Pilot/gradual rollout plan | PASS | 4-stage plan in §H |

### 9. Defensive self-review

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Server/shell boundary not confused | PASS | Responsibility matrix explicit |
| Not designing from scratch | PASS | Reuses check_quota(), handle_approval_request(), existing tables |
| Not sacrificing operational reality for simplicity | PASS | 4-stage rollout, per-user pilot, rollback at each stage |
| No duplicate logic | PASS | `handle_quota_status()` calls `check_quota()`, doesn't reimplement |
| Rollback exists | PASS | Each stage independently reversible |
| Not overpromising | PASS | Acknowledged: window.close impossible, eventual consistency, cold start latency |

### 10. Final approval readiness

| Check | Pass/Fail | Evidence |
|-------|-----------|---------|
| Implementable on current system | PASS | All dependencies exist (boto3, SigV4, DynamoDB tables, API Gateway routing) |
| Meets requirements operationally | PASS | All 10 test scenarios mapped |
| Reversible on failure | PASS | 4-stage rollback |
| Extensible | PASS | `/quota/status` can be used by future clients (SDK helper, IDE plugin, etc.) |
| Recommended as final implementation plan | PASS | Single coherent design, no alternatives needed |

---

## K. Final Recommendation

This design is ready for implementation approval. It adds exactly 2 files (handler.py modification + new shell hook), requires one `terraform apply` (Lambda code hash only), and has rollback at every stage.

The design reuses all existing server-side logic without duplication, maintains strict server/client separation, and does not touch any existing inference, approval, portal, or email flows.

---

## Boundary Statement

This document is a design review artifact. No runtime code, IaC, or deployment changes have been made. Implementation requires explicit approval.
