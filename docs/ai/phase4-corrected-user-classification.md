# Phase 4 — Corrected User Classification & Next Work Packet

> Date: 2026-03-24
> Status: Planning artifact — no implementation changes.
> Supersedes user classification sections of `phase4-backend-remediation-analysis.md`.
> Operator corrections applied: sbkim identity, shlee exception lock, hermee deferred, endpoint validation status.

---

## 1. Confirmed Gateway-Managed Seed Targets

Only users with explicit operator approval or clear operational justification:

| Principal ID | Justification | Invocations (2026-03) |
|---|---|---|
| `107650139384#BedrockUser-cgjang` | Already registered. Canonical validation principal. Update `allowed_models` only. | Smoke test |
| `107650139384#BedrockUser-jwlee` | Second-heaviest user (2,917 invocations). Active gateway candidate. | 2,917 |
| `107650139384#BedrockUser-sbkim` | Existing BedrockUser role. Minimal usage (1 invocation). | 1 |

Seed parameters: `monthly_cost_limit_krw=500000`, `max_monthly_cost_limit_krw=2000000`,
approval-band model (500K increments, hard cap 2M KRW), month-scoped TTL.

---

## 2. Users Requiring Separate Operator Decision

| Principal ID | Invocations | Question |
|---|---|---|
| `107650139384#BedrockUser-hermee` | 1 | Usage alone does not equal policy enrollment. Operator must explicitly approve hermee as gateway-managed before seeding. |
| `107650139384#BedrockUser-shlee2` | 3 | Operator must decide: gateway-managed (seed into principal_policy) or exception/direct-use (add to EXCEPTION_USERS)? |

Neither hermee nor shlee2 should be seeded until the operator explicitly confirms their classification.

---

## 3. Confirmed Exception-Only Users

| Principal ID | Status | Enforcement |
|---|---|---|
| `107650139384#BedrockUser-shlee` | Direct-use exception — **locked operator decision** | No quota enforcement. No approval-band. No principal_policy entry. Unrestricted direct Bedrock access. Monitoring-only via CloudWatch Logs. |

Locked truths:
- shlee is NOT seeded into `principal_policy` — ever, unless operator explicitly reverses this decision.
- shlee is NOT subject to gateway quota / approval / monthly limit enforcement.
- shlee visibility in monitoring does NOT imply policy enrollment.
- shlee appears in `EXCEPTION_USERS` dict in `gateway_usage.py` (code already correct).

---

## 4. Implemented vs Assumed Exception Monitoring Paths

### Implemented (code exists in repo):

| Endpoint | File | Status |
|---|---|---|
| `GET /api/gateway/exception-usage` | `gateway_usage.py` line 545 | **Code exists. Route defined. Blueprint registered in app.py.** |
| `GET /api/gateway/pricing` | `gateway_usage.py` line 168 | Code exists. Route defined. |
| `GET /api/gateway/users` | `gateway_usage.py` line 178 | Code exists. Route defined. |
| `GET /api/gateway/users/<pid>/usage` | `gateway_usage.py` line 213 | Code exists. Route defined. |
| `GET /api/gateway/users/<pid>/policy` | `gateway_usage.py` line 248 | Code exists. Route defined. |

### NOT runtime-validated:

**Critical gap**: There is no documented evidence that the backend-admin Docker container
was rebuilt after `gateway_usage.py` was added (Phase 4 Scope A). The last confirmed
Docker rebuild was during Phase 3 (2026-03-23), before gateway_usage.py existed.

This means:
- The code is in the repo and syntactically valid (getDiagnostics passed).
- The blueprint is registered in `app.py`.
- But the running container may still be serving the Phase 3 image.
- No HTTP-level validation (curl, smoke test) has been performed on any Phase 4 Scope A endpoint.
- The `/api/gateway/exception-usage` endpoint specifically depends on CloudWatch Logs Insights
  queries that have a 2-second polling loop — this has never been tested at runtime.

**Before claiming any endpoint "works", a Docker rebuild + HTTP smoke test is required.**

### Proposed/Future (not yet implemented):

| Endpoint | Status |
|---|---|
| `GET /api/gateway/ledger` | Not implemented. Requires IAM fix (4A.1) first. |
| `GET /api/gateway/users/<pid>/history` | Not implemented. Requires request_ledger GSI or full-scan approach. |
| `routes/gateway_policy.py` (CRUD) | Not implemented. |
| `routes/gateway_pricing.py` (CRUD) | Not implemented. |

---

## 5. Corrected Final Classification

```
┌─────────────────────────────────────────────────────────────┐
│ CONFIRMED GATEWAY-MANAGED (seed immediately upon approval)  │
│   cgjang  — update allowed_models                           │
│   jwlee   — new seed (2,917 invocations)                    │
│   sbkim   — new seed (1 invocation)                         │
├─────────────────────────────────────────────────────────────┤
│ OPERATOR DECISION REQUIRED                                  │
│   hermee  — managed or deferred? (1 invocation)             │
│   shlee2  — managed or exception? (3 invocations)           │
├─────────────────────────────────────────────────────────────┤
│ LOCKED EXCEPTION (monitoring only, no policy enrollment)    │
│   shlee   — direct-use, unrestricted Bedrock access         │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Immediate Backend/Admin-Plane Next Tasks

These can proceed with no additional operator identity decisions:

| # | Task | Dependency | Type |
|---|---|---|---|
| A1 | Docker rebuild backend-admin to pick up gateway_usage.py + gateway_approval.py | None | Operator action |
| A2 | HTTP smoke test all 6 read endpoints + 4 approval endpoints | A1 | Operator validation |
| A3 | Seed model_pricing (11 items) | None — data-only, no identity dependency | Operator action |
| A4 | Seed principal_policy for confirmed users only (jwlee, sbkim) + update cgjang allowed_models | None — confirmed targets only | Operator action |

Tasks A1-A4 are safe to execute without resolving hermee/shlee2 classification.

---

## 7. Immediate IAM / Read-Access Next Tasks

| # | Task | Dependency | Type |
|---|---|---|---|
| B1 | Update `BedrockGatewayScopeAReadTemp` to add request-ledger, daily-usage, approval-request, session-metadata | None | Operator IAM action |

This is independent of user classification. It unblocks table reads for all future
admin-plane endpoints regardless of which users are managed.

Exact CLI command: see `phase4-backend-remediation-analysis.md` §7.
AWS CLI prefix: `env AWS_PROFILE=virginia-sso AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2 AWS_PAGER="" aws ...`

---

## 8. Immediate Monitoring / Data-Source Next Tasks

| # | Task | Dependency | Type |
|---|---|---|---|
| C1 | Validate `/api/gateway/exception-usage` returns shlee data after Docker rebuild | A1 (rebuild) + A3 (pricing seed) | Operator validation |
| C2 | Verify CloudWatch Logs Insights query completes within timeout (20s polling) | A1 | Operator validation |
| C3 | Confirm exception-usage cost estimation works for shlee's top models after pricing seed | A1 + A3 | Operator validation |

C1-C3 validate the exception monitoring path that is implemented in code but never runtime-tested.

---

## 9. Exact Next Implementation Order

```
Step 1: IAM policy update (B1)                    — unblocks all table reads
Step 2: Model pricing seed (A3, 11 items)          — unblocks cost estimation for all users
Step 3: Docker rebuild backend-admin (A1)          — picks up Phase 4 Scope A code
Step 4: HTTP smoke test all endpoints (A2)         — validates code actually works at runtime
Step 5: Validate exception-usage for shlee (C1-C3) — confirms monitoring path
Step 6: Seed confirmed managed users (A4)          — jwlee + sbkim + cgjang update only
Step 7: Verify managed user data in API (A2 re-run)— confirm users visible in /api/gateway/users
```

Steps 1-7 require NO additional operator identity decisions.
hermee and shlee2 seeding is deferred until operator explicitly classifies them.

After Step 7, the operator can:
- Decide hermee classification → seed if managed
- Decide shlee2 classification → seed if managed, or add to EXCEPTION_USERS if exception

---

## 10. Remaining Operator Decisions

| # | Decision | Impact | Blocking? |
|---|---|---|---|
| 1 | hermee: gateway-managed or deferred? | If managed → seed into principal_policy. If deferred → no action needed now. | Not blocking Steps 1-7 |
| 2 | shlee2: gateway-managed or exception? | If managed → seed into principal_policy. If exception → add to EXCEPTION_USERS dict (code change). | Not blocking Steps 1-7 |
| 3 | USD pricing verification for 11 new models | Operator must verify against current AWS pricing page before executing Step 2. | Blocks Step 2 |
| 4 | Opus 4.6 in all managed users' allowed_models? | Currently proposed for jwlee + cgjang only. sbkim proposed without Opus. | Not blocking — can be updated later via DynamoDB UpdateItem |
| 5 | Exchange rate: stay at 1,450 KRW/USD? | Affects all KRW pricing calculations. | Blocks Step 2 if rate has changed significantly |
| 6 | Docker rebuild approval | Phase 4 Scope A code is in repo but container not rebuilt. Operator must approve rebuild. | Blocks Steps 3-7 |

Decision #3 (USD pricing) and #6 (Docker rebuild) are the only ones blocking immediate progress.
All identity decisions (#1, #2, #4) can be deferred without blocking the core pipeline.
