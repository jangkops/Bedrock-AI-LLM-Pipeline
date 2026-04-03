# Phase 5: Portal + Terraform Ops + Cost Verification Plan

## Date: 2026-03-30

## Scope

4 workstreams, ordered by dependency:

### WS1: Portal Daily Breakdown (frontend + backend)
- Add daily KST breakdown API to gateway_usage.py
- Add daily drill-down UI to BedrockGateway.jsx
- Monthly default view preserved, daily expandable per user

### WS2: Team/Admin/User Governance Schema
- Add team_config DynamoDB table or JSON config
- 3 teams: mRNA AI, Small Molecule AI, Computational Biology
- Per-team: admin(s), users, direct_access exceptions
- Terraform manages desired state, portal reads/writes config

### WS3: Direct Access Exception
- Add `gateway_managed: false` field to principal_policy or team_config
- Exception users bypass quota enforcement but are monitored
- Portal shows exception status clearly

### WS4: Cost Verification (≤100K KRW)
- Real model calls across providers
- DynamoDB/portal/band state verification
- Reconciliation

## Current State

- Portal: monthly view only, no daily breakdown
- Teams: no team structure, single approver hardcoded
- Direct access: EXCEPTION_USERS dict hardcoded in gateway_usage.py
- gateway_policy_bp: exists but NOT registered in app.py
- Cost engine: PASS (20 models, 7 providers, diff=0)

## Architecture Decision

Portal → DynamoDB (team_config table) → backend reads → portal displays.
Terraform manages principal_policy items via `aws_dynamodb_table_item` or seed script.
Portal admin UI writes to team_config DynamoDB table directly (operational data, not infrastructure).
This avoids Terraform drift because:
- Infrastructure (tables, Lambda, API GW) = Terraform
- Operational data (policies, team membership, approvals) = DynamoDB via portal/API
- This is the standard pattern: Terraform manages schema, application manages data

## Approval Required

This plan involves:
1. New backend API endpoints (daily breakdown, team management)
2. Frontend changes (daily drill-down, team admin UI)
3. Possible new DynamoDB table (team_config)
4. Real cost incurrence (≤100K KRW)
5. gateway_policy_bp registration in app.py

## Estimated Changes

| Component | Files | Scope |
|-----------|-------|-------|
| Backend | gateway_usage.py, gateway_policy.py, app.py | New daily API, register policy bp |
| Frontend | BedrockGateway.jsx | Daily drill-down, team display |
| Terraform | dynamodb.tf, variables.tf | team_config table (optional) |
| Lambda | handler.py | No changes (cost engine PASS) |
| Docker | docker-compose-fixed.yml | No changes |

## Risk Assessment

- Blast radius: portal UI + backend API only. Lambda/gateway untouched.
- Rollback: revert frontend build + backend container restart
- Cost: ≤100K KRW for verification calls
- Security: admin JWT auth on all new endpoints
