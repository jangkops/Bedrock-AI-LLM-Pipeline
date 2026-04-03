# Decision Resolution: Open Questions Q1–Q6

> Date: 2026-03-18
> Phase: Phase 0 prerequisite resolution (no implementation)
> Status: APPROVED (2026-03-18) — all Q1-Q6 decisions approved by operator
> Trigger: Governance review found `gateway_approval.py` (Phase 4) created before Phase 0 decisions resolved
> Approval: Operator approved all 6 recommendations on 2026-03-18. No modifications to recommendations.

---

## Context

The governance review of `gateway_approval.py` identified that Phase 4 (Admin API) was started before Phase 0 (Open Questions Q1–Q6) was resolved. This document provides concrete recommendations for each question, their downstream impact, and the execution order to unblock Phases 1–4.

`gateway_approval.py` is technically valid but procedurally premature. It remains frozen (no extension) until these decisions are finalized and Phases 1–3 complete.

---

## Q1: KRW Pricing Source / Exchange Rate Handling

### Recommendation: Fixed KRW rates in ModelPricing DynamoDB table, admin-managed. No real-time FX.

### Rationale

- The codebase already has a real-time exchange rate utility (`backend-cost/utils/exchange_rate.py`) that calls the Bank of Korea API. However, this is in `backend-cost` (a separate service) and depends on Redis — neither of which the Lambda has access to.
- Lambda is serverless with no Redis dependency. Adding a real-time FX API call to every inference request adds latency, a new failure mode, and a new external dependency to the critical path.
- AWS Bedrock pricing changes infrequently (quarterly at most). USD→KRW exchange rate fluctuates daily but the operational budget model (KRW 10M/month) is a planning number, not a financial accounting system.
- Admin updates the ModelPricing table periodically (e.g. monthly or when AWS pricing changes). This is operationally simple and eliminates runtime FX dependency.

### Impact if adopted

| File | Impact |
|------|--------|
| `infra/bedrock-gateway/dynamodb.tf` | Add ModelPricing table (Task 1.1) |
| `infra/bedrock-gateway/lambda/handler.py` | Add `lookup_model_pricing()`, cache at cold start (Task 2.1) |
| `infra/bedrock-gateway/lambda.tf` | Add `TABLE_MODEL_PRICING` env var |
| `infra/bedrock-gateway/iam.tf` | Add ModelPricing table ARN to DynamoDB read policy |
| `gateway_approval.py` | No change needed — approval routes don't reference pricing |

### What does NOT change
- No Redis dependency added to Lambda
- No real-time FX API call in inference path
- `backend-cost/utils/exchange_rate.py` remains untouched (separate service)

---

## Q2: Global Budget — Hard Enforcement vs Alerting-Only

### Recommendation: Alerting-only for v1. No hard enforcement on global budget.

### Rationale

- Hard enforcement on a single global counter (`GlobalBudget` table, PK: `YYYY-MM`) creates a DynamoDB hot key under concurrent load. Every inference request from every user would atomic-ADD to the same item.
- With 20 users and moderate concurrency, this is manageable. But it's an unnecessary single point of contention when per-user enforcement already caps individual spend.
- Per-user hard cap (KRW 2M) × 20 users = KRW 40M theoretical max, but realistic spend is bounded by actual usage patterns. The KRW 10M global budget is a planning/alerting threshold, not a billing hard stop.
- v1: CloudWatch alarm when sum of MonthlyUsage across all principals approaches 80%/90%/100% of KRW 10M. Admin receives alert. No automated request blocking at global level.
- v2: If hard enforcement is needed, add GlobalBudget counter with conditional check.

### Impact if adopted

| File | Impact |
|------|--------|
| `infra/bedrock-gateway/dynamodb.tf` | No GlobalBudget table in v1 (Task 1.7 deferred) |
| `infra/bedrock-gateway/lambda/handler.py` | No global budget check in inference path |
| `gateway_approval.py` | No change needed |
| Monitoring | CloudWatch metric filter + alarm on MonthlyUsage sum (operational setup, not code) |

---

## Q3: Monthly Reset Boundary — UTC vs KST

### Recommendation: KST (Asia/Seoul, UTC+9) for the monthly budget boundary.

### Rationale — why KST, not UTC

- The organization operates in Korea. Budget cycles, approvals, and user expectations are KST-aligned.
- "End of month" means end of the Korean business day, not UTC midnight (which is 09:00 KST next day).
- A user working at 23:30 KST on March 31 expects their budget to reset at KST midnight, not 9 hours earlier (UTC midnight = 09:00 KST March 31).
- The approval ladder routes to a Korean team lead (`changgeun.jang@mogam.er.kr`). Budget conversations happen in KST context.
- The existing `backend-cost` service handles Korean financial data (Bank of Korea exchange rates). Aligning the gateway budget boundary to KST is consistent.
- UTC would create a 9-hour misalignment where the budget resets mid-morning KST — confusing for users and admins.

### Current UTC assumptions that must be corrected

| Location | Current Code | Required Change |
|----------|-------------|-----------------|
| `handler.py:check_quota()` line ~280 | `datetime.now(timezone.utc).strftime("%Y-%m-%d")` | Change to KST date for monthly partition key (`YYYY-MM`) |
| `handler.py:update_daily_usage()` line ~340 | `datetime.now(timezone.utc).strftime("%Y-%m-%d")` | Change to KST date (this function becomes `update_monthly_usage()`) |
| `gateway_approval.py:_end_of_month_ttl()` | `datetime.now(timezone.utc)` + `monthrange` → UTC EOM | Change to KST EOM: last day of month at 23:59:59 KST |
| `handler.py:handle_approval_request()` line ~380 | Lock TTL uses `time.time()` (epoch, timezone-neutral) | OK as-is — epoch is timezone-neutral. But the 7-day TTL concept is unaffected. |
| MonthlyUsage PK format | `<principal_id>#YYYY-MM` | The `YYYY-MM` must be derived from KST date, not UTC |
| MonthlyUsage TTL | ~35 days from record creation | OK as-is — TTL is relative, not boundary-dependent |

### Implementation pattern

```python
from datetime import timezone, timedelta
KST = timezone(timedelta(hours=9))

def current_month_kst() -> str:
    """Return current month as YYYY-MM in KST."""
    return datetime.now(KST).strftime("%Y-%m")

def end_of_month_ttl_kst() -> int:
    """Return Unix epoch for end of current month in KST."""
    now = datetime.now(KST)
    _, last_day = monthrange(now.year, now.month)
    eom = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=KST)
    return int(eom.timestamp())
```

### Impact if adopted

| File | Impact |
|------|--------|
| `handler.py` | `check_quota()` and `update_monthly_usage()` use KST for month partition key (Phase 2 rewrite) |
| `gateway_approval.py` | `_end_of_month_ttl()` must use KST instead of UTC — **revision needed after Phase 3** |
| `design.md` | Document KST boundary decision |
| `requirements.md` | Req 4 acceptance criteria: "Monthly reset at KST month boundary" |

### Risk

- DynamoDB TTL is epoch-based (timezone-neutral). No TTL issue.
- CloudWatch timestamps are UTC. Log correlation requires awareness that budget boundaries are KST.
- If the organization later expands to non-KST regions, the boundary decision may need revisiting. Acceptable for v1 (single-region, Korean org).

---

## Q4: Boost Duration — End of Month vs 30 Days

### Recommendation: End of current month (KST).

### Rationale

- Aligns with the monthly budget cycle. A boost approved on March 15 expires at March 31 23:59:59 KST, not April 14.
- Simpler mental model for users and admins: "your boost lasts until the end of this month."
- Next month, the user starts fresh with the base budget and must request a new boost if needed.
- 30-day rolling boosts create complexity: a boost approved March 25 would extend into April, overlapping with the new month's fresh budget. This makes effective limit calculation ambiguous across month boundaries.

### Impact if adopted

| File | Impact |
|------|--------|
| `gateway_approval.py:_end_of_month_ttl()` | Already implements end-of-month, but uses UTC. Must change to KST per Q3. |
| `handler.py:handle_approval_request()` | Lock TTL (7 days) is independent of boost duration — no change. |
| `design.md` | Document: "Boost TTL = end of current month (KST)" |

### Dependency on Q3

Q4 inherits Q3's timezone decision. If Q3 = KST, then boost expiry = end of month KST. The two decisions are coupled.

---

## Q5: Approval Action Method — Deep Link vs Signed URL

### Recommendation: Deep link to Admin UI for v1. Signed URL is v2.

### Rationale

- Deep link is already implemented in both `handler.py:_send_approval_email()` (Lambda side) and `gateway_approval.py` (admin API side).
- Signed URL requires: new API Gateway route, time-limited token generation, single-use enforcement, and security review. This is significant scope for v1.
- The admin portal already has authentication. Deep link leverages existing auth.
- The team lead (approver) already uses the admin portal for other operations.

### Impact if adopted

| File | Impact |
|------|--------|
| All files | No change — deep link is already the implemented pattern |
| `design.md` | Document: "v1: deep link. v2: signed URL one-click approval." |

---

## Q6: Token Counts in MonthlyUsage for Audit

### Recommendation: Yes, keep `input_tokens` and `output_tokens` in MonthlyUsage alongside `cost_krw`.

### Rationale

- Token counts are the raw measurement. Cost is derived (tokens × pricing). If pricing data is later found to be incorrect, token counts allow retroactive cost recalculation.
- Operational debugging: "why is this user's cost so high?" → check token counts per model.
- Minimal storage overhead: two additional Number attributes per MonthlyUsage record.
- RequestLedger already stores per-request token counts. MonthlyUsage aggregates provide quick summary without scanning the ledger.

### Impact if adopted

| File | Impact |
|------|--------|
| `dynamodb.tf` | MonthlyUsage table includes `cost_krw`, `input_tokens`, `output_tokens` fields (no schema change needed — DynamoDB is schemaless for non-key attributes) |
| `handler.py:update_monthly_usage()` | Atomic ADD for all three fields: `cost_krw`, `input_tokens`, `output_tokens` |
| `gateway_approval.py` | No change needed — approval routes don't reference usage details |

---

## Impact on `gateway_approval.py`

### Safe to keep as-is

| Aspect | Status |
|--------|--------|
| KRW approval ladder constants (500K increment, 2M cap) | Correct — matches design.md |
| `_get_effective_limit()` logic | Correct — reads `monthly_cost_limit_krw`, sums `extra_cost_krw` boosts |
| Approve/reject flow | Correct — creates boost, deletes lock, sends SES |
| DynamoDB table naming | Correct — uses `bedrock-gw-${env}-${region}-${table}` pattern |
| Blueprint registration in `app.py` | Correct — additive, no existing routes affected |

### Must be revisited after Q3 decision is finalized

| Aspect | Issue | Required Change |
|--------|-------|-----------------|
| `_end_of_month_ttl()` | Uses `datetime.now(timezone.utc)` | Must change to KST if Q3 = KST |

This is a one-line change (`timezone.utc` → `KST`) but should not be made until Phase 3 (Approval Ladder Rewrite) is formally in scope.

### Not affected by any Q1–Q6 decision

- List approvals route
- Get single approval route
- Approve route (except TTL timezone)
- Reject route
- SES notification logic
- Decimal serialization

---

## Recommended Execution Order

### Step 0: Decision Approval (this document)

Operator reviews and approves Q1–Q6 recommendations. No code changes.

### Step 1: Update Governance Artifacts

After Q1–Q6 approval, update:
- `requirements.md` — close Open Questions table, update Req 4/5 acceptance criteria
- `design.md` — update Locked Decisions, add KST boundary, add ModelPricing table
- `tasks.md` — mark Task 0.1 complete, update Phase 1–3 task descriptions
- `docs/ai/research.md` — add Q1–Q6 resolution section
- `docs/ai/todo.md` — update Phase 0 status
- `docs/ai/risk_register.md` — add pricing staleness risk, close Q-related open items

### Step 2: Phase 1 — Data Model (requires separate approval)

- Task 1.1: Add ModelPricing table to `dynamodb.tf`
- Task 1.2: Rename DailyUsage → MonthlyUsage in `dynamodb.tf` + Lambda env vars
- Task 1.3: Update PrincipalPolicy schema documentation (DynamoDB is schemaless — the schema change is in Lambda code that reads/writes the fields)
- Task 1.4: Update TemporaryQuotaBoost schema documentation
- Task 1.5: Update ApprovalRequest schema documentation
- Task 1.6: Update RequestLedger schema documentation (add `estimated_cost_krw`)
- Task 1.7: Deferred (GlobalBudget — alerting-only, no table needed)

### Step 3: Phase 2 — Lambda Quota Logic Rewrite (requires separate approval)

- Task 2.1: `lookup_model_pricing()` with cold-start cache
- Task 2.2: `estimate_cost_krw()` function
- Task 2.3: Rewrite `check_quota()` → KRW monthly, KST boundary
- Task 2.4: Rewrite `update_daily_usage()` → `update_monthly_usage()`
- Task 2.5: Update `get_effective_limit()` for KRW model
- Task 2.6: Add `estimated_cost_krw` to ledger writes
- Task 2.7: Wire pricing lookup into main handler flow

### Step 4: Phase 3 — Approval Ladder Rewrite (requires separate approval)

- Task 3.1: Update `handle_approval_request()` in Lambda — validate reason, fixed increment, hard cap
- Task 3.2: Update `handle_approval_decision()` in Lambda — KRW boost, KST EOM TTL
- Task 3.3: Update SES email templates — KRW amounts, team lead routing

### Step 5: Phase 4 — Admin API Continuation (requires separate approval)

- Task 4.1: `gateway_policy.py` — KRW fields
- Task 4.2: `gateway_pricing.py` — ModelPricing CRUD (new file)
- Task 4.3: `gateway_usage.py` — MonthlyUsage queries (new file)
- Task 4.4: `gateway_approval.py` — fix `_end_of_month_ttl()` to KST, add reason display
- Unfreeze `gateway_approval.py` for extension

Each step requires its own explicit approval per devops-operating-model.md.

---

## Current File Disposition

| File | Status |
|------|--------|
| `gateway_approval.py` | Frozen. Do not extend. One known revision needed (Q3 KST timezone) but deferred to Phase 4. |
| `app.py` | Blueprint registration is harmless. No change needed. |
| `handler.py` | Frozen for quota/approval logic. Phase 2–3 rewrites pending. |
| `dynamodb.tf` | Frozen. Phase 1 schema changes pending. |
| All other IaC | Frozen. |

---

## No-Change Confirmation

This document is a governance/planning artifact only. No runtime code, IaC, deployment configs, or infrastructure were modified.

Created: `docs/ai/decision-resolution-q1-q6.md` (this file)
Modified: none
