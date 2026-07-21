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
from typing import Iterable

# ─── Money primitives ──────────────────────────────────────────────────────

TOLERANCE_PAISE = 1  # <=1 paise drift is float-noise, not real drift.


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
