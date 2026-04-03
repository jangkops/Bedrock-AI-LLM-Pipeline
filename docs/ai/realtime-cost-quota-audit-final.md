# Bedrock Gateway 실시간 비용 측정 최종 감사 보고서

## Date: 2026-03-30

---

## 1. 최종 판정

비용 계산 엔진은 PASS다. 운영 카탈로그도 정리 완료다.

현재 gateway scope 안에서, 실제 callable로 확인된 운영 대상 모델 집합(7 providers, 20 models)에 대해 실시간 비용 계산은 정확하다. allowed_models에 있는 모든 모델은 production-callable 상태이며, 사용자-facing 500이 발생하는 모델은 없다.

out-of-scope / inaccessible / undeployed 모델은 비용 계산 엔진 검증 대상이 아니라 운영 카탈로그/접근성 관리 대상이다.

- quota enforcement suitability: **PASS**
- active session approval suitability: **PASS**
- catalog consistency (allowed = callable): **PASS**
- billing truth suitability: **FAIL** (CUR 미설정, FX 1450 하드코딩)

---

## 2. 왜 이번 턴이 필요했는가

이전 보고서에서 `us.anthropic.claude-sonnet-4-20250514-v1:0`이 모든 principal의 allowed_models에 포함되어 있었으나, gateway 경유 호출 시 HTTP 500 (AccessDeniedException)을 반환했다. 비용 엔진 문제는 아니지만, allowed_models에 있는 모델이 사용자에게 500을 내는 것은 운영상 미완료 상태다. 이를 닫기 위해 해당 모델을 allowed_models에서 제거하고, validator를 강화하여 재발을 방지했다.

---

## 3. Allowed_models vs Callable 상태

응답 경로 3종 분리:

| 경로 | HTTP | 의미 | 비용 적재 |
|------|------|------|-----------|
| Catalog deny | 403 | allowed_models/pricing 단계에서 차단 | 없음 |
| Runtime accessibility failure | 500 | Bedrock runtime에서 ResourceNotFound/AccessDenied | 없음 |
| Positive callable success | 200 | 정상 호출 + 비용 추적 | 있음 |

운영 기준: allowed_models에 있는 모델은 반드시 200 경로여야 한다. 500 경로가 나는 모델은 allowed_models에서 제거하거나 access grant를 완료해야 한다.

---

## 4. sonnet-4-20250514 최종 처리

| 항목 | 값 |
|------|-----|
| model_id | us.anthropic.claude-sonnet-4-20250514-v1:0 |
| lifecycle | ACTIVE |
| gateway result | HTTP 500, AccessDeniedException |
| root cause | Bedrock account-level model access grant 미완료 |
| 조치 | 모든 principal(5명) allowed_models에서 제거 |
| 재추가 조건 | Bedrock 콘솔에서 model access 활성화 + gateway 호출 성공 확인 후 |

---

## 5. Principal 전수 점검 결과

| principal | models | access-disabled 포함 | status |
|-----------|--------|---------------------|--------|
| cgjang | 7 | 없음 | OK |
| sbkim | 5 | 없음 | OK |
| jwlee | 9 | 없음 | OK |
| shlee2 | 9 | 없음 | OK |
| hermee | 9 | 없음 | OK |

모든 principal의 allowed_models에 있는 모델은 production-callable 상태다.

---

## 6. Validator 강화 결과

validator (`validate-model-catalog.py`) 상태 레벨:
- BLOCK: 배포 전 반드시 수정 (allowed + access-disabled, allowed + no pricing)
- WARN: 운영자 판단 필요 (stale direct ID 등)
- OK: 문제 없음

탐지 항목:
- allowed + KNOWN_ACCESS_DISABLED → BLOCK
- allowed + no pricing → BLOCK
- stale direct ID (us. 버전 존재) → WARN
- known callable direct ID → OK (whitelist)

최종 실행 결과: 5 principals, 0 BLOCK, 0 WARN. PASS.

---

## 7. 사용자-facing 500 제거 여부

제거 완료. `us.anthropic.claude-sonnet-4-20250514-v1:0`을 모든 principal에서 제거했으므로, 현재 allowed_models에 있는 모든 모델은 gateway 경유 호출 시 200 (ALLOW) 또는 429 (quota exceeded)만 반환한다. 500 경로는 발생하지 않는다.

---

## 8. 즉시 운영 가능 여부

즉시 운영 가능.

현재 pricing table에 등록된 운영 대상 callable 모델 집합에 대해, 사용자별 실시간 비용 추적/산정과 quota enforcement가 정확하게 동작하며, 기존 작업 세션에서도 승인 요청을 통해 작업을 이어갈 수 있다. allowed_models에 있는 모든 모델은 production-callable이며 사용자-facing 500이 발생하지 않는다.

---

## 9. 남은 리스크

| 리스크 | 영향 | 조치 |
|--------|------|------|
| FX 1450 하드코딩 | billing truth FAIL | 별도 FX 동적 조회 구현 |
| CUR 미설정 | AWS 청구 비교 불가 | 별도 CUR 파이프라인 |
| Cache 비용 미반영 | undercount (현재 0) | handler.py에 warning log 추가 완료 |
| sonnet-4-20250514 미사용 | 해당 모델 사용 불가 | Bedrock model access grant 후 재추가 |
| 4개 LEGACY 모델 | inference profile 비활성 | pricing table에 유지, allowed에 미포함 |

---

## 10. 원복/최종 상태

| 항목 | 최종 값 |
|------|---------|
| cgjang allowed_models | 7 (sonnet-4-20250514 제거) |
| sbkim allowed_models | 5 (동일 제거) |
| jwlee allowed_models | 9 (동일 제거) |
| shlee2 allowed_models | 9 (동일 제거) |
| hermee allowed_models | 9 (동일 제거) |
| cgjang usage | 4.4617 + 0.9309 + 0.052374 + 0.09921625 (원복) |
| boost | 0건 |
| pending lock | 없음 |
| base_limit | 500,000 (원복) |
| validator | 0 BLOCK, 0 WARN |

---

## 5개 ERROR 모델 최종 상태 (참조)

| model_id | gateway exception | root cause | allowed 포함 | 조치 |
|----------|-------------------|------------|-------------|------|
| us.anthropic.claude-3-5-haiku-20241022-v1:0 | ResourceNotFoundException | LEGACY inference profile unavailable | 없음 | pricing 유지, allowed 미포함 |
| us.anthropic.claude-sonnet-4-20250514-v1:0 | AccessDeniedException | model access grant 미완료 | 제거됨 | access grant 후 재추가 |
| us.anthropic.claude-3-7-sonnet-20250219-v1:0 | ResourceNotFoundException | LEGACY inference profile unavailable | 없음 | pricing 유지, allowed 미포함 |
| us.meta.llama3-2-1b-instruct-v1:0 | ResourceNotFoundException | LEGACY inference profile unavailable | 없음 | pricing 유지, allowed 미포함 |
| us.meta.llama3-2-3b-instruct-v1:0 | ResourceNotFoundException | LEGACY inference profile unavailable | 없음 | pricing 유지, allowed 미포함 |

5개 모두 비용 계산 엔진 문제가 아니라 운영 카탈로그/접근성 문제다. gateway handler의 estimate_cost_krw()에 도달하기 전에 Bedrock runtime 단계에서 실패하므로 비용이 적재되지 않는다.
