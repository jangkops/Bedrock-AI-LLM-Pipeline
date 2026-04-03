# Bedrock Access Control Gateway — Project Status Summary

> Date: 2026-03-23
> Status: Phase 2 COMPLETE. Phase 3 DEPLOYED AND VERIFIED IN DEV. Phase 4 Scope A IMPLEMENTED AND RUNTIME-VALIDATED IN DEV (M1+M3+M4+M5+M7+M8). Scope B (M2 GSI + M6) requires separate Terraform approval.
> This document is a read-only status summary. No implementation authorized.

---

## 1. Phase Status Overview

| Phase | Status | Key Artifact | Date |
|-------|--------|-------------|------|
| Phase 0: Pre-Implementation Decisions | ✅ COMPLETE | `docs/ai/decision-resolution-q1-q6.md` | 2026-03-18 |
| Phase 1: Data Model Migration | ✅ COMPLETE (Tasks 1.1-1.3, 1.6 applied; 1.4 partial, 1.5 Phase 3) | `docs/ai/plan.md`, `docs/ai/phase1-post-apply-validation.md` | 2026-03-18 |
| Phase 2: Lambda Quota Logic Rewrite | ✅ COMPLETE — All C1-C9 PASS | `docs/ai/phase2-dev-validation-report.md` | 2026-03-20 |
| Task 2: Bypass Prevention | ✅ COMPLETE — LIVE VERIFIED | `docs/ai/task2-bypass-prevention-execution.md` | 2026-03-19 |
| Task 3: Principal Discovery | ⚠️ PARTIAL — C1 captured, C2/C3/C5 deferred | `docs/ai/validation_plan.md` | 2026-03-17 |
| Phase 3: Approval Ladder Rewrite | ✅ COMPLETE — DEPLOYED AND VERIFIED IN DEV | `docs/ai/phase3-dev-validation-report.md` | 2026-03-23 |
| Phase 4: Admin API (Scope A) | ✅ SCOPE A IMPLEMENTED AND RUNTIME-VALIDATED IN DEV — M1+M3+M4+M5+M7+M8 | `account-portal/backend-admin/routes/gateway_usage.py` | 2026-03-23 |
| Phase 5: Frontend | ✅ TASK 12 DEPLOYED + NEAR-REAL-TIME UPGRADE | `account-portal/frontend/src/pages/BedrockGateway.jsx` | 2026-03-23 |

---

## 2. What Is Verified and Operational (Ground Truth)

These conclusions are fixed and must not be reopened:

- Phase 2 dev validation: all C1-C9 PASS (2026-03-20)
- cgjang is the canonical validation principal: `107650139384#BedrockUser-cgjang`
- KRW cost-based monthly quota is operational: `estimated_cost_krw: 0.0551`, `remaining_quota.cost_krw: 499999.7796`
- Candidate F normalization live-verified: `<account>#<role-name>` format
- Bypass prevention live-verified: `DenyDirectBedrockInference` on all 6 `BedrockUser-*` roles
- shlee is a deliberate direct-use exception (deny removed per operator approval 2026-03-19)
- `daily_usage` table is legacy/inactive — zero writes since Phase 2
- `session_metadata` is internal/support data, NOT a dashboard source
- Approval ladder semantics: cumulative band model (500K → 1M → 1.5M → 2M)
- Model IDs: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (primary), `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (fallback)
- IAM: `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` (not `bedrock:Converse`)

---

## 3. Phase 3 Status

Phase 3 DEPLOYED AND VERIFIED IN DEV (2026-03-23). All critical acceptance criteria pass.

| Item | Status |
|------|--------|
| Operator approval | ✅ GRANTED (2026-03-22, `PHASE3_APPROVED = true`) |
| `handler.py:handle_approval_request()` — reason/increment/hard-cap validation | ✅ DEPLOYED AND VERIFIED |
| `handler.py:_send_approval_email()` — KRW context in email body | ✅ DEPLOYED AND VERIFIED |
| `gateway_approval.py:_end_of_month_ttl()` — UTC→KST fix | ✅ DEPLOYED AND VERIFIED |
| `gateway_approval.py` SES email text — KST reference | ✅ DEPLOYED AND VERIFIED |
| `terraform apply` (Lambda code hash update) | ✅ COMPLETE — `0 added, 1 changed, 0 destroyed` |
| Docker rebuild (backend-admin) | ✅ COMPLETE — running healthy |
| SES domain verification (`mogam.er.kr`) (R23) | ❌ PENDING — non-blocking for core logic |
| AC7 (inference regression) | ✅ PASS — HTTP 200, `decision=ALLOW`, `estimated_cost_krw=0.0551` |
| AC1 (empty reason) | ✅ PASS — HTTP 400 |
| AC2 (wrong increment) | ✅ PASS — HTTP 400, `"must be 500000 (got 100000)"` |
| AC5 (valid request) | ✅ PASS — HTTP 201, enriched record created |
| Approve path | ✅ PASS — boost created, `new_effective_limit_krw=1000000` |
| KST TTL | ✅ PASS — `1774969199` = 2026-03-31T23:59:59 KST |

Final report: `docs/ai/phase3-dev-validation-report.md`.

---

## 4. What Blocks Phase 4 Scope B

| Blocker | Type | Resolution |
|---------|------|------------|
| ~~Phase 3 completion~~ | ~~Dependency~~ | ✅ Phase 3 COMPLETE (2026-03-23) |
| ~~Phase 4 Scope A approval~~ | ~~Governance~~ | ✅ Scope A IMPLEMENTED (2026-03-23) |
| Phase 4 Scope B approval | Governance | Separate Terraform approval required for M2 (GSI) + M6 (request history) |
| GSI on `request_ledger` (BL-1) | Terraform | Additive, no blast radius. Required for M6 endpoint. |

Phase 4 Scope A (IMPLEMENTED):
- M1: Admin auth enforcement (`@admin_required`) ✅
- M3: `gateway_usage.py` blueprint + `app.py` registration ✅
- M4: GET /api/gateway/users ✅
- M5: GET /api/gateway/users/<pid>/usage ✅
- M7: GET /api/gateway/users/<pid>/policy ✅
- M8: GET /api/gateway/pricing ✅

Phase 4 Scope B (BLOCKED — requires Terraform approval):
- M2: GSI on `request_ledger` (principal_id + timestamp)
- M6: GET /api/gateway/users/<pid>/requests

Execution-readiness verdict: READY pending operator approval. See `docs/ai/phase4-execution-readiness-master.md`.

---

## 4a. Phase 4 Scope A Validation Results (2026-03-23)

| Check | Result | Evidence |
|-------|--------|----------|
| Container healthy | ✅ PASS | `Up (healthy)` |
| Route registration (4 routes) | ✅ PASS | All 4 Scope A routes confirmed at runtime |
| Auth: no header → 401 | ✅ PASS | `{"error":"missing or malformed Authorization header"}` |
| Auth: non-admin JWT → 403 | ✅ PASS | `{"error":"admin role required"}` |
| Auth: expired JWT → 401 | ✅ PASS | `{"error":"token expired"}` |
| Auth: invalid signature → 401 | ✅ PASS | `{"error":"invalid token"}` |
| M8 pricing → 200 | ✅ PASS | 5 models returned with KRW pricing |
| M4 users → 200 | ✅ PASS | cgjang in `managed_users`, shlee in `exception_users` only |
| M4 cgjang cost data | ✅ PASS | `current_month_cost_krw: 0.2755`, `effective_limit_krw: 500000` |
| M5 cgjang usage → 200 | ✅ PASS | 1 model, `cost_krw: 0.2755`, pricing join correct |
| M5 shlee → 404 | ✅ PASS | `"exception user — no gateway usage data"` |
| M7 cgjang policy → 200 | ✅ PASS | 5 allowed models, `effective_limit_krw: 500000`, `approval_band: 0` |
| M7 shlee → 404 | ✅ PASS | `"exception user — no gateway policy"` |
| Nonexistent principal → 404 | ✅ PASS | Both usage and policy return `"principal not found"` |
| Decimal/JSON serialization | ✅ PASS | No serialization errors across all endpoints |

---

## 5. Open Risks

| # | Risk | Severity | Phase |
|---|------|----------|-------|
| R2 | SCP 적용 승인 지연 | Medium | Post-implementation |
| R10 | ~~backend-admin IAM role 확장 승인 지연~~ | ~~Medium~~ | ✅ RESOLVED (2026-03-23) — DynamoDB read 권한 추가, Scope A 런타임 검증 완료 |
| R22 | ModelPricing staleness | Medium | Operational |
| R23 | Approver email domain unverified (`mogam.er.kr`) | Medium | Phase 3 |
| R24 | ~~`_end_of_month_ttl()` UTC→KST 미수정~~ | ~~Low~~ | ✅ RESOLVED AND DEPLOYED (2026-03-23) — KST fix applied and verified. TTL `1774969199` = 2026-03-31T23:59:59 KST. |
| R25 | ~~Lambda `handle_approval_request()` 입력 검증 부재~~ | ~~Medium~~ | ✅ RESOLVED AND DEPLOYED (2026-03-23) — reason/increment/hard-cap validation deployed and verified. |
| R26 | Approval endpoint 인가 — `@admin_required` 이미 적용됨, Phase 3 유지 검증 | High→Mitigated | 기존 코드 확인됨 |

---

## 6. Deferred Validation (Task 3)

| Capture | Status | Impact |
|---------|--------|--------|
| C1 (cgjang FSx) | ✅ CAPTURED | Candidate F live-verified |
| C2 (cgjang laptop) | ❌ DEFERRED | Cross-env consistency — Candidate F structurally sound, not blocking |
| C3 (cross-role isolation) | ❌ DEFERRED | Cross-role isolation — unit-tested, not blocking |
| C5 (fail-closed) | ❌ DEFERRED | Fail-closed — unit-tested, not blocking |

---

## 7. Artifact Index

### Spec Documents
| File | Purpose | Last Updated |
|------|---------|-------------|
| `.kiro/specs/bedrock-access-gateway/requirements.md` | EARS requirements | 2026-03-20 |
| `.kiro/specs/bedrock-access-gateway/design.md` | Architecture and data model | 2026-03-20 |
| `.kiro/specs/bedrock-access-gateway/tasks.md` | Implementation task list | 2026-03-20 |

### Governance Documents
| File | Purpose | Last Updated |
|------|---------|-------------|
| `docs/ai/todo.md` | Master TODO tracker | 2026-03-23 |
| `docs/ai/risk_register.md` | Risk register (R1-R26) | 2026-03-23 |
| `docs/ai/runbook.md` | Operator runbook | 2026-03-23 |
| `docs/ai/rollback.md` | Rollback procedures | 2026-03-23 |
| `docs/ai/validation_plan.md` | Validation plan (Task 3 + Phase 2) | 2026-03-23 |
| `docs/ai/plan.md` | Phase 1 implementation plan | 2026-03-20 |

### Phase-Specific Documents
| File | Purpose | Last Updated |
|------|---------|-------------|
| `docs/ai/phase2-dev-validation-report.md` | Phase 2 final validation report | 2026-03-20 |
| `docs/ai/phase3-approval-ladder-semantics.md` | Approval ladder definitive spec | 2026-03-20 |
| `docs/ai/phase3-implementation-ready-draft.md` | Phase 3 implementation plan (IMPLEMENTED) | 2026-03-23 |
| `docs/ai/phase3-dev-validation-report.md` | Phase 3 final validation report | 2026-03-23 |

### Phase 4 Execution-Readiness
| File | Purpose | Last Updated |
|------|---------|-------------|
| `docs/ai/phase4-execution-readiness-master.md` | **Single authoritative Phase 4 artifact** (MVP boundary, ready/blocked, implementation order) | 2026-03-23 |
| `docs/ai/account-portal-mvp-api-data-contract.md` | Authoritative API schemas (request/response formats) | 2026-03-20 |

### Historical / Superseded (reference only)
| File | Purpose | Last Updated |
|------|---------|-------------|
| `docs/ai/phase4-backend-mvp-execution-package.md` | Superseded by `phase4-execution-readiness-master.md` | 2026-03-23 |
| `docs/ai/account-portal-implementation-ready-backlog.md` | Superseded by `phase4-execution-readiness-master.md` | 2026-03-23 |
| `docs/ai/account-portal-operator-observability-future-work.md` | Post-MVP future work reference (Phase 4 MVP items consolidated) | 2026-03-20 |

---

## 8. Next Actions (by priority)

1. **Phase 4 Scope B approval decision** — GSI on `request_ledger` (Terraform additive) + M6 request-history endpoint. See `docs/ai/phase4-execution-readiness-master.md`.
2. **Frontend user page (Task 13)** — User-facing usage/quota view. Requires design decision on auth model (user JWT vs admin-only).
3. **SES domain verification** (R23) — operator must verify `mogam.er.kr` for real email delivery. Non-blocking for Phase 4 query endpoints.
4. **Deferred Task 3 captures** (C2/C3/C5) — optional validation follow-up, not blocking.
5. **Clean up old assets** — `dist.bak` and old hashed assets in `dist/assets/` can be removed after operator confirms portal is stable.

---

## Boundary Statement

This document is a read-only status summary. No runtime code, IaC, deployment configs, or infrastructure were modified.
