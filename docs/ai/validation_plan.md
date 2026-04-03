# Validation Plan: Bedrock Access Control Gateway

> Phase 2 artifact. Updated: 2026-03-20.
> Identity model re-baselined: per-user assume-role (`BedrockUser-<username>`) is primary.
>
> **DEPLOYMENT BLOCK PARTIALLY LIFTED (2026-03-17)**: `normalize_principal_id()` Candidate F implemented and live-verified (single-user).
> Discovery Lambda 재배포 완료. `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인.
> C2/C3/C5 captures are deferred validation follow-up, not deployment blocker.
>
> **PHASE 2 DEPLOYED TO DEV AND VERIFIED (2026-03-20)**: KRW cost-based monthly quota rewrite complete. All C1-C9 PASS. See `docs/ai/phase2-dev-validation-report.md`.
> **Phase 3 DEPLOYED TO DEV AND VERIFIED (2026-03-23).** Approval ladder rewrite complete. All critical AC pass. See `docs/ai/phase3-dev-validation-report.md`.

---

## Task 3: Principal Discovery — Execution Plan

> Updated: 2026-03-17. Per-user assume-role이 primary identity model로 변경됨.
> 이전 permission-set 기반 C1-real 계획은 폐기. Per-user role 기반으로 재정의.

### Prerequisites

1. **Temporary dev/discovery-only deployment** — NOT the prod endpoint.
   - Deploy API Gateway + Lambda with `DISCOVERY_MODE=true` using a **separate Terraform workspace** (`terraform workspace new discovery`). This creates isolated state — the discovery deployment cannot affect prod state.
   - Do NOT use the prod workspace with a variable override. Separate state is mandatory.
   - This deployment uses Task 1 infra definitions but targets a throwaway `discovery` stage, not `prod`.
   - No DynamoDB business data is written (discovery mode bypasses the inference pipeline).
   - The normal prod deployment block remains in effect — this exception is scoped to discovery only.
2. Per-user role (`BedrockUser-<username>`)에 `execute-api:Invoke` 권한 추가 (discovery API Gateway ARN 대상)
3. Laptop: per-user role assume 가능한 profile 설정 (admin이 `aws sts assume-role` 또는 profile 설정)
4. FSx: 기존 `[default]` profile 사용 — credential 파일 수정 불필요 (R11 대폭 완화)

### Discovery Environment Lifecycle

- Deploy: `terraform workspace new discovery || terraform workspace select discovery` → `terraform plan -var environment=discovery -var discovery_mode=true` → `terraform apply -var environment=discovery -var discovery_mode=true`. Separate state file — prod state untouched.
- Capture: C1 (laptop) + C2 (FSx) — see below.
- Teardown: `terraform destroy -var environment=discovery -var discovery_mode=true` in the `discovery` workspace immediately after captures complete. Then `terraform workspace select default` and `terraform workspace delete discovery`.
- `DISCOVERY_MODE` defaults to `false` in `variables.tf`. It is only set to `true` via `-var` for the temporary discovery deployment. After teardown, no deployed Lambda has `DISCOVERY_MODE=true`.
- The prod deployment proceeds only after normalization rule is confirmed and `normalize_principal_id()` is updated.

### Discovery Call Path

```
사용자 (laptop 또는 FSx)
  │  Per-user assume-role (BedrockUser-<username>) → temporary credentials
  │  (FSx: credential_source = Ec2InstanceMetadata, 기존 [default] profile)
  │  (Laptop: aws sts assume-role 또는 profile 설정)
  │  aws sts get-caller-identity   ← credential validation (필수)
  ▼  SigV4-signed HTTPS POST (any SigV4-capable client)
API Gateway — discovery stage (AWS_IAM auth) → SigV4 검증
  ▼
Gateway Lambda (DISCOVERY_MODE=true)
  │  handle_discovery(event["requestContext"])
  │    → extract_identity()
  │    → normalize_principal_id()
  ▼  Returns JSON:
  {
    "discovery": true,
    "raw_identity": {
      "userArn": "arn:aws:sts::107650139384:assumed-role/BedrockUser-<username>/<session-name>",
      "caller": "...", "accountId": "...", "accessKey": "...",
      "sourceIp": "...", "userAgent": "..."
    },
    "derived_principal_id": "<account>#BedrockUser-<username>"
  }
```

> Note: `derived_principal_id`는 Candidate F 형식으로 반환됨 (재배포 완료). Live 확인: `107650139384#BedrockUser-cgjang`.

### Credential Validation (필수, 캡처 전 수행)

```bash
# FSx (기존 [default] profile 사용 — 수정 불필요):
aws sts get-caller-identity
# Expected: arn:aws:sts::107650139384:assumed-role/BedrockUser-<username>/<session-name>

# Laptop (per-user role assume):
aws sts get-caller-identity --profile bedrock-user-<username>
# 또는 admin이 직접 assume-role:
aws sts assume-role --role-arn arn:aws:iam::107650139384:role/BedrockUser-<username> --role-session-name laptop-discovery
# Expected: arn:aws:sts::107650139384:assumed-role/BedrockUser-<username>/laptop-discovery
# Record this output — it provides the userArn independently of API Gateway.
```

### Discovery Request (any SigV4-capable client)

The actual API Gateway call can use any SigV4-capable client: `awscurl`, `boto3` script, Postman with AWS auth, etc. The client choice is not prescribed.

```bash
# Example: awscurl (FSx, using default profile)
awscurl --service execute-api --region us-west-2 \
  -X POST -d '{"modelId":"discovery-test"}' \
  "${DISCOVERY_URL}"

# Example: boto3/botocore script
python3 -c "
import boto3, json
session = boto3.Session()  # FSx: uses [default] profile
# ... SigV4-signed request to discovery endpoint
"

# Example: curl with AWS SigV4 (requires curl 7.75+)
curl --aws-sigv4 "aws:amz:us-west-2:execute-api" \
  --user "\$AWS_ACCESS_KEY_ID:\$AWS_SECRET_ACCESS_KEY" \
  -H "x-amz-security-token: \$AWS_SESSION_TOKEN" \
  -X POST -d '{"modelId":"discovery-test"}' \
  "${DISCOVERY_URL}"
```

### Data to Capture

| Field | Source | Purpose |
|---|---|---|
| `userArn` | `requestContext.identity.userArn` | Primary normalization candidate |
| `caller` | `requestContext.identity.caller` | Fallback candidate |
| `accountId` | `requestContext.identity.accountId` | Cross-account check |
| `accessKey` | `requestContext.identity.accessKey` | Session correlation |
| `sourceIp` | `requestContext.identity.sourceIp` | Environment differentiation |
| `userAgent` | `requestContext.identity.userAgent` | Client identification |

### Required Captures — Multi-Role Matrix

> 2+ distinct per-user role을 캡처하여 cross-role isolation을 실증해야 함.
> 최소 2명의 서로 다른 사용자 (User A, User B)로 캡처.

| # | Environment | User | Role | Credential Source | Purpose | Status |
|---|---|---|---|---|---|---|
| C1 | Laptop | User A (e.g. jwlee) | `BedrockUser-jwlee` | `aws sts assume-role` or profile | 랩탑 ARN 패턴 캡처 | Pending |
| C2 | FSx interactive | User A (same as C1) | `BedrockUser-jwlee` | `[default]` profile, `credential_source = Ec2InstanceMetadata` | 동일 사용자 cross-env 정규화 일치 확인 | Pending |
| C3 | Laptop or FSx | User B (e.g. shlee2) | `BedrockUser-shlee2` | 동일 방식 | 다른 사용자 → 다른 principal_id 확인 | Pending |
| C4 | (optional) FSx or Laptop | User B (C3과 다른 환경) | `BedrockUser-shlee2` | 동일 방식 | User B cross-env 정규화 일치 확인 | Optional |
| C5 | Laptop or FSx | Admin | `BedrockUser-Shared` | `aws sts assume-role` | Fail-closed 동작 확인 (비-개인 role) | Pending |

### Evidence Fields Per Capture

각 캡처(C1-C5)에 대해 다음 필드를 기록한다:

```json
{
  "capture_id": "C1",
  "timestamp": "2026-03-XX T..Z",
  "environment": "laptop | fsx",
  "user": "<human username>",
  "role_assumed": "<full role ARN>",
  "credential_source": "sts assume-role | Ec2InstanceMetadata",

  "sts_get_caller_identity": {
    "Account": "107650139384",
    "UserId": "<RoleId>:<session-name>",
    "Arn": "arn:aws:sts::107650139384:assumed-role/BedrockUser-<username>/<session-name>"
  },

  "api_gateway_request_context_identity": {
    "userArn": "",
    "caller": "",
    "accountId": "",
    "accessKey": "",
    "sourceIp": "",
    "userAgent": ""
  },

  "discovery_lambda_response": {
    "raw_identity": {},
    "derived_principal_id": ""
  },

  "extracted_fields": {
    "role_name": "BedrockUser-<username>",
    "session_name": "<actual session name value>",
    "account_id": "107650139384"
  },

  "candidate_f_result": "<account>#<role-name>"
}
```

파일 저장 위치: `docs/ai/discovery/c1-evidence.json`, `c2-evidence.json`, ... `c5-evidence.json`

### Success Criteria

All must be true before normalization is confirmed:

**Cross-environment consistency (User A: C1 + C2)**
1. C1 and C2 both captured (same human user, both environments)
2. `BedrockUser-<username>` assumed-role ARN structure documented for both
3. A normalization rule exists: `normalize(C1.userArn) == normalize(C2.userArn)` — same user, same key
4. Role name 부분이 두 환경에서 동일한지 확인 (session name은 다를 수 있음)
5. Session name 값이 각 환경에서 무엇인지 기록 (EC2 instance ID vs laptop session name)
6. Rule is deterministic for any valid per-user assume-role session

**Cross-role isolation (User A vs User B: C1/C2 vs C3)**
7. **Exact-match isolation**: `normalize(C1.userArn) != normalize(C3.userArn)` — 서로 다른 per-user role이 서로 다른 principal_id로 정규화됨. Family-level collision 없음.
8. C3 캡처에서 User B의 role name이 User A와 다른 `BedrockUser-<username>` 패턴임을 확인.
9. Candidate F 적용 시: `107650139384#BedrockUser-jwlee` ≠ `107650139384#BedrockUser-shlee2` 실증.

**Fail-closed (C5: non-personal role)**
10. **Fail-closed**: `BedrockUser-Shared` role로 캡처 시 normalization이 빈 문자열 반환 → deny-by-default 동작 확인.
11. `BedrockUser-Shared`의 userArn 패턴이 `arn:aws:sts::107650139384:assumed-role/BedrockUser-Shared/<session>` 형태임을 확인.
12. Normalization 로직이 `BedrockUser-Shared`를 명시적으로 거부하는지 확인 (role name == `BedrockUser-Shared` → reject).

**Design invariants**
13. **No wildcard interpretation**: principal_id lookup이 exact match로만 동작하며, prefix/suffix/contains 매칭이 불가능함을 확인. DynamoDB GetItem은 본질적으로 exact-match이므로 코드 리뷰로 확인.
14. **Metadata separation**: derived username (role name에서 추출)이 enforcement에 사용되지 않고 display/reporting에만 사용됨을 확인. handler.py 코드 리뷰로 확인.

### Normalization Rule Candidates

ARN pattern: `arn:aws:sts::<acct>:assumed-role/BedrockUser-<username>/<session-name>`

| # | Rule | 예시 | Pros | Cons |
|---|---|---|---|---|
| A | Full userArn as-is (current placeholder) | `arn:aws:sts::107650139384:assumed-role/BedrockUser-jwlee/i-0abc123` | Simple | Unstable — session name varies by environment |
| E | Role name extraction (`BedrockUser-<username>`) | `BedrockUser-jwlee` | Stable, session-independent, concise | Not globally unique across accounts |
| F | `<account>#<role-name>` (recommended, CONFIRMED single-user) | `107650139384#BedrockUser-jwlee` | Unique + stable + session-independent | Slightly longer key |
| G | Full role ARN without session | `arn:aws:iam::107650139384:role/BedrockUser-jwlee` | IAM canonical form | Verbose as DynamoDB key |

이전 후보 D (`<account>#<session-name>`)는 폐기: per-user assume-role에서 session name은 username이 아님.

**Candidate F 정의 (CONFIRMED — single-user live-verified, cross-user deferred):**
- Exact per-principal key. Grouping key 아님.
- `107650139384#BedrockUser-jwlee` = jwlee 한 명만 나타냄
- `107650139384#BedrockUser-shlee2` = shlee2 한 명만 나타냄 (다른 키)
- Policy/quota/approval lookup은 exact principal_id match only
- Wildcard, prefix (`BedrockUser-*`), suffix, contains 매칭 금지
- Derived username (`jwlee`)은 display/reporting metadata only — enforcement identity는 `<account>#<full-role-name>` 전체
- Role name이 예상 패턴과 불일치 시 normalization fail closed → 빈 문자열 → deny-by-default

### Post-Discovery Actions

1. ~~Confirm rule (E/F/G or new)~~ → Candidate F implemented and live-verified (2026-03-17)
2. ~~Update `normalize_principal_id()`~~ → Done. 11 unit tests in `test_normalize_principal_id.py`.
3. Update `design.md` Locked Decision #3 (PROVISIONAL → CONFIRMED) — single-user live-verified; full confirmation after C2/C3/C5
4. Update `requirements.md` Req 2.4-2.6 (discovery 필수 → 확정) — after C2/C3/C5
5. ~~Define PrincipalPolicy `principal_id` key format~~ → `<account>#BedrockUser-<username>`
6. ~~Remove deployment block~~ → Partially lifted (2026-03-17)
7. ~~Discovery Lambda 재배포~~ → Done (2026-03-17), live-verified
8. Proceed to Task 10 (checkpoint)

### Exact Function to Update

**File**: `infra/bedrock-gateway/lambda/handler.py`
**Function**: `normalize_principal_id`

> **UPDATED (2026-03-17)**: Candidate F 구현 완료. Live-verified (single-user, cgjang FSx).
> Discovery Lambda 재배포 완료 — `derived_principal_id` = `107650139384#BedrockUser-cgjang`.
> 아래 "CURRENT" 코드는 현재 배포된 실제 코드임 (더 이상 placeholder 아님).

---

## Task 3: Discovery Validation Checklist

> Updated: 2026-03-17. Per-user assume-role 기반, multi-role capture matrix 적용.

### Phase A: Discovery Environment Setup
- [x] Temporary discovery deployment 생성 (separate Terraform workspace `discovery`, `DISCOVERY_MODE=true`) ✅ (2026-03-17, API ID: `ugpt5xi8b7`, stage: `v1`)
- [x] Per-user role (`BedrockUser-cgjang`)에 `execute-api:Invoke` 권한 추가 (discovery API Gateway ARN) ✅ (2026-03-17, cgjang 캡처 성공으로 확인)
- [ ] Per-user role (`BedrockUser-shlee2`, `BedrockUser-Shared`)에 `execute-api:Invoke` 권한 추가 — C3, C5 캡처 전 필요
- [x] `docs/ai/discovery/` 디렉토리 생성 (evidence 파일 저장용) ✅ (2026-03-17, templates created: c1-c5-evidence.json, phase-e-code-review.json, task3-execution-summary.md)

### Phase B: User A Captures (cross-environment consistency)
- [x] C1: FSx — `aws sts get-caller-identity` (cgjang per-user role, `credential_source = Ec2InstanceMetadata`) 출력 기록 ✅ (2026-03-17)
- [x] C1: FSx — SigV4 discovery 요청 → requestContext.identity 전체 캡처 → `docs/ai/discovery/c1-evidence.json` ✅ (2026-03-17)
- [ ] C2: 랩탑 — `aws sts get-caller-identity` (cgjang, laptop profile) 출력 기록
- [ ] C2: 랩탑 — SigV4 discovery 요청 → requestContext.identity 전체 캡처 → `docs/ai/discovery/c2-evidence.json`
- [ ] C1/C2 userArn 패턴 비교 → role name 동일, session name 상이 확인
- [ ] `normalize(C1.userArn) == normalize(C2.userArn)` 확인 (Candidate F 적용)

### Phase C: User B Captures (cross-role isolation)
- [ ] C3: 랩탑 또는 FSx — User B per-user role assume → SigV4 discovery 요청 → `docs/ai/discovery/c3-evidence.json`
- [ ] `normalize(C1.userArn) != normalize(C3.userArn)` 확인 — family-level collision 없음
- [ ] (Optional) C4: User B 다른 환경 → `docs/ai/discovery/c4-evidence.json` — User B cross-env 일치 확인

### Phase D: Fail-Closed Verification
- [ ] C5: `BedrockUser-Shared` role assume → SigV4 discovery 요청 → `docs/ai/discovery/c5-evidence.json`
- [ ] C5 normalization 결과가 빈 문자열임을 확인 → deny-by-default 동작 검증

### Phase E: Design Invariant Verification (코드 리뷰)
- [x] handler.py `normalize_principal_id()` — exact match only, wildcard 로직 없음 확인 ✅ (2026-03-17, E1)
- [x] handler.py `lookup_principal_policy()` — DynamoDB GetItem (exact key) 확인 ✅ (2026-03-17, E2)
- [x] derived username이 enforcement path에 사용되지 않음 확인 ✅ (2026-03-17, E3)
- [x] RequestLedger immutability — IAM explicit Deny 확인 ✅ (2026-03-17, E4)
- [x] PrincipalPolicy PK exact-match by design 확인 ✅ (2026-03-17, E5)
- [x] No wildcard/prefix/suffix/contains matching in entire handler.py 확인 ✅ (2026-03-17, E6)
> Evidence: `docs/ai/discovery/phase-e-code-review.json`

### Phase F: Normalization Confirmation + Cleanup
- [x] 규칙 후보 F 구현 — exact per-principal key (`<account>#<role-name>`), wildcard 금지, fail-closed ✅ (2026-03-17)
- [x] normalize_principal_id() 업데이트 (handler.py) — Candidate F, 11 unit tests pass ✅ (2026-03-17)
- [ ] design.md Locked Decision #3 업데이트 (PROVISIONAL → CONFIRMED) — C2/C3/C5 완료 후
- [ ] requirements.md Req 2.4-2.6 업데이트 (discovery 필수 → 확정) — C2/C3/C5 완료 후
- [x] PrincipalPolicy principal_id 키 형식 확정: `<account>#BedrockUser-<username>` ✅ (2026-03-17)
- [ ] Discovery deployment 즉시 삭제 (`terraform destroy` + `terraform workspace delete discovery`)
- [x] 배포 차단 부분 해제 (todo.md, validation_plan.md, runbook.md) ✅ (2026-03-17)

---

## Post-Task-3 Implementation Impact

> Task 3 완료 후 업데이트가 필요한 파일/함수 목록. 코드 변경은 Task 3 결과 확정 후에만 수행.

### Runtime Code (승인 필요)

| File | Location | Change Required |
|---|---|---|
| `infra/bedrock-gateway/lambda/handler.py` | `normalize_principal_id()` | ~~Placeholder (userArn as-is) → Candidate F 로직~~ **DONE (2026-03-17). Live-verified (single-user).** `<account>#<role-name>`, fail-closed, `BedrockUser-Shared` reject. 11 unit tests. Discovery Lambda 재배포 완료 — `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인. |
| `infra/bedrock-gateway/lambda/handler.py` | `handle_discovery()` (lines 310-330) | Discovery 완료 후 `DISCOVERY_MODE` 코드 제거 또는 유지 결정 (기능적 영향 없음 — env var default=false) |

### Governance Artifacts (승인 불필요 — planning docs)

| File | Section | Change Required |
|---|---|---|
| `.kiro/specs/bedrock-access-gateway/design.md` | Locked Decision #3 | `PROVISIONAL` → `CONFIRMED`. 실제 캡처 결과 기반 정규화 규칙 명시. |
| `.kiro/specs/bedrock-access-gateway/requirements.md` | Req 2.4-2.6 | `discovery 필수` → `discovery 완료, 규칙 확정`. Candidate F 확정 시 구체적 형식 명시. |
| `docs/ai/validation_plan.md` | Deployment Block header | 배포 차단 해제. |
| `docs/ai/todo.md` | Deployment Block + Task 3 | Task 3 완료 표시. 배포 차단 해제. |
| `docs/ai/runbook.md` | Deployment Block section | 배포 차단 해제. |
| `docs/ai/research.md` | Candidate F 정의 | `PROVISIONAL` → `CONFIRMED`. 실제 캡처 evidence 참조 추가. |
| `docs/ai/risk_register.md` | R1, R16, R20 | Status: `Open` → `Closed` (discovery 완료). R16 배포 차단 해제. |

### DynamoDB Schema Impact

| Table | Key Field | Impact |
|---|---|---|
| PrincipalPolicy | `principal_id` (PK) | Admin이 정책 생성 시 Candidate F 형식 (`107650139384#BedrockUser-jwlee`) 사용 필수. |
| MonthlyUsage | `principal_id_month` (PK) | `<principal_id>#<YYYY-MM>` 형식. Phase 2 active table. principal_id 부분이 Candidate F. |
| ~~DailyUsage~~ | ~~`principal_id_date` (PK)~~ | **Legacy/inactive (Phase 2에서 대체됨).** `monthly_usage`가 active. 제거 후보 (post-Phase-3). |
| TemporaryQuotaBoost | `principal_id` (PK) | Candidate F 형식. |
| ApprovalRequest | `principal_id` | Candidate F 형식. |
| ApprovalPendingLock | `principal_id` (PK) | Candidate F 형식. |
| RequestLedger | `principal_id` (field) | Candidate F 형식으로 기록. |
| SessionMetadata | `principal_id` (field) | Candidate F 형식으로 기록. |

> 모든 DynamoDB 테이블은 미배포 상태이므로 기존 데이터 마이그레이션 불필요. 키 형식만 확정하면 됨.

---

## Remaining Unresolved Assumptions (Task 3 부분 완료 — C2/C3/C5 deferred)

| # | Assumption | Verification Method | Impact if Wrong | Status |
|---|---|---|---|---|
| A1 | `credential_source = Ec2InstanceMetadata`로 assume-role 시 session name이 EC2 instance ID 형태 | C2 캡처에서 실제 session name 확인 | Candidate F는 session name에 의존하지 않으므로 정규화에 영향 없음. 단, session name 형태 기록은 필요 (감사/디버깅용). | **부분 반증 (C1)**: FSx session name = `botocore-session-<epoch>` (SDK-generated, NOT EC2 instance ID). Candidate F 영향 없음. |
| A2 | 랩탑에서 `aws sts assume-role --role-session-name` 지정 시 해당 값이 userArn에 반영됨 | C1 캡처에서 확인 | Candidate F는 session name에 의존하지 않으므로 정규화에 영향 없음. | Deferred (C2 laptop 캡처 필요) |
| A3 | API Gateway `requestContext.identity.userArn`이 `arn:aws:sts::<acct>:assumed-role/<role>/<session>` 형태 | C1, C2 캡처에서 확인 | 형태가 다르면 Candidate F 파싱 로직 수정 필요. 이 경우 정규화 규칙 재설계. | **확인됨 (C1)**: `arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/botocore-session-1773807868` |
| A4 | `BedrockUser-Shared` role의 userArn도 동일한 assumed-role 패턴 | C5 캡처에서 확인 | 패턴이 다르면 fail-closed 로직 조건 수정 필요. | Deferred (C5 캡처 필요) |
| A5 | 모든 per-user role이 `BedrockUser-` prefix를 사용 | 기존 IAM role 목록 확인 (research.md에 3개 확인됨) | Prefix가 다른 per-user role이 있으면 normalization 허용 패턴 확장 필요. | **확인됨**: 6개 `BedrockUser-*` role 확인 (Task 2에서 전수 적용) |
| A6 | `requestContext.identity.caller` 필드가 `<RoleId>:<session-name>` 형태 | C1, C2 캡처에서 확인 | Candidate F는 caller에 의존하지 않으므로 정규화에 영향 없음. 단, fallback 로직 설계에 참고. | Deferred (C2 캡처 필요) |

---

## No-Change Confirmation

> Task 3 실행 준비 과정에서 다음 파일은 수정하지 않았음을 확인:
> - `infra/bedrock-gateway/lambda/handler.py` — runtime code 변경 없음
> - `infra/bedrock-gateway/*.tf` — Terraform 파일 변경 없음
> - `account-portal/` — 기존 서비스 변경 없음
> - `ansible/` — 기존 자동화 변경 없음
>
> 변경된 파일: `docs/ai/validation_plan.md` (이 파일) — governance/planning artifact only.

---

## Task 10: Lambda Checkpoint Validation

- [ ] deny 시나리오: 정책 없음, 모델 불허, 쿼터 초과, DynamoDB 오류
- [ ] 토큰 카운팅: DynamoDB ADD 원자성 확인
- [ ] 쿼터 합산: 여러 모델 사용 시 글로벌 합산 정확성
- [ ] Idempotency: 중복 request_id → Bedrock 미호출
- [ ] RequestLedger 불변성: UpdateItem/DeleteItem IAM deny 확인
- [ ] Failure mode: DynamoDB 오류 시 deny-by-default

## Task 14: E2E Validation

- [ ] 사용자 SigV4 호출 → Lambda → Bedrock → 응답 전체 플로우
- [ ] 쿼터 초과 → 부스트 요청 → 관리자 승인 → 부스트 적용 → 만료 플로우
- [ ] Bedrock 직접 호출 차단 확인 (IAM deny)
- [ ] Terraform 기반 롤백 테스트
- [ ] Lambda alias 전환 롤백 테스트
- [ ] CloudWatch 3-layer 감사 경로 확인
- [ ] Converse API 미지원 모델 요청 시 명시적 에러 확인

## Acceptance Criteria

- 모든 deny 시나리오에서 deny-by-default 동작
- 감사 로그 3-layer 모두 정상 기록
- 쿼터 합산이 글로벌 (모델별 아님)으로 정확히 동작
- 롤백 시 서비스 중단 없이 이전 버전 복구
