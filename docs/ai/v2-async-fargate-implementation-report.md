# v2 Async Fargate Implementation Report

> Date: 2026-04-02
> Status: IMPLEMENTATION COMPLETE — PENDING DEPLOYMENT

## Executive Summary

API Gateway 29초 타임아웃 문제를 async job 구조로 구조적으로 해결. 장시간 Bedrock 호출(30분~1시간)은 Step Functions + Fargate로 처리. 기존 sync short path는 유지. 보안 모델(DenyDirectBedrockInference, Fargate private only, user role deny on ECS/SFN) 강화.

## What Changed

### 1. Spec Documents (3개)
- `requirements.md`: Req 1 수정 (sole Lambda invocation → sole control plane entry point), Req 4/6/7/10 확장, Req 16-20 신규 (Fargate isolation, concurrency, retry, payload storage, operator controls)
- `design.md`: async architecture 재작성, Step Functions + Fargate flow, JobState/Semaphore 데이터 모델, 동시성/보안/retry/pricing/logging 설계
- `tasks.md`: Phase 8-16 추가 (async implementation phases)

### 2. Terraform IaC (6개 파일)
- `dynamodb.tf`: job-state, concurrency-semaphore 테이블 추가
- `ecs.tf`: ECS cluster, Fargate task definition, task/execution roles
- `stepfunctions.tf`: Standard state machine (job orchestrator)
- `s3.tf`: payload/result 저장 버킷
- `lambda.tf`: 새 env vars (TABLE_JOB_STATE, TABLE_CONCURRENCY_SEMAPHORE, PAYLOAD_BUCKET, SFN_STATE_MACHINE_ARN)
- `iam.tf`: Lambda에 SFN StartExecution + S3 + 새 DynamoDB 테이블 권한 추가

### 3. Lambda Handler
- `handler.py`: POST /converse-jobs (job submit), GET /converse-jobs/{jobId} (status polling) 엔드포인트 추가
- 기존 /converse, /quota/status, /approval/request, /longrun/* 모두 유지

### 4. Fargate Worker
- `worker/main.py`: Bedrock Converse 호출 + retry/backoff + cost settlement + ledger events
- `worker/Dockerfile`: Python 3.12 slim + boto3

## Architecture Resolution

### 이전 모순
- "Gateway Lambda is the sole Bedrock invocation path" vs Fargate가 Bedrock 호출

### 해결
- "외부 사용자의 유일한 통제 진입점은 gateway control plane (API Gateway + Lambda)"
- "실제 Bedrock invocation은 승인된 내부 실행 주체(Lambda exec role / Fargate task role)만 수행"
- 사용자 role은 direct Bedrock, direct ECS, direct Step Functions 모두 차단

## Deployment Checklist

1. ECR repository 생성: `bedrock-gw-dev-worker`
2. Docker image build & push
3. VPC private subnet IDs + security group IDs를 tfvars에 추가
4. `terraform apply` (SSO admin)
5. Semaphore 초기 슬롯 seed (slot-0 ~ slot-4)
6. `__gateway_config__`에 `async_jobs_enabled: true` 설정

## Remaining Items

- API Gateway timeout Service Quotas 승인 대기 (29s → 900s)
- ECR repository 생성 + Docker image build/push
- VPC subnet/SG 설정 확인
- User role에 ECS/SFN deny policy 추가
- 실제 long-running 테스트 (Fargate 배포 후)
- Portal async job 표시 UI

## Rollback

- Feature flag: `async_jobs_enabled: false` → async 경로 비활성화
- Sync /converse 경로는 항상 사용 가능
- 새 DynamoDB 테이블/S3/ECS/SFN은 독립적 — 삭제해도 기존 기능 영향 없음
