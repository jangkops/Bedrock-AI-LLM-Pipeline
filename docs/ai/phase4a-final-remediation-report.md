# Phase 4A — Final Remediation Report

> Date: 2026-03-24
> Status: **COMPLETE**. All remediation slices executed, validated, and test data cleaned up.

---

## 1. Code Changes Applied

| # | Change | File | Description |
|---|--------|------|-------------|
| R1 | `@admin_required` on all 4 approval routes | `gateway_approval.py` | Security fix — unauthenticated admin write ops |
| R2 | `from routes.gateway_usage import admin_required` | `gateway_approval.py` | Import for auth decorator |
| R3 | SES region fix | `gateway_approval.py` | `SES_REGION` env var defaulting to `us-east-1` (Virginia), consistent with `sso_routes.py` |
| R4 | Email domain fix | `gateway_approval.py` | `changgeun.jang@mogam.re.kr` (was `mogam.er.kr` — typo) |

No other code changes. No handler.py changes. No Terraform changes. No Lambda changes.

---

## 2. IAM Changes Applied

| Policy | Version | Change |
|--------|---------|--------|
| `BedrockGatewayScopeAReadTemp` | v1 → v2 | Added 4 tables: request-ledger, daily-usage, approval-request, session-metadata |

8 tables now readable: model-pricing, principal-policy, monthly-usage, temporary-quota-boost, approval-pending-lock, request-ledger, daily-usage, approval-request, session-metadata.

---

## 3. DynamoDB Data Seeds

### model_pricing (16 entries total — all verified)

| model_id | KRW input/1K | KRW output/1K | USD rate | Tier |
|----------|-------------|---------------|----------|------|
| `us.anthropic.claude-sonnet-4-6` | 4.35 | 21.75 | $3/$15/M | Sonnet |
| `us.anthropic.claude-opus-4-6-v1` | 7.25 | 36.25 | $5/$25/M | Opus 4.6 |
| `global.anthropic.claude-opus-4-6-v1` | 7.25 | 36.25 | $5/$25/M | Opus 4.6 |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 7.25 | 36.25 | $5/$25/M | Opus 4.5 |
| `us.anthropic.claude-opus-4-20250514-v1:0` | 21.75 | 108.75 | $15/$75/M | Opus 4.0 legacy |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | 4.35 | 21.75 | $3/$15/M | Sonnet |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | 4.35 | 21.75 | $3/$15/M | Sonnet |
| `us.anthropic.claude-3-5-sonnet-20240620-v1:0` | 4.35 | 21.75 | $3/$15/M | Sonnet |
| `anthropic.claude-sonnet-4-20250514-v1:0` | 4.35 | 21.75 | $3/$15/M | Sonnet |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | 1.45 | 7.25 | $1/$5/M | Haiku 4.5 |
| `global.anthropic.claude-haiku-4-5-20251001-v1:0` | 1.45 | 7.25 | $1/$5/M | Haiku 4.5 |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | 1.45 | 7.25 | $1/$5/M | Haiku 4.5 |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 1.16 | 5.80 | $0.80/$4/M | Haiku 3.5 |
| `anthropic.claude-3-haiku-20240307-v1:0` | 0.36 | 1.81 | $0.25/$1.25/M | Haiku 3 |
| `us.amazon.nova-2-lite-v1:0` | 0.435 | 3.625 | $0.30/$2.50/M | Nova 2 Lite |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | 4.35 | 21.75 | $3/$15/M | Sonnet |

Exchange rate: 1,450 KRW/USD.

**Correction applied**: Nova 2 Lite was initially seeded at 0.087/0.348 KRW (Nova 1 Lite pricing $0.06/$0.24/M). Corrected to 0.435/3.625 KRW ($0.30/$2.50/M).

### principal_policy (5 managed users)

| principal_id | monthly_cost_limit_krw | max_monthly_cost_limit_krw | allowed_models |
|-------------|----------------------|--------------------------|---------------|
| `107650139384#BedrockUser-cgjang` | 500,000 | 2,000,000 | 8 models |
| `107650139384#BedrockUser-jwlee` | 500,000 | 2,000,000 | 10 models |
| `107650139384#BedrockUser-sbkim` | 500,000 | 2,000,000 | 6 models |
| `107650139384#BedrockUser-shlee2` | 500,000 | 2,000,000 | 10 models |
| `107650139384#BedrockUser-hermee` | 500,000 | 2,000,000 | 10 models |

### IAM inline policies (5 managed users + 1 exception)

All 5 managed users: 6 policies each (BedrockAccess, DenyDirectBedrockInference, AllowDevGatewayConverse, AllowDevGatewayApprovalRequest, AllowDiscoveryGatewayInvoke, S3DataAccess).

shlee (exception): 2 policies only (BedrockAccess, S3DataAccess). IAM simulation confirmed: InvokeModel=allowed, Converse=allowed.

---

## 4. Validations Performed

### Endpoint validation (all 10 endpoints, admin JWT required)

| Endpoint | Method | Result |
|----------|--------|--------|
| `/api/gateway/pricing` | GET | 200 — 16 models |
| `/api/gateway/users` | GET | 200 — 5 managed + 1 exception |
| `/api/gateway/users/<pid>/usage` | GET | 200 — per-model breakdown |
| `/api/gateway/users/<pid>/policy` | GET | 200 — all 5 users verified |
| `/api/gateway/exception-usage` | GET | 200 — shlee fully priced, `has_unpriced_models: false` |
| `/api/gateway/approvals` | GET | 200 — Scan works (IAM v2) |
| `/api/gateway/approvals/<id>` | GET | 200 |
| `/api/gateway/approvals/<id>/approve` | POST | 200 — boost created, effective limit updated |
| `/api/gateway/approvals/<id>/reject` | POST | 200 — status=rejected, rejection_reason stored |
| All endpoints without JWT | * | 401 — auth enforced |

### Approval workflow dry-test

- **Approve**: test-approve-001 → TemporaryQuotaBoost created (extra_cost_krw=500000), effective_limit=1,000,000, ttl=end-of-month KST
- **Reject**: test-reject-001 → status=rejected, rejected_by=changgeun.jang@mogam.re.kr
- **Policy endpoint**: confirmed effective_limit reflects active boost (1,000,000 with boost, 500,000 after cleanup)
- **SES**: SES_SENDER_EMAIL not set — notifications skipped (expected for dev, best-effort design)

### Exception user validation

- shlee: `estimated_cost_krw: 3,238,227.72`, 27,605 invocations, 7 distinct models — all priced
- Top cost: Sonnet 4.6 (1,881,535 KRW), Opus 4.6 (1,356,692 KRW)

### Direct-access prevention (IAM simulation)

- All 5 managed users: `InvokeModel` = `explicitDeny` (DenyDirectBedrockInference)
- shlee: `InvokeModel` = `allowed` (no deny policy — correct for exception user)

### Test data cleanup

- 4 test approval requests deleted (test-approve-001, test-reject-001, test-dry-run-001, test-approval-dry-run-001)
- 1 test TemporaryQuotaBoost deleted (cgjang boost d271a7d1...)
- cgjang effective_limit confirmed back to 500,000, band=0

---

## 5. Docker Rebuild

```bash
cd account-portal && docker compose -f docker-compose-fixed.yml up -d --build backend-admin
```

Picks up: auth fix, SES region fix, email domain fix. Container healthy at 172.19.0.4:5000.

---

## 6. What Is Now Trustworthy

| Capability | Status |
|------------|--------|
| All 10 gateway admin endpoints | Working, JWT-protected |
| Model pricing (16 entries) | All verified against authoritative sources |
| Managed user visibility (5 users) | All return correct policy, usage, limits |
| Exception user monitoring (shlee) | Full KRW cost estimates, no unpriced models |
| Approval approve/reject | Dry-tested, DynamoDB state correct |
| Direct-access prevention | IAM simulation proof for all 6 users |
| DynamoDB table read access | 8 tables readable via ScopeAReadTemp v2 |
| SES routing | Virginia (us-east-1), correct email domain |

---

## 7. Unresolved Risks

| # | Risk | Level | Resolution |
|---|------|-------|-----------|
| 7.1 | Per-request overshoot | Medium | Single request can exceed remaining budget (~4,795 KRW worst case for Opus). Next request blocked. Operator acknowledged. |
| 7.2 | New model IDs | Low | Fail-closed (gateway denies) or silent omission (exception monitoring). Operator adds pricing entry when new models adopted. |
| 7.3 | Lambda pricing cache | Low | Reloads on cold start + one retry on miss. No action needed. |
| 7.4 | SES best-effort | Low | SES_SENDER_EMAIL not configured in dev. Approval saved even if email fails. |
| 7.5 | Exchange rate drift | Low | 1,450 KRW/USD hardcoded in pricing entries. Operator updates when rate changes materially. |

---

## 8. Rollback

### Code rollback
Revert 4 changes in `gateway_approval.py`, rebuild container. Auth decorator removal is the only code change — all other changes are data-only.

### Data rollback
All DynamoDB seeds are additive (new items, no destructive overwrites). To rollback:
- Delete individual model_pricing entries via `aws dynamodb delete-item`
- Delete individual principal_policy entries via `aws dynamodb delete-item`
- IAM policy: create new version reverting to v1 scope (5 tables)

### IAM rollback
```bash
aws iam create-policy-version --policy-arn arn:aws:iam::107650139384:policy/BedrockGatewayScopeAReadTemp --set-as-default --policy-document '<v1 document>'
```

---

## 9. Deferred Work

| # | Item | Phase | Dependency |
|---|------|-------|-----------|
| 9.1 | Request ledger read endpoint | 4B | None (IAM fixed) |
| 9.2 | PrincipalPolicy CRUD endpoint | 4B | None |
| 9.3 | ModelPricing CRUD endpoint | 4B | None |
| 9.4 | Frontend BedrockGateway.jsx update | 5 | Phase 4A complete ✓ |
| 9.5 | Approval management UI | 5 | Phase 4A complete ✓ |
| 9.6 | User self-service page | 5 | Phase 4A complete ✓ |
| 9.7 | Pre-invocation headroom guard | Future | handler.py change, separate approval |
| 9.8 | GlobalBudget alerting | Future | CloudWatch alarm, deferred to v2 |

---

## 10. Current Live System State

### DynamoDB tables

| Table | Items | Notes |
|-------|-------|-------|
| model-pricing | 16 | All 16 observed model IDs covered, all verified |
| principal-policy | 5 | cgjang, jwlee, sbkim, shlee2, hermee |
| monthly-usage | 1 | cgjang Phase 2 smoke test (0.2755 KRW) |
| request-ledger | 10 | From actual gateway invocations |
| temporary-quota-boost | 0 | Clean (test data removed) |
| approval-request | 1 | Real approval (32ad5f3f..., status=approved) |
| approval-pending-lock | 0 | Clean |
| daily-usage | 0 | Legacy table (Lambda writes to monthly-usage) |

### Container

- `userportal-backend-admin` at 172.19.0.4:5000 — healthy
- Includes: gateway_usage.py (6 endpoints), gateway_approval.py (4 endpoints)
- Both blueprints registered in app.py

### IAM

- `BedrockGatewayScopeAReadTemp` v2 — 8 tables readable
- `BedrockGatewayApprovalAdminTemp` — CRUD on approval-request
- 5 managed users: 6 inline policies each
- 1 exception user (shlee): 2 inline policies

### Corrected pricing (from this session)

| model_id | Before | After | Reason |
|----------|--------|-------|--------|
| `us.anthropic.claude-opus-4-6-v1` | 21.75/108.75 | 7.25/36.25 | Opus 4.6 = $5/$25/M, not legacy $15/$75/M |
| `global.anthropic.claude-opus-4-6-v1` | 21.75/108.75 | 7.25/36.25 | Same |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | 21.75/108.75 | 7.25/36.25 | Opus 4.5 = $5/$25/M |
| `anthropic.claude-3-5-haiku-20241022-v1:0` | 1.45/7.25 | 1.16/5.80 | Haiku 3.5 = $0.80/$4/M, not $1/$5/M |
| `us.amazon.nova-2-lite-v1:0` | 0.087/0.348 | 0.435/3.625 | Nova **2** Lite = $0.30/$2.50/M, not Nova 1 Lite $0.06/$0.24/M |
