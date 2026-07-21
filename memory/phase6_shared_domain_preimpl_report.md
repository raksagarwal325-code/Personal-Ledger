# Phase 6 — Shared Domain Calculation Consolidation
## Pre-Implementation Report

**Status:** DRAFT — awaiting review. **No code changes have been made.**
**Author:** main_agent
**Date:** 2026-07-21
**Scope:** Refactoring only. Zero user-visible behaviour change, zero API-contract change, zero DB-schema change.

---

## 1. Executive summary

Phase 5 introduced `backend/domain.py` as the paise-safe source-of-truth for the reconciliation engine (invariants 21/21 use it). However, **only `reconcile.py` imports from `domain.py` today.** Every other module — the dashboard endpoint, `compute_order_aggregates`, `compute_purchase`, `_derived_entries_for_party` in Party Ledger v2, `derive_account_balance` in Transfers, `_recompute_payment_aggregates_for_orders`, and the CSV/XLSX exporters — still does ad-hoc `float(x.get("amount") or 0)` sums, inlines its own active-record filters, and rounds with plain Python `round()`.

**Concretely:** `77` inline `float(... .get("amount") ...)` sums and `63` `round()` calls remain across `server.py`, `party_ledger_v2.py`, `transfers.py`, and `party_sync.py` — every one of which is a location where the KPI logic could silently drift away from the reconcile invariants. Phase 6 folds all of these into `domain.py` so that:

- Every KPI shown to Rakshit ties to the exact same helper the reconcile engine uses to prove that KPI is correct.
- Adding a new active-record rule (e.g. `voided=true` on customer payments) becomes a **one-line** change in `domain.py`; today it would require touching ~7 files.
- Fixing a floating-point paise drift in one place fixes it everywhere.

The refactor is **purely internal**. Endpoints return the same numbers to the byte. All existing tests continue to pass unchanged; a new test file pins the "helper equivalence" so that dashboard and reconcile can never diverge again.

---

## 2. Current state — the drift surface

### 2.1 What's already in `domain.py` (Phase 5)

Money primitives:
- `to_paise(x)` / `from_paise(n)` — Decimal, HALF_UP, exact.
- `money_eq(a, b, tol_paise=1)` — 1-paise tolerance.
- `TOLERANCE_PAISE = 1` constant.

Active-record filters (single-sourced):
- `is_order_active(o)` — excludes Cancelled.
- `is_customer_payment_active(p)` — excludes voided / reversed.
- `is_purchase_payment_active(p)` — excludes voided / reversed.
- `is_cash_book_entry_canonical(e)` — excludes legacy_shim, reversed, migrated transfers.
- `is_transfer_active(t)` — excludes reversed.
- `is_account_active(a)` — excludes archived.

Canonical KPI sums (paise-domain integers):
- `sum_received_kpi(cust_pays, cb_entries)`
- `sum_paid_kpi(purchase_pays, cb_entries)`
- `sum_mode_totals(cust_pays, purchase_pays, cb_entries)` — blank/None mode goes in the `""` sentinel bucket.
- `sum_allocations_to_order(cust_pays, oid)`
- `sum_allocations_to_purchase(purchase_pays, pid)`

Consumers today: **`reconcile.py` only.**

### 2.2 Duplicated / drift-prone logic elsewhere

| # | Site | Function/lines | What it computes | Drift risk |
|---|---|---|---|---|
| A1 | `server.py:1258–1475` | `dashboard()` | `received`, `paid`, `modes`, `customer_advances`, `outstanding_receivable`, `outstanding_payable`, `boxes`, `freight`. | **HIGH** — reimplements `sum_received_kpi` + `sum_paid_kpi` + `sum_mode_totals` with plain `float(...)` sums and its own Mongo `{"reversed":{"$ne":True}, ...}` filter. If reconcile's rule (e.g. adding `voided`) evolves, dashboard will not follow. |
| A2 | `server.py:1475–1620` (approx) | `dashboard_breakdown()` | Per-mode/per-party breakdown. | **HIGH** — duplicates the mode bucketing logic. |
| B  | `server.py:380–540` | `compute_order_aggregates(order)` | `operating_revenue`, `net_profit`, `estimated_*`, `unrealized_*`, `total_cost`, `invoice_total`, `margin`, `tax_amount`. | **MEDIUM** — the shipped/estimated ratio math is order-specific but the money-rounding, paise-tolerance, and "recognized-on-shipped-qty" contract belong in `domain.py`. |
| C  | `server.py:545–735` | `_recompute_payment_aggregates_for_orders(order_ids)` | Per-order `total_received`, `outstanding`, `payment_status`. | **HIGH** — this is exactly `sum_allocations_to_order` with the outstanding derived from `invoice_total`. Currently uses `float(a.get("amount") or 0)` sums. |
| D  | `server.py:1226–1258` | `customer_outstanding_orders(name)` | Same as C, at the customer level. | **HIGH** — parallel implementation of C. |
| E  | `server.py:4003–4110` | `compute_purchase(p)` + `_recompute_purchase_payment_aggregates(...)` | Vendor-side of C. | **HIGH** — parallel implementation. |
| F  | `party_ledger_v2.py:227–450` | `_derived_entries_for_party(db, party)` | Party ledger rows derived from orders / cust_pays / purchase_pays / purchases / transfers. Per-row `amount`, `delta_you_pay`. | **HIGH** — its `float(o.get("invoice_total") or 0)`, `float(p.get("amount") or 0)`, active-record filters (`"reversed":{"$ne":True}` inline) all re-derive what reconcile enforces. |
| G  | `party_ledger_v2.py:155–171` | `_resolve_delta(cat, amount, direction)`, `_status_from_balance(bal)` | Sign convention (`You Pay` / `You Receive` / `Settled`) and 50-paise "≈0" threshold. | **LOW** — thresholds diverge from `TOLERANCE_PAISE=1`. Worth harmonising as a domain constant `SETTLED_THRESHOLD_PAISE=50`. |
| H  | `transfers.py:306–398` | `derive_account_balance(db, aid)`, `ff_settlement_delta_from_transfers(db)`, `_apply_transfer_to_account_balance(t, aid)` | Account balance from customer_payments + purchase_payments + non-transfer cash-book + ± transfers. | **HIGH** — its filters `{"source":{"$ne":"legacy_shim"},"reversed":{"$ne":True},"kind":{"$ne":"transfer"}}` are the same rule `is_cash_book_entry_canonical` enforces on the read side. Reconcile checks the DB; here we compute the balance. If one changes without the other, `A2A net-zero` and `FF settlement` invariants report drift. |
| I  | `server.py:2232–2350` | `party_ledger_summary()` (v1 legacy summary) | Aggregate view over the legacy `payments` collection. | **LOW** — legacy, already deprecated by Party Ledger v2. Recommended: mark for retirement in Phase 6 (do NOT rewrite). |
| J  | `server.py:3200–3400` (approx) | `/export/payments.csv`, `/export/payments.xlsx` | Canonical union of cust_pays / purchase_pays / cb_entries / migrations. | **MEDIUM** — currently filters inline; should use `is_cash_book_entry_canonical` / `is_*_active`. |
| K  | `server.py:4397+` | `_compute_quotation_totals(q)` | Quotation math. | **NONE** — quotation is isolated from money movement, out of Phase 6 scope. |
| L  | `admin_reset.py::execute_reset` post-reset check | Reads reconciliation and returns snapshot. | **NONE** — already uses `domain.py` via `reconcile.py`. |

**Signal statistics (grep across `server.py`, `party_ledger_v2.py`, `transfers.py`, `party_sync.py`):**
- `float(... .get("amount") ...)` inline sums: **77 occurrences**
- `round(...)` calls: **63 occurrences** (many are display-only; a subset are financial and should route through `to_paise/from_paise`)
- Inline `"reversed":{"$ne":True}` filters: **≥7 occurrences**
- Inline `source":{"$ne":"legacy_shim"}` filters: **3 occurrences** (dashboard, exports, transfers).

---

## 3. Design — the target surface

### 3.1 Additions to `domain.py`

All additions are **pure functions**; no I/O, no Mongo dependency (existing pattern).

#### 3.1.1 Money constants
```python
SETTLED_THRESHOLD_PAISE = 50          # ≡ ₹0.50 — used by _status_from_balance
DEFAULT_TAX_ROUNDING = "HALF_UP"
```

#### 3.1.2 Order-level helpers (fold `compute_order_aggregates` money math)
- `order_shipped_qty_by_item(order) -> dict[str, float]`
- `order_shipped_ratio_per_item(order) -> dict[str, Decimal]`
- `order_realized_amounts(order) -> dict` returning `{operating_revenue_paise, total_cost_paise, net_profit_paise, invoice_total_paise, tax_amount_paise, margin_bp}` — everything reconcile P4.orders.identities already checks.
- `order_estimated_amounts(order) -> dict` — same shape, full-order projection.
- `order_unrealized(order) -> dict` — `{unrealized_revenue_paise, unrealized_net_profit_paise}` (estimated − realized).
- `order_outstanding_from_alloc(order, alloc_sum_paise) -> int` — canonical outstanding.

`compute_order_aggregates(order)` becomes a thin adapter that calls these helpers, writes back the same denormalised fields, and rounds to display floats at the very end. Business rule (revenue-recognised-on-shipped-qty) lives in ONE place.

#### 3.1.3 Purchase-level helpers
- `purchase_realized_amounts(purchase) -> dict`
- `purchase_outstanding_from_alloc(purchase, alloc_sum_paise) -> int`

`compute_purchase(p)` becomes a thin adapter.

#### 3.1.4 Dashboard-level composites (new)
- `dashboard_kpis(*, orders, cust_pays, purchase_pays, cb_entries, purchases, transfers, accounts) -> dict`
  Returns the ENTIRE dashboard KPI block in a single call. Every subsum internally uses `sum_received_kpi`, `sum_paid_kpi`, `sum_mode_totals`, `order_realized_amounts`, `order_estimated_amounts`, `sum_allocations_to_*`, `is_*_active`.
  The endpoint in `server.py::dashboard()` becomes:
  ```python
  orders          = await db.orders.find(...).to_list(10000)
  cust_pays       = await db.customer_payments.find(...).to_list(20000)
  purchase_pays   = await db.purchase_payments.find(...).to_list(20000)
  cb_entries      = await db.cash_book_entries.find(...).to_list(20000)
  purchases       = await db.purchases.find(...).to_list(20000)
  transfers       = await db.transfers.find(...).to_list(20000)
  accounts        = await db.accounts.find(...).to_list(200)
  return dashboard_kpis(
      orders=orders, cust_pays=cust_pays, purchase_pays=purchase_pays,
      cb_entries=cb_entries, purchases=purchases, transfers=transfers,
      accounts=accounts,
  )
  ```
  All Mongo filters are removed from the endpoint; `domain.py::is_*_active` decides what's canonical.

#### 3.1.5 Party ledger helpers
- `party_status_from_paise(balance_paise: int) -> Literal["Settled","You Pay","You Receive"]` — uses `SETTLED_THRESHOLD_PAISE`.
- `party_delta_for_row(cat, amount_paise, direction) -> int` — paise-safe version of `_resolve_delta`.

`_derived_entries_for_party` continues to own the row-building shape (id / txn_ref / party_id / date etc — that's IO-shape, not money math), but every `float(...)` sum inside it routes through `to_paise / from_paise / sum_allocations_to_order / sum_allocations_to_purchase`.

#### 3.1.6 Account balance helpers
- `apply_transfer_to_account_balance(t, aid) -> int` (paise) — folded from `transfers.py`.
- `sum_cashbook_net_for_account(cb_entries, aid) -> int` — filter with `is_cash_book_entry_canonical`.
- `account_balance(*, opening_paise, cust_pays, purchase_pays, cb_entries, transfers, account_id) -> int` (paise) — this is exactly what `derive_account_balance` does today, but as a pure function. The Mongo-fetching endpoint in `transfers.py::derive_account_balance` becomes a thin wrapper that fetches the four lists and calls this helper.

#### 3.1.7 Grand totals
- `sum_ff_settlement_delta_from_transfers(transfers) -> int` (paise) — folded from `transfers.py::ff_settlement_delta_from_transfers`.

### 3.2 What's OUT of scope for Phase 6

- **Party migration & sync** (`party_sync.py`) — party normalisation / dedupe. Different concern (identity, not money).
- **Auth / bootstrap** (`auth.py`, admin bootstrap endpoints).
- **Backup / restore / audit** (`admin_reset.py`) — already reads reconcile via `domain.py` transitively.
- **Frontend** — no changes needed. All endpoints preserve their exact response shape. `data-testid`s, key names, number formatting all remain identical.
- **Reconcile engine** — already on `domain.py`; NO changes to invariant list, invariant ids, or engine_version. Once the dashboard is on `domain.py` too, the drift invariants become **trivially satisfied** because both sides call the same code.

---

## 4. Migration plan — 6 slices, each independently mergeable

Each slice ends green (all existing tests pass, plus its own new tests). Any slice can be rolled back independently.

### Slice 1 — Enrich `domain.py` with new helpers (additive; no callers switched yet)
- Add sections 3.1.1 → 3.1.7 to `domain.py`.
- Add `backend/tests/test_p6_domain.py` with unit tests for each new helper. **Target: ≥40 assertions** covering:
  - paise round-trip identity, HALF_UP boundaries.
  - Active-record filters against synthetic docs for every exclusion rule.
  - `dashboard_kpis` given a scripted fixture produces exactly the numbers `dashboard()` currently returns (golden-master run — script captures current output before the switch).
  - `order_realized_amounts`/`order_estimated_amounts` reproduce `compute_order_aggregates` output within `TOLERANCE_PAISE` on 5 fixtures (no-shipment, full-shipment, 40% partial, tax-manual, freight-only shipment).
- **Exit criteria:** new file added, `pytest -k p6_domain` green, existing suite unchanged.

### Slice 2 — Switch `dashboard()` and `dashboard_breakdown()` to `dashboard_kpis`
- Delete the inline `float(...)` sums from `server.py::dashboard()` (lines ~1291–1330).
- Endpoint body shrinks to fetch + one helper call + serialise.
- **Regression guard:** golden-master test asserts response is byte-identical (after normalising float→str formatting) to a pre-refactor snapshot recorded from the current deployment.
- **Exit criteria:** all P0/P1/P4/P5 backend tests still green; new `test_p6_dashboard_uses_domain.py` snapshots pass. Reconcile invariants P0.modes.no_unknown_mode, X.orders.total_received_matches trivially pass because they now read from the same code path.

### Slice 3 — `compute_order_aggregates` → `order_realized_amounts` + `order_estimated_amounts`
- Adapter pattern: keep the function name & signature, replace body.
- Freight/packing/tax rules preserved bit-for-bit.
- **Regression guard:** `test_p4_partial_shipment_revenue.py` continues to pass 6/6 unmodified.

### Slice 4 — `_recompute_payment_aggregates_for_orders` + `customer_outstanding_orders` + purchases twin
- Replace inline `sum(float(a.get("amount") or 0) for a in allocs)` with `sum_allocations_to_order(cust_pays, oid)`.
- `outstanding = order_outstanding_from_alloc(order, alloc_sum_paise)`.
- Similar for purchases (`compute_purchase`, `_recompute_purchase_payment_aggregates`, `vendor_outstanding_purchases`).
- **Regression guard:** `test_purchase_sources.py` + `test_review_workflow.py` remain green.

### Slice 5 — Party Ledger v2 `_derived_entries_for_party` + `_status_from_balance`
- Row shapes remain identical (id, txn_ref, party_id, date, category, amount, delta_you_pay, notes).
- Every `float(...)` → `from_paise(to_paise(...))` when displaying, else the paise integer wins internally.
- `_status_from_balance(bal)` calls `party_status_from_paise(to_paise(bal))`.
- **Regression guard:** `test_party_ledger_v2.py` + `test_party_ledger_reconciliation.py` pass isolated.

### Slice 6 — Transfers: `derive_account_balance`, `ff_settlement_delta_from_transfers`
- Adapter pattern — endpoint fetches four lists (customer_payments / purchase_payments / cash_book_entries / transfers) and calls `account_balance(...)`.
- **Regression guard:** `test_p3_transfers.py` 17/17 unchanged.

### Slice 7 (optional cleanup) — retire legacy `party_ledger_summary` and stale `_refresh_stored_aggregates` code paths that duplicate the new helpers.
- Only after slices 1-6 are in production for one release cycle.

---

## 5. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Silent numeric drift on some fixture (float → paise rounding difference on legacy rows). | Medium | High | Golden-master snapshot test in Slice 2 asserts byte-equality; if any KPI diverges by more than `TOLERANCE_PAISE`, the test fails BEFORE deploy. |
| Reconcile suddenly reports NEW offenders because dashboard now agrees with reconcile (i.e. it USED to be wrong). | Medium | Low (positive!) | Run `POST /api/reconcile/run` before + after each slice; delta is the truth-set of previously-hidden bugs. Attach to the PR review. |
| Party Ledger v2's `_status_from_balance` uses a 0.5-rupee threshold today, `TOLERANCE_PAISE=1` paise elsewhere. Consolidating could change 1-2 party's status label. | Low | Low | Preserve `SETTLED_THRESHOLD_PAISE=50` (=₹0.50) as an explicit domain constant. Do NOT unify with `TOLERANCE_PAISE`. Add a test that pins the exact boundary. |
| An adapter change (Slice 3) accidentally changes tax computation order (base includes/excludes other_expense_total). | Low | High | Slice 3 opens with a "before" snapshot of `compute_order_aggregates` output on the current 47-order seed; asserts the "after" is bit-identical. |
| xdist-parallel test flakes (currently 2 flaky tests in reconciliation suite). | Medium | Low | Run each slice's tests with `-p no:xdist` in CI in addition to parallel; document that flakes are pre-existing per audit §6 P2. |
| Frontend regression (should be zero). | Very low | High | Frontend test IDs / response keys not renamed. `auto_frontend_testing_agent` smoke test at end of programme. |

---

## 6. Testing strategy

New files:
- `backend/tests/test_p6_domain.py` — pure-function unit tests for every new helper (≥40 assertions).
- `backend/tests/test_p6_dashboard_uses_domain.py` — API contract snapshots; asserts `/api/dashboard` and `/api/dashboard/breakdown` response shape + numbers survive the refactor bit-for-bit.
- `backend/tests/test_p6_helper_equivalence.py` — for each helper being folded (order_realized, purchase_realized, account_balance, party_ledger row math), asserts the OLD inline implementation and the NEW `domain.py` helper produce identical numbers on 20+ synthetic fixtures + the current live seed. This is the anti-drift regression net.

Existing suites re-run unchanged:
- `test_p0_canonical_cashbook.py` (9/9)
- `test_p1_party_auto_create.py` (14/14)
- `test_p3_transfers.py` (17/17)
- `test_p4_partial_shipment_revenue.py` (6/6)
- `test_p5_reconcile.py` (20/20)

Post-refactor sanity: `POST /api/reconcile/run` must return `healthy: true` with `failed_count == 0` on the current seed dataset.

---

## 7. Deliverables & acceptance criteria

1. **Zero API-shape change.** Every endpoint response payload matches the pre-refactor snapshot down to key names, ordering (where deterministic), and numeric value (with `≤ TOLERANCE_PAISE` variance allowed on rounding).
2. **`domain.py` is the sole location for**: money conversion, active-record filters, dashboard KPI composition, order realized/estimated math, purchase realized math, account balance, party settled-threshold, FF settlement delta from transfers.
3. **77 → 0** `float(x.get("amount") or 0)` inline sums in `server.py`, `party_ledger_v2.py`, `transfers.py` (verified via grep gate in CI).
4. **Inline `"reversed":{"$ne":True}` / `"source":{"$ne":"legacy_shim"}` Mongo filters** replaced by fetching + `is_*_active` / `is_cash_book_entry_canonical` in Python (7 → 0 occurrences).
5. **Reconcile programme (all 21 invariants) still HEALTHY** after every slice.
6. **No frontend changes**; screenshot-diff of Dashboard, Orders, Party Ledger, Cash Book, Transfers pages before-vs-after is zero-pixel-different for the same underlying data.
7. **Full test suite:** ≥ Phase 5 baseline (170 pass / 26 flake tolerated per audit §6 P2). New Phase 6 tests add ≥ 60 assertions passing.
8. **`engine_version` stays `"P5"`** on `/api/reconcile` (Phase 6 is a refactor, not an engine bump).
9. **Documentation update** in `memory/PRD.md` — Phase 6 section, mirroring the Phase-5 write-up.

---

## 8. Estimated size

| Slice | Files touched (LOC delta est.) | Test LOC added | Reviewer time |
|---|---|---|---|
| 1 (helpers + tests only) | `domain.py` (+ ~250), new test file (+ ~350) | +350 | ~40 min |
| 2 (dashboard) | `server.py` (-60, +15), new snapshot test (+ ~150) | +150 | ~30 min |
| 3 (order aggregates) | `server.py` (-90, +25) | +80 | ~30 min |
| 4 (payment aggregates + outstanding) | `server.py` (-140, +40) | +100 | ~30 min |
| 5 (party ledger v2 derived) | `party_ledger_v2.py` (-120, +50) | +100 | ~40 min |
| 6 (transfers/account balance) | `transfers.py` (-60, +20) | +80 | ~30 min |
| **Total** | **~-470 net LOC in prod code, +860 LOC in tests** | **+860** | **~3.5 hours review** |

The prod-code line count DROPS by ~470 lines even after adding all new helpers — a good sign that consolidation is genuine, not just re-shuffling.

---

## 9. Open questions for reviewer

1. **`SETTLED_THRESHOLD_PAISE = 50`** — do we keep the existing 0.5-rupee threshold from `_status_from_balance`, or tighten it to `TOLERANCE_PAISE = 1` (i.e. ₹0.01) to match the reconcile engine? Recommend keeping 50 for UX (avoids labelling near-zero balances as "You Pay ₹0.02").
2. **Legacy `party_ledger_summary` (v1)** — retire in Slice 7 or defer to a separate cleanup PR? Recommend defer.
3. **`_refresh_stored_aggregates` on startup** — after Slice 3 this becomes a thin loop. Keep it (idempotent backfill safety) or remove (Phase 3+ writes are already correct)? Recommend keep for one more release.
4. **Golden-master snapshot** — do we lock the snapshot to today's seed (47 orders, dashboard KPIs currently observed: shipped revenue = ₹46,98,786, realized profit = ₹19,74,465, total cost = ₹27,24,321), or generate a synthetic minimal fixture? Recommend BOTH — synthetic for unit test determinism + live snapshot as an integration sentinel.
5. **Merge cadence** — one slice per PR, or all six in a single PR with a slice-by-slice commit history? Recommend one PR per slice for reviewability.

---

**End of pre-implementation report.** Awaiting reviewer sign-off before starting Slice 1.
