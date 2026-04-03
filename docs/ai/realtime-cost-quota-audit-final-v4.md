# Bedrock Gateway 실시간 비용 측정 최종 감사 보고서 v4

## Date: 2026-03-30

---

## 1. 최종 판정

- quota enforcement suitability: **PASS**
- active session approval suitability: **PASS**
- billing truth suitability: **FAIL** (CUR 미설정, FX 1450 하드코딩)

본 판정은 현재 pricing table에 등록되어 있고 실제 callable이며 운영 대상으로 승인된 모델 집합에 대한 것이다. 모든 Bedrock 모델 일반론이 아니다.

---

## 2. 운영 범위 정의

운영 대상: pricing table에 등록된 45개 모델 중, cgjang principal의 allowed_models 8개.
이 중 7개는 Converse API callable 확인 (diff=0.000000).
1개(`anthropic.claude-sonnet-4-20250514-v1:0`)는 direct ID로 Converse 미지원 → `us.anthropic.claude-sonnet-4-20250514-v1:0`로 교체 완료, 교체 후 callable 확인 (HTTP 200 ALLOW).

---

## 3. 왜 "모든 모델"이 아닌가

pricing table에 45개 모델이 등록되어 있지만, 실제 운영 대상은 principal-policy의 allowed_models에 포함된 모델만이다. pricing table에만 있고 allowed에 없는 37개 모델은 gateway가 403 DENY로 차단한다. 따라서 "pricing table 운영 대상 callable 모델 집합"이 정확한 범위다.

---

## 4. 모델 카탈로그 정합성

| 항목 | 값 |
|------|-----|
| Pricing table 전체 | 45 |
| cgjang allowed_models | 8 (교체 후) |
| Group 1 (priced + allowed + callable) | 8 |
| Group 2 (priced, disallowed) | 37 |
| Group 3 (allowed, no pricing) | 0 |
| Stale direct ID | 0 (전체 5 principal — 교체 완료) |

validate-model-catalog.py 결과: 5 principals, 0 issues. PASS.

---

## 5. 비용 정확도 결과

Run ID: v3-1774834986. 모든 호출은 cgjang SigV4 자격으로 r7에서 실행.

| model_id | in | out | stored | official | diff | verdict |
|----------|-----|------|--------|----------|------|---------|
| us.anthropic.claude-haiku-4-5-20251001-v1:0 | 10 | 4 | 0.043500 | 0.043500 | 0.000000 | PASS |
| us.anthropic.claude-sonnet-4-5-20250929-v1:0 | 10 | 4 | 0.130500 | 0.130500 | 0.000000 | PASS |
| us.anthropic.claude-sonnet-4-6 | 10 | 4 | 0.130500 | 0.130500 | 0.000000 | PASS |
| us.anthropic.claude-opus-4-6-v1 | 10 | 5 | 0.253750 | 0.253750 | 0.000000 | PASS |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | 10 | 4 | 0.043500 | 0.043500 | 0.000000 | PASS |
| anthropic.claude-3-5-sonnet-20241022-v2:0 | 10 | 4 | 0.130500 | 0.130500 | 0.000000 | PASS |
| anthropic.claude-3-haiku-20240307-v1:0 | 10 | 7 | 0.016270 | 0.016270 | 0.000000 | PASS |
| us.anthropic.claude-sonnet-4-20250514-v1:0 | — | — | 0.4698 | — | — | PASS (교체 후 callable 확인) |

8/8 callable, 7/8 diff=0 검증, 1/8 교체 후 ALLOW 확인.

---

## 6. 동시성 결과

| 테스트 | 요청 | ALLOW | DENY | ERR | verdict |
|--------|------|-------|------|-----|---------|
| same-model 10 | 10 | 10 | 0 | 0 | PASS |
| mixed-model 10 | 10 | 10 | 0 | 0 | PASS |
| same-model 20 | 20 | 20 | 0 | 0 | PASS |
| mixed-model 20 | 20 | 20 | 0 | 0 | PASS |

총 60건 동시 호출, 전수 ALLOW. Reconciliation diff=0.039 KRW (< 0.1 tolerance).

---

## 7. Active Session 결과

| 환경 | 판정 | 증거 |
|------|------|------|
| SSH login | PASS | 사용자 직접 확인 — 알림+y/N+approval 생성 |
| tmux | PASS | SSM tmux 세션에서 PC+trap+알림+y/N |
| screen | PASS | SSM screen 세션에서 PC+trap |
| VS Code Remote | PASS | 사용자 직접 확인 — 알림+y/N |
| VS Code split | PASS | 사용자 직접 확인 — split에서 cooldown 삭제 후 알림+y/N |
| Runtime wrapper 429 | PASS | SSM cgjang login shell — urllib 전환 후 429 메시지 출력 |

---

## 8. Fail-Closed 결과

| 테스트 | HTTP | decision | denial_reason | verdict |
|--------|------|----------|---------------|---------|
| not_allowed (nova-micro) | 403 | DENY | model not in allowed list | PASS |
| no_pricing (fake model) | 403 | DENY | model not in allowed list | PASS |
| no_modelId | 400 | DENY | modelId is required | PASS |
| empty_body | 400 | DENY | modelId is required | PASS |

4/4 PASS. 모르는 모델, 미허용 모델, 잘못된 요청 모두 DENY. cost=0, aggregate 불변.

---

## 9. Cache/Thinking/Tool/Streaming 최종 판정

| 항목 | 상태 | enforcement 영향 |
|------|------|-----------------|
| cacheRead/Write 수집 | PASS (0 반환) | 없음 |
| cache 비용 반영 | NOT_IMPLEMENTED | 없음 (현재 미사용) |
| cache non-zero 경고 | IMPLEMENTED | handler.py에 structured warning log 추가 |
| thinking (outputTokens) | PASS | 보수적 과대 계상 → 안전 |
| tool use | PASS | 정확 |
| ConverseStream | NOT_APPLICABLE | v1=non-streaming |

현재 enforcement 정확도 영향: 0. Cache 도입 시 handler.py의 `cache_tokens_nonzero_cost_not_included` 경고가 CloudWatch에 발생하므로 운영자가 인지 가능.

---

## 10. Billing Truth 한계

| 항목 | 상태 |
|------|------|
| CUR | 미설정 |
| FX | 1450 하드코딩 |
| Cache 비용 | 미반영 (undercount 방향) |
| 판정 | quota enforcement와 분리 — enforcement는 PASS, billing truth는 FAIL |

Billing truth는 quota enforcement의 전제조건이 아니다. Enforcement는 "사용자가 한도를 초과하지 못하게 막는 것"이고, billing truth는 "실제 AWS 청구와 일치하는 것"이다. 전자는 PASS, 후자는 별도 CUR 파이프라인 구축 필요.

---

## 11. 운영 체크리스트

- [x] allowed_models stale direct ID 교체 (cgjang)
- [x] validate-model-catalog.py 작성
- [x] preflight-quota-gateway-check.py 작성
- [x] model-catalog-governance.md 작성
- [x] shell-hook-runbook.md 작성
- [x] runtime-wrapper-runbook.md 작성
- [x] cache non-zero warning log 추가 (handler.py)
- [x] bedrock_gw.py urllib 전환 + FSx 배포
- [x] 다른 principal (sbkim, jwlee, shlee2, hermee)의 stale direct ID 정리
- [x] Lambda 재배포 (cache warning log 반영) — 2026-03-30T05:18:35Z

---

## 12. 원복 결과

| 항목 | 상태 |
|------|------|
| cgjang allowed_models | 8개 (교체 후 최종 상태 유지) |
| haiku cost_krw | 4.4617 |
| sonnet-4-5 cost_krw | 0.9309 |
| nova-lite cost_krw | 0.052374 |
| nova-micro cost_krw | 0.09921625 |
| 테스트 생성 모델 usage | 삭제 완료 |
| boost | 0건 |
| pending lock | 삭제 |

---

## 13. Acceptance Criteria

| # | 항목 | 판정 |
|---|------|------|
| 1 | stale allowed model 교체 | PASS |
| 2 | model catalog validator 스크립트 | PASS |
| 3 | preflight 운영 점검 스크립트 | PASS |
| 4 | pricing/allowed/callable 정합성 | PASS |
| 5 | shell hook runbook | PASS |
| 6 | runtime wrapper runbook | PASS |
| 7 | model catalog governance 문서 | PASS |
| 8 | cache non-zero 경고 로깅 | PASS |
| 9 | final report 갱신 | PASS |
| 10 | 테스트 아티팩트 원복 | PASS |

10/10 PASS.
