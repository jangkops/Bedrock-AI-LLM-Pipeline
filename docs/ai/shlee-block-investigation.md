# shlee Block Root-Cause Investigation

> Investigated: 2026-03-19 ~ 2026-03-20
> Status: COMPLETE — verdict confirmed
> Scope: Determine why shlee was blocked from Bedrock access and whether the gateway quota was involved

---

## Verdict

**shlee의 Bedrock 차단은 gateway 500,000 KRW 쿼터와 무관.**

shlee는 gateway를 통하지 않고 Bedrock을 직접 호출하고 있었음. Task 2에서 모든 6개 `BedrockUser-*` 역할에 적용된 `DenyDirectBedrockInference` inline policy가 직접 호출을 차단한 것이 원인.

---

## Evidence Summary

### 1. Gateway DynamoDB — shlee 기록 없음

모든 gateway DynamoDB 테이블에서 shlee 관련 레코드 0건:

| Table | Query | Result |
|-------|-------|--------|
| `principal_policy` | `107650139384#BedrockUser-shlee` | NOT FOUND |
| `monthly_usage` | scan for `shlee` | 0 items |
| `daily_usage` | scan for `shlee` | 0 items |
| `request_ledger` | scan for `shlee` | 0 items |
| `approval_request` | scan for `shlee` | 0 items |
| `temporary_quota_boost` | scan for `shlee` | 0 items |

**해석**: shlee는 gateway를 한 번도 사용한 적 없음. Gateway 쿼터 시행 대상이 아니었음.

### 2. BedrockUser-shlee IAM Role — 직접 Bedrock 권한 보유

`BedrockUser-shlee` 역할의 inline policies (DenyDirectBedrockInference 제거 후):

| Policy Name | 내용 |
|-------------|------|
| `BedrockAccess` | `bedrock:InvokeModel`, `bedrock:Converse`, etc. — foundation models + inference profiles 직접 접근 허용 |
| `S3DataAccess` | S3 데이터 접근 |

`BedrockAccess` policy는 `bedrock:InvokeModel`, `bedrock:Converse`, `bedrock:ConverseStream` 등을 `anthropic.claude*` foundation models 및 `inference-profile/*` 리소스에 대해 허용. 이는 shlee가 gateway 없이 직접 Bedrock API를 호출할 수 있었음을 의미.

### 3. 차단 메커니즘

Task 2 (2026-03-19)에서 모든 6개 `BedrockUser-*` 역할에 `DenyDirectBedrockInference` inline policy 적용:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyDirectBedrockAccess",
    "Effect": "Deny",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
    "Resource": "*"
  }]
}
```

IAM explicit deny는 모든 allow를 override. shlee의 `BedrockAccess` allow policy가 있어도 `DenyDirectBedrockInference`의 explicit deny가 우선 적용되어 직접 Bedrock 호출이 차단됨.

### 4. 해결

Task 3 (2026-03-19): operator가 `BedrockUser-shlee`에서만 `DenyDirectBedrockInference` policy 제거. 다른 5개 역할은 변경 없음.

확인: 제거 후 `BedrockUser-shlee`에는 `BedrockAccess`와 `S3DataAccess`만 남아있음.

---

## Architectural Implication

**직접 Bedrock 사용자는 gateway 쿼터/감사를 완전히 우회함.**

| 경로 | 쿼터 시행 | 감사 로그 | 비용 추적 |
|------|----------|----------|----------|
| Gateway (API GW → Lambda → Bedrock) | ✅ 시행됨 | ✅ RequestLedger | ✅ MonthlyUsage |
| 직접 Bedrock (boto3 → bedrock-runtime) | ❌ 없음 | ❌ 없음 | ❌ 없음 (CloudTrail만) |

shlee는 직접 경로를 사용하므로:
- Gateway의 500,000 KRW 월간 쿼터가 적용되지 않음
- RequestLedger에 기록되지 않음
- MonthlyUsage에 비용이 집계되지 않음
- 비용 통제는 AWS 계정 수준 Cost Explorer / CloudTrail로만 가능

이는 의도된 예외 처리임 — shlee는 별도 승인 하에 직접 Bedrock 접근이 허용됨.

---

## Risk Assessment

| 리스크 | 심각도 | 완화 |
|--------|--------|------|
| shlee 비용이 gateway 집계에 포함되지 않음 | Medium | CloudTrail + Cost Explorer로 별도 모니터링 |
| shlee가 gateway 모델 allowlist 제한을 받지 않음 | Low | `BedrockAccess` policy의 Resource 제한으로 부분 통제 |
| 다른 사용자가 동일 예외를 요청할 수 있음 | Low | 명시적 승인 게이트 유지 |

---

## Rollback (shlee deny 재적용)

필요 시 shlee에 deny policy 재적용:

```bash
aws iam put-role-policy \
  --role-name BedrockUser-shlee \
  --policy-name DenyDirectBedrockInference \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "DenyDirectBedrockAccess",
      "Effect": "Deny",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"],
      "Resource": "*"
    }]
  }'
```

---

## Timeline

| 시점 | 이벤트 |
|------|--------|
| (이전) | shlee가 `BedrockUser-shlee` 역할로 Bedrock 직접 호출 사용 중 |
| 2026-03-19 | Task 2: `DenyDirectBedrockInference` 모든 6개 역할에 적용 → shlee 직접 호출 차단 |
| 2026-03-19 | shlee 차단 보고 |
| 2026-03-19 | Task 3: operator가 `BedrockUser-shlee`에서만 deny policy 제거 |
| 2026-03-20 | 본 조사 보고서 작성 — 근본 원인 확인 완료 |
