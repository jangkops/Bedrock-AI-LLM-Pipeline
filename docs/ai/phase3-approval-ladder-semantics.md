# Phase 3: Approval Ladder Semantics — Definitive Specification

> Date: 2026-03-20
> Status: ANALYSIS COMPLETE — requires operator approval before implementation
> Scope: Approval ladder operational semantics only. No code changes.
> Phase 3 implementation remains NOT STARTED and requires separate approval.

---

## 1. Problem Statement

The current design documents describe the approval ladder as "KRW 500,000 fixed increments, hard cap 2M" (Locked Decision #9) but do not explicitly define:
- Whether approval grants a cumulative upper bound or an incremental delta
- How the effective limit formula behaves across multiple approval steps
- Whether approval state is monthly-scoped
- Whether the current data model correctly represents these semantics

This document resolves all ambiguity.

---

## 2. Recommendation: Cumulative Band Model

Approvals grant cumulative upper bounds, not request-time deltas.

### Justification

1. **Operational clarity**: "Your limit is now 1,000,000 KRW" is unambiguous. "You got a +500,000 delta from wherever you were when you asked" is confusing and audit-hostile.
2. **Predictable ladder**: The admin sees exactly 4 possible states per user per month: 500K, 1M, 1.5M, 2M. No fractional or context-dependent states.
3. **Audit simplicity**: Each TemporaryQuotaBoost record means "this principal's effective ceiling moved up by one band." The number of active boosts directly maps to the band index.
4. **No consumption-dependency**: The effective limit does not depend on how much the user had consumed at the time of the request. It depends only on the base limit + number of approved boosts.

### Why not delta-from-request-point

- If a user consumed 450K and requests a boost, a "delta" model could mean the new limit is 450K + 500K = 950K. This is confusing — the user's effective ceiling depends on when they asked, not on a predictable band.
- Two users with the same number of approvals could have different effective limits. This is operationally untestable and audit-unfriendly.
- The current code (`_get_effective_limit` in both `handler.py` and `gateway_approval.py`) already implements cumulative semantics: `base + sum(boosts)`. Delta semantics would require tracking consumption-at-request-time, which neither the data model nor the code supports.

---

## 3. Exact Interpretation of the Approval Ladder

### Band Table

| Band | Approvals Granted | Effective Monthly Limit | Active Boosts |
|------|-------------------|------------------------|---------------|
| 0 (default) | 0 | KRW 500,000 | 0 |
| 1 | 1 | KRW 1,000,000 | 1 × 500K |
| 2 | 2 | KRW 1,500,000 | 2 × 500K |
| 3 (hard cap) | 3 | KRW 2,000,000 | 3 × 500K |

### Effective Limit Formula

```
effective_limit = min(
    policy.monthly_cost_limit_krw + sum(active_boost.extra_cost_krw for each active boost),
    policy.max_monthly_cost_limit_krw
)
```

Where:
- `policy.monthly_cost_limit_krw` = 500,000 (default base)
- `policy.max_monthly_cost_limit_krw` = 2,000,000 (hard cap)
- Each active boost has `extra_cost_krw` = 500,000
- "Active" = `boost.ttl > current_epoch`

### Worked Examples

**Example 1: User at band 0, first approval**
- Base: 500,000
- Active boosts: 0
- Effective limit: 500,000
- After approval: 1 boost created (extra_cost_krw=500,000, TTL=EOM KST)
- New effective: min(500,000 + 500,000, 2,000,000) = 1,000,000

**Example 2: User at band 1, second approval**
- Base: 500,000
- Active boosts: 1 × 500,000
- Effective limit: 1,000,000
- After approval: 2nd boost created
- New effective: min(500,000 + 1,000,000, 2,000,000) = 1,500,000

**Example 3: User at band 2, third approval**
- Base: 500,000
- Active boosts: 2 × 500,000
- Effective limit: 1,500,000
- After approval: 3rd boost created
- New effective: min(500,000 + 1,500,000, 2,000,000) = 2,000,000

**Example 4: User at band 3, requests 4th approval**
- Base: 500,000
- Active boosts: 3 × 500,000
- Effective limit: 2,000,000
- Pre-validation: 2,000,000 + 500,000 = 2,500,000 > 2,000,000 → REJECT
- Hard cap enforced. No 4th boost possible.

**Example 5: User consumed 450K of 500K, requests first approval**
- Consumption is irrelevant to the approval decision
- Pre-validation: effective_limit (500K) + 500K = 1,000K ≤ 2,000K → ALLOW
- New effective: 1,000,000
- User now has 550K remaining (1,000K - 450K)

---

## 4. Monthly Scope and Reset

### Boost TTL = End of Current Month (KST)

- Each TemporaryQuotaBoost has `ttl` = end of current month in KST (Locked Decision Q4)
- When the month rolls over (KST midnight on the 1st), all boosts from the previous month expire via DynamoDB TTL
- The user starts the new month at band 0 (base limit only)
- If the user needs elevated limits again, they must request new approvals

### Monthly Reset Behavior

| Event | Effect |
|-------|--------|
| Month boundary (KST) | All boosts expire. MonthlyUsage resets (new PK). User returns to band 0. |
| Boost approved mid-month | Boost active until EOM KST. Effective limit increases immediately. |
| Boost approved on last day | Boost expires at EOM KST (same day 23:59:59). Minimal utility but operationally correct. |

### No Cross-Month Carryover

- Boosts do not carry over to the next month
- Approval history (ApprovalRequest records) persists for audit but does not affect next month's effective limit
- Each month is independent

---

## 5. Current Data Model Assessment

### What exists and is correct

| Component | Status | Notes |
|-----------|--------|-------|
| `PrincipalPolicy.monthly_cost_limit_krw` | ✅ Correct | Base limit (default 500K) |
| `PrincipalPolicy.max_monthly_cost_limit_krw` | ✅ Correct | Hard cap (2M) |
| `TemporaryQuotaBoost` table (PK: `principal_id`, SK: `boost_id`) | ✅ Correct | Each boost = one band increment |
| `TemporaryQuotaBoost.extra_cost_krw` | ✅ Correct | Fixed 500K per boost |
| `TemporaryQuotaBoost.ttl` | ⚠️ Partially correct | `gateway_approval.py` uses UTC EOM. Must be KST EOM (Q3/Q4). Known revision, deferred to Phase 3. |
| `handler.py:check_quota()` effective limit calc | ✅ Correct | `base + sum(active boosts)`, capped at `max_monthly_cost_limit_krw` |
| `gateway_approval.py:_get_effective_limit()` | ✅ Correct | Same formula as handler |
| `gateway_approval.py:approve_request()` hard cap check | ✅ Correct | `current_effective + 500K ≤ 2M` |
| `ApprovalPendingLock` (one pending per principal) | ✅ Correct | Race-safe, prevents duplicate concurrent requests |

### What is ambiguous or needs correction

| Issue | Severity | Required Fix | Phase |
|-------|----------|-------------|-------|
| `_end_of_month_ttl()` uses UTC, not KST | Medium | Change `timezone.utc` → `KST` | Phase 3 |
| `handle_approval_request()` in Lambda does not validate `reason` non-empty | Medium | Add reason validation | Phase 3 |
| `handle_approval_request()` in Lambda does not validate increment amount | Medium | Add `requested_increment_krw == 500000` validation | Phase 3 |
| `handle_approval_request()` in Lambda does not check hard cap pre-validation | Medium | Add `effective + 500K ≤ 2M` check before creating ApprovalRequest | Phase 3 |
| SES email in `gateway_approval.py` says "end of current month (UTC)" | Low | Change to "(KST)" | Phase 3 |
| No explicit "band index" stored | Low | Not needed — band is derivable from count of active boosts. Adding it would create a consistency risk. |

### Conclusion: Data model is correct

The current data model correctly supports cumulative band semantics. Each TemporaryQuotaBoost record represents one 500K band increment. The effective limit formula (`base + sum(active boosts)`, capped at hard cap) is already implemented in both the Lambda handler and the admin API. The number of active boosts directly corresponds to the band index.

No new tables, no new fields, no schema changes required for the approval ladder semantics. The only corrections needed are:
1. UTC → KST in `_end_of_month_ttl()` (Phase 3, known)
2. Input validation in Lambda's `handle_approval_request()` (Phase 3)
3. Hard cap pre-validation in Lambda's `handle_approval_request()` (Phase 3)

### Optional Clarity Fields Assessment

The operator asked whether adding explicit fields like `approved_upper_bound_krw` or `approval_band_index` would improve operational clarity.

**Assessment: Not recommended. Sufficient-without-ambiguity as-is.**

| Candidate Field | Benefit | Risk | Verdict |
|----------------|---------|------|---------|
| `approved_upper_bound_krw` (on TemporaryQuotaBoost) | Makes the post-approval ceiling explicit per boost record | Creates a consistency risk: if `monthly_cost_limit_krw` changes, the stored upper bound becomes stale. The derived value (`base + sum(boosts)`) is always correct. | **Skip** — derivable, and storing it creates a new consistency invariant to maintain |
| `approval_band_index` (on TemporaryQuotaBoost or PrincipalPolicy) | Makes the current band (0/1/2/3) explicit | Same staleness risk. Also, band index is trivially derivable: `count(active_boosts)`. Adding it means two sources of truth for the same fact. | **Skip** — `count(active_boosts)` is the canonical band index |
| `effective_limit_at_approval_time` (on ApprovalRequest) | Audit trail: what was the effective limit when the approval was granted | Read-only audit field, no consistency risk. Useful for post-hoc review. | **Consider for Phase 3** — low risk, audit value. But not required for runtime correctness. |

The current model is functionally sufficient and operationally unambiguous because:
1. The band is always derivable from `count(active_boosts_where_ttl > now)`
2. The effective limit is always derivable from `base + sum(active_boosts.extra_cost_krw)`
3. Both Lambda and admin API already implement this derivation identically
4. There are exactly 4 possible effective-limit states (500K, 1M, 1.5M, 2M) — no fractional or ambiguous states exist

### Honest Assessment: Runtime Sufficient, Slightly Ambiguous Operationally

The current model is runtime-correct and functionally sufficient. However, from a pure operational/audit perspective, there is slight ambiguity:

- An operator looking at a `TemporaryQuotaBoost` record sees `extra_cost_krw: 500000` but cannot immediately tell what the resulting effective ceiling was without also querying the base policy and counting all active boosts.
- The `ApprovalRequest` record does not capture the effective limit at the time of approval, so post-hoc audit requires reconstructing state.

This ambiguity is acceptable for v1 because:
- The band space is small (4 states) and deterministic
- Both code paths derive the same value the same way
- Adding explicit fields (`approved_upper_bound_krw`, `approval_band_index`) would create consistency risks that outweigh the audit convenience

If operational audit requirements increase in v2, consider adding `effective_limit_at_approval_time` as a read-only audit field on `ApprovalRequest` — low risk, no consistency hazard.

---

## 6. Operationally Testable Invariants

These invariants must hold at all times:

1. `effective_limit = min(base + sum(active_boosts), hard_cap)`
2. `0 ≤ count(active_boosts) ≤ 3` (since 4 × 500K would exceed 2M hard cap)
3. Each boost has `extra_cost_krw == 500,000` (fixed increment, no partial boosts)
4. `effective_limit ∈ {500000, 1000000, 1500000, 2000000}` (exactly 4 possible values)
5. All boost TTLs for a given month expire at the same EOM boundary (KST)
6. At month rollover, `count(active_boosts) == 0` (all expired)
7. `ApprovalPendingLock` prevents more than one pending request per principal at any time

---

## 7. Summary of Answers to Operator Questions

| # | Question | Answer |
|---|----------|--------|
| 1 | What does an approval mean? | Approval grants the next cumulative upper bound. It creates one TemporaryQuotaBoost (500K), raising the effective ceiling by one band. |
| 2 | If user consumed 500K and gets approval, new limit? | 1,000,000 KRW total for that month. Consumption is irrelevant to the approval decision. |
| 3 | How does the ladder behave? | 500K → 1M → 1.5M → 2M. Each step = one approval = one boost record. Hard cap at 2M. |
| 4 | Is approval state monthly-scoped? | Yes. Boosts have TTL = EOM (KST). All expire at month boundary. User starts fresh each month. |
| 5 | Data model needed? | Already correct. `TemporaryQuotaBoost` with `extra_cost_krw=500000` and EOM TTL. No new tables or fields. Only correction: UTC → KST in TTL calculation (Phase 3). |

---

## Boundary Statement

This document is a governance/planning artifact only. No runtime code, IaC, deployment configs, or infrastructure were modified.
Phase 3 implementation requires separate explicit approval.
