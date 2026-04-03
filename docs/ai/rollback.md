# Rollback Plan: Bedrock Access Control Gateway

> Phase 2 artifact. Updated: 2026-03-23.
> Phase 2 DEPLOYED AND VERIFIED (2026-03-20). KRW cost-based monthly quota operational.
> Phase 3 DEPLOYED AND VERIFIED (2026-03-23). Approval ladder rewrite operational.

## Terraform 인프라 롤백

```bash
cd infra/bedrock-gateway

# 이전 상태로 롤백 (plan 먼저 확인)
terraform plan -var-file=env/prod.tfvars
terraform apply -var-file=env/prod.tfvars

# 또는 특정 state로 복원
terraform state pull > backup.tfstate
# ... 수정 후 ...
terraform state push backup.tfstate
```

## Lambda 즉시 롤백

```bash
# live alias를 이전 버전으로 전환 (인프라 변경 없이 즉시)
aws lambda update-alias \
  --function-name bedrock-gw-prod-gateway \
  --name live \
  --function-version <PREVIOUS_VERSION>
```

## API Gateway 스테이지 롤백

```bash
# 이전 deployment로 전환
aws apigateway update-stage \
  --rest-api-id <API_ID> \
  --stage-name prod \
  --patch-operations op=replace,path=/deploymentId,value=<PREV_DEPLOYMENT_ID>
```

## DynamoDB 데이터 영향

| 테이블 | 롤백 영향 | 조치 |
|--------|----------|------|
| PrincipalPolicy | 데이터 유지 | 스키마 호환성 확인 필수. KRW 필드 (`monthly_cost_limit_krw`, `max_monthly_cost_limit_krw`) 존재 확인. |
| MonthlyUsage | TTL ~35일 자동 정리 | Phase 2 active table. PK: `<principal_id>#YYYY-MM`, SK: `model_id`. Fields: `cost_krw`, `input_tokens`, `output_tokens`. |
| DailyUsage | TTL 자동 정리 | Phase 2에서 더 이상 write 없음. 보존 중 (post-Phase-3 cleanup 예정). |
| ModelPricing | 데이터 유지 (admin-managed, no TTL) | 5 models seeded (2 `us.` prefix + 3 legacy). Lambda cold-start cache. |
| RequestLedger | 불변, 영구 보존 | `estimated_cost_krw` 필드 포함 (Phase 2). Append-only (IAM deny on Update/Delete). |
| TemporaryQuotaBoost | TTL 자동 만료 (EOM KST) | `extra_cost_krw` 필드. Phase 3에서 TTL UTC→KST 수정 완료 (2026-03-23). |
| ApprovalRequest | 데이터 유지 | 상태 일관성 확인 |
| ApprovalPendingLock | 데이터 유지 | ApprovalRequest와 lock 일관성 확인. 고아 lock 발생 시 TTL(7일)로 자동 만료. TTL 전 수동 삭제도 가능. |
| SessionMetadata | TTL 30일 자동 삭제 | 영향 없음 |
| IdempotencyRecord | TTL 24시간 자동 삭제 | 영향 없음 |

## Phase 3 Lambda 롤백 (approval ladder validation → Phase 2 state)

Phase 3 Lambda 코드를 롤백하면 approval request validation이 제거됨 (reason/increment/hard-cap 검증 없이 요청 생성 가능):

**Lambda rollback** (backup zip 사용):
```bash
# Phase 2 Lambda backup 복원
cp /home/app/infra/bedrock-gateway/.rollback/phase2-lambda-backup.zip infra/bedrock-gateway/lambda/
# 또는 git checkout으로 handler.py 복원:
git checkout <pre-phase3-commit> -- infra/bedrock-gateway/lambda/handler.py
terraform plan -var-file=env/dev.tfvars -out rollback.tfplan
terraform apply rollback.tfplan
```

**backend-admin rollback** (Docker tag 사용):
```bash
# Phase 2 rollback Docker image 사용
docker tag account-portal-backend-admin:phase2-rollback account-portal-backend-admin:latest
# 또는 git checkout + rebuild:
git checkout <pre-phase3-commit> -- account-portal/backend-admin/routes/gateway_approval.py
cd account-portal
docker compose -f docker-compose-fixed.yml up -d --build backend-admin
```

**Rollback artifacts**:
- Lambda backup: `/home/app/infra/bedrock-gateway/.rollback/phase2-lambda-backup.zip` (28,393 bytes)
- Docker rollback tag: `account-portal-backend-admin:phase2-rollback` → image `a6a85c6d87ec`

**주의**: Phase 3 롤백 시 `_end_of_month_ttl()` KST fix도 함께 롤백됨 (UTC로 복귀). 이미 생성된 KST TTL boost는 정상 만료됨.

## Phase 2 Lambda 롤백 (KRW quota → 이전 token-count)

Phase 2 Lambda 코드를 롤백하면 token-count daily quota로 복귀:
```bash
# handler.py + lambda.tf를 Phase 1 상태로 복원
git checkout <pre-phase2-commit> -- infra/bedrock-gateway/lambda/handler.py infra/bedrock-gateway/lambda.tf
terraform apply -var-file=env/dev.tfvars
```
**주의**: Phase 2 롤백 시 `monthly_usage` 테이블 데이터는 보존되지만 사용되지 않음. `daily_usage`가 다시 active. `model_pricing` 테이블도 보존되지만 미사용.

## Phase 2 Cost-Precision Fix 롤백

cost-precision fix (`int()` → `float()`) + Decimal ledger fix를 롤백하면:
- Sub-1 KRW 비용이 0으로 truncate됨 (`int(Decimal("0.0551"))` → 0)
- Ledger write가 `Float types are not supported` 에러로 실패
- **권장하지 않음** — 이 fix는 Phase 2 정상 동작의 전제조건

## 비상 전체 차단

API Gateway 스테이지 삭제로 모든 요청 즉시 차단:
```bash
aws apigateway delete-stage --rest-api-id <API_ID> --stage-name prod
```
복구: Terraform apply로 스테이지 재생성.

## backend-admin 변경 롤백

backend-admin의 gateway 관련 변경은 additive (신규 Blueprint 추가). 롤백 시:
1. `app.py`에서 gateway Blueprint 등록 제거
2. Docker 이미지 재빌드 + 재배포
3. 프론트엔드에서 gateway 라우트 제거 + 재빌드

## Bypass Prevention 롤백 (Task 2)

`DenyDirectBedrockInference` 제거 시 사용자가 직접 Bedrock 호출 가능:
```bash
for ROLE in BedrockUser-cgjang BedrockUser-hermee BedrockUser-jwlee BedrockUser-sbkim BedrockUser-shlee2; do
  aws iam delete-role-policy --role-name "$ROLE" --policy-name DenyDirectBedrockInference
  echo "Removed DenyDirectBedrockInference from $ROLE"
done
# Note: BedrockUser-shlee excluded — deny already removed (2026-03-19).
```

## DynamoDB 수동 보정

> Phase 2 verified (2026-03-20). `monthly-usage` is the active usage table.

```bash
# MonthlyUsage KRW model (ACTIVE):
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-monthly-usage \
  --key '{"principal_id_month": {"S": "<principal_id>#<YYYY-MM>"}, "model_id": {"S": "<model_id>"}}' \
  --update-expression "ADD cost_krw :c, input_tokens :i, output_tokens :o" \
  --expression-attribute-values '{":c": {"N": "<krw_amount>"}, ":i": {"N": "<amount>"}, ":o": {"N": "<amount>"}}'
```
