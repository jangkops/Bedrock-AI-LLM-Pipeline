# Discovery → Dev Rollout Gap Analysis

> Date: 2026-03-18
> Scope: Single-user (cgjang) dev rollout only
> Excluded: admin UI expansion, multi-user validation, prod rollout, architecture redesign
> Workspace strategy: Fresh `dev` workspace (separate state from `discovery`)

## 1. Current State

**Discovery deployment** (Terraform workspace `discovery`):
- API ID: `ugpt5xi8b7`, stage `v1`, us-west-2
- `DISCOVERY_MODE=true` — Lambda returns raw identity probe, skips all enforcement
- `ENVIRONMENT=discovery`
- `normalize_principal_id()` Candidate F live-verified: `107650139384#BedrockUser-cgjang`
- DynamoDB tables: `bedrock-gw-discovery-us-west-2-*` (8 tables, empty business data)
- 11 unit tests pass. Discovery Lambda redeployed 2026-03-17.

**Lambda code** (`handler.py`, 788 lines):
- Full inference pipeline wired: identity → idempotency → policy → model → quota → bedrock → usage → ledger → session
- Discovery mode is a clean early-return gate at line ~620: `if DISCOVERY_MODE: return handle_discovery(request_context)`
- When `DISCOVERY_MODE=false`, the entire enforcement pipeline executes
- No code changes needed for dev rollout

**IAM permissions** (`iam.tf`):
- Bedrock: `bedrock:Converse` only — correct for v1 (handler uses `bedrock_runtime.converse()`)
- DynamoDB: full CRUD on 7 tables, PutItem-only on RequestLedger, explicit Deny on RequestLedger UpdateItem/DeleteItem
- SES: SendEmail, SendRawEmail
- CloudWatch: via AWSLambdaBasicExecutionRole managed policy

## 2. Gap Analysis: Discovery → Dev

### MUST-FIX before dev rollout

| # | Gap | Current | Required | Fix |
|---|-----|---------|----------|-----|
| G1 | `discovery_mode` in `dev.tfvars` | ~~`true`~~ | `false` | ~~Update `env/dev.tfvars` line 5~~ **DONE (2026-03-18)** |
| G2 | SES email placeholders | `REPLACE-bedrock-gw@example.com`, `REPLACE-admin-group@example.com` | Real values OR documented as partial-function | Documented as partial-function (2026-03-18). Core enforcement proceeds. |
| G3 | Terraform workspace | Only `discovery` exists | Fresh `dev` workspace with separate state | `terraform workspace new dev` |
| G4 | PrincipalPolicy seed data | Empty tables | At least 1 PrincipalPolicy for cgjang | DynamoDB PutItem after deploy |
| G5 | `execute-api:Invoke` on dev API GW | cgjang role has permission for discovery API GW ARN only | Add permission for dev API GW ARN | IAM policy update on `BedrockUser-cgjang` role |

### CAN BE DEFERRED (not blocking dev rollout)

| # | Item | Reason |
|---|------|--------|
| D1 | C2/C3/C5 discovery captures | Candidate F structurally sound, single-user live-verified, unit-tested |
| D2 | Admin UI (Tasks 11-13) | Dev rollout validates core Lambda pipeline only |
| D3 | SCP for direct Bedrock deny (Task 2) | IAM deny is interim strategy, separate approval track |
| D4 | Multi-user PrincipalPolicy seeding | Single-user scope |
| D5 | Discovery stack teardown | Keep temporarily per operator preference |
| D6 | Prod deployment | Separate approval gate |
| D7 | WAF / custom domain | v2 scope |
| D8 | Provisioned Concurrency | Optimization, not functional |

## 3. Gap Details

### G1: `discovery_mode` flag

`env/dev.tfvars` line 5 currently reads:
```hcl
discovery_mode = true # Enable for Task 3, disable after discovery
```

Must be changed to:
```hcl
discovery_mode = false
```

When `DISCOVERY_MODE=false` (the `variables.tf` default), the Lambda skips the discovery early-return and executes the full enforcement pipeline. No Lambda code change needed — the env var controls the behavior.

**Recommendation**: Update `env/dev.tfvars` in-place. This file is the dev environment config. The discovery deployment uses `env/discovery.tfvars` (or `-var` overrides) in its own workspace. Changing `dev.tfvars` does not affect the discovery workspace.

### G2: SES email configuration

Current `dev.tfvars`:
```hcl
ses_sender_email    = "REPLACE-bedrock-gw@example.com"
ses_admin_group_email = "REPLACE-admin-group@example.com"
```

The handler handles missing/placeholder SES gracefully:
- `_send_approval_email()` checks `if not SES_SENDER_EMAIL or not SES_ADMIN_GROUP_EMAIL` → logs warning, returns without sending
- ApprovalRequest is still saved to DynamoDB regardless of email outcome (R7 accepted risk)

**Decision (per operator input)**: SES is a required pre-deploy configuration item for real approval-email behavior, but does NOT block core dev rollout. The gateway's identity/quota/principal_id enforcement can proceed. Approval email sending is marked as pending real SES configuration.

**Action**: Either:
- (a) Replace with real SES values before deploy (preferred if available)
- (b) Deploy with placeholders — approval emails will silently not send, but all other functionality works. Document this as a known partial-function gap.

### G3: Fresh `dev` workspace

```bash
cd infra/bedrock-gateway
terraform workspace new dev
terraform plan -var-file=env/dev.tfvars
terraform apply -var-file=env/dev.tfvars
```

This creates entirely separate infrastructure:
- New API Gateway (different API ID from discovery `ugpt5xi8b7`)
- New Lambda function (`bedrock-gw-dev-gateway`) with `DISCOVERY_MODE=false`
- New DynamoDB tables (`bedrock-gw-dev-us-west-2-*`)
- New CloudWatch log groups
- New IAM role (`bedrock-gw-dev-lambda-exec`)

Discovery workspace state is untouched. Both can coexist.

### G4: PrincipalPolicy seed data

The handler's `lookup_principal_policy()` reads these fields from the PrincipalPolicy table:
- `principal_id` (PK, String) — exact match key
- `allowed_models` (List of String) — model IDs permitted
- `daily_input_token_limit` (Number) — global daily input token quota
- `daily_output_token_limit` (Number) — global daily output token quota

Seed item for cgjang:
```bash
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --item '{
    "principal_id": {"S": "107650139384#BedrockUser-cgjang"},
    "allowed_models": {"L": [
      {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
      {"S": "anthropic.claude-3-haiku-20240307-v1:0"}
    ]},
    "daily_input_token_limit": {"N": "100000"},
    "daily_output_token_limit": {"N": "50000"}
  }' \
  --region us-west-2
```

Without this seed data, every request hits "no policy defined for principal" → 403 deny.

### G5: `execute-api:Invoke` permission for dev API Gateway

The `BedrockUser-cgjang` role currently has `execute-api:Invoke` for the discovery API Gateway ARN. The dev deployment creates a new API Gateway with a different ARN.

After `terraform apply`, get the new API Gateway ID from output:
```bash
DEV_API_ID=$(terraform output -raw api_gateway_id)
```

Then add `execute-api:Invoke` permission for the dev API Gateway ARN to the `BedrockUser-cgjang` role:
```
arn:aws:execute-api:us-west-2:107650139384:${DEV_API_ID}/*
```

This is an IAM policy change on the per-user role, not a Terraform-managed resource. Operator action required.

## 4. Code / Config Delta Summary

### Files that need changes

| File | Change | Type |
|------|--------|------|
| `infra/bedrock-gateway/env/dev.tfvars` | `discovery_mode = true` → `discovery_mode = false` | Config (tfvars) |
| `infra/bedrock-gateway/env/dev.tfvars` | SES emails: replace placeholders OR document as partial-function | Config (tfvars) |

### Files that do NOT need changes

| File | Reason |
|------|--------|
| `infra/bedrock-gateway/lambda/handler.py` | Full pipeline already wired. Discovery gate controlled by env var. |
| `infra/bedrock-gateway/iam.tf` | `bedrock:Converse` is correct for v1. DynamoDB/SES/CW permissions complete. |
| `infra/bedrock-gateway/main.tf` | API Gateway config is environment-agnostic (uses `local.prefix`). |
| `infra/bedrock-gateway/lambda.tf` | Lambda config is environment-agnostic. |
| `infra/bedrock-gateway/dynamodb.tf` | Table definitions are environment-agnostic (uses `local.table_prefix`). |
| `infra/bedrock-gateway/variables.tf` | `discovery_mode` default is already `false`. |
| `infra/bedrock-gateway/locals.tf` | Prefix logic is correct. |
| `infra/bedrock-gateway/logs.tf` | Log group config is environment-agnostic. |
| `infra/bedrock-gateway/outputs.tf` | Output definitions are environment-agnostic. |
| `infra/bedrock-gateway/providers.tf` | Provider config is environment-agnostic. |

### Discovery-only behavior analysis

The only discovery-specific behavior in `handler.py` is:
```python
DISCOVERY_MODE = os.environ.get("DISCOVERY_MODE", "false").lower() == "true"
# ...
if DISCOVERY_MODE:
    return handle_discovery(request_context)
```

When `DISCOVERY_MODE=false` (dev deployment):
- `handle_discovery()` is never called
- No discovery-specific fields appear in responses
- The `handle_discovery` function and `DISCOVERY_MODE` variable remain in code but are inert
- No cleanup needed for dev rollout — dead code removal is optional future housekeeping

## 5. Identity / Enforcement Confirmation

Per operator-confirmed decisions, the dev rollout preserves:

| Principle | Implementation | Status |
|-----------|---------------|--------|
| Per-user assume-role primary identity model | `normalize_principal_id()` extracts `<account>#<role-name>` from assumed-role ARN | Implemented, live-verified |
| Exact-match principal_id enforcement | `lookup_principal_policy()` uses DynamoDB GetItem (inherently exact-match) | Implemented, code-reviewed (E2, E5) |
| Enforcement key = `account_id#full_role_name` | Example: `107650139384#BedrockUser-cgjang` | Live-verified (C1) |
| Full assumed-role ARN NOT used as enforcement key | ARN stored in SessionMetadata as audit/debug metadata only | Implemented, code-reviewed (E3) |
| Fail-closed on normalization failure | Empty principal_id → deny-by-default | Implemented, unit-tested (11 tests) |
| No wildcard/prefix/suffix matching | DynamoDB GetItem + no wildcard logic in handler.py | Code-reviewed (E6) |

## 6. Recommended Rollout Order

### Pre-deploy (operator actions, no Terraform apply)

1. **Update `env/dev.tfvars`**: Set `discovery_mode = false`. Optionally set real SES values.
2. **Review**: `terraform workspace new dev && terraform plan -var-file=env/dev.tfvars` — review the plan output. Should show all-new resources (no modifications to existing infra).

### Deploy (requires explicit approval)

3. **Apply**: `terraform apply -var-file=env/dev.tfvars` — creates dev API Gateway, Lambda, DynamoDB tables, IAM role, log groups.
4. **Record outputs**: `terraform output` — capture `api_gateway_invoke_url`, `api_gateway_id`, `lambda_function_arn`, `lambda_role_arn`.

### Post-deploy (operator actions)

5. **Add `execute-api:Invoke`** to `BedrockUser-cgjang` role for the new dev API Gateway ARN.
6. **Seed PrincipalPolicy** for cgjang (see §3 G4 above).
7. **Smoke test**: SigV4-signed POST to dev API Gateway with a valid Converse request body.

### Validation sequence

8. **Identity verification**: Confirm `principal_id` in Lambda logs matches `107650139384#BedrockUser-cgjang`.
9. **Policy enforcement**: Confirm request with valid model → ALLOW, invalid model → DENY.
10. **Quota enforcement**: Confirm token counting increments in DailyUsage table.
11. **Bedrock invocation**: Confirm actual Bedrock Converse response returned.
12. **Idempotency**: Confirm duplicate `X-Request-Id` returns cached response without re-invoking Bedrock.
13. **Audit trail**: Confirm RequestLedger entry written, SessionMetadata entry written, CloudWatch structured logs emitted.
14. **Deny scenarios**: Confirm no-policy principal → deny, disallowed model → deny, quota exceeded → deny with boost hint.

## 7. Discovery Stack Recommendation

**Keep discovery temporarily.** Rationale:
- Near-zero cost (no traffic, PAY_PER_REQUEST DynamoDB, no provisioned Lambda concurrency)
- Useful as reference/fallback if dev deployment has issues
- Can run deferred C2/C3/C5 captures later if desired
- Tear down after dev is confirmed stable

**Teardown procedure** (when ready):
```bash
cd infra/bedrock-gateway
terraform workspace select discovery
terraform destroy -var-file=env/discovery.tfvars  # or -var environment=discovery -var discovery_mode=true
terraform workspace select dev
terraform workspace delete discovery
```

## 8. Residual Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Cross-user validation deferred (C2/C3/C5) | Medium | Candidate F is structurally sound, unit-tested, single-user live-verified. Accept for single-user dev. |
| SES placeholders → approval emails don't send | Low | ApprovalRequest still saved. Admin can check DynamoDB/UI directly. Non-blocking for core enforcement. |
| Seed data schema mismatch | Low | Schema verified against `lookup_principal_policy()` and `check_quota()` in handler.py. Fields: `principal_id`, `allowed_models`, `daily_input_token_limit`, `daily_output_token_limit`. |
| Dev gateway exposed to all IAM-authenticated callers with execute-api:Invoke | Low | Same as discovery. AWS_IAM auth limits to account principals with explicit permission. |
| Cold start latency | Low | Acceptable for dev. Provisioned Concurrency is a deferred optimization. |

## 9. Scope Confirmation

This analysis covers ONLY:
- Discovery → dev rollout gap for single-user (cgjang)
- Minimum config changes to enable non-discovery operation
- Fresh `dev` Terraform workspace with separate state

Explicitly EXCLUDED:
- Admin UI expansion (Tasks 11-13)
- Multi-user validation or onboarding
- Production deployment
- Architecture redesign
- WAF / custom domain
- CI/CD pipeline
- FSx credential setup for additional users
- IAM Identity Center permission-set model
- Discovery stack teardown (kept temporarily)
