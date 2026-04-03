# Runbook: Bedrock Access Control Gateway

> Phase 2 artifact. Updated: 2026-03-20.
> Identity model: per-user assume-role (`BedrockUser-<username>`) primary.
> **Phase 2 DEPLOYED TO DEV AND VERIFIED (2026-03-20)**: KRW cost-based monthly quota rewrite. API `5l764dh7y9`, env vars confirmed. All C1-C9 PASS. See `docs/ai/phase2-dev-validation-report.md`.
> **SEED DATA APPLIED (2026-03-18). IAM BEDROCK FIX APPLIED (2026-03-19). INFERENCE PROFILE FIX APPLIED (2026-03-19). COST-PRECISION + DECIMAL LEDGER FIX DEPLOYED AND VERIFIED (2026-03-20).**
> IAM fix: `bedrock:Converse` (invalid action) -> `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream`. Inference profile fix: 4.5+ model keys switched from base model IDs to `us.` prefix cross-region inference profile IDs in `model_pricing` + `principal_policy`. No runtime code change. See `docs/ai/phase2-inference-profile-fix.md`.
> **MODEL UPGRADE TO 4.5+ APPLIED (2026-03-19):** Primary: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (inference profile ID). Fallback: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (inference profile ID). `model_pricing` 5 models (2 `us.` prefix + 3 legacy), `principal_policy` 5 allowed_models.
> **COST-PRECISION FIX + DECIMAL LEDGER FIX DEPLOYED AND VERIFIED (2026-03-20)** -- `int()` -> `float()` fix applied (response body), DynamoDB Decimal-vs-float ledger defect fixed: ledger_entry `estimated_cost_krw` keeps raw `Decimal` for DynamoDB. cgjang live smoke test PASSED: `decision: ALLOW`, `estimated_cost_krw: 0.0551`, HTTP 200. See `docs/ai/phase2-cgjang-validation-plan.md`.
> **TASK 2 BYPASS PREVENTION COMPLETE (2026-03-19):** `DenyDirectBedrockInference` inline policy applied to all 6 `BedrockUser-*` roles. **LIVE VERIFIED**: direct Bedrock calls denied (`AccessDeniedException`), gateway path reaches Lambda. See `docs/ai/task2-bypass-prevention-execution.md`.

## 🔓 Deployment Block — Partially Lifted

**`normalize_principal_id()` Candidate F 구현 및 live 검증 완료 (2026-03-17).**
- Rule: `<account>#<role-name>` — session name excluded, fail-closed on non-BedrockUser/Shared roles.
- 11 unit tests pass. Discovery Lambda 재배포 완료.
- Single-user live-verified: `derived_principal_id` = `107650139384#BedrockUser-cgjang` (session `botocore-session-1773807868`).
- Remaining captures (C2 laptop, C3 cross-role, C5 fail-closed) are deferred validation follow-up.

Prod deployment is permitted after:
1. ~~Task 3 discovery completes~~ → Normalization implemented based on C1 evidence
2. ~~Normalization rule confirmed~~ → Candidate F implemented
3. ~~`normalize_principal_id()` updated~~ → Done (2026-03-17)
4. ~~Discovery Lambda 재배포~~ → Done (2026-03-17), live-verified
5. Operator accepts single-user evidence risk OR completes C2/C3/C5 captures

### Task 3 Discovery Status (2026-03-17)

- Discovery gateway DEPLOYED: API ID `ugpt5xi8b7`, stage `v1`, `DISCOVERY_MODE=true`
- C1 (cgjang FSx) CAPTURED — single-user evidence supports Candidate F
- `normalize_principal_id()` Candidate F IMPLEMENTED — 11 unit tests pass
- **Discovery Lambda 재배포 완료** — `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인. Placeholder 동작 제거됨.
- Deferred: C2 (cgjang laptop), C3 (cross-role isolation), C5 (fail-closed) — validation follow-up
- Deployment block partially lifted

### Task 3 Discovery Deployment Exception

A temporary dev/discovery-only deployment is permitted for Task 3:
- **Separate Terraform workspace** (`terraform workspace new discovery || terraform workspace select discovery`) — isolated state, cannot affect prod
- `DISCOVERY_MODE=true` via `-var discovery_mode=true` — Lambda returns raw requestContext only, no business data written
- `DISCOVERY_MODE` defaults to `false` in `variables.tf` — only overridden for this temporary deployment
- Target: throwaway `discovery` API Gateway stage, NOT `prod`
- Per-user role (`BedrockUser-<username>`)에 `execute-api:Invoke` 권한 추가 필요 (discovery API Gateway ARN)
- FSx C2 캡처: 기존 `[default]` profile 사용 — credential 파일 수정 불필요
- Must be fully destroyed (`terraform destroy -var environment=discovery -var discovery_mode=true` + workspace delete) immediately after C1+C2 captures complete
- This exception does NOT lift the prod deploy

---

> **Monthly Boundary: KST (UTC+9)** — All monthly budget resets, boost expiry, and MonthlyUsage partition keys use KST.
> CloudWatch timestamps are UTC. When correlating budget events with CloudWatch logs, add 9 hours to UTC timestamps.
> Budget month boundary = KST midnight (= 15:00 UTC previous day).
> Approved: Q3/Q4 decisions (2026-03-18). See `docs/ai/decision-resolution-q1-q6.md`.

## 배포

> **Phase 1 Applied (2026-03-18)**: 2 new DynamoDB tables (`monthly_usage`, `model_pricing`) + IAM + outputs deployed to dev. Runtime unchanged.
> **Phase 2 Verified (2026-03-20)**: Lambda quota logic rewrite deployed and all C1-C9 criteria pass. See `docs/ai/phase2-dev-validation-report.md`.

```bash
cd infra/bedrock-gateway
terraform init
terraform plan -var-file=env/prod.tfvars
terraform apply -var-file=env/prod.tfvars
```

## Lambda 버전 전환

```bash
# 현재 live alias 확인
aws lambda get-alias --function-name bedrock-gw-prod-gateway --name live

# 특정 버전으로 alias 전환
aws lambda update-alias --function-name bedrock-gw-prod-gateway --name live --function-version <VERSION>
```

## CloudWatch 알람 대응

### RequestLedger PutItem 실패
- 원인: DynamoDB 일시적 오류 또는 IAM 권한 문제
- 조치: CloudWatch Logs에서 에러 상세 확인 → DynamoDB 서비스 상태 확인 → IAM role 권한 확인
- 영향: 해당 요청은 deny됨. 감사 로그 누락 가능.

### MonthlyUsage ADD 실패 (Bedrock 성공 후)
- 원인: DynamoDB 일시적 오류
- 조치: CloudWatch Logs에서 해당 request_id 확인 → RequestLedger에서 실제 비용(estimated_cost_krw) 확인 → MonthlyUsage 수동 보정
- 영향: 응답은 정상 반환됨. 쿼터 카운터 부정확.

### Lambda 에러율 임계값 초과
- 원인: 코드 버그, DynamoDB 장애, Bedrock 서비스 장애
- 조치: CloudWatch Logs 확인 → 원인별 대응 → 필요 시 Lambda alias 롤백

## Bypass Prevention (Task 2)

> Applied: 2026-03-19. `DenyDirectBedrockInference` on all 6 `BedrockUser-*` roles.

### Verify Deny Policy Exists

```bash
for ROLE in BedrockUser-cgjang BedrockUser-hermee BedrockUser-jwlee BedrockUser-sbkim BedrockUser-shlee2; do
  aws iam get-role-policy --role-name "$ROLE" --policy-name DenyDirectBedrockInference --query 'PolicyDocument.Statement[0].Effect' --output text 2>&1
done
# Expected: Deny (5 times)
# Note: BedrockUser-shlee is excluded — deny removed per operator approval (2026-03-19).
# See docs/ai/shlee-block-investigation.md.
```

### Add Deny to a New BedrockUser-* Role

When a new `BedrockUser-<username>` role is created, apply the deny policy:
```bash
aws iam put-role-policy \
  --role-name BedrockUser-<username> \
  --policy-name DenyDirectBedrockInference \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "DenyDirectBedrockAccess",
      "Effect": "Deny",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": "*"
    }]
  }'
```

### Rollback (Remove Deny from All Roles)

```bash
for ROLE in BedrockUser-cgjang BedrockUser-hermee BedrockUser-jwlee BedrockUser-sbkim BedrockUser-shlee2; do
  aws iam delete-role-policy --role-name "$ROLE" --policy-name DenyDirectBedrockInference
  echo "Removed DenyDirectBedrockInference from $ROLE"
done
# Note: BedrockUser-shlee excluded — deny already removed (2026-03-19).
```

### Validate Bypass Is Blocked (IAM Simulation)

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::107650139384:role/BedrockUser-cgjang \
  --action-names bedrock:InvokeModel \
  --resource-arns "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0" \
  --query 'EvaluationResults[0].EvalDecision' --output text
# Expected: explicitDeny
```

---

## 비상 차단

```bash
# API Gateway 스테이지를 이전 배포로 전환
aws apigateway update-stage --rest-api-id <API_ID> --stage-name prod --patch-operations op=replace,path=/deploymentId,value=<PREV_DEPLOYMENT_ID>

# 최악의 경우: 모든 요청 차단
aws apigateway delete-stage --rest-api-id <API_ID> --stage-name prod
```

## DynamoDB 수동 보정

> ⚠️ Phase 2 verified (2026-03-20). `monthly-usage` is the active usage table. `daily-usage` is preserved but receives no new writes.
> PK: `<principal_id>#<YYYY-MM>` (KST month). Fields: `cost_krw`, `input_tokens`, `output_tokens`.

```bash
# MonthlyUsage KRW model (ACTIVE — Phase 2 verified):
aws dynamodb update-item \
  --table-name bedrock-gw-prod-us-west-2-monthly-usage \
  --key '{"principal_id_month": {"S": "<principal_id>#<YYYY-MM>"}, "model_id": {"S": "<model_id>"}}' \
  --update-expression "ADD cost_krw :c, input_tokens :i, output_tokens :o" \
  --expression-attribute-values '{":c": {"N": "<krw_amount>"}, ":i": {"N": "<amount>"}, ":o": {"N": "<amount>"}}'

# Legacy DailyUsage (preserved, no new writes — do not use for corrections):
# aws dynamodb update-item \
#   --table-name bedrock-gw-prod-us-west-2-daily-usage \
#   --key '{"pk": {"S": "<principal_id>#<date>"}, "model_id": {"S": "<model_id>"}}' \
#   --update-expression "ADD input_tokens :i, output_tokens :o" \
#   --expression-attribute-values '{":i": {"N": "<amount>"}, ":o": {"N": "<amount>"}}'
```

---

## Phase 3: Approval Ladder Operations (CODE APPLIED — PENDING DEPLOY)

> Status: CODE CHANGES APPLIED (2026-03-22). Pending `terraform apply` + Docker rebuild.
> Approval: GRANTED (2026-03-22, `PHASE3_APPROVED = true`).
> Implementation plan: `docs/ai/phase3-implementation-ready-draft.md`
> Semantics: `docs/ai/phase3-approval-ladder-semantics.md`

### Approval Ladder Summary

| Band | Cumulative Approvals | Monthly Limit (KRW) |
|------|---------------------|---------------------|
| Base | 0 | 500,000 |
| 1st approval | 1 | 1,000,000 |
| 2nd approval | 2 | 1,500,000 |
| 3rd approval | 3 | 2,000,000 (hard cap) |

- Month-scoped budget, resets at KST month boundary
- No carryover between months
- Fixed KRW 500,000 increment per approval

### Key Changes (applied 2026-03-22, pending deploy)

1. `handler.py:handle_approval_request()` — V1 reason non-empty, V2 `requested_increment_krw == 500000`, V3 hard cap pre-validation (`effective + 500K ≤ 2M`). Validation runs BEFORE lock acquisition. ApprovalRequest enriched with `requested_amount_krw`, `current_effective_limit_krw`, `approver_email`. Response enriched with `current_effective_limit_krw`, `requested_new_limit_krw`.
2. `handler.py:_send_approval_email()` — accepts `current_limit_krw` and `requested_new_limit_krw`. Email body includes KRW context.
3. `gateway_approval.py:_end_of_month_ttl()` — UTC→KST fix (R24 RESOLVED). `timezone.utc` → `KST = timezone(timedelta(hours=9))`.
4. `gateway_approval.py` SES email text — `"end of current month (UTC)"` → `"end of current month (KST)"`.
5. Blast radius: approval path only. Inference pipeline untouched.

### Deploy Steps (operator action required)

```bash
# 1. Lambda update
cd infra/bedrock-gateway
terraform plan   # expect: Lambda function code hash change
terraform apply  # Lambda + alias updated

# 2. backend-admin rebuild
cd account-portal
docker compose -f docker-compose-fixed.yml up -d --build

# 3. Smoke tests — AC1-AC9 from phase3-implementation-ready-draft.md
```

### Operational Procedures (to be completed after implementation)

- Granting approval: admin endpoint `POST /api/gateway/approval` (R26: `@admin_required` already applied)
- Verifying limit change: query MonthlyUsage + PrincipalPolicy for user
- Month-boundary behavior: budget resets at KST 00:00 (= UTC 15:00 previous day)
- Hard cap enforcement: KRW 2,000,000 ceiling regardless of approval count
- Rollback: revert Lambda to Phase 2 handler + Docker rebuild for backend-admin. No DynamoDB schema change needed.
