# TODO: Bedrock Access Control Gateway

> Phase 2 artifact. Updated: 2026-03-23.
> Identity model re-baselined: per-user assume-role (`BedrockUser-<username>`) is primary.
>
> **DEPLOYMENT BLOCK PARTIALLY LIFTED (2026-03-17)**: `normalize_principal_id()` implemented with Candidate F (`<account>#<role-name>`).
> Single-user live-verified (cgjang FSx, session `botocore-session-1773807868`): `derived_principal_id` = `107650139384#BedrockUser-cgjang`.
> Discovery Lambda 재배포 완료. 11 unit tests pass.
> Remaining captures (C2 laptop, C3 cross-role, C5 fail-closed) are deferred — treat as validation follow-up, not blocker.
> `terraform apply` to prod is permitted after remaining captures confirm the rule or operator accepts single-user evidence risk.
>
> **PHASE 1 APPLIED TO DEV (2026-03-18)**: Additive approach (Option B). `monthly_usage` + `model_pricing` tables deployed alongside existing `daily_usage`. IAM + outputs updated. `daily_usage` preserved. Runtime unchanged.
>
> **PHASE 2 DEPLOYED TO DEV (2026-03-18)**: Lambda quota logic rewrite deployed. `handler.py` + `lambda.tf` updated, `terraform apply` complete (API `5l764dh7y9`). Env vars `TABLE_MONTHLY_USAGE` + `TABLE_MODEL_PRICING` confirmed present. **SEED DATA APPLIED (2026-03-18). IAM BEDROCK FIX APPLIED (2026-03-19). INFERENCE PROFILE FIX APPLIED (2026-03-19).** 4.5+ model keys switched from base model IDs to cross-region inference profile IDs (`us.` prefix) in `model_pricing` + `principal_policy`. No runtime code change. See `docs/ai/phase2-inference-profile-fix.md`. **COST-PRECISION FIX (`int()`→`float()`) + DECIMAL LEDGER FIX (2026-03-20) — DEPLOYED AND VERIFIED.** cgjang live smoke test PASSED: `decision: ALLOW`, `estimated_cost_krw: 0.0551`, `remaining_quota.cost_krw: 499999.7796`. Ledger defect (`float()` → raw `Decimal`) confirmed resolved. See `docs/ai/phase2-cgjang-validation-plan.md`.
>
> **TASK 2 BYPASS PREVENTION COMPLETE (2026-03-19)**: `DenyDirectBedrockInference` inline policy applied to all 6 `BedrockUser-*` roles. **LIVE VERIFIED**: direct Bedrock calls denied (`AccessDeniedException` across providers/models), gateway path reaches Lambda. See `docs/ai/task2-bypass-prevention-execution.md`.

## Pre-Implementation (현재 단계)

- [x] Architecture decision: A (API Gateway + AWS_IAM + Lambda) 확정
- [x] IaC tool: Terraform 확정. SAM/CDK 제거.
- [x] v1 Bedrock API scope: Converse only. InvokeModel/ConverseStream v2 연기.
- [x] Quota semantics: Principal 글로벌 (모델별 아님)
- [x] Phase 2 거버넌스 아티팩트 생성
- [x] Implementation-readiness review 완료
- [x] 리뷰 결과 반영 (blocker 해소)
- [x] Non-disruption governance policy 적용 (devops-operating-model.md, tech.md, requirements.md, design.md, research.md)
- [x] Approval-gate-check hook 확장 (Terraform, Ansible, nginx, docker-compose 패턴 추가)
- [x] FSx credential model 분석 완료: permission-set-based named profile 후보 확정, 리스크 문서화
- [x] Pre-implementation consistency check 완료: tasks.md, risk_register.md, rollback.md, research.md B-version 정합성 수정
- [x] ApprovalPendingLock race-safe fix 완료: 8개 DynamoDB 테이블, locked decision #10 추가, 전체 문서 정합성 반영
- [x] Identity model re-baseline: per-user assume-role (`BedrockUser-<username>`) primary로 확정. Permission-set 모델은 optional future path로 강등. 전체 docs/specs/governance 아티팩트 업데이트.
- [x] 사용자 Phase 1 구현 승인 획득
- [x] **Phase 0 Q1-Q6 결정 완료 (2026-03-18)**: Q1=fixed KRW ModelPricing, Q2=alerting-only, Q3=KST, Q4=EOM KST, Q5=deep link v1, Q6=keep tokens. `docs/ai/decision-resolution-q1-q6.md` 참조.

## Implementation (승인 후)

- [x] Task 1: Terraform 스캐폴딩 (split-file: main.tf, iam.tf, dynamodb.tf, lambda.tf, logs.tf, locals.tf)
- [x] Task 2: Direct Bedrock access deny policy for human per-user roles (`BedrockUser-*`) — **LIVE VERIFIED / COMPLETE (2026-03-19)**. `DenyDirectBedrockInference` inline policy applied to all 6 `BedrockUser-*` roles. Live evidence: (A) direct Bedrock calls denied with `AccessDeniedException` across providers/models, (B) gateway-path request reached Lambda (downstream inference-profile error is Phase 2 scope, not Task 2). See `docs/ai/task2-bypass-prevention-execution.md`. **Exception: `BedrockUser-shlee` — deny policy removed (2026-03-19) per operator approval. shlee uses direct Bedrock (not gateway). See `docs/ai/shlee-block-investigation.md`.**
- [ ] Task 3: Principal discovery for per-user assume-role sessions (랩탑 + FSx 두 환경) — **Phase A (setup) COMPLETE: discovery gateway deployed (`ugpt5xi8b7`, stage `v1`). Phase E (code review) COMPLETE. Phase F (normalization impl + redeploy) COMPLETE: Candidate F live-verified (`107650139384#BedrockUser-cgjang`). C1 (cgjang FSx) CAPTURED + live smoke test PASSED. Deferred: C2 (cgjang laptop), C3 (cross-role), C5 (fail-closed). Evidence: `docs/ai/discovery/`. Prod 배포 차단 유지 (부분 해제). 임시 discovery-only 배포만 허용.**
- [x] Task 4: Lambda 핵심 프레임워크 (handler.py skeleton, structured logging, deny-by-default)
- [x] Task 5: PrincipalPolicy + 모델 통제 (lookup_principal_policy, check_model_access) — normalize_principal_id Candidate F 구현 완료
- [x] Task 6: 토큰 쿼터 시행 (check_quota 글로벌 합산, update_daily_usage ADD, TemporaryQuotaBoost) — principal_id 키 형식 확정 (`<account>#<role-name>`)
- [x] Task 7: Bedrock Converse 호출 (invoke_bedrock, ValidationException 처리)
- [x] Task 8: Idempotency + Ledger (check/create/complete_idempotency, write_request_ledger, write_session_metadata) — principal_id 키 형식 확정
- [x] Task 9: Approval 엔드포인트 (ApprovalPendingLock conditional PutItem, SES deep link, 7d TTL) — principal_id 키 형식 확정
- [x] lambda_handler 전체 파이프라인 배선 완료 (idempotency → policy → model → quota → bedrock → usage → ledger → session)
- **normalize_principal_id() Candidate F 구현 및 live 검증 완료 (2026-03-17). 11 unit tests pass. Discovery Lambda 재배포 완료 — `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인 (session `botocore-session-1773807868`). C2/C3/C5 캡처는 deferred validation follow-up.**
- [ ] Task 10: Checkpoint
- [ ] **KRW cost-based quota migration (Phase 1-3)** — requires separate approval per phase:
  - [x] Phase 1: Data model migration — **APPLIED TO DEV (2026-03-18)**. Additive approach (Option B): `monthly_usage` + `model_pricing` tables deployed alongside existing `daily_usage`. IAM + outputs updated. Post-apply validation pending. See `docs/ai/phase1-post-apply-validation.md`.
  - [x] Phase 2: Lambda quota logic rewrite (pricing lookup, cost estimation, KRW monthly check, KST boundary) — **DEPLOYED TO DEV AND VERIFIED (2026-03-20)**. All C1-C9 PASS. Claude 4.5+ models switched from base model IDs to cross-region inference profile IDs (`us.anthropic.claude-haiku-4-5-*`, `us.anthropic.claude-sonnet-4-5-*`) in `model_pricing` keys + `allowed_models` entries. Cost-precision fix (`int()` → `float()`) + DynamoDB Decimal ledger fix deployed. **cgjang live smoke test PASSED**: `decision: ALLOW`, `estimated_cost_krw: 0.0551`, `remaining_quota.cost_krw: 499999.7796`, HTTP 200. Final report: `docs/ai/phase2-dev-validation-report.md`. Approval ladder semantics documented: `docs/ai/phase3-approval-ladder-semantics.md`.
  - [x] Phase 3: Approval ladder rewrite (KRW increment, KST EOM TTL, reason validation) — **DEPLOYED TO DEV AND VERIFIED (2026-03-23). All critical AC pass. Terraform apply: `0 added, 1 changed, 0 destroyed`. backend-admin rebuilt and healthy. Inference regression PASS. Approval path PASS. KST TTL `1774969199` = 2026-03-31T23:59:59 KST PASS. Final report: `docs/ai/phase3-dev-validation-report.md`.**
- [ ] Task 11: backend-admin Admin API — **Phase 4 Scope A IMPLEMENTED AND RUNTIME-VALIDATED IN DEV (2026-03-23). `gateway_usage.py` created: M1 (`@admin_required`), M3 (blueprint), M4 (users), M5 (usage), M7 (policy), M8 (pricing). Blueprint registered in `app.py`. All 4 endpoints return correct data against live DynamoDB. Auth: 401/403/200 all verified. cgjang managed-user data correct. shlee exception-user 404 correct. Nonexistent principal 404 correct. Scope B (M2 GSI + M6 request history) requires separate Terraform approval.**
- [ ] Task 12: 프론트엔드 관리자 페이지 — **Phase 4 Frontend MVP DEPLOYED + Near-Real-Time Upgrade (2026-03-23). `BedrockGateway.jsx` upgraded: 5s auto-polling (silent refresh, no spinner on poll), usage/limit progress bar with ₩50만 band markers and effective-limit indicator, pulsing pending-approval badge, band-level badge (기본/+1/+2/+3), polling status indicator (자동 갱신 ON/OFF toggle), lastUpdated timestamp, polling paused when detail modal open, auth-error stops polling. Built via Docker, safe publish. `dist.bak` preserved for rollback.**
- [ ] Task 13: 프론트엔드 사용자 페이지
- [ ] Task 14: E2E 검증
- [ ] Task 15: 클라이언트 가이드 (per-user role assume 방법, FSx `[default]` profile 사용, 랩탑 profile 설정)

## Post-Implementation

- [ ] SCP 적용 승인 획득 → human per-user role deny에서 SCP로 전환
- [ ] Per-user role에서 Bedrock 직접 호출 권한 제거 (gateway 전환 완료 후)
- [ ] (Optional future) IAM Identity Center permission-set 병렬 지원 검토
- [ ] v2 검토: ConverseStream, InvokeModel, WAF
- [ ] Provisioned Concurrency 검토 (cold start 최적화)
- [ ] S3/Athena 기반 장기 로그 분석 파이프라인
