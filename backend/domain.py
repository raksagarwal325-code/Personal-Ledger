"""Phase 5 (P2) — Shared domain calculation helpers.

Single source of truth for financial arithmetic. Dashboard, Cash Book,
Party Ledger and Reconciliation all read from these helpers instead of
ad-hoc `float(x.get("amount") or 0)` calls. Every helper works in
INTEGER PAISE so equality checks are exact.

Terminology
-----------
    * paise           — int, 1 rupee = 100 paise. Store & compare in this unit.
    * money value     — user-facing display value, rupees float w/ 2dp rounding.
    * canonical rows  — rows that participate in a KPI computation. Every
                        helper defines its own active-record filter.

No helper in this module reads from or writes to Mongo. Data is passed
in as already-fetched lists of dicts (this makes them easy to unit-test
and reuse between the dashboard endpoint and the reconcile engine).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

# ─── Money primitives ──────────────────────────────────────────────────────

TOLERANCE_PAISE = 1  # <=1 paise drift is float-noise, not real drift.

# Party Ledger displays "Settled" when the absolute balance is within
# ₹0.50 (50 paise). This is a USER-FACING UX threshold and is intentionally
# distinct from TOLERANCE_PAISE (which is the mathematical drift tolerance
# used by the reconciliation engine). Do not unify — see Phase 6 report §5.
SETTLED_THRESHOLD_PAISE = 50


def to_paise(x) -> int:
    """Convert a rupees-domain number to integer paise.

    Handles float, int, str, Decimal, None. Rounds HALF_UP to nearest paise.
    None / '' / non-numeric returns 0.
    """
    if x is None or x == "":
        return 0
    try:
        d = Decimal(str(x))
    except Exception:
        return 0
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_paise(n: int) -> float:
    """Convert integer paise back to a 2dp float for display."""
    return round(int(n) / 100.0, 2)


def money_eq(a_paise: int, b_paise: int, tol_paise: int = TOLERANCE_PAISE) -> bool:
    """Paise-safe equality with a small integer tolerance."""
    return abs(int(a_paise) - int(b_paise)) <= int(tol_paise)


# ─── Active-record filters ─────────────────────────────────────────────────
#
# Each helper here is deliberately explicit about which docs it considers
# "live". Every reconcile invariant declares which filter it applies so
# that reviewers and testers can spot policy drift immediately.


def is_order_active(o: dict) -> bool:
    """Cancelled orders are excluded from KPIs and reconciliation math."""
    return (o.get("status") or "").lower() != "cancelled"


def is_customer_payment_active(p: dict) -> bool:
    """Voided customer payments do not participate in KPIs.
    (No `void` field exists yet in the schema — this hook is future-proof.)
    """
    return not p.get("voided") and not p.get("reversed")


def is_purchase_payment_active(p: dict) -> bool:
    return not p.get("voided") and not p.get("reversed")


def is_cash_book_entry_canonical(e: dict) -> bool:
    """A cash-book entry participates in KPI totals only when:
      * it is NOT a legacy-shim mirror of `db.payments`,
      * it has NOT been reversed,
      * it has NOT been migrated to a `db.transfers` row (transfers are
        counted separately, not via this collection).
    Transfers themselves are excluded from received/paid KPIs.
    """
    if e.get("source") == "legacy_shim":
        return False
    if e.get("reversed"):
        return False
    if e.get("migrated_to_transfer_id"):
        return False
    return True


def is_transfer_active(t: dict) -> bool:
    """A transfer is 'active' when its status is not 'reversed'. Reversal
    docs (whose `reverses_transfer_id` is set) are themselves active."""
    return (t.get("status") or "active") != "reversed"


def is_account_active(a: dict) -> bool:
    """Archived accounts do not participate in fresh KPIs but their
    historical balances remain derivable."""
    return not a.get("archived")


# ─── Canonical KPI sums (rupees-domain floats returned; call to_paise for
# paise-safe comparisons in reconcile). ───────────────────────────────────


def sum_received_kpi(cust_pays: Iterable[dict], cb_entries: Iterable[dict]) -> int:
    """Return canonical `received` KPI in paise:
       Σ customer_payments.amount (active)
     + Σ cash_book_entries.amount where kind=general_income (canonical).
    """
    total = 0
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        total += to_paise(p.get("amount"))
    for e in cb_entries:
        if not is_cash_book_entry_canonical(e):
            continue
        if e.get("kind") == "general_income":
            total += to_paise(e.get("amount"))
    return total


def sum_paid_kpi(purchase_pays: Iterable[dict], cb_entries: Iterable[dict]) -> int:
    """Return canonical `paid` KPI in paise."""
    total = 0
    for p in purchase_pays:
        if not is_purchase_payment_active(p):
            continue
        total += to_paise(p.get("amount"))
    for e in cb_entries:
        if not is_cash_book_entry_canonical(e):
            continue
        if e.get("kind") == "general_expense":
            total += to_paise(e.get("amount"))
    return total


def sum_mode_totals(cust_pays: Iterable[dict],
                    purchase_pays: Iterable[dict],
                    cb_entries: Iterable[dict]) -> dict:
    """Return {mode: {received_paise, paid_paise}} using canonical rows only.
    Blank / None modes are reported under the sentinel key ``""`` so
    reconcile can flag them.
    """
    out: dict[str, dict] = {}
    def _bucket(mode):
        key = mode if (mode and str(mode).strip()) else ""
        return out.setdefault(key, {"received_paise": 0, "paid_paise": 0})
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        _bucket(p.get("mode"))["received_paise"] += to_paise(p.get("amount"))
    for p in purchase_pays:
        if not is_purchase_payment_active(p):
            continue
        _bucket(p.get("mode"))["paid_paise"] += to_paise(p.get("amount"))
    for e in cb_entries:
        if not is_cash_book_entry_canonical(e):
            continue
        if e.get("kind") == "general_income":
            _bucket(e.get("mode"))["received_paise"] += to_paise(e.get("amount"))
        elif e.get("kind") == "general_expense":
            _bucket(e.get("mode"))["paid_paise"] += to_paise(e.get("amount"))
    return out


def sum_allocations_to_order(cust_pays: Iterable[dict], oid: str) -> int:
    """Σ allocations on non-voided customer_payments where order_id == oid, in paise."""
    total = 0
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        for a in (p.get("allocations") or []):
            if a.get("order_id") == oid:
                total += to_paise(a.get("amount"))
    return total


def sum_allocations_to_purchase(purchase_pays: Iterable[dict], pid: str) -> int:
    total = 0
    for p in purchase_pays:
        if not is_purchase_payment_active(p):
            continue
        for a in (p.get("allocations") or []):
            if a.get("purchase_id") == pid:
                total += to_paise(a.get("amount"))
    return total


# ═══════════════════════════════════════════════════════════════════════════
# Phase 6 (P2) — Composable domain helpers (Slice 1: additive only)
# ═══════════════════════════════════════════════════════════════════════════
# Design principles (see /app/memory/phase6_shared_domain_preimpl_report.md):
#   * Every helper is a pure function: same inputs → same outputs, no I/O,
#     no time-dependence, no global state.
#   * Every helper receives already-fetched lists of dicts. No Mongo. No HTTP.
#   * Every monetary value is computed in INTEGER PAISE internally. Callers
#     convert to display floats via from_paise() at the boundary.
#   * Helpers MUST NOT mutate inputs. Property-tested in
#     backend/tests/test_p6_domain.py.


# ─── Order-level helpers ───────────────────────────────────────────────────

def _order_shipped_qty_by_item(order: dict) -> dict:
    """Return {order_item_id: shipped_qty(float)}. Pure. Non-mutating."""
    out: dict = {}
    for sh in (order.get("shipments") or []):
        for si in (sh.get("items") or []):
            iid = si.get("order_item_id")
            if not iid:
                continue
            out[iid] = out.get(iid, 0.0) + float(si.get("qty") or 0)
    return out


def order_shipped_ratio_per_item(order: dict) -> dict:
    """Return {order_item_id: Decimal(shipped/ordered)}.

    Non-negative. Not clamped to ≤ 1 — over-shipment (shipped > ordered)
    yields a ratio > 1 to match pre-Phase-6 behaviour: any revenue and cost
    proportioned by this ratio scales linearly. Missing / zero ordered qty
    yields Decimal('0'). Pure."""
    shipped = _order_shipped_qty_by_item(order)
    ratios: dict = {}
    for it in (order.get("items") or []):
        iid = it.get("id")
        if not iid:
            continue
        ordered_qty = Decimal(str(it.get("qty") or 0))
        shipped_qty = Decimal(str(shipped.get(iid, 0)))
        if ordered_qty <= 0:
            ratios[iid] = Decimal("0")
        else:
            r = shipped_qty / ordered_qty
            if r < 0:
                r = Decimal("0")
            ratios[iid] = r
    return ratios


def _item_ordered_product_sales_paise(it: dict) -> int:
    """qty * rate (fallback to stored product_sales if set). Paise."""
    stored = it.get("product_sales")
    if stored not in (None, "", 0):
        return to_paise(stored)
    q = Decimal(str(it.get("qty") or 0))
    r = Decimal(str(it.get("rate") or 0))
    return to_paise(q * r)


def _sum_amounts_paise(rows: Iterable[dict], key: str = "amount") -> int:
    """Σ to_paise(row[key]) over rows. Pure."""
    return sum(to_paise((r or {}).get(key)) for r in rows)


def order_realized_amounts(order: dict) -> dict:
    """Realized (recognised-on-shipped-qty) monetary totals for one order.

    Returns everything in PAISE (int). Non-mutating.

    Keys:
      * operating_revenue_paise
      * total_cost_paise
      * net_profit_paise
      * invoice_total_paise
      * tax_amount_paise
      * shipped_product_sales_paise
      * ship_freight_charged_paise
      * ship_freight_paid_paise
      * packing_cost_paise
      * packing_recovery_paise
      * other_revenue_total_paise
      * other_expense_total_paise
      * factory_cost_realized_paise
      * outside_cost_realized_paise
    """
    ratios = order_shipped_ratio_per_item(order)
    shipped_product_sales_p = 0
    factory_cost_p = 0
    outside_cost_p = 0
    for it in (order.get("items") or []):
        iid = it.get("id")
        r = ratios.get(iid, Decimal("0"))
        item_sales_p = _item_ordered_product_sales_paise(it)
        shipped_product_sales_p += int((Decimal(item_sales_p) * r).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        for k in ("factory_complete", "factory_glass", "factory_fitting"):
            factory_cost_p += int(
                (Decimal(to_paise(it.get(k))) * r).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP))
        for k in ("outside_complete", "outside_glass", "outside_fitting"):
            outside_cost_p += int(
                (Decimal(to_paise(it.get(k))) * r).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP))

    other_rev_p = _sum_amounts_paise(order.get("other_revenue") or [])
    other_exp_p = _sum_amounts_paise(order.get("other_expense") or [])
    packing_cost_p = to_paise(order.get("packing_cost"))
    packing_recovery_p = to_paise(order.get("packing_recovery"))

    shipments = order.get("shipments") or []
    ship_freight_charged_p = sum(to_paise((s or {}).get("freight_charged")) for s in shipments)
    ship_freight_paid_p = sum(to_paise((s or {}).get("freight_paid")) for s in shipments)

    operating_revenue_p = (shipped_product_sales_p + ship_freight_charged_p
                           + packing_recovery_p + other_rev_p)
    total_cost_p = (factory_cost_p + outside_cost_p + packing_cost_p
                    + ship_freight_paid_p + other_exp_p)

    tax_applicable = bool(order.get("tax_applicable"))
    tax_manual = bool(order.get("tax_amount_manual"))
    if tax_applicable:
        if tax_manual:
            tax_amount_p = to_paise(order.get("tax_amount"))
        else:
            tax_percent = Decimal(str(order.get("tax_percent") or 0))
            tax_base_p = max(0, operating_revenue_p - other_exp_p)
            tax_amount_p = int((Decimal(tax_base_p) * tax_percent / Decimal(100))
                               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        tax_amount_p = 0

    invoice_total_p = operating_revenue_p + tax_amount_p
    net_profit_p = operating_revenue_p - total_cost_p

    return {
        "operating_revenue_paise": operating_revenue_p,
        "total_cost_paise": total_cost_p,
        "net_profit_paise": net_profit_p,
        "invoice_total_paise": invoice_total_p,
        "tax_amount_paise": tax_amount_p,
        "shipped_product_sales_paise": shipped_product_sales_p,
        "ship_freight_charged_paise": ship_freight_charged_p,
        "ship_freight_paid_paise": ship_freight_paid_p,
        "packing_cost_paise": packing_cost_p,
        "packing_recovery_paise": packing_recovery_p,
        "other_revenue_total_paise": other_rev_p,
        "other_expense_total_paise": other_exp_p,
        "factory_cost_realized_paise": factory_cost_p,
        "outside_cost_realized_paise": outside_cost_p,
    }


def order_estimated_amounts(order: dict) -> dict:
    """Estimated (full-order projection) monetary totals for one order.
    All in PAISE (int). Non-mutating.

    Keys mirror `order_realized_amounts` with the `estimated_` prefix on the
    aggregated triplet + the raw components:
      * estimated_operating_revenue_paise
      * estimated_total_cost_paise
      * estimated_net_profit_paise
      * estimated_factory_cost_paise
      * estimated_outside_cost_paise
      * estimated_product_sales_paise
    """
    est_product_sales_p = 0
    est_factory_p = 0
    est_outside_p = 0
    for it in (order.get("items") or []):
        est_product_sales_p += _item_ordered_product_sales_paise(it)
        for k in ("factory_complete", "factory_glass", "factory_fitting"):
            est_factory_p += to_paise(it.get(k))
        for k in ("outside_complete", "outside_glass", "outside_fitting"):
            est_outside_p += to_paise(it.get(k))

    other_rev_p = _sum_amounts_paise(order.get("other_revenue") or [])
    other_exp_p = _sum_amounts_paise(order.get("other_expense") or [])
    packing_cost_p = to_paise(order.get("packing_cost"))
    packing_recovery_p = to_paise(order.get("packing_recovery"))
    shipments = order.get("shipments") or []
    ship_freight_charged_p = sum(to_paise((s or {}).get("freight_charged")) for s in shipments)
    ship_freight_paid_p = sum(to_paise((s or {}).get("freight_paid")) for s in shipments)

    est_operating_revenue_p = (est_product_sales_p + ship_freight_charged_p
                               + packing_recovery_p + other_rev_p)
    est_total_cost_p = (est_factory_p + est_outside_p + packing_cost_p
                        + ship_freight_paid_p + other_exp_p)
    est_net_profit_p = est_operating_revenue_p - est_total_cost_p

    return {
        "estimated_operating_revenue_paise": est_operating_revenue_p,
        "estimated_total_cost_paise": est_total_cost_p,
        "estimated_net_profit_paise": est_net_profit_p,
        "estimated_factory_cost_paise": est_factory_p,
        "estimated_outside_cost_paise": est_outside_p,
        "estimated_product_sales_paise": est_product_sales_p,
    }


def order_unrealized(order: dict) -> dict:
    """Unrealized = estimated − realized. All in PAISE. Non-mutating.

    Guaranteed property (proved by test_p6_domain.py):
      estimated_x_paise == realized_x_paise + unrealized_x_paise
    for x in {operating_revenue, net_profit}.
    """
    real = order_realized_amounts(order)
    est = order_estimated_amounts(order)
    return {
        "unrealized_revenue_paise": (est["estimated_operating_revenue_paise"]
                                     - real["operating_revenue_paise"]),
        "unrealized_net_profit_paise": (est["estimated_net_profit_paise"]
                                        - real["net_profit_paise"]),
    }


def order_outstanding_from_alloc(order: dict, alloc_sum_paise: int) -> int:
    """outstanding = invoice_total − allocations_received. Never negative.

    `alloc_sum_paise` should come from `sum_allocations_to_order`.
    Non-mutating."""
    inv_p = to_paise(order.get("invoice_total"))
    return max(0, inv_p - int(alloc_sum_paise))


# ─── Purchase-level helpers ────────────────────────────────────────────────

def _purchase_item_amount_paise(it: dict) -> int:
    """Item amount: stored `amount` when non-zero, else qty*rate. Paise.
    Matches server.compute_purchase fallback behaviour exactly."""
    stored = it.get("amount")
    if stored not in (None, "", 0):
        return to_paise(stored)
    q = Decimal(str(it.get("qty") or 0))
    r = Decimal(str(it.get("rate") or 0))
    return to_paise(q * r)


def purchase_realized_amounts(purchase: dict) -> dict:
    """Realized monetary totals for a purchase (vendor bill). PAISE. Pure.

    Business rules — mirrors server.compute_purchase pre-Phase-6:
      * subtotal_paise    = Σ item amounts (stored, else qty*rate)
      * freight_paise     = purchase.freight (top-level, not per-shipment)
      * other_charges_paise = purchase.other_charges
      * tax_amount_paise  = auto (base*tax_percent/100, paise HALF_UP)
                            OR manual (purchase.tax_amount)
                            OR 0 when tax_applicable is falsy
      * invoice_total_paise = subtotal + freight + other + tax
    """
    items = purchase.get("items") or []
    subtotal_p = sum(_purchase_item_amount_paise(it) for it in items)
    freight_p = to_paise(purchase.get("freight"))
    other_p = to_paise(purchase.get("other_charges"))
    base_p = subtotal_p + freight_p + other_p

    if purchase.get("tax_applicable"):
        if purchase.get("tax_amount_manual"):
            tax_p = to_paise(purchase.get("tax_amount"))
        else:
            tax_percent = Decimal(str(purchase.get("tax_percent") or 0))
            tax_p = int((Decimal(base_p) * tax_percent / Decimal(100))
                        .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        tax_p = 0

    return {
        "subtotal_paise": subtotal_p,
        "freight_paise": freight_p,
        "other_charges_paise": other_p,
        "tax_amount_paise": tax_p,
        "invoice_total_paise": base_p + tax_p,
    }


def purchase_outstanding_from_alloc(purchase: dict, alloc_sum_paise: int) -> int:
    """outstanding = invoice_total − allocations_paid. Never negative.
    Non-mutating."""
    inv_p = to_paise(purchase.get("invoice_total"))
    return max(0, inv_p - int(alloc_sum_paise))


# ─── Party ledger helpers ──────────────────────────────────────────────────

CATEGORY_SIGN_MAP = {
    # Customer-side (party_ledger_v2 canonical signs, paise-domain).
    "sale_invoice":     -1,   # customer owes you → you-pay decreases
    "customer_payment": +1,
    "customer_refund":  -1,
    # Vendor-side.
    "purchase":         +1,   # you owe vendor → you-pay increases
    "purchase_return":  -1,
    "vendor_payment":   -1,
    "purchase_refund":  +1,
    "advance":          -1,   # vendor advance = extra paid
    # Ancillary rows appearing on the merged ledger.
    "packing":          +1,
    "expense":          -1,   # Rakshit paid an expense on the party's behalf
    "income":           +1,   # party gave Rakshit income
    "credit_note":      -1,
    "discount":         -1,
    # 'opening_balance', 'transfer', 'adjustment' use explicit direction hint.
}


def party_delta_for_row(category: str, amount_paise: int,
                        direction: Optional[str] = None) -> int:
    """Sign-corrected delta for a party ledger row (paise). Pure.

    Mirrors the legacy `_resolve_delta` from party_ledger_v2 in paise.
    When category is directional (opening_balance/transfer/adjustment),
    the caller must pass `direction ∈ {'you_pay', 'you_receive'}`.
    Default = 'you_pay'.
    """
    amt = abs(int(amount_paise or 0))
    if category in CATEGORY_SIGN_MAP:
        return CATEGORY_SIGN_MAP[category] * amt
    if direction == "you_receive":
        return -amt
    return +amt  # you_pay (default)


def party_status_from_paise(balance_paise: int) -> str:
    """UX label used by Party Ledger v2 — STRICT less-than semantics.
      |bal| <  SETTLED_THRESHOLD_PAISE (50)  → 'Settled'
      bal >  0                                → 'You Pay'
      bal <  0                                → 'You Receive'
    Note: strict `<` matches the pre-Phase-6 `if abs(bal) < 0.5` rule.
    A balance of EXACTLY 50 paise (₹0.50) is NOT settled — it's a labelled
    direction. Boundary pinned by test_party_status_from_paise_settled_boundary.
    """
    b = int(balance_paise or 0)
    if abs(b) < SETTLED_THRESHOLD_PAISE:
        return "Settled"
    return "You Pay" if b > 0 else "You Receive"


# ─── Transfer + account balance helpers ────────────────────────────────────

def apply_transfer_to_account_balance_paise(t: dict, account_id: str) -> int:
    """Signed impact of one transfer on ONE account, in paise. Pure.

    Positive → account balance increased; Negative → decreased.
    Ignores reversed transfers.
    """
    if not is_transfer_active(t):
        return 0
    amt_p = to_paise(t.get("amount"))
    from_side = t.get("from") or {}
    to_side = t.get("to") or {}
    delta = 0
    if from_side.get("account_id") == account_id:
        delta -= amt_p
    if to_side.get("account_id") == account_id:
        delta += amt_p
    return delta


def sum_cashbook_net_for_account_paise(cb_entries: Iterable[dict],
                                       account_id: str) -> int:
    """Σ (general_income − general_expense) on canonical cash-book entries
    tagged to `account_id`. Paise. Pure. Skips transfers + non-canonical rows."""
    total = 0
    for e in cb_entries:
        if not is_cash_book_entry_canonical(e):
            continue
        if e.get("account_id") != account_id:
            continue
        kind = e.get("kind")
        if kind == "general_income":
            total += to_paise(e.get("amount"))
        elif kind == "general_expense":
            total -= to_paise(e.get("amount"))
    return total


def account_balance_paise(*, opening_paise: int,
                          cust_pays: Iterable[dict],
                          purchase_pays: Iterable[dict],
                          cb_entries: Iterable[dict],
                          transfers: Iterable[dict],
                          account_id: str) -> int:
    """Derived account balance in PAISE. Pure.

    Formula:
        opening
        + Σ customer_payments.amount tagged to this account
        − Σ purchase_payments.amount tagged to this account
        + Σ canonical cash-book net for this account
        + Σ transfer deltas for this account
    """
    total = int(opening_paise or 0)
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        if p.get("account_id") == account_id:
            total += to_paise(p.get("amount"))
    for p in purchase_pays:
        if not is_purchase_payment_active(p):
            continue
        if p.get("account_id") == account_id:
            total -= to_paise(p.get("amount"))
    total += sum_cashbook_net_for_account_paise(cb_entries, account_id)
    for t in transfers:
        total += apply_transfer_to_account_balance_paise(t, account_id)
    return total


def sum_ff_settlement_delta_from_transfers_paise(transfers: Iterable[dict]) -> int:
    """Signed FF settlement delta contributed by transfers. PAISE. Pure.

    * rakshit_to_ff  → +amount  (FF now owes Rakshit less; Rakshit owes FF more)
    * ff_to_rakshit  → −amount  (opposite)
    * account_to_account → 0 (never touches FF)
    Ignores reversed transfers.
    """
    total = 0
    for t in transfers:
        if not is_transfer_active(t):
            continue
        amt_p = to_paise(t.get("amount"))
        kind = t.get("kind")
        if kind == "rakshit_to_ff":
            total += amt_p
        elif kind == "ff_to_rakshit":
            total -= amt_p
    return total


# ─── Composable dashboard metric builders ──────────────────────────────────
# Per Phase 6 adjustment §3 — no single giant dashboard_kpis. Compose from
# small named helpers, each independently testable.

def compute_receipts(cust_pays: Iterable[dict],
                     cb_entries: Iterable[dict]) -> dict:
    """Receipts KPI block. Returns paise ints. Pure."""
    cust_pays = list(cust_pays)
    cb_entries = list(cb_entries)
    total_p = sum_received_kpi(cust_pays, cb_entries)
    unallocated_p = 0
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        unallocated_p += to_paise(p.get("unallocated"))
    return {
        "received_paise": total_p,
        "customer_advances_paise": unallocated_p,
    }


def compute_payments(purchase_pays: Iterable[dict],
                     cb_entries: Iterable[dict]) -> dict:
    """Payments KPI block. Returns paise ints. Pure."""
    total_p = sum_paid_kpi(list(purchase_pays), list(cb_entries))
    return {"paid_paise": total_p}


def compute_order_metrics(orders: Iterable[dict],
                          cust_pays: Iterable[dict]) -> dict:
    """Order-level KPI block. Returns paise ints for money + counts.

    Uses each order's LIVE computation via order_realized_amounts /
    order_estimated_amounts — does NOT rely on the denormalised
    `operating_revenue` / `net_profit` stored on the doc. This is what
    makes the dashboard drift-free once callers switch to this helper.
    """
    orders = [o for o in orders if is_order_active(o)]
    cust_pays_list = list(cust_pays)

    op_rev_p = 0
    total_cost_p = 0
    net_profit_p = 0
    invoice_total_p = 0
    tax_p = 0
    est_rev_p = 0
    est_cost_p = 0
    est_profit_p = 0
    outstanding_p = 0
    boxes_used = 0
    boxes_shipped = 0
    freight_charged_p = 0
    freight_paid_p = 0
    packing_cost_p = 0
    for o in orders:
        real = order_realized_amounts(o)
        est = order_estimated_amounts(o)
        op_rev_p += real["operating_revenue_paise"]
        total_cost_p += real["total_cost_paise"]
        net_profit_p += real["net_profit_paise"]
        invoice_total_p += real["invoice_total_paise"]
        tax_p += real["tax_amount_paise"]
        est_rev_p += est["estimated_operating_revenue_paise"]
        est_cost_p += est["estimated_total_cost_paise"]
        est_profit_p += est["estimated_net_profit_paise"]
        alloc_p = sum_allocations_to_order(cust_pays_list, o.get("id") or "")
        outstanding_p += order_outstanding_from_alloc(o, alloc_p)
        for sh in (o.get("shipments") or []):
            boxes_shipped += int(sh.get("boxes_shipped") or 0)
            freight_charged_p += to_paise((sh or {}).get("freight_charged"))
            freight_paid_p += to_paise((sh or {}).get("freight_paid"))
        boxes_used += int(o.get("boxes_used") or 0)
        packing_cost_p += to_paise(o.get("packing_cost"))

    unrealized_rev_p = est_rev_p - op_rev_p
    unrealized_profit_p = est_profit_p - net_profit_p
    return {
        "operating_revenue_paise": op_rev_p,
        "total_cost_paise": total_cost_p,
        "net_profit_paise": net_profit_p,
        "invoice_value_paise": invoice_total_p,
        "gst_collected_paise": tax_p,
        "estimated_revenue_paise": est_rev_p,
        "estimated_total_cost_paise": est_cost_p,
        "estimated_net_profit_paise": est_profit_p,
        "unrealized_revenue_paise": unrealized_rev_p,
        "unrealized_net_profit_paise": unrealized_profit_p,
        "outstanding_receivable_paise": outstanding_p,
        "order_count": len(orders),
        "boxes_used": boxes_used,
        "boxes_shipped": boxes_shipped,
        "freight_charged_paise": freight_charged_p,
        "freight_paid_paise": freight_paid_p,
        "packing_cost_paise": packing_cost_p,
    }


def compute_purchase_metrics(purchases: Iterable[dict],
                             purchase_pays: Iterable[dict]) -> dict:
    """Purchase-level KPI block. Returns paise ints. Pure."""
    purchases = list(purchases)
    purchase_pays = list(purchase_pays)
    value_p = sum(to_paise((p or {}).get("invoice_total")) for p in purchases)
    paid_p = sum(to_paise((p or {}).get("amount")) for p in purchase_pays
                 if is_purchase_payment_active(p))
    outstanding_p = 0
    for p in purchases:
        alloc_p = sum_allocations_to_purchase(purchase_pays, p.get("id") or "")
        outstanding_p += purchase_outstanding_from_alloc(p, alloc_p)
    return {
        "purchase_value_paise": value_p,
        "purchase_paid_paise": paid_p,
        "purchase_outstanding_paise": outstanding_p,
        "purchase_count": len(purchases),
    }


def compute_transfer_metrics(transfers: Iterable[dict]) -> dict:
    """Transfer-level KPI block. Pure.

    Fields:
      * ff_settlement_delta_paise — signed FF delta from active transfers.
      * transfer_count_active     — how many transfers are non-reversed.
    """
    tlist = list(transfers)
    return {
        "ff_settlement_delta_paise": sum_ff_settlement_delta_from_transfers_paise(tlist),
        "transfer_count_active": sum(1 for t in tlist if is_transfer_active(t)),
    }


def compute_party_metrics(cust_pays: Iterable[dict],
                          purchase_pays: Iterable[dict]) -> dict:
    """Party-level roll-ups. Paise ints. Pure.

    * customer_advances_paise — Σ unallocated on active customer payments.
    * (More may be added in later slices as party v2 folds in.)
    """
    total_p = 0
    for p in cust_pays:
        if not is_customer_payment_active(p):
            continue
        total_p += to_paise(p.get("unallocated"))
    _ = list(purchase_pays)  # accepted for symmetry; may be used in Slice 5.
    return {"customer_advances_paise": total_p}


def build_dashboard_kpis(*, orders: Iterable[dict],
                         cust_pays: Iterable[dict],
                         purchase_pays: Iterable[dict],
                         cb_entries: Iterable[dict],
                         purchases: Iterable[dict],
                         transfers: Iterable[dict]) -> dict:
    """Compose every dashboard KPI from the smaller helpers above. Pure.

    Returns paise ints everywhere. The FastAPI endpoint is responsible
    for converting to display floats (from_paise) at the response boundary.
    """
    orders_list = list(orders)
    cust_pays_list = list(cust_pays)
    purchase_pays_list = list(purchase_pays)
    cb_entries_list = list(cb_entries)
    purchases_list = list(purchases)
    transfers_list = list(transfers)

    receipts = compute_receipts(cust_pays_list, cb_entries_list)
    payments = compute_payments(purchase_pays_list, cb_entries_list)
    orders_m = compute_order_metrics(orders_list, cust_pays_list)
    purchases_m = compute_purchase_metrics(purchases_list, purchase_pays_list)
    transfers_m = compute_transfer_metrics(transfers_list)
    party_m = compute_party_metrics(cust_pays_list, purchase_pays_list)
    modes = sum_mode_totals(cust_pays_list, purchase_pays_list, cb_entries_list)

    out: dict = {}
    out.update(orders_m)
    out.update(purchases_m)
    out.update(receipts)
    out.update(payments)
    out.update(transfers_m)
    # party_m contributes customer_advances_paise which also appears in
    # receipts; both paths must agree — reconcile invariant catches drift.
    out.update(party_m)
    out["modes_paise"] = modes
    return out

