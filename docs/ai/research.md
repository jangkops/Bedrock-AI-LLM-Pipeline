# Research: Bedrock Access Control Gateway

> Phase 1 artifact. Architecture decision research.
> Updated with 9 locked decisions.

## Architecture Decision Record

### Problem
내부 사용자의 Bedrock 접근을 사용자별 AWS principal 기반으로 통제해야 함.

### Options Evaluated

| Option | Description | Identity Model | Verdict |
|--------|-------------|---------------|---------|
| A: API Gateway + AWS_IAM + Lambda | 서버리스, SigV4 기반 | AWS가 검증 (trust boundary 내) | **채택 (최종 목표)** |
| B: Flask/Docker + JWT | 기존 패턴, 자체 JWT | 자기 선언 (trust boundary 밖) | **기각** |
| C: Flask/Docker + STS GetCallerIdentity | 기존 패턴, STS 사후 검증 | 서버가 확인 (약한 trust) | **임시안만 허용 (기한 필수)** |

### Why A (최종 목표 아키텍처)
- SigV4 서명을 AWS가 직접 검증 → identity 위변조 불가
- Lambda에 `event.requestContext.identity`로 검증된 identity fields 전달
- API Gateway access/execution logging + Lambda structured logs + Bedrock invocation logs = 3-layer 감사
- Bedrock 직접 차단이 IAM/SCP로 깔끔하게 구현됨
- 서버리스: 인프라 운영 부담 최소

### Why not B (기각)
- JWT는 자체 발급 토큰, AWS identity chain과 무관
- JWT 탈취 시 identity spoofing 가능
- 감사 로그의 principal이 AWS가 보증하지 않는 값
- Bedrock 직접 차단과 무관한 별도 인증 체계

### Why C is temporary only (임시안)
- 매 요청마다 STS API 호출 오버헤드
- Credentials가 HTTP 헤더로 전송 (서버 메모리에 존재)
- API Gateway의 request-level 인증이 아닌 사후 확인
- Replay 방지를 직접 구현해야 함
- A안 대비 잃는 것: SigV4 자동 검증, API Gateway 감사 로그, 서버리스 운영 이점

## Locked Architecture Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Regional REST API (v1) | 랩탑 + FSx 모두 Private API 네트워크 도달성을 가정할 수 없음 |
| 2 | Non-streaming only (v1) | API Gateway REST API는 Lambda proxy에서 streaming 미지원 |
| 3 | Principal: userArn 우선, raw fields 보존. Per-user assume-role이 primary identity model. Normalized principal_id는 exact per-principal key. Wildcard/prefix 매칭 금지. 미매칭 시 fail closed. | requestContext.identity.caller가 항상 canonical이 아닐 수 있음. Per-user role name에 username 포함. Derived username은 display metadata only. Single-user live-verified (C1, cgjang FSx): `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인 (session `botocore-session-1773807868`). Discovery Lambda 재배포 완료. Cross-env/cross-role/fail-closed deferred. |
| 4 | Bedrock 차단: SCP 목표, IAM deny 임시 | SCP 즉시 적용 불가 시 human role에 IAM deny 적용 |
| 5 | backend-admin: admin portal only | inference 프록시 금지. inference는 API Gateway AWS_IAM auth 경유 필수 |
| 6 | SES: 외부화, verified sender 1개/env | admin group alias로 수신자 설정 |
| 7 | DynamoDB: `bedrock-gw-${env}-${region}-${table}` | 환경/리전 인식 네이밍 |
| 8 | Global quota + model-level accounting | 시행은 principal global, 기록은 model-level |
| 9 | Idempotency state와 audit log 분리 | immutable audit와 duplicate replay state를 분리해야 정합성 유지 가능 |

## Current Architecture (Existing Repo)

| Component | Status | Notes |
|-----------|--------|-------|
| backend-admin | 운영 중 | Flask, port 5000, Docker Compose |
| backend-cost | 운영 중 | Flask, port 5001, Docker Compose |
| backend-gateway/ | 빈 디렉토리 | 코드 없음 |
| docker-compose-fixed.yml | gateway 서비스 없음 | admin, cost, redis, nginx만 |
| frontend | gateway 관련 없음 | 라우트/API 호출 없음 |

## Key Findings

### 1. Principal Normalization (미확정 — discovery 필수)

> Updated: 2026-03-17. Primary identity model이 per-user assume-role로 변경됨.

Per-user assume-role ARN ~~예상~~ 확인된 패턴 (C1 live evidence, cgjang FSx):
- `arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/botocore-session-1773732261`
- 정규화 추천 후보 F: `<account>#<role-name>` → `107650139384#BedrockUser-cgjang`
- Role name에 username이 포함되어 session name에 의존하지 않는 안정적 정규화 가능
- Session name = `botocore-session-<epoch>` (SDK-generated, non-deterministic) — A1 가정 부분 반증 (EC2 instance ID 아님)
- `caller` = `AROARSEDSYT4BXBD4YZYI:botocore-session-<epoch>` — A6 가정 확인

이전 permission-set 모델의 정규화 후보 D (`account#session-name`)는 per-user role에서 session name이 username이 아니므로 폐기.

**주의**: ~~이 패턴은 가정.~~ 단일 사용자(cgjang, FSx) live evidence로 ARN 구조 확인됨. Discovery Lambda 재배포 완료 — `derived_principal_id` = `107650139384#BedrockUser-cgjang` live 확인 (session `botocore-session-1773807868`). Cross-env (laptop), cross-role, fail-closed 검증은 deferred. 최종 full confirmation은 전체 캡처 완료 후 (Task 3).

### 2. ConverseStream + API Gateway
API Gateway REST API는 Lambda proxy integration에서 streaming 응답 미지원.
v1: non-streaming(Converse API)만 지원. Streaming은 v2로 연기.

### 3. Admin UI 통합 패턴
- 프론트엔드 → backend-admin → DynamoDB (기존 JWT 인증)
- Bedrock inference는 사용자 → API Gateway (SigV4) → Lambda (별도 경로)
- backend-admin은 inference 프록시로 사용하지 않음

### 4. Bedrock 직접 차단 전략
- 임시: human role에 IAM deny policy (bedrock:Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream)
- 목표: Organization SCP (Gateway Lambda role ARN 제외)
- 전환: SCP 승인 획득 후 IAM deny → SCP 교체

### 5. Quota Race Condition (v1)
- post-call ADD 전략: Bedrock 호출 후 DailyUsage 원자적 업데이트
- 동시 요청 시 최대 1회 호출분 초과 허용 (v1 허용 범위)
- v2에서 pre-reservation 패턴 고려 가능

## Open Questions (Resolved)

| # | Question | Resolution |
|---|----------|------------|
| 1 | Regional vs Private REST API | Regional (v1). Private는 VPC-only future variant |
| 2 | ConverseStream 지원 시점 | v2. v1은 non-streaming only |
| 3 | Principal normalization 패턴 | discovery 필수 (Task 3). userArn 우선, raw 보존 |
| 4 | SCP vs IAM deny | SCP 목표, IAM deny 임시 |
| 5 | backend-admin 역할 | admin portal only. inference 프록시 금지 |
| 6 | SES 설정 | 외부화, 1 verified sender/env, admin group alias |
| 7 | DynamoDB 네이밍 | `bedrock-gw-${env}-${region}-${table}` |

## Identity Model Analysis

### Primary Model: Per-User Assume-Role (확정)

> Updated: 2026-03-17. Per-user assume-role이 primary identity model로 확정됨.
> IAM Identity Center permission-set 모델은 optional future path로 강등.

기존 per-user IAM role이 이미 운영 중이다:
- `BedrockUser-cgjang`, `BedrockUser-sbkim`, `BedrockUser-shlee2` — 일반 사용자
- `BedrockUser-Shared` — admin/bootstrap 전용 (관리자만 사용하나 현재인 3/17일 기준 삭제했음)

FSx credential 패턴:
```ini
[default]
role_arn = arn:aws:iam::107650139384:role/BedrockUser-<username>
credential_source = Ec2InstanceMetadata
```

Role 매핑은 root/admin만 관리 — 사용자가 자기 role을 선택할 수 없다.

### 1. Per-User Assume-Role이 Gateway Identity Model에 충분한가

**결론: 충분하다. Permission-set 모델보다 운영 현실에 더 적합하다.**

Per-user role은 `credential_source = Ec2InstanceMetadata`로 EC2 instance profile을 통해 AssumeRole한다. 이 credentials로 SigV4 서명한 요청이 API Gateway에 도달하면, API Gateway가 SigV4를 검증하고 Lambda에 `event.requestContext.identity`를 전달한다.

핵심 요건 충족 여부:
- **SigV4 서명**: assume-role temporary credentials로 SigV4 서명 가능 → 충족
- **API Gateway AWS_IAM auth**: assumed-role credentials는 IAM principal이므로 AWS_IAM auth 통과 → 충족
- **execute-api:Invoke 권한**: per-user role의 IAM policy에 `execute-api:Invoke` 추가 필요 → 구성 가능
- **per-user identity 식별**: userArn의 role name에 username이 포함 (`BedrockUser-<username>`) → 충족

Permission-set 대비 장점:
- FSx 사용자가 이미 `[default]` profile로 per-user role을 사용 중 — 추가 credential 설정 불필요
- SSO login 불필요 — `credential_source = Ec2InstanceMetadata`로 자동 갱신
- FSx credential setup 승인 게이트(R11)가 대폭 완화됨 — 기존 config를 읽기만 하면 됨
- Role name에 username이 포함되어 session name에 의존하지 않는 안정적 정규화 가능

### 2. Per-User Assume-Role Identity가 API Gateway / Lambda에 어떻게 나타나는가

예상 API Gateway requestContext.identity (per-user role, `credential_source = Ec2InstanceMetadata`):

**Live evidence (C1, cgjang FSx, 2026-03-17):**

```json
{
  "identity": {
    "userArn": "arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/botocore-session-1773732261",
    "caller": "AROARSEDSYT4BXBD4YZYI:botocore-session-1773732261",
    "accountId": "107650139384",
    "sourceIp": "35.161.33.3",
    "userAgent": "Python-urllib/3.10"
  }
}
```

**필드 분석 (live evidence 기반 업데이트):**
- `userArn`: `arn:aws:sts::107650139384:assumed-role/BedrockUser-cgjang/botocore-session-1773732261`
  - role name에 username이 포함 — 안정적 식별자 (**live 확인**)
  - session name = `botocore-session-<epoch>` — SDK-generated, non-deterministic (**live 확인, A1 부분 반증: EC2 instance ID 아님**)
  - 정규화: role name 추출 → `BedrockUser-cgjang` 또는 account + role name
- `caller`: `AROARSEDSYT4BXBD4YZYI:botocore-session-1773732261` — role unique ID + session name (**A6 확인**)
- `accountId`: `107650139384`

**Permission-set 모델과의 구조적 차이:**
- Permission-set: username이 session name에 위치 (`/AWSReservedSSO_PermSet_HASH/<username>`)
- Per-user role: username이 role name에 위치 (`/BedrockUser-<username>/<session-name>`)
- 정규화 전략이 근본적으로 다름 — session name이 아닌 role name에서 identity를 추출해야 함

### 3. Principal Normalization 후보 (Per-User Role Model)

| # | Rule | 예시 값 | Pros | Cons |
|---|------|---------|------|------|
| E | Role name 추출 | `BedrockUser-cgjang` | 안정적, session 무관, 간결 | 계정 간 유일성 미보장 |
| F | Account + role name | `107650139384#BedrockUser-cgjang` | 유일 + 안정 + session 무관 | 약간 긴 키 |
| G | Full role ARN (session 제외) | `arn:aws:iam::107650139384:role/BedrockUser-cgjang` | IAM canonical form | DynamoDB 키로 장황 |

**추천 후보: F (`107650139384#BedrockUser-cgjang`)** — CONFIRMED (single-user live-verified, cross-user deferred)
- 계정 범위에서 유일한 exact per-principal key (grouping key 아님)
- Session name에 의존하지 않아 안정적 — **C1 live evidence: session name `botocore-session-<epoch>`는 SDK-generated, 호출마다 변동 확인**
- DynamoDB PK로 적절한 길이
- `107650139384#BedrockUser-cgjang`는 cgjang 한 명만 나타냄. 다른 사용자는 반드시 다른 키: `107650139384#BedrockUser-shlee2`, `107650139384#BedrockUser-kmkim` 등
- Policy/quota/approval lookup은 exact principal_id match only. Wildcard, prefix, suffix, contains 매칭 금지.
- Role name에서 username 추출 가능 (`BedrockUser-` prefix 제거) — 단, 추출된 username은 display/reporting metadata only. Enforcement identity는 `account_id + full role_name` 전체.
- Role name이 `BedrockUser-` prefix와 일치하지 않는 경우 normalization은 fail closed (빈 문자열 반환 → deny-by-default)

**이전 후보 D (`account#session-name`)는 폐기:**
- Per-user assume-role에서 session name은 username이 아님
- `credential_source = Ec2InstanceMetadata` 사용 시 session name은 EC2 instance ID 등 불안정한 값

**Discovery에서 확인해야 할 사항:**
1. ~~`credential_source = Ec2InstanceMetadata`로 assume-role 시 실제 session name 값~~ **확인됨 (C1): `botocore-session-<epoch>`, EC2 instance ID 아님**
2. 랩탑에서 동일 per-user role을 assume할 때의 session name 값 — **C2 pending**
3. ~~두 환경에서 role name 부분이 동일한지 확인~~ **FSx에서 role name `BedrockUser-cgjang` 확인. Laptop C2에서 동일 role name 확인 필요.**
4. 두 개의 서로 다른 per-user role이 서로 다른 principal_id로 정규화되는지 확인 (family-level collision 없음) — **C3 pending**
5. `BedrockUser-` prefix가 아닌 role name (예: `BedrockUser-Shared`, 일반 service role)이 정규화 시 어떻게 처리되는지 확인 — fail closed 동작 검증 — **C5 pending**

### 4. FSx Credential 안전성 (Per-User Role Model)

**Permission-set 모델 대비 대폭 단순화됨.**

Per-user role + `credential_source = Ec2InstanceMetadata`:
- SSO cache 파일 없음 — EC2 instance metadata에서 직접 credential 획득
- `~/.aws/sso/cache/` 관련 리스크(F1, F3, F6) 해소
- 홈 디렉토리 `~/.aws/config`만 보호하면 됨

잔여 리스크:
| # | Risk | Severity | Mitigation | Residual |
|---|------|----------|------------|----------|
| F2 | root/sudo 사용자의 타 사용자 config 접근 | Medium | sudo 접근 최소화, 감사 로그 | 본질적 한계 |
| F4 | 사용자가 다른 role_arn으로 config 변조 | Low | config 파일 소유권 + 권한 600 | root 접근 시 불가 |
| F5 | ~/.aws/config 파일 변조 (다른 사용자가 수정) | Medium | 파일 소유권 + 홈 디렉토리 700 | root 접근 시 불가 |
| F8 | EC2 instance metadata 접근 제한 미설정 | Low | IMDSv2 강제 + hop limit 설정 | 인스턴스 수준 설정 |

### 5. Named Profile vs [default] (Per-User Role Model)

**현재 상태: FSx 사용자는 `[default]`에 per-user role이 설정되어 있음.**

Per-user role 모델에서는 `[default]` 사용이 permission-set 모델보다 덜 위험하다:
- Role 자체가 per-user이므로 "실수로 다른 사용자의 credential 사용" 리스크 없음
- 단, gateway 전용 `execute-api:Invoke` 권한만 필요한 경우 `[default]`의 넓은 권한이 과다할 수 있음

**권장**: 기존 `[default]` profile의 per-user role에 `execute-api:Invoke` 권한을 추가하는 것이 가장 단순. 별도 named profile은 optional.

### 결론

Per-user assume-role은 Bedrock gateway identity model의 primary path로 적합하다. 기존 FSx credential 설정을 그대로 활용할 수 있어 운영 부담이 최소이며, role name에 username이 포함되어 안정적 정규화가 가능하다.

**Enforcement 원칙:**
- Normalized principal_id (`<account>#<full-role-name>`)는 exact per-principal key. Grouping key 아님.
- Policy/quota/approval lookup은 exact match only. Wildcard/prefix/suffix/contains 매칭 금지.
- Derived username은 display/reporting metadata only. Enforcement identity는 full principal_id.
- Role name이 예상 패턴과 불일치 시 normalization fail closed → deny-by-default.

Task 3 discovery에서 실제 requestContext.identity를 캡처하여 정규화 규칙(후보 F)을 확정해야 한다.

---

## Optional Future: IAM Identity Center Permission-Set Model

> 이 섹션은 이전 primary 모델이었으나, per-user assume-role이 primary로 확정됨에 따라 optional future path로 강등됨.
> 랩탑 사용자가 FSx 없이 직접 gateway를 호출해야 하는 경우, 또는 IAM Identity Center 기반 통합 인증이 필요한 경우 검토.

Permission-set 모델 요약:
- IAM Identity Center permission set (`BedrockGatewayUser`) 생성
- 사용자가 `aws sso login --profile bedrock-gw`로 인증
- `arn:aws:sts::<acct>:assumed-role/AWSReservedSSO_<PermSet>_<hash>/<username>` 형태의 ARN
- Session name = SSO username (안정적)
- 정규화 후보: `<account>#<session-name>` (이전 Candidate D)

Per-user role 대비 단점:
- FSx 사용자에게 추가 SSO login 절차 필요
- `~/.aws/sso/cache/` 보안 관리 필요
- FSx credential setup 별도 승인 게이트 필요 (R11)
- 기존 `[default]` profile과 충돌 가능

Per-user role 대비 장점:
- IAM Identity Center 중앙 관리 (사용자 추가/제거 용이)
- 랩탑에서 EC2 instance metadata 없이도 사용 가능
- Permission set 단위로 권한 일괄 관리 가능

**현재 상태**: 구현 계획 없음. Per-user role 모델이 안정화된 후 필요 시 병렬 지원 검토.

## Remaining Approval Blockers

1. **Task 3 (Discovery)**: 실제 requestContext.identity 캡처 전까지 principal_id 정규화 로직 확정 불가. FSx(per-user role) + 랩탑 두 환경 모두 캡처 필수.
2. **SCP 적용 승인**: 조직 수준 SCP 적용 가능 여부 확인 필요
3. **backend-admin IAM role 확장**: DynamoDB + SES 권한 추가 승인
4. **Per-user role에 execute-api:Invoke 권한 추가**: 기존 BedrockUser-* role의 IAM policy 수정 승인 필요. 기존 role의 Bedrock 직접 호출 권한은 gateway 전환 후 제거 대상.

## Resolved Blockers (이번 리뷰에서 해결)

1. **IaC 도구 선택**: Terraform 확정. SAM/CDK 제거. Ansible은 기존 컨테이너/호스트 운영에만 사용.
2. **InvokeModel/InvokeModelWithResponseStream**: v2로 명시적 연기. v1은 Converse only.
3. **DailyUsage 쿼터 의미론**: Principal 글로벌 (모델별 아님). DailyUsage는 모델별 기록, 쿼터 비교 시 합산.
4. **Phase 2 거버넌스 아티팩트**: docs/ai/ 하위에 plan.md, risk_register.md, validation_plan.md, runbook.md, rollback.md, todo.md 생성 완료.

## Q1-Q6 Resolution (2026-03-18)

> Phase 0 prerequisite decisions. All approved by operator on 2026-03-18.
> Full rationale: `docs/ai/decision-resolution-q1-q6.md`

| # | Question | Approved Decision |
|---|----------|-------------------|
| Q1 | KRW pricing source | Fixed KRW rates in ModelPricing DynamoDB table, admin-managed. No real-time FX. Lambda has no Redis/FX API dependency. |
| Q2 | Global budget enforcement | Alerting-only for v1. CloudWatch alarm at 80/90/100% of KRW 10M. No GlobalBudget table. Avoids DynamoDB hot key. |
| Q3 | Monthly reset timezone | KST (Asia/Seoul, UTC+9). Korean org, KST-aligned budget cycles. UTC midnight = 09:00 KST — confusing for users/admins. |
| Q4 | Boost duration | End of current month (KST). Aligns with monthly budget cycle. No cross-month overlap. |
| Q5 | Approval action method | Deep link to Admin UI for v1. Signed URL deferred to v2. Already implemented pattern. |
| Q6 | Token counts in MonthlyUsage | Keep `input_tokens` and `output_tokens` alongside `cost_krw`. Enables retroactive cost recalculation. |

### UTC→KST Correction Registry

The following code locations currently use UTC and must be corrected to KST during implementation phases:

| Location | Current | Required | Phase |
|----------|---------|----------|-------|
| `handler.py:check_quota()` ~line 280 | `datetime.now(timezone.utc).strftime("%Y-%m-%d")` | KST month key (`YYYY-MM`) | Phase 2 (Task 2.3) |
| `handler.py:update_daily_usage()` ~line 340 | `datetime.now(timezone.utc).strftime("%Y-%m-%d")` | KST date, function renamed to `update_monthly_usage()` | Phase 2 (Task 2.4) |
| `gateway_approval.py:_end_of_month_ttl()` | `datetime.now(timezone.utc)` | KST EOM: last day of month 23:59:59 KST | Phase 4 (Task 4.4) |
| MonthlyUsage PK `YYYY-MM` | Derived from UTC | Derived from KST | Phase 2 (Task 2.3/2.4) |

### KST Implementation Pattern (reference for Phase 2-4)

```python
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))

def current_month_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m")

def end_of_month_ttl_kst() -> int:
    now = datetime.now(KST)
    _, last_day = monthrange(now.year, now.month)
    eom = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=KST)
    return int(eom.timestamp())
```

### Impact on Existing Files

- `gateway_approval.py`: Frozen. One known revision (`_end_of_month_ttl()` UTC→KST) deferred to Phase 4.
- `handler.py`: Frozen for quota/approval logic. Phase 2-3 rewrites pending.
- `dynamodb.tf`: Frozen. Phase 1 schema changes pending (ModelPricing table, DailyUsage→MonthlyUsage).
- Phase execution order: Phase 1 (data model) → Phase 2 (Lambda) → Phase 3 (approval ladder) → Phase 4 (admin API). Each requires separate approval.
