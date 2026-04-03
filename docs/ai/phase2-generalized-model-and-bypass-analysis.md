# Phase 2 Generalized Model Target, Pricing, and Bypass Prevention Analysis

> Generated: 2026-03-19
> Scope: Phase 2 verification/design correction ONLY. No Phase 3/4 work.
> Method: Deep read of handler.py (939 lines), iam.tf, dynamodb.tf, main.tf, lambda.tf, variables.tf, design.md, requirements.md, research.md, todo.md, tasks.md.

---

## 1. Root-Cause Summary

The current Phase 2 implementation treats `modelId` from the user request as a single opaque string that flows through three roles simultaneously:

1. **Policy allowlist key** (`check_model_access()` — exact match against `principal_policy.allowed_models`)
2. **Bedrock invocation target** (`invoke_bedrock()` — passed directly as `modelId` to `bedrock_runtime.converse()`)
3. **Pricing lookup key** (`lookup_model_pricing()` — exact match against `model_pricing.model_id`)

This works when the user-supplied `modelId` is a plain foundation model ID (e.g., `anthropic.claude-haiku-4-5-20251001-v1:0`) AND that same string is valid for all three roles. It breaks when:

- A model requires an **inference profile ARN** for invocation (some Bedrock models require `us.anthropic.claude-*` cross-region inference profile IDs instead of direct model IDs)
- Different providers have **different billable dimensions** (e.g., image models bill per image, not per token)
- The **pricing lookup key** differs from the **invocation target** (e.g., multiple inference profiles map to the same underlying model pricing)

This is not a single-model bug. It's a structural conflation of three distinct concerns.

---

## 2. What Is Already Implemented Correctly

| Component | Status | Evidence |
|-----------|--------|----------|
| **Principal extraction + normalization** | Implemented and enforced | `normalize_principal_id()` Candidate F, live-verified, 11 unit tests |
| **Fail-closed deny-by-default** | Implemented and enforced | Every error path in `lambda_handler()` returns deny. Catch-all at bottom. |
| **Policy lookup → deny if missing** | Implemented and enforced | Step 3 in handler: `if not policy: return deny_response(...)` |
| **Model allowlist check** | Implemented and enforced | `check_model_access()` — exact match, empty list = deny-all |
| **Pricing lookup → deny if missing** | Implemented and enforced | Step 5: `if not pricing: return deny_response(...)` |
| **KRW monthly quota check** | Implemented and enforced | `check_quota()` — KST boundary, cross-model aggregation, boost support |
| **Post-call cost ADD** | Implemented and enforced | `update_monthly_usage()` — atomic ADD, TTL, per-model SK |
| **Immutable audit ledger** | Implemented and enforced | `write_request_ledger()` — PutItem only, IAM denies Update/Delete |
| **Idempotency** | Implemented and enforced | `check_idempotency()` / `create_idempotency_record()` / `complete_idempotency_record()` |
| **Lambda execution role Bedrock IAM** | Implemented | `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` on `Resource: ["*"]` |
| **API Gateway AWS_IAM auth** | Implemented and enforced | `authorization = "AWS_IAM"` on all methods |
| **DynamoDB table structure** | Implemented | All 10 tables deployed, correct schemas |
| **ModelPricing cache** | Implemented | Cold-start scan + one-reload retry on cache miss |
| **Cost estimation formula** | Implemented | `estimate_cost_krw()` — `(input × price/1K) + (output × price/1K)` |

**Summary: The core enforcement pipeline is structurally sound.** The quota, policy, pricing, and audit systems work correctly for the current scope (Converse API, token-billed models, direct model IDs).

---

## 3. What Is Partially Implemented, Documented-Only, or Missing

### 3.1 Partially Implemented

| Item | Current State | Gap |
|------|--------------|-----|
| **Model ID triple-role conflation** | `modelId` from request is used as-is for policy check, Bedrock invocation, and pricing lookup | No separation between policy-facing ID, invocation target, and pricing key. Works for current models but structurally fragile. |
| **Lambda Bedrock IAM scope** | `Resource: ["*"]` for `bedrock:InvokeModel` | Correct for broad model coverage. No model-level IAM restriction needed (policy enforcement is in Lambda code, not IAM). This is actually correct — tightening to specific model ARNs would break the gateway's purpose. |

### 3.2 Documented But Not Enforced

| Item | Current State | Gap |
|------|--------------|-----|
| **Direct Bedrock bypass prevention (Task 2)** | Documented in `research.md` §4, `todo.md` Task 2, `requirements.md` Req 1 | **NOT IMPLEMENTED.** No IAM deny policy exists on `BedrockUser-*` roles for `bedrock:InvokeModel`/`bedrock:InvokeModelWithResponseStream`. No SCP exists. Users with `BedrockUser-*` roles can currently call Bedrock directly, bypassing the gateway entirely. |
| **SCP for organization-level Bedrock deny** | Documented as target in `research.md` §4 | **NOT IMPLEMENTED.** No SCP in codebase. Documented as future goal. |

### 3.3 Missing (Not Designed or Implemented)

| Item | Description |
|------|-------------|
| **Inference profile target resolution** | No concept of inference profile IDs/ARNs anywhere in the codebase. If a model requires an inference profile for invocation, the current code will fail at `bedrock_runtime.converse()` because it passes the raw model ID. |
| **Multi-provider pricing model** | `model_pricing` table uses `model_id` as PK with `input_price_per_1k` / `output_price_per_1k`. This assumes all models bill per token. Image models, embedding models, or models with different billing dimensions are not supported. |
| **Region-specific pricing** | No region dimension in `model_pricing`. All pricing is implicitly for `us-west-2`. |
| **Invocation target type classification** | No distinction between direct model ID, inference profile ID, inference profile ARN, or provisioned throughput ARN. |

---

## 4. Generalized Bedrock Invocation-Target Policy

### 4.1 Bedrock Invocation Target Types

Bedrock supports multiple invocation target formats:

| Type | Format Example | When Required |
|------|---------------|---------------|
| **Foundation model ID** | `anthropic.claude-haiku-4-5-20251001-v1:0` | Direct invocation of on-demand models in the current region |
| **Cross-region inference profile ID** | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | Required for some models that only support cross-region inference profiles |
| **Inference profile ARN** | `arn:aws:bedrock:us-west-2:107650139384:inference-profile/us.anthropic.claude-*` | Application inference profiles (custom routing) |
| **Provisioned throughput ARN** | `arn:aws:bedrock:us-west-2:107650139384:provisioned-model/...` | Provisioned capacity |

### 4.2 Current Scope Assessment

For the current project scope (v1: Converse API only, Anthropic Claude family, us-west-2):

- **Foundation model IDs** work for Claude Haiku 4.5 and Claude Sonnet 4.5 in us-west-2 (confirmed: both are AUTHORIZED + AVAILABLE)
- **Cross-region inference profiles** are NOT required for these models in us-west-2
- **Provisioned throughput** is out of scope (v1)
- **Application inference profiles** are out of scope (v1)

### 4.3 Recommendation: Minimal v1 Approach

**For v1, the current single-string model ID approach is sufficient** for the confirmed in-scope models (Claude Haiku 4.5, Claude Sonnet 4.5 in us-west-2). These models accept direct foundation model IDs via `bedrock_runtime.converse()`.

**However**, the design should explicitly acknowledge the triple-role conflation and document the v2 separation plan:

| Role | v1 (current) | v2 (future) |
|------|-------------|-------------|
| Policy allowlist key | `modelId` from request | Policy-facing model alias or canonical ID |
| Bedrock invocation target | Same `modelId` | Resolved target (may be inference profile ARN) |
| Pricing lookup key | Same `modelId` | Canonical pricing key (maps multiple targets to one price) |

**No Phase 2 runtime code change is required for target resolution** — the current models work with direct IDs. But the design doc should be updated to acknowledge this as a known structural limitation.

---

## 5. Generalized Bedrock Pricing-Handling Policy

### 5.1 Current State

The `model_pricing` table uses `model_id` (S) as PK with:
- `input_price_per_1k` (N) — KRW per 1K input tokens
- `output_price_per_1k` (N) — KRW per 1K output tokens

This assumes:
- All models bill per token (input + output)
- All pricing is for one region (us-west-2)
- One model ID = one pricing entry

### 5.2 Assessment for Current Scope

For the current in-scope models (Claude family, Converse API, us-west-2):
- **All bill per token** (input + output) ✓
- **All are in us-west-2** ✓
- **Each model ID maps to exactly one pricing entry** ✓

The current pricing model is correct for the current scope.

### 5.3 Known Limitations (v2 Concerns, Not v1 Blockers)

| Limitation | Impact | When It Matters |
|-----------|--------|-----------------|
| No region dimension | Cannot support multi-region pricing differences | When gateway serves multiple regions |
| Token-only billing | Cannot price image models, embedding models | When non-text models are added |
| No provider dimension | Cannot distinguish pricing rules by provider | When Amazon Titan or other providers are added |
| No inference profile → model mapping | Cannot map multiple invocation targets to one price | When inference profiles are used |

### 5.4 Recommendation

**No `model_pricing` schema change is required for Phase 2.** The current schema correctly handles the in-scope models. The design doc should document the known limitations as v2 scope items.

---

## 6. Policy Model ID vs Invocation Target vs Pricing Key

### 6.1 Current State (v1)

All three are the same string: the `modelId` from the user request.

```
User request: {"modelId": "anthropic.claude-haiku-4-5-20251001-v1:0"}
  → Policy check:  allowed_models contains "anthropic.claude-haiku-4-5-20251001-v1:0"? ✓
  → Pricing lookup: model_pricing["anthropic.claude-haiku-4-5-20251001-v1:0"] ✓
  → Bedrock call:   converse(modelId="anthropic.claude-haiku-4-5-20251001-v1:0") ✓
```

### 6.2 Assessment

This works for v1 scope. The three roles are conflated but produce correct results for the current model set. Separating them now would be over-engineering with no immediate benefit.

### 6.3 v2 Separation Plan (Document Only, Do Not Implement)

When inference profiles or non-token-billed models are added:
1. `allowed_models` in PrincipalPolicy should use canonical model aliases
2. A target resolution layer maps canonical alias → actual invocation target
3. A pricing resolution layer maps canonical alias → pricing key
4. `model_pricing` may need a composite key or alias mapping table

---

## 7. Phase 2 Runtime Code Change Assessment

### 7.1 Is a Code Change Required?

**No.** The current `handler.py` correctly handles the in-scope models:
- `anthropic.claude-haiku-4-5-20251001-v1:0` — works as direct model ID for Converse
- `anthropic.claude-sonnet-4-5-20250929-v1:0` — works as direct model ID for Converse
- Legacy models in allowlist — work as direct model IDs

The `invoke_bedrock()` function passes `modelId` to `bedrock_runtime.converse()`, which is the correct invocation pattern for these models.

### 7.2 What Would Require a Code Change?

A code change would be needed if:
- A model is added that requires an inference profile ID for invocation
- A non-token-billed model is added (different cost formula)
- Multi-region invocation is needed

None of these are in v1 scope.

---

## 8. DynamoDB Seed/Data Model Change Assessment

### 8.1 `model_pricing` Table

**No schema change required.** Current schema (`model_id` PK, `input_price_per_1k`, `output_price_per_1k`) is correct for token-billed models.

**Seed data is correct:** 5 models seeded (2 ACTIVE 4.5+, 3 legacy) with correct KRW pricing.

### 8.2 `principal_policy.allowed_models`

**No schema change required.** The `allowed_models` list contains model ID strings that match exactly what users send in requests and what exists in `model_pricing`. This is consistent.

**Current seed:** 5 models in `allowed_models` for cgjang. Correct.

### 8.3 Future Consideration

If inference profiles are needed, the data model would need either:
- A mapping table (`model_alias` → `invocation_target`, `pricing_key`)
- Or composite entries in `model_pricing` with an alias field

This is v2 scope.

---

## 9. Gateway Enforcement / Bypass Prevention Strategy

### 9.1 Current Architecture (Three Layers)

| Layer | Purpose | Status |
|-------|---------|--------|
| **Gateway authorization** | API Gateway AWS_IAM auth → Lambda policy/quota/model check | **IMPLEMENTED AND ENFORCED** |
| **Direct Bedrock bypass prevention** | Prevent users from calling `bedrock-runtime` directly | **NOT IMPLEMENTED** |
| **Per-user policy allowlist enforcement** | Lambda checks `allowed_models`, quota, pricing | **IMPLEMENTED AND ENFORCED** |

### 9.2 The Bypass Gap

**UPDATE (2026-03-19): BYPASS GAP CLOSED AND LIVE VERIFIED.** `DenyDirectBedrockInference` inline policy applied to all 6 `BedrockUser-*` roles. Live evidence: direct Bedrock calls return `AccessDeniedException` across providers/models. Gateway path reaches Lambda. Task 2 complete. See `docs/ai/task2-bypass-prevention-execution.md`.

~~**This is the most critical finding.** The gateway enforcement pipeline is correct, but it can be entirely bypassed:~~

- `BedrockUser-cgjang` (and any `BedrockUser-*` role) currently has **no IAM deny** for `bedrock:InvokeModel` or `bedrock:InvokeModelWithResponseStream`
- If the user calls `bedrock-runtime` directly (e.g., `boto3.client('bedrock-runtime').converse(...)` from FSx), the gateway is never invoked
- All quota, policy, audit, and cost tracking are bypassed
- The user gets unmetered, unaudited Bedrock access

This is documented as Task 2 in `todo.md` but has never been implemented.

### 9.3 Bypass Surface

The primary bypass actions are:
- `bedrock:InvokeModel` — used by Converse API at IAM level
- `bedrock:InvokeModelWithResponseStream` — used by ConverseStream at IAM level

Secondary (lower risk, still bypass):
- `bedrock:InvokeAgent` — if agents are configured
- `bedrock:Retrieve` / `bedrock:RetrieveAndGenerate` — if knowledge bases exist

### 9.4 Correct Enforcement Strategy

Three options, in order of preference:

| Option | Mechanism | Scope | Pros | Cons |
|--------|-----------|-------|------|------|
| **A: IAM deny on user roles** | Explicit deny policy on each `BedrockUser-*` role | Per-role | Immediate, no org-level approval needed | Must be applied to every user role individually |
| **B: Permission boundary** | Permission boundary on `BedrockUser-*` roles | Per-role | Cleaner than inline deny, prevents future grants | Requires modifying role trust/boundary config |
| **C: SCP** | Organization SCP denying Bedrock for all except Lambda role | Org-wide | Comprehensive, cannot be overridden by IAM | Requires org admin approval, affects all accounts |

### 9.5 Recommendation

**Option A (IAM deny on user roles) is the correct immediate action.** This is what `research.md` §4 already designed. It was never executed.

The deny policy for each `BedrockUser-*` role should be:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyDirectBedrockAccess",
    "Effect": "Deny",
    "Action": [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ],
    "Resource": "*"
  }]
}
```

This does NOT affect the gateway Lambda execution role (separate IAM role: `bedrock-gw-dev-lambda-exec`). The Lambda role's `bedrock:InvokeModel` Allow is on a different principal.

**Option C (SCP) remains the target** per `research.md` §4 and `todo.md` post-implementation items. The SCP would use a condition key to exempt the Lambda execution role ARN.

### 9.6 Scope Clarification

Task 2 (direct Bedrock deny) is listed in `todo.md` as a parallel task, NOT a Phase 2 task. It is a separate work item that should be tracked independently. However, it is a **security prerequisite** for the gateway to be considered operationally complete — without it, the gateway is an optional path, not an enforced one.

---

## 10. Current IAM/SCP Posture — Does It Block Bypass?

**No.** Based on evidence:

1. No SCP exists in the codebase (`grep` for `scp`, `service_control`, `organizations_policy` in `*.tf` — zero results)
2. No IAM deny policy for Bedrock actions exists on `BedrockUser-*` roles (no Terraform resource, no documented manual application)
3. `BedrockUser-cgjang` currently has `execute-api:Invoke` for the gateway API AND whatever Bedrock permissions were granted when the role was created
4. Task 2 in `todo.md` is explicitly unchecked: `[ ] Task 2: Direct Bedrock access deny policy for human per-user roles (BedrockUser-*)`

**The gateway is currently an optional path, not an enforced one.** Any user with a `BedrockUser-*` role can bypass it entirely.

---

## 11. Files/Docs/Scripts That Must Change

### 11.1 Phase 2 Scope (Design/Doc Corrections Only)

These are documentation and design corrections to accurately reflect the generalized model:

| File | Change | Type |
|------|--------|------|
| `.kiro/specs/bedrock-access-gateway/design.md` | Add section: "Model ID Triple-Role Conflation (v1 Known Limitation)" documenting that policy key, invocation target, and pricing key are the same string in v1, with v2 separation plan | Doc update |
| `.kiro/specs/bedrock-access-gateway/design.md` | Add section: "Pricing Model Scope (v1)" documenting token-only billing assumption and v2 multi-dimension plan | Doc update |
| `.kiro/specs/bedrock-access-gateway/design.md` | Add section: "Bypass Prevention Architecture" documenting the three-layer enforcement model | Doc update |
| `.kiro/specs/bedrock-access-gateway/requirements.md` | Update Req 1 acceptance criteria to explicitly list the IAM deny requirement | Doc update |
| `docs/ai/todo.md` | Elevate Task 2 visibility — note it as a security prerequisite, not just a parallel task | Doc update |

### 11.2 Separate Work Item (Task 2 — NOT Phase 2)

| File | Change | Type |
|------|--------|------|
| IAM policy on `BedrockUser-*` roles | Add explicit deny for `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | IAM change (manual or Terraform, requires separate approval) |

### 11.3 No Changes Required

| File | Reason |
|------|--------|
| `handler.py` | Runtime logic is correct for v1 scope |
| `iam.tf` | Lambda execution role permissions are correct |
| `dynamodb.tf` | Table schemas are correct for v1 scope |
| `lambda.tf` | Env vars are correct |
| `model_pricing` seed data | Correct for current models |
| `principal_policy` seed data | Correct for current models |
| `phase2-smoke-test.py` | Correct — uses `anthropic.claude-haiku-4-5-20251001-v1:0` |

---

## 12. Seed/Update Command Changes

**None required.** The current seed data is correct:
- `model_pricing`: 5 models with correct KRW pricing (token-based)
- `principal_policy`: 5 `allowed_models`, KRW fields set

---

## 13. Revised Smoke Test Strategy

**No change to the smoke test itself.** The current `phase2-smoke-test.py` correctly tests:
- SigV4 auth → API Gateway → Lambda
- Policy lookup → model allowlist → pricing lookup → quota check → Bedrock Converse → cost ADD → ledger write
- Response includes `decision: ALLOW`, `estimated_cost_krw`, `remaining_quota`, `usage`

**Additional verification recommended (separate from Phase 2 smoke test):**
- Verify that `BedrockUser-cgjang` CAN call Bedrock directly (confirming the bypass gap exists)
- After Task 2 IAM deny is applied, verify that direct Bedrock calls are denied

This is Task 2 verification scope, not Phase 2 scope.

---

## 14. Phase 2 Boundary Confirmation

This analysis confirms:
- **Phase 2 runtime code is correct** for the current scope
- **Phase 2 data model is correct** for the current scope
- **Phase 2 smoke test strategy is correct**
- **No Phase 2 code changes are needed** for generalized model support (v1 scope is token-billed Claude models via direct model IDs)
- **The bypass prevention gap (Task 2) is real but is a separate work item**, not a Phase 2 defect
- **Design/doc updates are needed** to accurately document the v1 limitations and the bypass prevention architecture
- **No Phase 3, Phase 4, or unrelated refactoring is included**

---

## 15. Summary of Findings

1. The Phase 2 runtime implementation is structurally correct for v1 scope
2. The model ID triple-role conflation is a known v1 limitation, not a bug — it works for the current model set
3. The pricing model is correct for token-billed models in a single region
4. **The most critical gap is Task 2 (bypass prevention)** — users can currently call Bedrock directly, bypassing all gateway controls. This is documented but not implemented.
5. No Phase 2 code, schema, or seed data changes are required
6. Design docs should be updated to explicitly document the v1 limitations and bypass prevention architecture
