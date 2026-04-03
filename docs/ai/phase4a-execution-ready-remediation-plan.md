# Phase 4A — Execution-Ready Backend/Admin-Plane Remediation Plan

> Date: 2026-03-24
> Status: Planning artifact — no implementation changes.
> Basis: `phase4-corrected-user-classification.md` (active), `phase4-backend-remediation-analysis.md` (corrected).
> Scope: Maximum safe work packet derivable from current confirmed state.

---

## 1. Hard Blockers

These prevent runtime validation of any Phase 4 Scope A endpoint. Nothing downstream can be confirmed working until these are resolved.

| # | Blocker | Why | Who |
|---|---------|-----|-----|
| H1 | Docker rebuild not performed since Phase 3 (2026-03-23) | Running container does not contain `gateway_usage.py` or `gateway_approval.py`. All 10 endpoints are unreachable at runtime regardless of data/IAM state. | Operator action |
| H2 | USD pricing for 11 new models not verified | Proposed KRW rates are derived from assumed USD rates. If USD rates are wrong, all cost estimation is wrong. Cannot seed model_pricing until operator confirms. | Operator verification |
| H3 | Exchange rate confirmation (1,450 KRW/USD) | All KRW calculations depend on this. If rate has shifted materially, all 16 pricing entries need recalculation. | Operator verification |

H2 and H3 block model_pricing seed (Task 4A.2).
H1 blocks all runtime validation (Tasks 4A.4, C1-C3).
None of these block code preparation or IAM policy preparation.

---

## 2. Non-Blocking Unknowns

These do NOT block the core pipeline (Steps 1-7 from corrected classification §9). They can be resolved in parallel or after.

| # | Unknown | Impact of Leaving Unresolved | Blocking? |
|---|---------|------------------------------|-----------|
| U1 | hermee classification (managed or deferred) | hermee remains invisible in `/api/gateway/users`. No quota enforcement. No cost tracking via gateway. hermee's 1 invocation this month is only visible via CloudWatch Logs (not via admin portal). Zero operational risk — hermee has negligible usage. | No |
| U2 | shlee2 classification (managed or exception) | shlee2 remains invisible in both managed user list AND exception-usage endpoint. 3 invocations this month. If exception → needs code change to add to EXCEPTION_USERS dict. If managed → needs principal_policy seed. Zero operational risk — shlee2 has negligible usage. | No |
| U3 | Opus 4.6 in sbkim's allowed_models | sbkim currently proposed without Opus. If sbkim needs Opus later, it's a single DynamoDB UpdateItem. No risk from omitting now. | No |
| U4 | Whether `list_approvals` Scan works on approval_request table | `BedrockGatewayApprovalAdminTemp` grants GetItem/PutItem/UpdateItem/DeleteItem/Query but NOT Scan. Unfiltered `GET /api/gateway/approvals` will fail. Filtered queries (by principal_id) will work via GSI. Workaround: always pass `?principal_id=` or `?status=` filter. Permanent fix: add Scan to ApprovalAdminTemp or add approval-request to ScopeAReadTemp (covered by Task 4A.1). | No — workaround exists |

---

## 3. Work That Can Be Fully Prepared Now (Category A)

No operator decision needed. Can be written, reviewed, and staged immediately.

### A1. IAM Policy Document — BedrockGatewayScopeAReadTemp Update

The exact policy JSON is already in `phase4-backend-remediation-analysis.md` §7. It adds read access (GetItem/Query/Scan) for:
- `bedrock-gw-dev-us-west-2-request-ledger` + indexes
- `bedrock-gw-dev-us-west-2-daily-usage` + indexes
- `bedrock-gw-dev-us-west-2-approval-request` + indexes
- `bedrock-gw-dev-us-west-2-session-metadata` + indexes

This is a single `aws iam create-policy-version` command. The policy document is complete and ready. No identity decisions affect this — it's table-level read access for the infra-admins group.

Impact: Unblocks all future admin-plane read endpoints (ledger, daily-usage, approval history). Also fixes the `list_approvals` Scan issue (U4).

### A2. Model Pricing Seed Commands — 11 DynamoDB PutItem

The exact CLI commands are in `phase4-backend-remediation-analysis.md` §8.1. All 11 items are ready. The only blocker is operator verification of USD rates (H2) and exchange rate (H3).

The commands themselves are fully prepared. Once operator confirms pricing, they can be executed verbatim.

### A3. Principal Policy Seed Commands — 2 Confirmed New + cgjang Update

Confirmed targets (no operator decision needed):
- `107650139384#BedrockUser-jwlee` — new seed (2,917 invocations)
- `107650139384#BedrockUser-sbkim` — new seed (1 invocation)
- `107650139384#BedrockUser-cgjang` — update allowed_models only

CLI commands are in `phase4-backend-remediation-analysis.md` §8.1. Ready to execute.

hermee and shlee2 commands are commented out with clear conditional instructions.

### A4. HTTP Smoke Test Script

Can be written now. Should cover all 10 deployed endpoints:
- 6 read endpoints (gateway_usage.py): pricing, users, user usage, user policy, exception-usage
- 4 approval endpoints (gateway_approval.py): list, get, approve, reject

Requires a valid admin JWT. The JWT_SECRET_KEY is `mogam-portal-secret-key-2024`.

### A5. Security Fix — Add @admin_required to gateway_approval.py

**Finding**: All 4 approval endpoints in `gateway_approval.py` lack the `@admin_required` decorator. They are currently unauthenticated. This is a security gap.

Evidence:
- `gateway_usage.py` correctly applies `@admin_required` to all 6 routes.
- `gateway_approval.py` defines no auth decorator and imports no JWT library.
- `list_approvals()`, `get_approval()`, `approve_request()`, `reject_request()` are all unprotected.

Fix: Import `admin_required` from `gateway_usage` (or duplicate the decorator) and apply to all 4 routes. This is a minimal, safe code change within Phase 4 scope (backend-admin only).

This can be fully prepared now. Requires approval before applying (devops-operating-model).

---

## 4. Work That Can Be Implemented Now But Not Applied Yet (Category B)

Code can be written and reviewed. Cannot be deployed until Docker rebuild (H1) is approved.

### B1. gateway_approval.py Auth Fix (code change)

Add `@admin_required` to all 4 approval routes. Two implementation options:

**Option 1 (preferred): Import from gateway_usage.**
```python
from routes.gateway_usage import admin_required
```
Then decorate all 4 routes. Minimal change, no code duplication.

Risk: Creates an import dependency between blueprints. If gateway_usage.py is removed or refactored, gateway_approval.py breaks. Acceptable for MVP — both files are tightly coupled to the same gateway domain.

**Option 2: Duplicate the decorator.**
Copy the `admin_required` function into gateway_approval.py. More code, but no cross-blueprint dependency.

Recommendation: Option 1. The coupling is already implicit (both files read the same DynamoDB tables with the same naming convention). Making it explicit via import is cleaner.

### B2. Ledger Read Endpoint (gateway_usage.py addition)

After IAM fix (A1), backend-admin can read `request_ledger`. A new endpoint can be prepared:
- `GET /api/gateway/ledger` — paginated scan of request_ledger (admin-only)
- No GSI exists for principal_id on request_ledger. Full scan with client-side filter is the only option without Terraform change.
- For MVP data volume (small), this is acceptable.

This is a Phase 4B task (Task 4B.1). Can be coded now, but deployment requires IAM fix first.

### B3. Approval Timeline Visibility

Current state: approval_request table stores `created_at`, `approved_at`/`rejected_at`, `approved_by`/`rejected_by`. The `GET /api/gateway/approvals` endpoint already returns these fields.

What's missing: no dedicated timeline/history view. The existing endpoint is sufficient for MVP — it returns all fields needed for timeline reconstruction. A dedicated timeline endpoint is a nice-to-have, not a blocker.

No code change needed for MVP. The frontend can construct timeline from existing data.

---

## 5. Work Requiring Operator Decision (Category C)

Cannot proceed until operator explicitly decides.

### C1. hermee Classification

Decision: gateway-managed or deferred?

If managed:
- Seed `107650139384#BedrockUser-hermee` into principal_policy (command prepared, commented out in §8.1)
- hermee becomes visible in `/api/gateway/users`
- hermee becomes subject to quota enforcement when using gateway

If deferred:
- No action. hermee remains invisible to admin portal.
- hermee's 1 invocation this month is only visible via CloudWatch Logs directly (not via admin portal exception-usage either, since hermee is not in EXCEPTION_USERS).
- Can be revisited at any time with a single DynamoDB PutItem.

Impact of leaving unresolved: Zero operational risk. hermee has 1 invocation total. No cost tracking gap worth worrying about.

### C2. shlee2 Classification

Decision: gateway-managed or exception?

If managed:
- Seed `107650139384#BedrockUser-shlee2` into principal_policy (command prepared, commented out)
- shlee2 becomes visible in `/api/gateway/users`

If exception:
- Add shlee2 to EXCEPTION_USERS dict in gateway_usage.py (code change)
- shlee2 becomes visible in `/api/gateway/exception-usage` via CloudWatch Logs
- Requires separate code approval + Docker rebuild

If deferred:
- shlee2 remains invisible everywhere. 3 invocations. No operational risk.

### C3. Opus 4.6 in sbkim's allowed_models

Current proposal: sbkim gets Sonnet-tier models but not Opus. jwlee and cgjang get Opus.

If operator wants sbkim to have Opus: add `us.anthropic.claude-opus-4-6-v1` to sbkim's allowed_models in the seed command. Single field change.

---

## 6. Work Requiring Operator Action (Category D)

These are runtime actions that only the operator can perform.

### D1. IAM Policy Update Execution

Run the `aws iam create-policy-version` command from §7 of the remediation analysis.
Requires: `virginia-sso` profile with IAM write permissions.
Prefix: `env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" aws ...`

### D2. Model Pricing Seed Execution

Run 11 `aws dynamodb put-item` commands from §8.1.
Requires: D1 is NOT a prerequisite (model_pricing is already readable). Can be done in parallel.
Blocked by: H2 (USD pricing verification), H3 (exchange rate confirmation).

### D3. Principal Policy Seed Execution

Run 2 `aws dynamodb put-item` + 1 `aws dynamodb update-item` from §8.1.
No prerequisite. Can be done in parallel with D1 and D2.

### D4. Docker Rebuild

```bash
cd account-portal
docker compose -f docker-compose-fixed.yml up -d --build
```
Picks up gateway_usage.py + gateway_approval.py (+ auth fix if approved).
Blocked by: H1 (operator approval for rebuild).

### D5. HTTP Smoke Test

After D4, validate all 10 endpoints return expected responses.
Requires valid admin JWT.

---

## 7. Execution-Ready Backend/Admin-Plane Packet

### Packet Summary

| Item | Type | Status | Blocked By |
|------|------|--------|------------|
| IAM policy document | Prepared CLI command | Ready to execute | Nothing — can run now |
| Model pricing seed (11 items) | Prepared CLI commands | Ready to execute | H2 (USD verification), H3 (exchange rate) |
| Principal policy seed (jwlee, sbkim, cgjang) | Prepared CLI commands | Ready to execute | Nothing — confirmed targets |
| gateway_approval.py auth fix | Code change (prepared) | Ready to implement | Approval gate (devops-operating-model) |
| Smoke test script | Can be written | Not yet written | D4 (Docker rebuild) for execution |
| Ledger read endpoint | Code change (design ready) | Not yet implemented | A1 (IAM fix) for runtime, approval gate for code |

### Dependency Graph

```
IAM policy update (D1) ──────────────────────────────────┐
Model pricing seed (D2) ─── blocked by H2/H3 ───────────┤
Principal policy seed (D3) ──────────────────────────────┤
gateway_approval.py auth fix (B1) ── needs approval ────┤
                                                          ▼
                                                Docker rebuild (D4)
                                                          │
                                                          ▼
                                                HTTP smoke test (D5)
                                                          │
                                                          ▼
                                            Exception-usage validation (C1-C3)
```

D1, D2, D3 are independent of each other. All three feed into D4.
B1 (auth fix) should be merged before D4 to avoid a second rebuild.

---

## 8. Minimum Safe First Implementation Slice

The smallest useful unit of work that produces a verifiable result:

### Slice 1: IAM + Pricing + Confirmed Seeds (operator actions only, no code)

1. Operator verifies USD pricing for 11 models against AWS pricing page
2. Operator confirms exchange rate (1,450 KRW/USD)
3. Operator runs IAM policy update (D1) — 1 command, ~2 minutes
4. Operator runs model pricing seed (D2) — 11 commands, ~5 minutes
5. Operator runs principal policy seed (D3) — 3 commands, ~3 minutes

After Slice 1: Data layer is correct. But endpoints are unreachable (container not rebuilt).

### Slice 2: Auth fix + Docker rebuild + Smoke test

6. Approve gateway_approval.py auth fix (B1)
7. Implement auth fix (add @admin_required to 4 routes)
8. Docker rebuild (D4)
9. HTTP smoke test all 10 endpoints (D5)
10. Validate exception-usage for shlee (C1-C3)

After Slice 2: All Phase 4 Scope A endpoints are runtime-validated. 3 managed users visible. shlee exception monitoring working with cost estimates.

### Slice 3: Deferred identity decisions (whenever operator is ready)

11. Operator decides hermee → seed or defer
12. Operator decides shlee2 → seed, exception, or defer
13. If shlee2 = exception → code change to EXCEPTION_USERS + another rebuild

Slice 3 has zero urgency. Can happen days or weeks later.

---

## 9. What Should Happen Immediately Next

In priority order:

1. **Operator: Verify USD pricing** for 11 new models against current AWS Bedrock pricing page. This is the single highest-value action — it unblocks the entire pricing seed and cost estimation pipeline. Specific models to verify:
   - `us.anthropic.claude-sonnet-4-6`: proposed $0.003/$0.015 per 1K tokens
   - `us.anthropic.claude-opus-4-6-v1`: proposed $0.015/$0.075 per 1K tokens
   - `us.amazon.nova-2-lite-v1:0`: proposed $0.00006/$0.00024 per 1K tokens
   - Remaining 8 models: same tier pricing as their base variants

2. **Operator: Confirm exchange rate** — still 1,450 KRW/USD?

3. **Operator: Approve gateway_approval.py auth fix** — 4 unauthenticated admin endpoints is a security gap. Minimal code change, no architectural impact, fully reversible.

4. **Operator: Approve Docker rebuild** — required for any runtime validation. No risk to other services (backend-admin only, separate container).

5. **After approvals received**: Execute Slice 1 (data), then Slice 2 (code + rebuild + validate).

Items 1-2 are verification-only (no system changes). Items 3-4 are approval gates. Item 5 is execution.

hermee and shlee2 decisions are explicitly NOT on this list. They can wait.
