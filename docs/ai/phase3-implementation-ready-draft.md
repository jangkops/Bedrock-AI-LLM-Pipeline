# Phase 3: Approval Ladder Rewrite — Implementation-Ready Draft

> Date: 2026-03-23
> Status: IMPLEMENTED AND VERIFIED — Phase 3 deployed to dev and all critical AC pass
> Prerequisites: Phase 2 dev validation COMPLETE (2026-03-20). Phase 3 semantics documented (`phase3-approval-ladder-semantics.md`).
> Scope: Lambda `handle_approval_request()` hardening + `gateway_approval.py` UTC→KST fix + SES template updates
> Final validation report: `docs/ai/phase3-dev-validation-report.md`

---

## 1. Problem Statement

Phase 2 deployed the KRW cost-based monthly quota pipeline. The approval ladder code exists in both `handler.py` (Lambda-side request submission) and `gateway_approval.py` (admin-side approve/reject), but has three categories of gaps:

1. **Missing input validation** in Lambda's `handle_approval_request()` — no reason validation, no increment validation, no hard cap pre-validation
2. **UTC→KST TTL bug** in `gateway_approval.py:_end_of_month_ttl()` — boost TTL uses UTC month boundary instead of KST (Q3/Q4 decision)
3. **SES email content** references UTC instead of KST

These are all documented in `phase3-approval-ladder-semantics.md` §5.

---

## 2. Current-State Constraints

### What exists and works
- `handler.py:handle_approval_request()` — creates ApprovalPendingLock + ApprovalRequest + sends SES. Functional but lacks validation.
- `gateway_approval.py:approve_request()` — creates TemporaryQuotaBoost with `extra_cost_krw: 500000`, deletes lock, sends SES. Hard cap check works. TTL uses UTC (bug).
- `gateway_approval.py:reject_request()` — updates status, deletes lock, sends SES. Functional.
- `gateway_approval.py:_get_effective_limit()` — correct formula: `base + sum(active boosts)`, capped at hard cap.
- `handler.py:check_quota()` — correct effective limit calculation, identical formula.

### What needs correction
| Issue | File | Function | Severity |
|-------|------|----------|----------|
| No `reason` non-empty validation | `handler.py` | `handle_approval_request()` | Medium |
| No `requested_increment_krw == 500000` validation | `handler.py` | `handle_approval_request()` | Medium |
| No hard cap pre-validation (`effective + 500K ≤ 2M`) | `handler.py` | `handle_approval_request()` | Medium |
| `_end_of_month_ttl()` uses UTC, not KST | `gateway_approval.py` | `_end_of_month_ttl()` | Medium |
| SES email says "end of current month (UTC)" | `gateway_approval.py` | `approve_request()` | Low |
| Lambda SES email lacks KRW context | `handler.py` | `_send_approval_email()` | Low |

---

## 3. Exact Requirements (from tasks.md Phase 3)

### Task 3.1: Update handle_approval_request()
- Validate `reason` field is non-empty string (reject with 400 if empty/whitespace)
- Validate `requested_increment_krw == 500000` (reject with 400 if missing or wrong value)
- Check hard cap: `effective_limit + 500000 ≤ 2,000,000` (reject with 422 if exceeded)
- Store `reason`, `requested_amount_krw`, `approver_email` in ApprovalRequest record
- Route SES notification to approver (env var: `SES_APPROVER_EMAIL` or `SES_ADMIN_GROUP_EMAIL`)

### Task 3.2: Update handle_approval_decision()
- On approve: create TemporaryQuotaBoost with `extra_cost_krw: 500000`
- Set TTL to end of current month (KST) — fix UTC→KST bug
- Delete ApprovalPendingLock
- Send SES confirmation to user with new effective limit
- On reject: update ApprovalRequest status, delete lock, notify user

### Task 3.3: Update SES Email Templates
- Approval request email: include principal, current limit, requested new limit, reason, deep link
- Approval confirmation email: include new effective limit
- Rejection email: include rejection notice
- All emails reference KST, not UTC

---

## 4. Data Model Implications

**No new tables required.** Phase 3 uses existing tables only.

**No schema changes required.** The `ApprovalRequest` table already accepts arbitrary fields via DynamoDB's schemaless nature. Adding `reason`, `requested_amount_krw`, `approver_email` fields is a write-time change only.

**Existing fields used:**
| Table | Field | Phase 3 Usage |
|-------|-------|---------------|
| `approval_request` | `reason` (S) | Already written by Lambda (from request body). Phase 3 adds non-empty validation. |
| `approval_request` | `requested_amount_krw` (N) | New field. Fixed value 500000. |
| `approval_request` | `approver_email` (S) | New field. From env var. |
| `temporary_quota_boost` | `extra_cost_krw` (N) | Already written by `gateway_approval.py`. Value 500000. |
| `temporary_quota_boost` | `ttl` (N) | Already written. Phase 3 fixes UTC→KST. |

---

## 5. Code Changes — Exact Locations

### 5.1 handler.py — `handle_approval_request()` (lines ~590-650)

**Current code** (abbreviated):
```python
def handle_approval_request(principal_id, identity_fields, request_body, request_id):
    # Step 1: Acquire lock (race-safe) — CORRECT, no change
    # Step 2: Create ApprovalRequest — NEEDS VALIDATION BEFORE THIS
    reason = request_body.get("reason", "")
    # ... creates record without validation ...
```

**Required changes:**
1. After extracting `reason`, validate non-empty: `if not reason or not reason.strip():`→ return 400
2. Extract and validate `requested_increment_krw`: must equal 500000
3. Before lock acquisition, compute effective limit and check hard cap
4. Add `requested_amount_krw`, `approver_email` to ApprovalRequest record
5. Update SES email to include current limit, requested new limit, reason

**Validation order** (before lock acquisition to avoid orphan locks):
```
1. Validate reason non-empty
2. Validate requested_increment_krw == 500000
3. Lookup effective limit (reuse check_quota logic or _get_effective_limit equivalent)
4. Check: effective_limit + 500000 <= 2,000,000
5. Acquire lock
6. Create ApprovalRequest (with enriched fields)
7. Send SES
```

Moving validation before lock acquisition is important — if validation fails, we don't want to leave an orphan lock that blocks future requests until TTL expiry.

### 5.2 gateway_approval.py — `_end_of_month_ttl()` (line ~80)

**Current code:**
```python
def _end_of_month_ttl() -> int:
    now = datetime.now(timezone.utc)
    _, last_day = monthrange(now.year, now.month)
    eom = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return int(eom.timestamp())
```

**Required change:**
```python
from datetime import timedelta
KST = timezone(timedelta(hours=9))

def _end_of_month_ttl() -> int:
    now = datetime.now(KST)
    _, last_day = monthrange(now.year, now.month)
    eom = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=KST)
    return int(eom.timestamp())
```

**Edge case**: If called at 00:01 KST on April 1, `now` is April in KST. The EOM is April 30 23:59:59 KST. Correct.
If called at 23:59 UTC on March 31 (= 08:59 KST April 1), `now` in KST is April 1. EOM is April 30. Correct — the boost applies to the new month.

### 5.3 gateway_approval.py — `approve_request()` SES body (line ~230)

**Current:**
```python
f'Expires: end of current month (UTC)\n'
```

**Required:**
```python
f'Expires: end of current month (KST)\n'
```

### 5.4 handler.py — `_send_approval_email()` (lines ~640-680)

**Current:** Sends basic email with principal, approval_id, reason, deep link.

**Required additions:**
- Current effective limit (KRW)
- Requested new limit (KRW)
- Requested increment (KRW 500,000)

---

## 6. Blast Radius Assessment

| Component | Affected | Change Type |
|-----------|----------|-------------|
| `handler.py` | Yes | Add validation logic before lock acquisition in `handle_approval_request()`. Enrich SES email. No changes to inference pipeline. |
| `gateway_approval.py` | Yes | Fix `_end_of_month_ttl()` UTC→KST. Fix SES email text. No changes to approve/reject logic. |
| `dynamodb.tf` | No | No table changes. |
| `lambda.tf` | No | No env var changes (SES vars already exist). |
| `iam.tf` | No | No IAM changes. |
| Inference pipeline | No | `lambda_handler()` inference path is untouched. Only `/approval/request` route affected. |
| `check_quota()` | No | Unchanged. |
| `update_monthly_usage()` | No | Unchanged. |

**Risk**: Low. Changes are confined to the approval request/decision path. The inference pipeline (pricing → quota → bedrock → usage → ledger) is completely untouched.

---

## 7. Testing Strategy

### Unit Tests (handler.py validation)
1. Empty reason → 400
2. Whitespace-only reason → 400
3. Missing `requested_increment_krw` → 400
4. Wrong increment value (e.g., 100000) → 400
5. Hard cap exceeded (effective=2M, request +500K) → 422
6. Valid request at band 0 → lock acquired, ApprovalRequest created
7. Valid request at band 2 → lock acquired (effective=1.5M + 500K = 2M ≤ 2M)

### Unit Tests (gateway_approval.py TTL fix)
1. `_end_of_month_ttl()` returns KST EOM, not UTC EOM
2. Cross-midnight edge case: UTC 15:00 March 31 = KST 00:00 April 1 → EOM should be April 30 KST

### Integration Tests (approval flow)
1. Submit valid request → pending, SES sent
2. Approve → boost created with KST TTL, lock deleted
3. Reject → status updated, lock deleted
4. Submit when at hard cap → 422 before lock acquisition
5. Submit with pending lock → 409

---

## 8. Acceptance Criteria

| # | Criterion | Validation Method |
|---|-----------|-------------------|
| AC1 | Empty/whitespace reason rejected with 400 | Unit test |
| AC2 | Wrong increment value rejected with 400 | Unit test |
| AC3 | Hard cap pre-validation rejects before lock acquisition | Unit test: verify no lock created when cap exceeded |
| AC4 | `_end_of_month_ttl()` returns KST-based epoch | Unit test: compare against known KST EOM |
| AC5 | Boost TTL in DynamoDB is KST EOM, not UTC EOM | Integration test: approve, read boost, verify TTL |
| AC6 | SES emails reference KST, not UTC | Code review |
| AC7 | ApprovalRequest record includes `reason`, `requested_amount_krw`, `approver_email` | Integration test: submit, read record |
| AC8 | Inference pipeline unaffected | Smoke test: existing cgjang inference still works after deploy |
| AC9 | Existing approval/rejection flow still works | Integration test: full approve + reject cycle |

---

## 9. Rollout Considerations

### Deploy sequence
1. Update `handler.py` with validation logic
2. Update `gateway_approval.py` with KST fix + SES text
3. `terraform plan` — expect Lambda function update only (code hash change)
4. `terraform apply` — Lambda + alias updated
5. Docker rebuild for backend-admin (gateway_approval.py change)
6. Smoke test: inference pipeline unaffected
7. Test: submit approval request with empty reason → 400
8. Test: submit valid approval request → pending
9. Test: approve → boost with KST TTL

### Rollback
- Lambda: `git checkout handler.py` + `terraform apply` (reverts to pre-Phase-3 validation-less code)
- backend-admin: `git checkout gateway_approval.py` + Docker rebuild
- No DynamoDB changes to revert
- Boosts created with KST TTL during Phase 3 are harmless — they expire correctly (KST EOM ≈ UTC EOM ± 9 hours)

### Risk notes
- The UTC→KST TTL difference is at most 9 hours. Boosts created before the fix expire up to 9 hours early (UTC EOM < KST EOM). This is operationally negligible for monthly boosts.
- Validation changes are additive — they reject previously-accepted bad inputs. No existing valid requests are affected.

---

## 10. Phase Ownership

This is Phase 3 scope. All changes are within the approval ladder rewrite boundary defined in `tasks.md`.

No Phase 4 (admin API) or Phase 5 (frontend) work is included or implied.

---

## 11. Dependencies

| Dependency | Status | Blocking? |
|------------|--------|-----------|
| Phase 2 complete | ✅ COMPLETE | No |
| Phase 3 semantics documented | ✅ COMPLETE (`phase3-approval-ladder-semantics.md`) | No |
| Operator approval for Phase 3 | ✅ GRANTED (2026-03-22) | No |
| Terraform apply (Lambda) | ✅ COMPLETE (2026-03-23) — `0 added, 1 changed, 0 destroyed` | No |
| Docker rebuild (backend-admin) | ✅ COMPLETE (2026-03-23) — running healthy | No |
| Dev validation (AC1-AC9) | ✅ COMPLETE (2026-03-23) — all critical AC pass | No |
| SES domain verification (`mogam.er.kr`) | ❌ UNVERIFIED (R23) | Partially — SES sends will fail silently if domain is wrong. Core logic works regardless. |
| Approval endpoint authorization (`@admin_required`) | ✅ VERIFIED (R26) | No — `@admin_required` decorator already applied in `gateway_approval.py`. Phase 3 preserves this. |

---

## Boundary Statement

This document was originally a governance/planning artifact. Phase 3 implementation was approved (2026-03-22), deployed, and verified (2026-03-23). See `docs/ai/phase3-dev-validation-report.md` for final validation results.
