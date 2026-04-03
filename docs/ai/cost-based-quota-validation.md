# Cost-Based Quota Requirements — Validation Against Existing Architecture

> Date: 2026-03-18
> Phase: Research + Planning (Phase 1-2). No implementation.
> Scope: Validate new KRW cost-based quota requirements against existing specs, code, infrastructure, hooks.

---

## 1. Validation Summary

The user's new requirements introduce a fundamental shift from **token-count-based daily quota** to **KRW cost-based monthly quota** with an approval ladder. This is a significant architectural change that touches the core enforcement pipeline, DynamoDB schema, approval flow, and admin UI.

**Key finding**: The current implementation (handler.py, DynamoDB schema, specs) is built entirely around **daily token-count quotas** (input/output tokens, per-day). The new requirements demand **monthly KRW cost aggregation** across all models. These are structurally incompatible — the change is not a parameter tweak but a quota model replacement.

**Verdict**: The new requirements are architecturally sound and fit within the existing serverless framework (API Gateway + Lambda + DynamoDB). However, they require coordinated changes across Lambda code, DynamoDB schema, Terraform, specs, and steering files. No existing code can be reused as-is for cost-based enforcement — the quota pipeline must be redesigned.

---

## 2. Architecture Fit / Mismatch Assessment

### Fits well (no structural conflict)

| Aspect | Assessment |
|--------|-----------|
| API Gateway + Lambda + DynamoDB serverless model | KRW cost tracking fits the same DynamoDB atomic-update pattern |
| Per-user assume-role identity model | Unchanged — `<account>#<role-name>` exact-match principal_id |
| Idempotency (IdempotencyRecord) | Unchanged — request dedup is orthogonal to quota model |
| RequestLedger immutable audit | Unchanged — add `estimated_cost_krw` field to ledger entries |
| SessionMetadata | Unchanged |
| SigV4 / AWS_IAM auth | Unchanged |
| Deny-by-default fail-closed | Unchanged |
| SES approval notification | Fits — route to team lead email instead of admin group |

### Structural mismatches (require redesign)

| Current | New Requirement | Impact |
|---------|----------------|--------|
| Daily token quota (`daily_input_token_limit`, `daily_output_token_limit`) | Monthly KRW cost quota (`monthly_cost_limit_krw`) | PrincipalPolicy schema change, check_quota() rewrite |
| DailyUsage table (PK: `principal_id#date`, SK: `model_id`, fields: `input_tokens`, `output_tokens`) | MonthlyUsage table (PK: `principal_id#YYYY-MM`, fields: `total_cost_krw`) | New table or table redesign, TTL change (25h → ~32d) |
| Token-count comparison (`total_input < limit`) | KRW cost comparison (`total_cost_krw < limit_krw`) | Need cost-per-token pricing table or per-model cost calculation |
| TemporaryQuotaBoost (extra tokens, TTL-based) | Approval ladder (KRW 500K increments, hard cap 2M) | Boost model changes from additive tokens to stepped KRW tiers |
| Approval email → admin group (`SES_ADMIN_GROUP_EMAIL`) | Approval email → team lead (temp: `changgeun.jang@mogam.er.kr`) | Routing change, per-principal or global approver config |
| No reason field required for approval | User must provide reason | Request body validation change |
| Global monthly budget concept does not exist | KRW 10,000,000 / 20 users global budget | New global budget tracking (optional enforcement or reporting-only) |

---

## 3. Exact Spec Files to Update

| File | Sections Requiring Update |
|------|--------------------------|
| `.kiro/specs/bedrock-access-gateway/requirements.md` | Req 4 (Token-Based → Cost-Based), Req 5 (Approval Workflow — ladder, reason, routing), Glossary (Token_Quota → Cost_Quota, new terms) |
| `.kiro/specs/bedrock-access-gateway/design.md` | Locked Decision #8 (Global quota + model-level accounting → KRW cost-based), Architecture diagram (DailyUsage → MonthlyUsage), Overview section |
| `.kiro/specs/bedrock-access-gateway/tasks.md` | Task 6 (quota enforcement rewrite), Task 9 (approval ladder), Task 11-13 (admin/user UI for KRW display) |

---

## 4. Exact Steering Files to Update

| File | Change |
|------|--------|
| `.kiro/steering/tech.md` | Add: "Quota model: KRW cost-based monthly, not token-count daily" |
| `.kiro/steering/product.md` | Update Bedrock Gateway feature description to mention KRW cost-based quotas |
| `.kiro/steering/structure.md` | No change needed (directory structure unchanged) |
| `.kiro/steering/devops-operating-model.md` | No change needed (governance model unchanged) |

---

## 5. Exact Hook Files to Update

| File | Change Needed |
|------|---------------|
| `.kiro/hooks/approval-gate-check.kiro.hook` | No change — already covers `infra/**/*.tf` and `account-portal/**/*.py` |
| `.kiro/hooks/docs-ai-reminder.kiro.hook` | No change — already reminds about docs/ai updates |
| `.kiro/hooks/fsx-credential-protection.kiro.hook` | No change — FSx credential model unchanged |
| `.kiro/hooks/infra-protection.kiro.hook` | No change — shared infra protection unchanged |

**Conclusion**: No hook changes required. Existing hooks already cover the relevant file patterns.

---

## 6. Recommended Changes

### 6.1 Spec Changes (`.kiro/specs/bedrock-access-gateway/`)

#### requirements.md — Req 4 Rewrite

Current title: "Token-Based Daily Quota Enforcement"
New title: "Cost-Based Monthly Quota Enforcement"

Key acceptance criteria changes:
- Replace `daily_input_token_limit` / `daily_output_token_limit` with `monthly_cost_limit_krw`
- Replace daily aggregation with monthly aggregation (`YYYY-MM` partition)
- Add: estimated cost calculation per request (model-specific pricing × tokens)
- Add: cross-model KRW aggregation per principal per month
- Add: global monthly budget KRW 10,000,000 (reporting/alerting, not necessarily hard enforcement)
- Default per-user: KRW 500,000/month
- Hard cap: KRW 2,000,000/month (even with approvals)
- Race condition: post-call ADD still applies, but in KRW not tokens

#### requirements.md — Req 5 Rewrite

Current: generic approval workflow
New: structured approval ladder

- Approval increments: KRW 500,000 steps (500K → 1M → 1.5M → 2M)
- Hard cap: KRW 2,000,000 — no approval can exceed this
- Reason field: mandatory on approval request submission
- Approval routing: email to team lead (configurable, temp: `changgeun.jang@mogam.er.kr`)
- Approval response: team lead approves/rejects via email-linked flow or admin UI

#### design.md — Locked Decision #8 Update

Current: "Global quota + model-level accounting"
New: "KRW cost-based monthly quota. Per-request cost estimated from model pricing × token usage. Cross-model aggregation per principal per month. Approval ladder in KRW 500K increments, hard cap KRW 2M."

#### tasks.md — Task 6 Rewrite

Replace token-based quota logic with:
- Model pricing lookup (cost per input token, cost per output token, per model)
- Post-Bedrock-call cost estimation: `(input_tokens × input_price) + (output_tokens × output_price)`
- MonthlyUsage atomic ADD (KRW amount)
- Pre-call check: `current_month_cost_krw < effective_limit_krw`
- Effective limit = base (500K) + approved boosts (in 500K increments, capped at 2M total)

### 6.2 Steering Changes

#### tech.md addition
```
## Quota Model
- KRW cost-based monthly quota (not token-count daily)
- Global monthly budget: KRW 10,000,000 / 20 users
- Default per-user: KRW 500,000/month
- Approval ladder: KRW 500,000 increments, hard cap KRW 2,000,000
- Near-real-time enforcement via DynamoDB (not delayed Cost Explorer)
```

#### product.md update
Add to Bedrock Gateway feature:
```
- KRW cost-based monthly quota enforcement with approval ladder
```

---

## 7. Recommended Data Model Changes

### 7.1 PrincipalPolicy Table — Schema Change

Current fields:
```
principal_id (PK, S)
allowed_models (L)
daily_input_token_limit (N)
daily_output_token_limit (N)
```

New fields:
```
principal_id (PK, S)                    — unchanged
allowed_models (L)                      — unchanged
monthly_cost_limit_krw (N)              — NEW: default 500000
max_monthly_cost_limit_krw (N)          — NEW: hard cap 2000000
```

Remove: `daily_input_token_limit`, `daily_output_token_limit`

### 7.2 DailyUsage Table → MonthlyUsage Table

Current schema:
```
principal_id_date (PK, S)  — format: <principal_id>#<YYYY-MM-DD>
model_id (SK, S)
input_tokens (N)
output_tokens (N)
ttl (N)                    — 25 hours
```

Option A — Repurpose DailyUsage as MonthlyUsage:
```
principal_id_month (PK, S) — format: <principal_id>#<YYYY-MM>
model_id (SK, S)           — keep for per-model cost breakdown reporting
cost_krw (N)               — KRW cost for this model this month
input_tokens (N)           — keep for reporting/audit
output_tokens (N)          — keep for reporting/audit
ttl (N)                    — ~35 days (month + buffer)
```

Option B — Keep DailyUsage for token audit, add separate MonthlyUsage for cost enforcement:
- More tables, but cleaner separation of concerns
- DailyUsage remains for detailed per-day per-model token audit
- MonthlyUsage is the enforcement table

**Recommendation**: Option A (repurpose). Simpler. Token counts are still recorded per-model for audit. Cost is the enforcement dimension. Rename table in Terraform: `daily-usage` → `monthly-usage`.

### 7.3 New Table: ModelPricing

For near-real-time cost estimation, the Lambda needs model-specific pricing:

```
model_id (PK, S)           — e.g. "anthropic.claude-3-5-sonnet-20241022-v2:0"
input_price_per_1k (N)     — KRW per 1,000 input tokens
output_price_per_1k (N)    — KRW per 1,000 output tokens
effective_date (S)          — ISO date when this pricing took effect
```

Alternative: hardcode pricing in Lambda env vars or a config file. DynamoDB table is more operationally flexible (admin can update pricing without Lambda redeploy).

**Recommendation**: DynamoDB ModelPricing table. Admin-managed. Lambda caches pricing at init (cold start) with periodic refresh. This is the 9th DynamoDB table.

### 7.4 TemporaryQuotaBoost Table — Schema Change

Current fields:
```
principal_id (PK, S)
boost_id (SK, S)
extra_input_tokens (N)
extra_output_tokens (N)
ttl (N)
```

New fields (approval ladder model):
```
principal_id (PK, S)       — unchanged
boost_id (SK, S)           — unchanged
extra_cost_krw (N)         — NEW: KRW 500,000 per approval step
approved_by (S)            — NEW: approver identity
approved_at (S)            — NEW: approval timestamp
reason (S)                 — NEW: user-provided reason
ttl (N)                    — end of month or explicit expiry
```

Remove: `extra_input_tokens`, `extra_output_tokens`

### 7.5 ApprovalRequest Table — Add reason field

Add:
```
reason (S)                 — mandatory, user-provided justification
requested_amount_krw (N)   — KRW 500,000 (fixed increment)
approver_email (S)         — routing target
```

### 7.6 RequestLedger — Add cost field

Add:
```
estimated_cost_krw (N)     — per-request estimated KRW cost
```

### 7.7 Global Budget Tracking (new concept)

Two options:
- (A) Separate GlobalBudget table with a single row per month — Lambda queries on each request
- (B) Derive from sum of all principals' MonthlyUsage — expensive scan, not suitable for real-time
- (C) Maintain a running counter in a single-row table, atomic ADD per request

**Recommendation**: Option C — single-row GlobalBudget counter. PK: `YYYY-MM`. Field: `total_cost_krw`. Atomic ADD per request. This is the 10th DynamoDB table (or a single-row partition in an existing table).

For v1, global budget can be alerting-only (CloudWatch alarm when approaching 10M KRW) rather than hard enforcement. Hard enforcement at the global level creates contention on a single DynamoDB item under concurrent load.

---

## 8. Recommended Approval Flow Design

### Current flow
```
User → POST /approval/request (no reason required)
  → ApprovalPendingLock (race-safe)
  → ApprovalRequest (status: pending)
  → SES email to admin group
Admin → approve via Admin UI → TemporaryQuotaBoost (extra tokens, TTL)
```

### New flow
```
User → POST /approval/request {"reason": "...", "requested_increment_krw": 500000}
  → Validate: reason non-empty, requested_increment_krw == 500000
  → Validate: current effective limit + 500000 ≤ 2,000,000 (hard cap)
  → ApprovalPendingLock (race-safe, unchanged)
  → ApprovalRequest (status: pending, reason, requested_amount_krw, approver_email)
  → SES email to team lead (temp: changgeun.jang@mogam.er.kr)
    Subject: [Bedrock Gateway] 쿼터 증액 요청 — <principal_id>
    Body: principal, current limit, requested new limit, reason, approve/reject link

Team lead → clicks approve link (email-linked flow) OR uses Admin UI
  → Admin API: POST /api/gateway/approval/<id>/approve
  → TemporaryQuotaBoost created (extra_cost_krw: 500000, ttl: end of month)
  → ApprovalPendingLock deleted
  → SES notification to user: approved, new effective limit

Enforcement:
  effective_limit = base (500K) + sum(active boosts)
  hard cap check: effective_limit ≤ 2,000,000
```

### Email-linked approval flow

Two implementation options:
- (A) Signed URL in email → API Gateway endpoint that processes approve/reject without login
  - Pros: one-click approval, no portal login needed
  - Cons: URL security (must be time-limited, single-use), requires new API Gateway route
- (B) Deep link to Admin UI approval page (current design)
  - Pros: simpler, uses existing auth
  - Cons: requires portal login

**Recommendation**: Start with (B) deep link to Admin UI (current design). Add (A) signed-URL one-click approval as a v2 enhancement. The email already contains a deep link — just update the routing target from admin group to team lead.

### Approval ladder enforcement

```python
def validate_approval_request(principal_id, requested_increment_krw):
    # 1. Fixed increment
    if requested_increment_krw != 500000:
        return deny("increment must be KRW 500,000")
    
    # 2. Hard cap check
    policy = lookup_principal_policy(principal_id)
    base_limit = policy.get("monthly_cost_limit_krw", 500000)
    active_boosts = get_active_boosts_total(principal_id)  # sum of extra_cost_krw
    new_effective = base_limit + active_boosts + requested_increment_krw
    if new_effective > 2000000:
        return deny("hard cap KRW 2,000,000 would be exceeded")
    
    # 3. Proceed with approval request
    ...
```

---

## 9. Open Questions / Ambiguities

| # | Question | Impact | Suggested Resolution |
|---|----------|--------|---------------------|
| Q1 | Model pricing source — where do KRW-per-token rates come from? AWS pricing is in USD. Exchange rate handling? | Cost calculation accuracy | Use fixed KRW rates in ModelPricing table, admin-managed. Periodic manual update based on AWS pricing + exchange rate. Avoid real-time FX API dependency. |
| Q2 | Global budget (KRW 10M) — hard enforcement or alerting-only? | Architecture complexity. Hard enforcement on a single counter creates DynamoDB hot key under concurrency. | Recommend alerting-only for v1. CloudWatch alarm at 80%/90%/100% thresholds. Hard enforcement is a v2 option. |
| Q3 | Approval routing — always to one team lead, or per-principal/per-team routing? | Config complexity | Start with single global approver (env var). Per-team routing is v2. |
| Q4 | Monthly reset — exact timing? UTC midnight on 1st? KST midnight? | Edge case at month boundary | Recommend UTC. `YYYY-MM` partition key. First request of new month starts fresh counter. |
| Q5 | Existing token-count fields in DailyUsage — keep for audit or drop entirely? | Migration complexity | Keep `input_tokens`/`output_tokens` in MonthlyUsage for audit/reporting. Cost is the enforcement dimension. |
| Q6 | Approval boost duration — end of current month, or 30 days from approval? | Boost expiry semantics | Recommend end of current month (UTC). Simpler mental model. User requests again next month if needed. |
| Q7 | Email-linked approval — signed URL (one-click) or deep link (portal login)? | Implementation scope | Deep link for v1 (current design). Signed URL is v2. |
| Q8 | Race condition under KRW model — post-call ADD can overshoot by one request's cost. Acceptable? | Same as current token model. Max overshoot = one request's cost (typically small relative to 500K KRW limit). | Accept for v1 (same risk profile as current token model). |
| Q9 | Cost estimation accuracy — Bedrock pricing can change. Stale ModelPricing data → inaccurate enforcement. | Under-/over-counting | Admin responsibility to keep ModelPricing current. Lambda logs actual tokens — reconciliation possible. |
| Q10 | 20-user assumption — is this a hard limit or a planning number? Does it affect per-user default? | Budget allocation | Treat as planning number. Per-user default (500K) is independently configurable per principal. Global budget (10M) is a separate alerting threshold. |

---

## 10. Review-Only vs Safe-to-Implement Recommendation

### Review-only (do NOT implement yet)

The following require explicit approval before any code/IaC changes:

1. **DynamoDB schema changes** — renaming/replacing DailyUsage, adding ModelPricing table, modifying PrincipalPolicy fields. These are breaking changes to the data model.
2. **Lambda handler.py `check_quota()` rewrite** — core enforcement logic change from tokens to KRW.
3. **Lambda handler.py `update_daily_usage()` → `update_monthly_usage()`** — usage tracking rewrite.
4. **Terraform `dynamodb.tf`** — table schema changes, new table definitions.
5. **Approval ladder logic** — new validation rules in `handle_approval_request()`.
6. **SES routing change** — approver email from admin group to team lead.

### Safe to implement now (governance artifacts only)

Per devops-operating-model.md, the following can be updated without approval:

1. Update `.kiro/specs/bedrock-access-gateway/requirements.md` — Req 4, Req 5 rewrite
2. Update `.kiro/specs/bedrock-access-gateway/design.md` — Locked Decision #8, architecture notes
3. Update `.kiro/specs/bedrock-access-gateway/tasks.md` — Task 6, Task 9 rewrite
4. Update `.kiro/steering/tech.md` — add quota model section
5. Update `.kiro/steering/product.md` — update feature description
6. Update `docs/ai/research.md` — add cost-based quota analysis section
7. Update `docs/ai/risk_register.md` — add new risks (cost estimation accuracy, pricing staleness, global budget hot key)
8. Update `docs/ai/todo.md` — add cost-based quota migration tasks
9. This file (`docs/ai/cost-based-quota-validation.md`)

---

## 11. Confirmation — Grounded in Existing Structure

This validation is grounded in:

- **Lambda code**: `infra/bedrock-gateway/lambda/handler.py` (788 lines) — read in full. `check_quota()`, `update_daily_usage()`, `lookup_principal_policy()`, `handle_approval_request()` analyzed.
- **DynamoDB schema**: `infra/bedrock-gateway/dynamodb.tf` — all 8 tables reviewed. PrincipalPolicy, DailyUsage, TemporaryQuotaBoost, ApprovalRequest schemas documented.
- **Terraform variables**: `infra/bedrock-gateway/variables.tf` — SES email vars, discovery_mode reviewed.
- **IAM permissions**: `infra/bedrock-gateway/iam.tf` — Lambda role permissions reviewed. No changes needed for cost-based model.
- **API Gateway**: `infra/bedrock-gateway/main.tf` — no changes needed.
- **Specs**: All three spec files read. Requirements, design, tasks cross-referenced.
- **Steering**: All four steering files read. tech.md and product.md need minor updates.
- **Hooks**: All four hooks read. No changes needed.
- **Governance docs**: research.md, risk_register.md, todo.md, runbook.md, validation_plan.md, rollout-gap-analysis.md all read.
- **Identity model**: Unchanged. `<account>#<role-name>` exact-match principal_id. No impact from quota model change.

---

## Appendix A: Current vs New — Side-by-Side

| Dimension | Current (Token-Based Daily) | New (KRW Cost-Based Monthly) |
|-----------|---------------------------|------------------------------|
| Enforcement unit | Input/output tokens | KRW (Korean Won) |
| Time window | Daily (YYYY-MM-DD) | Monthly (YYYY-MM) |
| Default limit | 100K input / 50K output tokens/day | KRW 500,000/month |
| Hard cap | None defined | KRW 2,000,000/month |
| Global budget | None | KRW 10,000,000/month (20 users) |
| Boost increment | Arbitrary extra tokens | Fixed KRW 500,000 steps |
| Boost duration | TTL-based (arbitrary) | End of month |
| Approval routing | Admin group email | Team lead email |
| Reason required | No | Yes (mandatory) |
| Cost calculation | N/A | Model pricing × tokens |
| Pricing source | N/A | ModelPricing DynamoDB table |

## Appendix B: New DynamoDB Table Summary (Post-Migration)

| # | Table | PK | SK | Key Fields | TTL |
|---|-------|----|----|-----------|-----|
| 1 | PrincipalPolicy | `principal_id` | — | `allowed_models`, `monthly_cost_limit_krw`, `max_monthly_cost_limit_krw` | — |
| 2 | MonthlyUsage (was DailyUsage) | `principal_id_month` | `model_id` | `cost_krw`, `input_tokens`, `output_tokens` | ~35d |
| 3 | TemporaryQuotaBoost | `principal_id` | `boost_id` | `extra_cost_krw`, `approved_by`, `reason` | EOM |
| 4 | ApprovalRequest | `request_id` | — | `principal_id`, `status`, `reason`, `requested_amount_krw` | — |
| 5 | RequestLedger | `request_id` | — | + `estimated_cost_krw` | — |
| 6 | SessionMetadata | `request_id` | — | unchanged | 30d |
| 7 | IdempotencyRecord | `request_id` | — | unchanged | 24h |
| 8 | ApprovalPendingLock | `principal_id` | — | unchanged | 7d |
| 9 | ModelPricing (NEW) | `model_id` | — | `input_price_per_1k`, `output_price_per_1k`, `effective_date` | — |
| 10 | GlobalBudget (NEW, optional) | `month` (YYYY-MM) | — | `total_cost_krw` | ~35d |
