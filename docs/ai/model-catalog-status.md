# Model Catalog Status Report

## Date: 2026-03-30

## 5개 ERROR 모델 Root Cause 최종 판정

| model_id | provider | pricing | allowed | gateway result | gateway exception | direct result (cgjang) | lifecycle | id type | root cause | action |
|----------|----------|---------|---------|---------------|-------------------|----------------------|-----------|---------|------------|--------|
| us.anthropic.claude-3-5-haiku-20241022-v1:0 | Anthropic | 있음 | 없음 | HTTP 500 | ResourceNotFoundException | AccessDeniedException | LEGACY | us. inference profile | inference profile unavailable — LEGACY 모델의 us. inference profile이 us-west-2에서 비활성 | keep in pricing, do not add to allowed |
| us.anthropic.claude-sonnet-4-20250514-v1:0 | Anthropic | 있음 | 없음 | HTTP 500 | AccessDeniedException | AccessDeniedException | ACTIVE | us. inference profile | IAM permission missing — Lambda role이 이 모델에 대한 Bedrock 접근 권한 부족 (model-level access grant 필요) | enable access later |
| us.anthropic.claude-3-7-sonnet-20250219-v1:0 | Anthropic | 있음 | 없음 | HTTP 500 | ResourceNotFoundException | AccessDeniedException | LEGACY | us. inference profile | inference profile unavailable — LEGACY 모델의 us. inference profile이 us-west-2에서 비활성 | keep in pricing, do not add to allowed |
| us.meta.llama3-2-1b-instruct-v1:0 | Meta | 있음 | 없음 | HTTP 500 | ResourceNotFoundException | AccessDeniedException | LEGACY | us. inference profile | inference profile unavailable — LEGACY 모델의 us. inference profile이 us-west-2에서 비활성 | keep in pricing, do not add to allowed |
| us.meta.llama3-2-3b-instruct-v1:0 | Meta | 있음 | 없음 | HTTP 500 | ResourceNotFoundException | AccessDeniedException | LEGACY | us. inference profile | inference profile unavailable — LEGACY 모델의 us. inference profile이 us-west-2에서 비활성 | keep in pricing, do not add to allowed |

## Gateway vs Direct 경로 차이

| 경로 | 호출 주체 | bedrock:InvokeModel 권한 | 결과 차이 |
|------|-----------|-------------------------|-----------|
| Gateway (API GW → Lambda) | Lambda execution role | Resource = ["*"] | ResourceNotFoundException = inference profile 자체가 없음 |
| Direct boto3 (cgjang) | BedrockUser-cgjang IAM role | 제한적 (특정 모델만) | AccessDeniedException = IAM 권한 부족 |

4개 모델(haiku-20241022, sonnet-20250219, llama-1b, llama-3b): gateway에서 ResourceNotFoundException → Lambda role은 모든 모델에 접근 가능하나 inference profile 자체가 us-west-2에 존재하지 않음. LEGACY lifecycle과 일치.

1개 모델(sonnet-4-20250514): gateway에서 AccessDeniedException → inference profile은 존재하나 model-level access grant가 필요. ACTIVE lifecycle이지만 계정에서 아직 접근 활성화 안 됨.

## 결론

5개 ERROR는 비용 계산 엔진 문제가 아니다. gateway handler의 estimate_cost_krw(), update_monthly_usage(), write_request_ledger() 함수는 이 모델들에 도달하기 전에 Bedrock runtime 호출 단계에서 실패한다. 비용이 적재되지 않으며 aggregate에 영향 없다.

## 모델 상태 분류

| 상태 | 모델 수 | 설명 |
|------|---------|------|
| production-callable | 20 | sweep에서 diff=0 확인 |
| legacy/unavailable | 4 | LEGACY inference profile 비활성 |
| needs-access-enable | 1 | ACTIVE이나 model access grant 필요 |
| out-of-scope | ~16 | image/embed/video (Stability, Cohere embed, TwelveLabs) |
