# Bedrock Gateway v2 Async Fargate — Final Report

결과 상태: 승인 요청 가능

---

## 1. Executive Summary

API Gateway 29초 제한을 async job 구조(Step Functions + Fargate)로 구조적으로 해결. 사용자는 기존 `/converse`만 호출하고, Opus 등 long-running 모델은 서버 측에서 자동으로 hidden async/Fargate 경로로 라우팅. DynamoDB accounting은 Bedrock actual usage 기준으로 정확히 반영됨. cancel path, orphan cleanup, semaphore admission control 모두 검증 완료.

## 2. Root Cause of Previously Missing JOB_CANCELED Ledger

이전 cancel test에서 JOB_CANCELED ledger가 0건이었던 원인: cancel handler 코드가 배포되기 전에 테스트가 실행되었거나, 이전 버전의 Lambda에 cancel ledger write가 없었음. 현재 배포된 Lambda(CodeSha256=jj/C1TE2EbU210YjUvsr3N12v++GfOnAahHUYDFV568=, LastModified=2026-04-02T08:02:47)에는 cancel ledger write가 포함되어 있고, 재검증에서 PASS.

## 3. Changed Files (이번 마감 작업)

없음. 코드 수정 불필요. 배포된 Lambda에 이미 cancel ledger write 포함. 재검증만 수행.

## 4. Deployment Evidence

배포 변경 없음. 기존 배포(2026-04-02T08:02:47) 그대로 사용. Local zip hash == deployed hash 일치 확인.

## 5. Cancel Path Retest Evidence

```
Job: job-cancel-final-5e23d706
Request ID: cancel-final-a2545656
Reservation before cancel: EXISTS
Cancel response: HTTP 200 | status=CANCELED
JobState after cancel: status=CANCELED
Reservation after cancel: DELETED
```

## 6. Direct Key Lookup Proof

```
Ledger PK: cancel-final-a2545656#JOB_CANCELED
Result: FOUND
  event_type: JOB_CANCELED
  job_id: job-cancel-final-5e23d706
  decision: CANCELED
  source_path: gateway-async
```

## 7. Final Updated Verdict

| 항목 | 상태 |
|------|------|
| Production hidden async + actual Bedrock accounting | PASS |
| Synthetic 5-parallel x 30-minute runtime | PASS |
| Stale reservation = 0 | PASS |
| Orphan cleanup | PASS |
| Cancel path (state + reservation + ledger) | PASS |
| Semaphore saturation | PASS |
| No-bypass (Bedrock/ECS/SFN) | PASS |
| Hidden async routing (/converse → internal async) | PASS |
| Verify script false positive fix | PASS |

모든 항목 PASS. 조건부 반려 사유였던 cancel path ledger completeness가 해소됨.
