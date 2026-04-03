# Phase 1 Post-Apply Validation Package

> Generated: 2026-03-18. Run these commands after Phase 1 `terraform apply` to confirm correct deployment.

## 1. Terraform Convergence Check

```bash
cd infra/bedrock-gateway
terraform workspace select dev
terraform plan -var-file=env/dev.tfvars
```

**Expected good output:**
```
No changes. Your infrastructure matches the configuration.
```

**Red flag:** Any planned changes (especially destroys or Lambda modifications). If plan shows changes, STOP and investigate before proceeding.

## 2. DynamoDB Table Existence

```bash
# New tables (Phase 1 additive)
aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2 --query 'Table.{Status:TableStatus,KeySchema:KeySchema}'
aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --query 'Table.{Status:TableStatus,KeySchema:KeySchema}'

# Existing table (must still exist)
aws dynamodb describe-table --table-name bedrock-gw-dev-us-west-2-daily-usage --region us-west-2 --query 'Table.TableStatus'
```

**Expected good output for monthly_usage:**
```json
{
    "Status": "ACTIVE",
    "KeySchema": [
        { "AttributeName": "principal_id_month", "KeyType": "HASH" },
        { "AttributeName": "model_id", "KeyType": "RANGE" }
    ]
}
```

**Expected good output for model_pricing:**
```json
{
    "Status": "ACTIVE",
    "KeySchema": [
        { "AttributeName": "model_id", "KeyType": "HASH" }
    ]
}
```

**Expected good output for daily_usage:**
```
"ACTIVE"
```

**Red flag:** Any table returning `ResourceNotFoundException`. If `daily_usage` is missing, STOP — something destroyed it.

## 3. Lambda Environment Variables (No Runtime Cutover)

```bash
aws lambda get-function-configuration --function-name bedrock-gw-dev-gateway --region us-west-2 \
  --query 'Environment.Variables' | python3 -c "
import sys, json
vars = json.load(sys.stdin)
print('TABLE_DAILY_USAGE present:', 'TABLE_DAILY_USAGE' in vars)
print('TABLE_MONTHLY_USAGE absent:', 'TABLE_MONTHLY_USAGE' not in vars)
print('TABLE_MODEL_PRICING absent:', 'TABLE_MODEL_PRICING' not in vars)
print('DISCOVERY_MODE:', vars.get('DISCOVERY_MODE', 'NOT SET'))
"
```

**Expected good output:**
```
TABLE_DAILY_USAGE present: True
TABLE_MONTHLY_USAGE absent: True
TABLE_MODEL_PRICING absent: True
DISCOVERY_MODE: false
```

**Red flag:** If `TABLE_MONTHLY_USAGE` or `TABLE_MODEL_PRICING` are present, a runtime cutover happened prematurely. STOP.

## 4. IAM Policy Verification

```bash
aws iam get-role-policy --role-name bedrock-gw-dev-lambda-exec --policy-name bedrock-gw-dev-dynamodb \
  | python3 -c "
import sys, json
doc = json.load(sys.stdin)['PolicyDocument']
stmts = {s['Sid']: s for s in doc['Statement']}
print('ModelPricingReadOnly statement exists:', 'ModelPricingReadOnly' in stmts)
non_ledger = stmts.get('DynamoDBReadWriteNonLedger', {})
resources = str(non_ledger.get('Resource', ''))
print('monthly-usage in NonLedger:', 'monthly-usage' in resources)
print('daily-usage in NonLedger:', 'daily-usage' in resources)
"
```

**Expected good output:**
```
ModelPricingReadOnly statement exists: True
monthly-usage in NonLedger: True
daily-usage in NonLedger: True
```

**Red flag:** Missing `ModelPricingReadOnly` statement or missing `monthly-usage` from NonLedger resources.

## 5. New Tables Are Empty (No Premature Data)

```bash
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-monthly-usage --region us-west-2 --select COUNT
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --select COUNT
```

**Expected good output:**
```json
{ "Count": 0, "ScannedCount": 0 }
```

Tables should be empty until seed data is loaded (model_pricing) and Phase 2 runtime starts writing (monthly_usage).

## 6. Existing Runtime Still Functional

```bash
# Quick smoke test — invoke the gateway endpoint (if seeded with PrincipalPolicy)
awscurl --service execute-api --region us-west-2 \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"modelId": "anthropic.claude-3-haiku-20240307-v1:0", "messages": [{"role": "user", "content": [{"text": "Hello"}]}]}' \
  "$(terraform output -raw api_gateway_invoke_url)/converse"
```

If PrincipalPolicy is seeded, expect a valid Bedrock response. If not seeded, expect a deny (policy not found) — this is correct behavior.

---

## Summary: Phase 1 Post-Apply Expected State

| Component | Expected State |
|-----------|---------------|
| `monthly_usage` table | ACTIVE, empty, correct key schema (PK: `principal_id_month`, SK: `model_id`) |
| `model_pricing` table | ACTIVE, empty, correct key schema (PK: `model_id`) |
| `daily_usage` table | ACTIVE, existing data intact |
| Lambda env vars | Old-path only (`TABLE_DAILY_USAGE`), no new vars |
| Lambda code | Unchanged (`handler.py` still uses daily quota logic) |
| IAM policy | Updated with `ModelPricingReadOnly` + `monthly-usage` in NonLedger |
| API Gateway | Unchanged |
| Terraform state | Converged (no planned changes) |
