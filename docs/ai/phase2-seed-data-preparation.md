# Phase 2 Seed Data Preparation

> Generated: 2026-03-18. Operator-ready seed commands for `model_pricing` and `principal_policy` tables.
> These commands are SAFE to run after Phase 1 post-apply validation passes.
> They do NOT require Phase 2 approval — they only populate data tables, not runtime code.

## Seed Timing Analysis

| Table | Safe to seed now? | Reason |
|-------|-------------------|--------|
| `model_pricing` | **YES** | Table exists but is unused by current runtime. Seeding is data-only. Phase 2 code will read from it. |
| `principal_policy` (KRW fields) | **YES, with care** | Table already exists and is actively used. Adding new attributes is safe — DynamoDB is schemaless, current `handler.py` ignores unknown attributes. |
| `monthly_usage` | **NO** | Must remain empty until Phase 2 runtime starts writing to it. |

## 1. ModelPricing Seed Data

### Pricing Approach (Q1 Decision)

Per `docs/ai/decision-resolution-q1-q6.md` Q1: Fixed KRW rate stored in `ModelPricing` table. Admin updates periodically. No real-time exchange rate API.

### Current Allowed Models

From `handler.py` (PrincipalPolicy `allowed_models`):

**PRIMARY (ACTIVE 4.5+, verification targets):**
- `anthropic.claude-haiku-4-5-20251001-v1:0` — cheapest 4.5+, primary smoke test target
- `anthropic.claude-sonnet-4-5-20250929-v1:0` — fallback verification target

**LEGACY (retained for reference, non-primary):**
- `anthropic.claude-3-5-sonnet-20241022-v2:0`
- `anthropic.claude-3-haiku-20240307-v1:0`
- `anthropic.claude-sonnet-4-20250514-v1:0`

> **Policy (2026-03-19):** Minimum version 4.5+ for all verification. No LEGACY models as primary smoke-test target.

### AWS Bedrock Pricing (us-west-2, approximate)

| Model | Status | USD Input/1K tokens | USD Output/1K tokens |
|-------|--------|---------------------|----------------------|
| Claude Haiku 4.5 | ACTIVE | $0.001 | $0.005 |
| Claude Sonnet 4.5 | ACTIVE | $0.003 | $0.015 |
| Claude 3.5 Sonnet v2 | LEGACY | $0.003 | $0.015 |
| Claude 3 Haiku | LEGACY | $0.00025 | $0.00125 |
| Claude Sonnet 4 | LEGACY | $0.003 | $0.015 |

> **IMPORTANT**: Operator must verify these prices against current AWS Bedrock pricing page.
> Prices change. These are estimates based on publicly available information.
> **Policy (2026-03-19):** 4.5+ ACTIVE models are primary verification targets. LEGACY models retained for reference only.

### KRW Conversion

Operator must decide the fixed KRW exchange rate. Example using 1 USD = 1,450 KRW:

| Model | Status | KRW Input/1K tokens | KRW Output/1K tokens |
|-------|--------|---------------------|----------------------|
| Claude Haiku 4.5 | ACTIVE | 1.45 | 7.25 |
| Claude Sonnet 4.5 | ACTIVE | 4.35 | 21.75 |
| Claude 3.5 Sonnet v2 | LEGACY | 4.35 | 21.75 |
| Claude 3 Haiku | LEGACY | 0.36 | 1.81 |
| Claude Sonnet 4 | LEGACY | 4.35 | 21.75 |

> Adjust the exchange rate as appropriate. The `exchange_rate.py` in `backend-cost` uses a cached rate from an external API, but per Q1 decision, the gateway uses a fixed admin-set rate.

### Seed Commands

```bash
# --- PRIMARY (ACTIVE 4.5+) ---

# Claude Haiku 4.5 (primary verification target, cheapest 4.5+)
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-haiku-4-5-20251001-v1:0"},
    "input_price_per_1k": {"N": "1.45"},
    "output_price_per_1k": {"N": "7.25"},
    "effective_date": {"S": "2026-03-19"},
    "source_usd_input_per_1k": {"N": "0.001"},
    "source_usd_output_per_1k": {"N": "0.005"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "ACTIVE 4.5+ model. Primary verification target."}
  }' \
  --region us-west-2

# Claude Sonnet 4.5 (fallback verification target)
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-sonnet-4-5-20250929-v1:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-19"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "ACTIVE 4.5+ model. Fallback verification target."}
  }' \
  --region us-west-2

# --- LEGACY (retained for reference, non-primary) ---

# Claude 3.5 Sonnet v2
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# Claude 3 Haiku
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-3-haiku-20240307-v1:0"},
    "input_price_per_1k": {"N": "0.36"},
    "output_price_per_1k": {"N": "1.81"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.00025"},
    "source_usd_output_per_1k": {"N": "0.00125"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2

# Claude Sonnet 4
aws dynamodb put-item \
  --table-name bedrock-gw-dev-us-west-2-model-pricing \
  --item '{
    "model_id": {"S": "anthropic.claude-sonnet-4-20250514-v1:0"},
    "input_price_per_1k": {"N": "4.35"},
    "output_price_per_1k": {"N": "21.75"},
    "effective_date": {"S": "2026-03-18"},
    "source_usd_input_per_1k": {"N": "0.003"},
    "source_usd_output_per_1k": {"N": "0.015"},
    "exchange_rate_krw_per_usd": {"N": "1450"},
    "notes": {"S": "LEGACY. Initial seed. Verify USD prices against AWS Bedrock pricing page."}
  }' \
  --region us-west-2
```

### Verification

```bash
aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2 --select COUNT
# Expected: {"Count": 5, "ScannedCount": 5}

aws dynamodb scan --table-name bedrock-gw-dev-us-west-2-model-pricing --region us-west-2
# Verify all 5 models present with correct pricing (2 ACTIVE 4.5+ + 3 LEGACY)
```

## 2. PrincipalPolicy KRW Field Migration

### Current State

The `principal_policy` table currently stores per-user quota config with token-based fields:
- `principal_id` (PK): `<account_id>#<role_name>` (e.g., `107650139384#BedrockUser-cgjang`)
- `daily_input_token_limit`: integer (current token-based quota)
- `daily_output_token_limit`: integer
- `allowed_models`: list of strings

### New Fields Needed (Phase 2 will read these)

Per design.md:
- `monthly_cost_limit_krw`: number — default 500000 (500K KRW)
- `max_monthly_cost_limit_krw`: number — hard cap 2000000 (2M KRW)

### Safety Analysis

Adding new attributes to existing DynamoDB items is safe because:
1. DynamoDB is schemaless for non-key attributes
2. Current `handler.py` reads specific attributes — it ignores unknown ones
3. The `check_quota()` function reads `daily_token_limit` — it won't see or be affected by `monthly_cost_limit_krw`
4. No runtime code change is involved

### Seed Commands

```bash
# Update cgjang's PrincipalPolicy with KRW fields
# This adds new attributes without affecting existing ones
aws dynamodb update-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --update-expression 'SET monthly_cost_limit_krw = :limit, max_monthly_cost_limit_krw = :max_limit' \
  --expression-attribute-values '{
    ":limit": {"N": "500000"},
    ":max_limit": {"N": "2000000"}
  }' \
  --region us-west-2
```

> For additional users, repeat with their `principal_id`. Default: 500K KRW monthly, 2M KRW hard cap.

### Verification

```bash
aws dynamodb get-item \
  --table-name bedrock-gw-dev-us-west-2-principal-policy \
  --key '{"principal_id": {"S": "107650139384#BedrockUser-cgjang"}}' \
  --region us-west-2

# Expected: item contains both old fields (daily_input_token_limit, etc.)
# AND new fields (monthly_cost_limit_krw: 500000, max_monthly_cost_limit_krw: 2000000)
```

## 3. Seed Data Schema Notes

### ModelPricing Extra Fields

The `source_usd_*` and `exchange_rate_krw_per_usd` fields are not required by Phase 2 runtime code (which only reads `input_price_per_1k` and `output_price_per_1k`). They are included for operator auditability — when reviewing pricing, the admin can see what USD rate and exchange rate produced the KRW values.

### Field Name Alignment

The design.md schema uses `input_price_per_1k` / `output_price_per_1k` (KRW). The seed commands above match this exactly. Phase 2 `lookup_model_pricing()` will read these field names.

## 4. Recommended Execution Order

1. Run Phase 1 post-apply validation (`docs/ai/phase1-post-apply-validation.md`) — confirm tables exist
2. Seed `model_pricing` table (§1 above)
3. Add KRW fields to `principal_policy` (§2 above)
4. Verify both seeds
5. Phase 2 approval and implementation can proceed
