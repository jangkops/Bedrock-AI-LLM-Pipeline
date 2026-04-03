# Phase 1 Implementation Plan: Data Model Migration (Revised)

> Date: 2026-03-18
> Phase: Phase 1 (Data Model / DynamoDB Schema Preparation)
> Status: PHASE 1 APPLIED TO DEV (2026-03-18). PHASE 2 DEPLOYED TO DEV AND VERIFIED (2026-03-20). All C1-C9 PASS. Phase 3 NOT STARTED.
> Revision reason: Original plan (v1) was rejected — destructive rename of `daily_usage` in Phase 1 creates intentionally broken quota enforcement. Operator requires backward-compatible, additive Phase 1.
> Scope: Tasks 1.1–1.6 from `tasks.md`. Task 1.7 deferred (Q2 = alerting-only).

---

## 1. Why the Original Phase 1 Plan Was Unsafe

The original plan proposed:
- Destroying `daily_usage` table and replacing it with `monthly_usage` in Phase 1
- Renaming `TABLE_DAILY_USAGE` → `TABLE_MONTHLY_USAGE` in Lambda env vars in Phase 1
- Updating `handler.py` table references from `TABLE_DAILY_USAGE` → `TABLE_MONTHLY_USAGE` in Phase 1

This created a known-broken intermediate state:
- `check_quota()` would reference the new `monthly_usage` table but still construct PK as `<principal_id>#YYYY-MM-DD` (daily format)
- `update_daily_usage()` would write to `monthly_usage` with the wrong PK format
- Quota enforcement would be non-functional between Phase 1 apply and Phase 2 completion

The plan explicitly accepted this breakage ("dev only, no production traffic"). The operator correctly rejected this — even in dev, intentional breakage is not an acceptable cutover model. The plan violated the principle that each phase should leave the system in a working state.

---

## 2. Migration Strategy Comparison

### Option A: Destructive Rename / Immediate Replacement (Original Plan — REJECTED)

Phase 1 destroys `daily_usage`, creates `monthly_usage`, renames all env vars and handler references.

| Criterion | Assessment |
|-----------|-----------|
| Blast radius | High — destroys existing table, breaks runtime quota |
| Compatibility with current runtime | None — `check_quota()` and `update_daily_usage()` break immediately |
| Risk of broken quota enforcement | Certain — intentional breakage between Phase 1 and Phase 2 |
| Terraform destruction risk | High — table destroyed, data lost |
| Rollback simplicity | Medium — git revert + re-apply recreates old table, but data is gone |
| Operator complexity | Low (fewer steps) but high risk |

**Verdict: REJECTED.** Intentional breakage is not acceptable.

### Option B: Parallel-Table Additive Approach (CONSIDERED)

Phase 1 adds `monthly_usage` and `model_pricing` as new tables alongside existing `daily_usage`. `daily_usage` is untouched. Lambda env vars and handler.py are untouched. Phase 2 adds new env vars, rewrites quota logic to use new tables. Post-validation cleanup removes `daily_usage`.

| Criterion | Assessment |
|-----------|-----------|
| Blast radius | Minimal — only additive Terraform changes |
| Compatibility with current runtime | Full — `daily_usage` untouched, current quota logic works |
| Risk of broken quota enforcement | Zero — current runtime is completely unaffected |
| Terraform destruction risk | Zero in Phase 1 — no tables destroyed |
| Rollback simplicity | Trivial — remove new table definitions, re-apply |
| Operator complexity | Low in Phase 1. Slightly higher in Phase 2 (dual env vars during transition) |

**Verdict: SAFE.** But requires Phase 2 to handle the env var introduction and handler.py switchover.

### Option C: Staged Compatibility Approach (CONSIDERED)

Phase 1 adds new tables AND adds new env vars (`TABLE_MONTHLY_USAGE`, `TABLE_MODEL_PRICING`) to Lambda, but keeps old env vars too. Handler.py gets new env var references but old code paths remain active. Phase 2 rewrites quota logic to use new tables. Post-validation cleanup removes old env vars and old table.

| Criterion | Assessment |
|-----------|-----------|
| Blast radius | Low — additive tables, additive env vars |
| Compatibility with current runtime | Full — old env vars and old code paths preserved |
| Risk of broken quota enforcement | Zero — old code paths still active |
| Terraform destruction risk | Zero in Phase 1 |
| Rollback simplicity | Easy — remove new table definitions and new env vars |
| Operator complexity | Medium — dual env vars in Lambda during transition, slightly more IAM complexity |

**Verdict: SAFE but over-engineered.** Adding unused env vars in Phase 1 creates dead references that serve no purpose until Phase 2. The Lambda would have env vars pointing to tables that no code path uses yet. This is not harmful but is unnecessary complexity.

### Comparison Summary

| Criterion | Option A (Destructive) | Option B (Additive) | Option C (Staged) |
|-----------|----------------------|--------------------|--------------------|
| Phase 1 safety | ❌ Broken quota | ✅ No breakage | ✅ No breakage |
| Phase 1 simplicity | Medium | High | Medium |
| Phase 2 complexity | Low (already switched) | Medium (switch + cleanup) | Medium (switch + cleanup) |
| Rollback simplicity | Medium | Trivial | Easy |
| Dead references | None | None | Yes (unused env vars) |
| Operator cognitive load | Low but risky | Low and safe | Medium |

---

## 3. Recommended Strategy: Option B (Parallel-Table Additive)

Option B is the safest practical path. It cleanly separates responsibilities:
- Phase 1 = add new DynamoDB tables (Terraform only, no Lambda changes)
- Phase 2 = rewrite Lambda logic, introduce new env vars, switch to new tables
- Post-validation = remove old table and old env vars

Option C adds unnecessary complexity (dead env vars) without meaningful benefit over Option B. The env var introduction belongs in Phase 2 when the code that uses them is also introduced.

---

## 4. Per-Item Phase Assignment

| Action | Phase | Rationale |
|--------|-------|-----------|
| Create `monthly_usage` DynamoDB table | **Phase 1** | Additive. No runtime dependency. Table exists but is unused until Phase 2. |
| Create `model_pricing` DynamoDB table | **Phase 1** | Additive. No runtime dependency. Table exists but is unused until Phase 2. |
| Modify `daily_usage` table | **NOT Phase 1** | Current runtime depends on it. No modification until Phase 2 switchover is complete. |
| Add `TABLE_MONTHLY_USAGE` Lambda env var | **Phase 2** | Env var should be introduced when the code that reads it is deployed. |
| Add `TABLE_MODEL_PRICING` Lambda env var | **Phase 2** | Same — introduce with the code that uses it. |
| Change `TABLE_DAILY_USAGE` Lambda env var | **NOT Phase 1, NOT Phase 2** | Keep old env var during Phase 2 transition. Remove in post-validation cleanup. |
| Change `handler.py` table references | **Phase 2** | Part of the quota logic rewrite. |
| Add `monthly_usage` ARN to IAM policy | **Phase 1** | Lambda role needs permission before Phase 2 code can use the table. Additive — does not remove any existing permission. |
| Add `model_pricing` ARN to IAM policy | **Phase 1** | Same — additive permission for Phase 2 readiness. |
| Remove `daily_usage` ARN from IAM policy | **Post-validation cleanup** | Only after Phase 2 is deployed and validated. |
| Remove `daily_usage` from outputs | **Post-validation cleanup** | Only after Phase 2 is deployed and validated. |
| Delete `daily_usage` table resource | **Post-validation cleanup** | Only after Phase 2 is deployed, validated, and old table confirmed unused. |
| Add `monthly_usage` and `model_pricing` to outputs | **Phase 1** | Additive. Does not remove existing outputs. |

---

## 5. Exact Phase 1 File Changes

### 5.1 `infra/bedrock-gateway/dynamodb.tf`

**Add** `model_pricing` table resource (new, after existing tables):

```hcl
resource "aws_dynamodb_table" "model_pricing" {
  name         = "${local.table_prefix}-model-pricing"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "model_id"

  attribute {
    name = "model_id"
    type = "S"
  }

  tags = {
    Service = "bedrock-access-gateway"
    Env     = var.environment
  }
}
```

**Add** `monthly_usage` table resource (new, after existing tables):

```hcl
resource "aws_dynamodb_table" "monthly_usage" {
  name         = "${local.table_prefix}-monthly-usage"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "principal_id_month"
  range_key    = "model_id"

  attribute {
    name = "principal_id_month"
    type = "S"
  }

  attribute {
    name = "model_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Service = "bedrock-access-gateway"
    Env     = var.environment
  }
}
```

**Update** header comment: table count from 8 to 10 (8 existing + 2 new).

**DO NOT** modify or remove `daily_usage` resource.

### 5.2 `infra/bedrock-gateway/iam.tf`

**Add** new IAM statement for the two new tables. Additive — no existing statements modified.

Add to the `DynamoDBReadWriteNonLedger` Resource list:
```hcl
aws_dynamodb_table.monthly_usage.arn,
```

Add a new statement for ModelPricing (read-only):
```hcl
{
  Sid    = "ModelPricingReadOnly"
  Effect = "Allow"
  Action = [
    "dynamodb:GetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
  ]
  Resource = [aws_dynamodb_table.model_pricing.arn]
}
```

**DO NOT** remove `daily_usage.arn` from existing statements.

### 5.3 `infra/bedrock-gateway/outputs.tf`

**Add** new entries to `dynamodb_table_arns` map:

```hcl
monthly_usage = aws_dynamodb_table.monthly_usage.arn
model_pricing = aws_dynamodb_table.model_pricing.arn
```

**DO NOT** remove `daily_usage` from the map.

### 5.4 Files NOT changed in Phase 1

| File | Reason |
|------|--------|
| `lambda.tf` | No new env vars until Phase 2 (code that uses them doesn't exist yet) |
| `lambda/handler.py` | No code changes until Phase 2 (quota logic rewrite) |
| `variables.tf` | No new variables needed |
| `locals.tf` | Unchanged |
| `main.tf` | Unchanged |
| `logs.tf` | Unchanged |
| `env/dev.tfvars` | No new tfvars needed |

---

## 6. Exact Phase Sequencing: Current State → Safe Future State

### Phase 1: Schema Preparation (this plan)

**Adds:**
- `monthly_usage` DynamoDB table (empty, unused by runtime)
- `model_pricing` DynamoDB table (empty, unused by runtime)
- IAM permissions for Lambda to access both new tables
- Output ARNs for both new tables

**Does NOT touch:**
- `daily_usage` table (preserved, still used by runtime)
- Lambda env vars (no changes)
- `handler.py` (no changes)
- Any existing IAM permissions or outputs

**Runtime state after Phase 1:** Identical to current. Quota enforcement works exactly as before. Two new empty tables exist but are not referenced by any code.

### Phase 2: Lambda Quota Logic Rewrite

**Adds:**
- `TABLE_MONTHLY_USAGE` env var in `lambda.tf` (pointing to `monthly_usage` table)
- `TABLE_MODEL_PRICING` env var in `lambda.tf` (pointing to `model_pricing` table)
- New functions in `handler.py`: `lookup_model_pricing()`, `estimate_cost_krw()`, `update_monthly_usage()`, rewritten `check_quota()`
- KST timezone handling (`current_month_kst()`, `end_of_month_ttl_kst()`)

**Removes from handler.py:**
- Old `check_quota()` body (replaced with KRW monthly logic)
- Old `update_daily_usage()` body (replaced with `update_monthly_usage()`)
- `TABLE_DAILY_USAGE` env var reference in handler.py (replaced with `TABLE_MONTHLY_USAGE`)

**Keeps temporarily:**
- `TABLE_DAILY_USAGE` env var in `lambda.tf` (can be removed in cleanup, but harmless to keep)
- `daily_usage` table in `dynamodb.tf` (still exists, no longer written to)
- `daily_usage.arn` in IAM policy (still exists, harmless)
- `daily_usage` in outputs (still exists, harmless)

**Runtime state after Phase 2:** KRW cost-based monthly quota enforcement is active. `monthly_usage` and `model_pricing` tables are in use. `daily_usage` table exists but is no longer read or written by any code path.

### Phase 3: Approval Ladder Rewrite

**Changes:**
- `handle_approval_request()` — validate reason, fixed KRW increment, hard cap check
- `handle_approval_decision()` — KRW boost, KST EOM TTL
- SES email templates — KRW amounts, team lead routing

**Runtime state after Phase 3:** Full KRW cost-based quota + approval ladder active.

### Post-Validation Cleanup (after Phase 2+3 validated)

**Removes:**
- `daily_usage` table resource from `dynamodb.tf`
- `TABLE_DAILY_USAGE` env var from `lambda.tf`
- `daily_usage.arn` from IAM policy in `iam.tf`
- `daily_usage` from outputs in `outputs.tf`

**Terraform plan will show:** 1 table destroyed (`daily-usage`), env var removed, IAM/output references removed.

**Prerequisite for cleanup:** Operator confirms Phase 2 is deployed, validated, and `daily_usage` table has no recent writes (check DynamoDB metrics or table item count).

---

## 7. Should `daily_usage` Remain During Phase 1?

**Yes.** `daily_usage` must remain during Phase 1.

The current runtime (`handler.py`) actively reads and writes `daily_usage` via `check_quota()` and `update_daily_usage()`. Removing or renaming it in Phase 1 would break quota enforcement immediately.

### When can `daily_usage` be safely removed?

`daily_usage` can be safely removed **after Phase 2 is deployed and validated**. Specifically:

1. Phase 2 deploys the rewritten `check_quota()` and `update_monthly_usage()` that use `TABLE_MONTHLY_USAGE` instead of `TABLE_DAILY_USAGE`.
2. Operator validates that the new quota logic works correctly (pre-call check, post-call ADD, cross-model aggregation).
3. Operator confirms `daily_usage` table has no recent writes (DynamoDB CloudWatch metrics: `ConsumedWriteCapacityUnits` = 0 for a reasonable observation period).
4. Post-validation cleanup removes the `daily_usage` resource from Terraform.
5. `terraform apply` destroys the old table.

The earliest safe removal point is **after Phase 2 validation is complete**. If Phase 3 is also required before cleanup, that's fine — `daily_usage` existing as an unused table has near-zero cost (PAY_PER_REQUEST with no requests = $0).

---

## 8. Terraform Plan Preview (Phase 1 Only)

Expected `terraform plan` output for Phase 1:

```
+ aws_dynamodb_table.monthly_usage    (create)
+ aws_dynamodb_table.model_pricing    (create)
~ aws_iam_role_policy.dynamodb        (update — add monthly_usage ARN to existing statement, add new ModelPricingReadOnly statement)
~ aws_dynamodb_table_arns output      (update — add monthly_usage and model_pricing keys)
```

No destroys. No Lambda changes. No API Gateway changes. No CloudWatch changes.

---

## 9. Validation Plan (Phase 1)

After `terraform apply`:

1. `terraform plan` shows no pending changes (clean state).
2. Verify new tables exist:
   ```bash
   aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2
   aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2
   ```
3. Verify old table still exists and is unchanged:
   ```bash
   aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-daily-usage --region us-west-2
   # Expected: table exists, schema unchanged
   ```
4. Verify Lambda env vars are unchanged (no `TABLE_MONTHLY_USAGE` or `TABLE_MODEL_PRICING` yet):
   ```bash
   aws lambda get-function-configuration --function-name bedrock-gw-dev-gateway --region us-west-2 \
     | jq '.Environment.Variables | keys'
   # Expected: TABLE_DAILY_USAGE present, TABLE_MONTHLY_USAGE absent
   ```
5. Verify IAM policy includes new ARNs:
   ```bash
   aws iam get-role-policy --role-name bedrock-gw-dev-lambda-exec --policy-name bedrock-gw-dev-dynamodb \
     | jq '.PolicyDocument'
   # Expected: monthly_usage ARN in DynamoDBReadWriteNonLedger, model_pricing ARN in ModelPricingReadOnly
   ```
6. Smoke test existing quota enforcement (optional but recommended):
   ```bash
   # SigV4-signed POST to dev gateway — should work exactly as before
   # check_quota() reads daily_usage (unchanged), update_daily_usage() writes daily_usage (unchanged)
   ```

---

## 10. Rollback Plan (Phase 1)

If Phase 1 apply causes issues:

1. Revert the 3 file changes (git checkout `dynamodb.tf`, `iam.tf`, `outputs.tf`).
2. `terraform apply -var-file=env/dev.tfvars` — removes `monthly_usage` and `model_pricing` tables, reverts IAM and outputs.
3. No data loss — `daily_usage` was never modified.
4. No runtime impact — Lambda was never changed.

---

## 11. Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Terraform apply fails mid-way (partial state) | Low | Low | Terraform handles partial apply. Re-run apply. New tables are independent resources. |
| IAM policy update causes Lambda permission error | Low | Very Low | Additive change only — no permissions removed. Existing permissions unchanged. |
| `monthly_usage` table name conflicts with existing resource | None | None | No existing table with this name. Fresh resource. |
| Phase 2 delayed — new tables sit empty | None | Medium | Empty PAY_PER_REQUEST tables cost $0. No operational impact. |

---

## 12. Go / No-Go Recommendation

**GO** — The revised Phase 1 plan is safe to implement after operator approval.

- Zero blast radius on existing runtime
- Zero risk of broken quota enforcement
- Zero Terraform destructions
- Trivially rollbackable
- Clean separation: Phase 1 = additive schema, Phase 2 = runtime switchover, cleanup = post-validation

---

## 13. Implementation Status

Phase 1 IaC implementation completed (2026-03-18). Additive changes only — Option B executed exactly as planned.

**Files modified (Phase 1 implementation):**
- `infra/bedrock-gateway/dynamodb.tf` — Added `model_pricing` and `monthly_usage` table resources. Header updated 8→10 tables. `daily_usage` untouched.
- `infra/bedrock-gateway/iam.tf` — Added `monthly_usage.arn` to `DynamoDBReadWriteNonLedger`. Added new `ModelPricingReadOnly` statement for `model_pricing`.
- `infra/bedrock-gateway/outputs.tf` — Added `monthly_usage` and `model_pricing` to `dynamodb_table_arns` map. `daily_usage` preserved.
- `.kiro/specs/bedrock-access-gateway/tasks.md` — Task 1.2 rewritten to reflect additive approach.

**Files confirmed NOT modified:**
- `infra/bedrock-gateway/lambda.tf` — No new env vars (Phase 2 scope)
- `infra/bedrock-gateway/lambda/handler.py` — No code changes (Phase 2 scope)
- `infra/bedrock-gateway/variables.tf`, `locals.tf`, `main.tf`, `logs.tf`, `env/dev.tfvars` — Unchanged

**Validation passed:** `terraform validate`, `terraform fmt -check`, content verification (daily_usage intact, no handler.py changes, no lambda.tf env var changes).

**Next step:** Operator executes `terraform apply -var-file=env/dev.tfvars` in `dev` workspace. See §14 for exact commands.


---

## 14. Phase 1 Operator Apply Package

**Phase 1 apply completed successfully (2026-03-18).** Dev stack now includes `monthly_usage` and `model_pricing` tables.

Post-apply validation commands and expected outputs are in `docs/ai/runbook.md` → "Phase 1 Post-Apply Validation" and `docs/ai/phase1-post-apply-validation.md`.

---

## 15. Phase 2 Readiness Assessment (Planning Only — NO Implementation)

> This section documents what Phase 2 will require. No code changes are made. Phase 2 requires separate explicit approval.

### 15.1 Files Phase 2 Will Touch

| File | Change Type | Description |
|------|-------------|-------------|
| `infra/bedrock-gateway/lambda/handler.py` | Rewrite | `check_quota()` → KRW monthly logic. `update_daily_usage()` → `update_monthly_usage()`. Add `lookup_model_pricing()`, `estimate_cost_krw()`, `current_month_kst()`, `end_of_month_ttl_kst()`. |
| `infra/bedrock-gateway/lambda.tf` | Add env vars | Add `TABLE_MONTHLY_USAGE` and `TABLE_MODEL_PRICING` env vars. Keep `TABLE_DAILY_USAGE` (harmless, removed in cleanup). |

### 15.2 Files Phase 2 Will NOT Touch

| File | Reason |
|------|--------|
| `dynamodb.tf` | Phase 1 already added tables. No schema changes needed. |
| `iam.tf` | Phase 1 already added permissions. |
| `outputs.tf` | Phase 1 already added output entries. |
| `variables.tf`, `locals.tf`, `main.tf`, `logs.tf` | No changes needed. |
| `gateway_approval.py` | Frozen until Phase 4. |
| All `account-portal/`, `ansible/`, `nginx/` | Non-disruption policy. |

### 15.3 handler.py Change Inventory

| Current Function | Phase 2 Action | New Function |
|-----------------|----------------|--------------|
| `check_quota()` (lines ~270-310) | Full rewrite | Query `MonthlyUsage` for `<principal_id>#YYYY-MM` (KST). Sum `cost_krw` across models. Compare against effective limit (base + boosts). |
| `update_daily_usage()` (lines ~340-360) | Replace | `update_monthly_usage()` — atomic ADD `cost_krw`, `input_tokens`, `output_tokens` to `MonthlyUsage`. PK: `<principal_id>#YYYY-MM` (KST). |
| (new) | Add | `lookup_model_pricing(model_id)` — read `ModelPricing` table, cache at cold start. |
| (new) | Add | `estimate_cost_krw(input_tokens, output_tokens, pricing)` — KRW cost calculation. |
| (new) | Add | `current_month_kst()` — return `YYYY-MM` in KST. |
| (new) | Add | `end_of_month_ttl_kst()` — return Unix epoch for EOM KST. |
| `lambda_handler()` | Modify | Insert pricing lookup (step 6) between model check and quota check. Replace `update_daily_usage()` call with `update_monthly_usage()`. Add `estimated_cost_krw` to ledger entry. |

### 15.4 lambda.tf Change Inventory

Add to `environment.variables` block:
```hcl
TABLE_MONTHLY_USAGE  = aws_dynamodb_table.monthly_usage.name
TABLE_MODEL_PRICING  = aws_dynamodb_table.model_pricing.name
```

Keep existing `TABLE_DAILY_USAGE` (harmless — no code reads it after Phase 2, but removing it is a separate cleanup step).

### 15.5 handler.py Environment Variable Changes

Add at module level:
```python
TABLE_MONTHLY_USAGE = os.environ.get("TABLE_MONTHLY_USAGE", "")
TABLE_MODEL_PRICING = os.environ.get("TABLE_MODEL_PRICING", "")
```

`TABLE_DAILY_USAGE` reference in `check_quota()` and `update_daily_usage()` is replaced by `TABLE_MONTHLY_USAGE` in the new functions. The old `TABLE_DAILY_USAGE` variable can remain (dead code, removed in cleanup).

### 15.6 Sequencing and Cutover

1. Phase 2 code changes are deployed atomically (single `terraform apply` updates both Lambda code and env vars simultaneously).
2. After apply, Lambda uses `TABLE_MONTHLY_USAGE` and `TABLE_MODEL_PRICING` for all new requests.
3. `daily_usage` table still exists but receives no new writes.
4. Validation: confirm `monthly_usage` table receives writes, `daily_usage` receives no new writes.
5. Post-validation cleanup (separate step): remove `daily_usage` table, `TABLE_DAILY_USAGE` env var.

### 15.7 Phase 2 Prerequisites

- [x] Phase 1 IaC code complete
- [x] Phase 1 `terraform apply` executed by operator — dev stack deployed (2026-03-18)
- [x] Post-apply validation confirmed — see `docs/ai/phase1-post-apply-validation.md`
- [x] ModelPricing table seeded with initial pricing data (2026-03-18) — 3 models, verified Count=3
- [x] PrincipalPolicy records updated with `monthly_cost_limit_krw` and `max_monthly_cost_limit_krw` fields (2026-03-18) — cgjang: 500000/2000000, 3 allowed_models
- [x] Phase 2 implementation plan reviewed and approved by operator
- [x] Phase 2 code implemented in repo (2026-03-18) — `handler.py` + `lambda.tf`
- [x] Phase 2 `terraform apply` executed by operator (2026-03-18) — API `5l764dh7y9`, env vars confirmed
- [x] Phase 2 post-deploy smoke test passed — cgjang live smoke test PASSED (2026-03-20). All C1-C9 PASS. See `docs/ai/phase2-dev-validation-report.md`.

### 15.8 ModelPricing Seed Data (Operator Action — Required Before Phase 2)

After Phase 1 apply, the `model_pricing` table must be seeded before Phase 2 code can function (fail-closed: missing pricing → deny).

```bash
# Seed pricing for allowed models (example — adjust KRW rates as needed):
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-18"}
  }' \
  --region us-west-2

aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
    "input_price_per_1k": {"N": "0.36"},
    "output_price_per_1k": {"N": "1.80"},
    "effective_date": {"S": "2026-03-18"}
  }' \
  --region us-west-2
```

> Note: KRW rates above are illustrative. Operator must calculate actual rates based on current AWS USD pricing × agreed KRW exchange rate. See Q1 decision in `docs/ai/decision-resolution-q1-q6.md`.

### 15.9 What Needs Phase 2 Approval

Per `devops-operating-model.md`, the following require explicit approval before execution:
- Modification of `handler.py` (runtime code)
- Modification of `lambda.tf` (deployment config / env vars)
- Any `terraform apply` that changes Lambda function

Phase 2 approval is separate from Phase 1 approval. Phase 1 apply must complete first.
