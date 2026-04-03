# Phase 2: 30-Minute Parallel Verification Runbook

> Execute after Phase 1 (code deployment) is complete.
> Requires: SSO admin session, ~35 minutes wall clock.
> This runbook covers the SYNTHETIC RUNTIME PROOF only.
> Actual Bedrock accounting proof was completed in Phase 1 (see final report).

## Prerequisites

```bash
aws sso login --profile virginia-sso
export AWS_PROFILE=virginia-sso
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
```

## Step 1: Reset Semaphore

```bash
python3 -c "
import boto3
ddb = boto3.resource('dynamodb', region_name='us-west-2')
sem = ddb.Table('bedrock-gw-dev-us-west-2-concurrency-semaphore')
for i in range(5):
    sem.update_item(Key={'slot_id': f'slot-{i}'}, UpdateExpression='SET job_id = :e, acquired_at = :e', ExpressionAttributeValues={':e': ''})
print('Semaphore reset: 0/5 occupied')
"
```

## Step 2: Start 5 Parallel 30-Minute Synthetic Jobs

```bash
python3 account-portal/backend-admin/data/start-5-parallel-30min.py
```

Save the output. It prints 5 job IDs like:
```
job-30m-0-a1b2c3d4
job-30m-1-e5f6g7h8
job-30m-2-i9j0k1l2
job-30m-3-m3n4o5p6
job-30m-4-q7r8s9t0
```

## Step 3: Monitor (Every 5 Minutes)

```bash
python3 account-portal/backend-admin/data/check-parallel-status.py \
  job-30m-0-XXXXXXXX job-30m-1-XXXXXXXX job-30m-2-XXXXXXXX job-30m-3-XXXXXXXX job-30m-4-XXXXXXXX
```

Replace with actual job IDs from Step 2.

Expected progression: ACCEPTED → RUNNING → SUCCEEDED (after ~1830s).

## Step 4: Verify Results (After 32 Minutes)

```bash
python3 account-portal/backend-admin/data/verify-30min-results.py \
  job-30m-0-XXXXXXXX job-30m-1-XXXXXXXX job-30m-2-XXXXXXXX job-30m-3-XXXXXXXX job-30m-4-XXXXXXXX
```

Expected output: `VERDICT: PASS`

## Step 5: Cancel Path Test

```bash
python3 account-portal/backend-admin/data/test-cancel-path.py
```

Expected output: `VERDICT: PASS`

## Step 6: Orphan Cleanup Test

```bash
python3 account-portal/backend-admin/data/test-orphan-cleanup.py
```

Expected output: `VERDICT: PASS`

## PASS/FAIL Criteria

PASS if ALL:
- 5 jobs SUCCEEDED
- 0 stale `__reserved__` entries
- Ledger has REQUEST_ACCEPTED + TASK_STARTED + TASK_COMPLETED for each
- Cancel test PASS
- Orphan cleanup test PASS

FAIL if ANY:
- Job stuck after 35 minutes
- Stale reservation pollutes quota
- Missing ledger events
- Cancel doesn't release reservation

## Important Notes

- Synthetic path bypasses Lambda admission control (no semaphore acquisition).
  This is expected — the purpose is runtime duration proof, not admission proof.
- Semaphore/admission was verified separately via production `/converse-jobs` path.
- Accounting values in synthetic path use mock tokens (50000 input, 2000 output).
  Actual Bedrock accounting accuracy was proven separately with real model calls.
