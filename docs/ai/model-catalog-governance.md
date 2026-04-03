# Model Catalog Governance

## 모델 추가 절차
1. AWS Bedrock 콘솔에서 모델 접근 권한 확인 (Model access)
2. Converse API 호출 가능 여부 확인 (inference profile ID 사용)
3. pricing table에 등록 (`bedrock-gw-{env}-{region}-model-pricing`)
   - model_id: inference profile ID (예: `us.anthropic.claude-...`)
   - input_price_per_1k, output_price_per_1k: KRW 단위
   - exchange_rate: 적용 환율
   - effective_date: 적용일
4. principal-policy allowed_models에 추가
5. `validate-model-catalog.py` 실행하여 정합성 확인

## Region/Profile Prefix 규칙
- us-west-2 cross-region: `us.` prefix (예: `us.anthropic.claude-haiku-4-5-20251001-v1:0`)
- global cross-region: `global.` prefix
- direct model ID (`anthropic.claude-...`): 일부 모델에서 Converse 미지원 → `us.` 버전 사용 권장
- pricing table에는 모든 variant를 별도 행으로 등록 (strict match, no normalization)

## Deprecated Model ID 제거
1. `validate-model-catalog.py` 실행 → STALE_DIRECT_ID 확인
2. `us.` prefix 버전이 pricing table에 있는지 확인
3. allowed_models에서 direct ID 제거, `us.` 버전으로 교체
4. 교체 후 실제 호출 성공 확인

## LEGACY / Unavailable 모델 관리
- Bedrock foundation model lifecycle이 LEGACY인 모델의 us. inference profile은 비활성될 수 있음
- gateway 경유 시 ResourceNotFoundException 발생 → 비용 미적재, aggregate 불변
- pricing table에는 유지 가능 (향후 재활성 대비)
- allowed_models에는 추가하지 않음 (사용자가 호출 시도 시 gateway가 500 반환)
- validator에서 LEGACY + allowed 조합을 WARN으로 표시

## Model Access Grant 필요 모델
- ACTIVE lifecycle이나 계정에서 model access grant가 안 된 모델
- gateway 경유 시 AccessDeniedException 발생
- Bedrock 콘솔에서 Model access 활성화 후 사용 가능
- 활성화 전까지 allowed_models에 추가하지 않음

## Stale ID 탐지
- `validate-model-catalog.py`가 자동 탐지:
  - `anthropic.` prefix (direct ID) → `us.` 버전 존재 시 STALE 경고
  - allowed에 있으나 pricing 없음 → NO_PRICING 경고
- 배포 전 preflight check에서도 동일 검사

## 배포 체크리스트
- [ ] pricing table에 신규 모델 등록
- [ ] allowed_models 업데이트
- [ ] `validate-model-catalog.py` PASS
- [ ] `preflight-quota-gateway-check.py` PASS
- [ ] 실제 Converse 호출 성공 확인
- [ ] 비용 정확도 검증 (stored vs official recalc)
