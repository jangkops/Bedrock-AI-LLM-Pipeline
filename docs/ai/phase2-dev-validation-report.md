# Phase 2 Dev Validation Report — Final

> Date: 2026-03-20
> Status: **ALL CRITERIA PASS — Phase 2 dev validation COMPLETE**
> Canonical principal: cgjang (only)
> shlee excluded — deliberate exception, direct Bedrock user
> Approval ladder semantics: `docs/ai/phase3-approval-ladder-semantics.md`

---

## Validation Evidence Summary

| Field | Value |
|-------|-------|
| Endpoint | `https://5l764dh7y9.execute-api.us-west-2.amazonaws.com/v1/converse` |
| Model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| HTTP Status | 200 |
| Decision | ALLOW |
| estimated_cost_krw | 0.0551 |
| remaining_quota.cost_krw | 499999.7796 |
| inputTokens | 13 |
| outputTokens | 5 |
| request_id | `d01542b3-61dc-4e96-a423-583954d031b4` |

---

## C5–C9 Criteria Status

### C5: Smoke test returns `decision: ALLOW` with `estimated_cost_krw`

**PASS.**

Evidence: HTTP 200, `decision: ALLOW`, `estimated_cost_krw: 0.0551` (non-zero, sub-1 KRW correctly preserved — confirms cost-precision fix). `remaining_quota.cost_krw: 499999.7796` (correctly decremented from 500,000 base).

### C6: `monthly_usage` table receives writes after smoke test

**PASS.**

Evidence: `remaining_quota.cost_krw = 499999.7796` in the response. This value is computed by `check_quota()` as `effective_limit - total_cost_krw_from_monthly_usage`. The response showing `500000 - 499999.7796 = 0.2204 KRW` accumulated cost proves `monthly_usage` has been written to and is being read correctly. The 0.2204 KRW total (vs 0.0551 for this single request) is consistent with earlier partially-applied requests during the Decimal-fix debugging cycle — expected and non-problematic.

No additional admin-side monthly_usage query is required. The response-body evidence is sufficient because the remaining_quota value is derived directly from a MonthlyUsage table query inside `check_quota()`. If MonthlyUsage had no writes, remaining_quota would equal exactly 500,000.

### C7: `daily_usage` table receives NO new writes

**PASS.**

Evidence: Admin-side scan returned `Count: 0`, `Items: []`. Phase 2 code calls `update_monthly_usage()`, not `update_daily_usage()`. Confirmed no regression.

### C8: `request_ledger` entries include `estimated_cost_krw`

**PASS.**

Evidence: Admin-side scan shows ledger entry for `request_id = d01542b3-61dc-4e96-a423-583954d031b4` with `decision = ALLOW`, `estimated_cost_krw = 0.0551`, `input_tokens = 13`, `output_tokens = 5`. The Decimal-vs-float ledger defect is confirmed resolved — DynamoDB accepted the Decimal value.

### C9: Lambda logs show no pricing/quota errors

**PASS.**

Evidence: CloudWatch logs for the successful request show `request_received`, `principal_identified`, normal END/REPORT. No `ledger_write_failed`, no `Float types are not supported`, no `pricing_lookup_failed`, no `quota_check_failed`.

---

## Earlier Partial Monthly Usage Note

The `remaining_quota.cost_krw` of 499999.7796 implies 0.2204 KRW total accumulated in `monthly_usage` for cgjang in 2026-03. This is slightly more than the single request's 0.0551 KRW. The difference (0.1653 KRW) is attributable to earlier requests during the debugging cycle where step 9 (`update_monthly_usage`) succeeded but step 11 (ledger write) failed due to the Decimal-vs-float defect. Those earlier requests incremented `monthly_usage` but did not write ledger entries. This is expected behavior — the design accepts that post-call ADD may overshoot (Enforcement Invariant #4 in design.md). The amounts are negligible (< 1 KRW total).

---

## Monthly Usage Final Evidence

| Field | Value |
|-------|-------|
| principal_id_month | `107650139384#BedrockUser-cgjang#2026-03` |
| model_id | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| cost_krw | 0.2204 |
| input_tokens | 52 |
| output_tokens | 20 |

This confirms cross-session aggregation is working correctly — multiple requests from the same principal accumulate into a single monthly record per model.

---

## Fix Chain Summary

| # | Defect | Fix | Deployed |
|---|--------|-----|----------|
| 1 | `int(Decimal("0.0551"))` → 0 (sub-1 KRW truncation) | `int()` → `float()` at 5 locations in handler.py | 2026-03-20 |
| 2 | `float(estimated_cost_krw)` in ledger_entry → DynamoDB rejects float | Keep raw `Decimal` in ledger_entry; `float()` only in response_body | 2026-03-20 |

Both fixes deployed in a single `terraform apply`. Lambda function + alias updated. No DynamoDB, API Gateway, or IAM changes.

---

## Conclusion

Phase 2 dev validation is COMPLETE. All 9 criteria (C1–C9) pass. The KRW cost-based monthly quota pipeline is operational: pricing lookup, cost estimation, monthly usage accumulation, ledger persistence, and remaining quota calculation all function correctly.

Next steps:
- Phase 3 (approval ladder rewrite) requires separate approval. Semantics documented in `docs/ai/phase3-approval-ladder-semantics.md`.
- Phase 4 (admin API) frozen until Phase 3 complete.
- `daily_usage` table removal deferred to post-Phase-3 cleanup.
