"""Phase 5 (P2) — /api/reconcile invariant engine.

Read-only integrity report. Every invariant produces the same schema:

    {
      "id":               "p1.parties.unique_active",       # STABLE
      "phase":            "P1",
      "severity":         "error" | "warning" | "info",
      "status":           "passed" | "failed" | "warning" | "error",
      "description":      "...",
      "expected":         "...",     # human-readable expected state
      "actual":           "...",     # observed state
      "difference":       "...",     # signed delta or offender summary
      "tolerance":        "1 paise", # or "exact" or "n/a"
      "checked_count":    int,       # how many rows were inspected
      "offender_count":   int,
      "offenders":        list[dict],    # capped at OFFENDERS_CAP (=50)
      "truncated":        bool,          # true when offender_count > cap
      "duration_ms":      float,
    }

The `run_reconcile(db)` entry-point:
  * Reads every relevant collection ONCE (no per-invariant round-trips).
  * Executes each invariant inside a per-invariant try/except so a bug
    in one check never poisons the whole report; on exception the check
    is emitted with status="error" and the exception summary.
  * Wraps the whole run with a start/end timestamp + duration and does
    a second `count_documents` pass; if any of the collections it read
    grew or shrunk while running, the report includes a
    `concurrent_modification` warning and consistency="best_effort".
  * NEVER writes.

The engine is imported by `server.py` for GET/POST endpoints, by the
admin reset flow to snapshot before + after resets, and by pytest.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from domain import (
    TOLERANCE_PAISE,
    from_paise,
    is_account_active,
    is_cash_book_entry_canonical,
    is_customer_payment_active,
    is_order_active,
    is_purchase_payment_active,
    is_transfer_active,
    money_eq,
    sum_allocations_to_order,
    sum_allocations_to_purchase,
    sum_mode_totals,
    sum_paid_kpi,
    sum_received_kpi,
    to_paise,
)
from party_sync import (
    FF_ALIASES,
    SYSTEM_FF_ID,
    SYSTEM_FF_NAME,
    is_ff_alias,
    normalize_name,
)

REPORT_VERSION = "1.0"
ENGINE_VERSION = "P5"
OFFENDERS_CAP = 50


# ─── Invariant primitive ────────────────────────────────────────────────────


def _mk_invariant(
    *,
    id_: str,
    phase: str,
    severity: str,
    description: str,
    ok: bool,
    expected: Any = "",
    actual: Any = "",
    difference: Any = "",
    tolerance: str = "exact",
    checked_count: int = 0,
    offenders: list[dict] | None = None,
    started_at_perf: float | None = None,
    status_override: str | None = None,
) -> dict:
    offs = list(offenders or [])
    truncated = len(offs) > OFFENDERS_CAP
    return {
        "id": id_,
        "phase": phase,
        "severity": severity,
        "status": status_override or ("passed" if ok else
                                       ("warning" if severity == "warning" else "failed")),
        "description": description,
        "expected": expected,
        "actual": actual,
        "difference": difference,
        "tolerance": tolerance,
        "checked_count": int(checked_count),
        "offender_count": len(offs),
        "offenders": offs[:OFFENDERS_CAP],
        "truncated": truncated,
        "duration_ms": (round((time.perf_counter() - started_at_perf) * 1000.0, 2)
                        if started_at_perf is not None else 0.0),
    }


def _run_check(name: str, fn: Callable[[], dict]) -> dict:
    """Wrap a check with an error-boundary so exceptions become status=error."""
    t0 = time.perf_counter()
    try:
        inv = fn()
        # Backfill duration if the check itself didn't stamp one
        if not inv.get("duration_ms"):
            inv["duration_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return inv
    except Exception as ex:
        tb = traceback.format_exc(limit=3)
        return {
            "id": name,
            "phase": "?",
            "severity": "error",
            "status": "error",
            "description": f"Invariant {name!r} raised during execution.",
            "expected": "invariant completes without exception",
            "actual": f"{type(ex).__name__}: {ex}",
            "difference": tb,
            "tolerance": "n/a",
            "checked_count": 0,
            "offender_count": 0,
            "offenders": [],
            "truncated": False,
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


# ─── Data snapshot ─────────────────────────────────────────────────────────


async def _snapshot(db) -> dict:
    """Fetch every collection reconcile needs, ONCE, and return a plain-dict
    context passed to each invariant."""
    orders = await db.orders.find({}, {"_id": 0}).to_list(50000)
    cust_pays = await db.customer_payments.find({}, {"_id": 0}).to_list(50000)
    purchase_pays = await db.purchase_payments.find({}, {"_id": 0}).to_list(50000)
    purchases = await db.purchases.find({}, {"_id": 0}).to_list(50000)
    payments_legacy = await db.payments.find({}, {"_id": 0}).to_list(50000)
    cb_entries = await db.cash_book_entries.find({}, {"_id": 0}).to_list(50000)
    transfers = await db.transfers.find({}, {"_id": 0}).to_list(50000)
    parties = await db.parties.find({}, {"_id": 0}).to_list(20000)
    vendors = await db.vendors.find({}, {"_id": 0}).to_list(20000)
    accounts = await db.accounts.find({}, {"_id": 0}).to_list(2000)
    return {
        "orders": orders,
        "customer_payments": cust_pays,
        "purchase_payments": purchase_pays,
        "purchases": purchases,
        "payments_legacy": payments_legacy,
        "cash_book_entries": cb_entries,
        "transfers": transfers,
        "parties": parties,
        "vendors": vendors,
        "accounts": accounts,
    }


async def _collection_sizes(db) -> dict:
    """Cheap size-check used to detect concurrent writes during a run."""
    names = ("orders", "customer_payments", "purchase_payments", "purchases",
             "payments", "cash_book_entries", "transfers", "parties",
             "vendors", "accounts")
    out = {}
    for n in names:
        out[n] = await db[n].count_documents({})
    return out


# ─── Invariant checks ──────────────────────────────────────────────────────

# --- P0 / Cash Book & KPIs -------------------------------------------------


def _c_payments_legacy_stamped(ctx: dict) -> dict:
    t0 = time.perf_counter()
    rows = ctx["payments_legacy"]
    bad = [r for r in rows if (r.get("source") or "") not in
           ("legacy_shim", "legacy_migrated")]
    return _mk_invariant(
        id_="p0.payments.legacy_stamped",
        phase="P0", severity="error",
        description="Every db.payments row is stamped source ∈ {legacy_shim, legacy_migrated}.",
        ok=(len(bad) == 0),
        expected="all rows stamped",
        actual=f"{len(rows) - len(bad)} stamped / {len(rows)} total",
        difference=f"{len(bad)} unstamped",
        tolerance="exact",
        checked_count=len(rows),
        offenders=[{"id": r.get("id"), "source": r.get("source") or None} for r in bad],
        started_at_perf=t0,
    )


def _c_mode_totals_no_unknown(ctx: dict) -> dict:
    """Canonical mode totals; blank / None / "Other" modes are reported."""
    t0 = time.perf_counter()
    totals = sum_mode_totals(ctx["customer_payments"], ctx["purchase_payments"], ctx["cash_book_entries"])
    unknown_paise = totals.get("", {"received_paise": 0, "paid_paise": 0})
    unknown_total = unknown_paise["received_paise"] + unknown_paise["paid_paise"]
    return _mk_invariant(
        id_="p0.modes.no_unknown_mode",
        phase="P0",
        severity="warning" if unknown_total else "info",
        description="No canonical row has a blank / null payment mode.",
        ok=(unknown_total == 0),
        expected="0 paise across blank-mode buckets",
        actual=f"{from_paise(unknown_total)} across blank-mode buckets",
        difference=from_paise(unknown_total),
        tolerance="exact",
        checked_count=len(ctx["customer_payments"]) + len(ctx["purchase_payments"]) + len(ctx["cash_book_entries"]),
        offenders=[{"mode": "", **{k: from_paise(v) for k, v in unknown_paise.items()}}] if unknown_total else [],
        started_at_perf=t0,
    )


def _c_cashbook_ids_unique(ctx: dict) -> dict:
    """Every canonical row has a unique id inside its own collection."""
    t0 = time.perf_counter()
    seen: dict[str, list[str]] = {}
    def _push(kind, rows):
        for r in rows:
            rid = r.get("id")
            if not rid:
                continue
            seen.setdefault(f"{kind}:{rid}", []).append(kind)
    _push("customer_payments", ctx["customer_payments"])
    _push("purchase_payments", ctx["purchase_payments"])
    _push("cash_book_entries", ctx["cash_book_entries"])
    _push("transfers", ctx["transfers"])
    dupes = [{"key": k, "count": len(v)} for k, v in seen.items() if len(v) > 1]
    return _mk_invariant(
        id_="p0.cashbook.ids_unique",
        phase="P0", severity="error",
        description="No duplicate ids within customer/purchase payments, cash-book entries and transfers.",
        ok=(len(dupes) == 0),
        expected="0 duplicates",
        actual=f"{len(dupes)} duplicate ids",
        difference=len(dupes),
        tolerance="exact",
        checked_count=len(seen),
        offenders=dupes,
        started_at_perf=t0,
    )


def _c_transfer_appears_once_in_cashbook(ctx: dict) -> dict:
    """Every active transfer must produce exactly ONE cash-book timeline row.
    (`cash_book_entries[kind=transfer]` that pre-date the P3 migration must
    be stamped `migrated_to_transfer_id` so they're suppressed; unstamped
    rows are counted here as offenders.)"""
    t0 = time.perf_counter()
    unstamped = [e for e in ctx["cash_book_entries"]
                 if e.get("kind") == "transfer"
                 and not e.get("migrated_to_transfer_id")]
    active_transfer_ids = {t.get("id") for t in ctx["transfers"] if is_transfer_active(t)}
    return _mk_invariant(
        id_="p0.cashbook.transfer_appears_once",
        phase="P0", severity="error",
        description="Every active db.transfers row is projected once in the Cash Book; no legacy transfer rows survive unstamped.",
        ok=(len(unstamped) == 0),
        expected="0 unstamped legacy transfer rows",
        actual=f"{len(unstamped)} unstamped rows across {len(active_transfer_ids)} active transfers",
        difference=len(unstamped),
        tolerance="exact",
        checked_count=len(ctx["cash_book_entries"]),
        offenders=[{"id": e.get("id"), "date": e.get("date")} for e in unstamped],
        started_at_perf=t0,
    )


# --- P1 / Party identity ---------------------------------------------------


def _c_parties_unique_active(ctx: dict) -> dict:
    t0 = time.perf_counter()
    active = [p for p in ctx["parties"] if not p.get("archived")]
    key_counts: dict[tuple, list[str]] = {}
    for p in active:
        key = ((p.get("type") or ""), (p.get("normalized_name") or normalize_name(p.get("name"))))
        key_counts.setdefault(key, []).append(p.get("id"))
    dupes = [{"type": k[0], "normalized_name": k[1], "ids": ids}
             for k, ids in key_counts.items() if len(ids) > 1]
    return _mk_invariant(
        id_="p1.parties.unique_active",
        phase="P1", severity="error",
        description="No two active parties share the same (type, normalized_name).",
        ok=(len(dupes) == 0),
        expected="0 duplicate (type, normalized_name) combinations",
        actual=f"{len(dupes)} duplicate combos",
        difference=len(dupes),
        tolerance="exact",
        checked_count=len(active),
        offenders=dupes,
        started_at_perf=t0,
    )


def _c_parties_normalized_names(ctx: dict) -> dict:
    t0 = time.perf_counter()
    bad = [p for p in ctx["parties"]
           if (p.get("normalized_name") or "") != normalize_name(p.get("name"))]
    return _mk_invariant(
        id_="p1.parties.normalized_names_current",
        phase="P1", severity="warning",
        description="Every party.normalized_name is equal to normalize_name(name).",
        ok=(len(bad) == 0),
        expected="normalized_name == normalize_name(name)",
        actual=f"{len(bad)} out of sync",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["parties"]),
        offenders=[{"id": p.get("id"), "name": p.get("name"),
                    "stored_norm": p.get("normalized_name"),
                    "expected_norm": normalize_name(p.get("name"))} for p in bad],
        started_at_perf=t0,
    )


def _c_system_ff_intact(ctx: dict) -> dict:
    t0 = time.perf_counter()
    ff = next((p for p in ctx["parties"] if p.get("id") == SYSTEM_FF_ID), None)
    ok = (ff is not None and ff.get("type") in ("self", "fathers_firm")
          and ff.get("name") == SYSTEM_FF_NAME and not ff.get("archived"))
    return _mk_invariant(
        id_="p1.parties.system_ff_intact",
        phase="P1", severity="error",
        description="system_fathers_firm party exists, is not archived, is not renamed.",
        ok=ok,
        expected=f'{{id: "{SYSTEM_FF_ID}", name: "{SYSTEM_FF_NAME}", not archived}}',
        actual=({k: ff.get(k) for k in ("id", "name", "type", "archived")}
                if ff else "party missing"),
        difference="ok" if ok else "system FF drift",
        tolerance="exact",
        checked_count=1 if ff else 0,
        offenders=[] if ok else [{"id": SYSTEM_FF_ID, "issue": "missing/renamed/archived"}],
        started_at_perf=t0,
    )


def _c_ff_aliases_only_system(ctx: dict) -> dict:
    """Any active party whose name normalizes to a Father's Firm alias must
    point to the system FF id."""
    t0 = time.perf_counter()
    bad = []
    for p in ctx["parties"]:
        if p.get("archived"):
            continue
        if is_ff_alias(p.get("name")) and p.get("id") != SYSTEM_FF_ID:
            bad.append({"id": p.get("id"), "name": p.get("name"), "type": p.get("type")})
    return _mk_invariant(
        id_="p1.parties.ff_aliases_only_system",
        phase="P1", severity="error",
        description="Every Father's Firm alias resolves only to the protected system_fathers_firm party.",
        ok=(len(bad) == 0),
        expected="0 non-system parties with an FF alias name",
        actual=f"{len(bad)} rogue aliases",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["parties"]),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_party_id_refs_resolve(ctx: dict) -> dict:
    """Every `*_party_id` field on transactions must resolve to a party."""
    t0 = time.perf_counter()
    ids = {p.get("id") for p in ctx["parties"] if p.get("id")}
    bad = []
    def _check(coll_name, rows, field):
        for r in rows:
            pid = r.get(field)
            if pid and pid not in ids:
                bad.append({"collection": coll_name, "id": r.get("id"), field: pid})
    _check("orders", ctx["orders"], "customer_party_id")
    _check("customer_payments", ctx["customer_payments"], "customer_party_id")
    _check("customer_payments", ctx["customer_payments"], "received_by_party_id")
    _check("purchases", ctx["purchases"], "vendor_party_id")
    _check("purchase_payments", ctx["purchase_payments"], "vendor_party_id")
    _check("purchase_payments", ctx["purchase_payments"], "paid_by_party_id")
    _check("vendors", ctx["vendors"], "party_id")
    return _mk_invariant(
        id_="p1.parties.foreign_keys_resolve",
        phase="P1", severity="error",
        description="Every *_party_id on orders / payments / purchases / vendors resolves to an existing party.",
        ok=(len(bad) == 0),
        expected="0 unresolved party references",
        actual=f"{len(bad)} unresolved references",
        difference=len(bad),
        tolerance="exact",
        checked_count=(len(ctx["orders"]) + len(ctx["customer_payments"])
                       + len(ctx["purchases"]) + len(ctx["purchase_payments"])
                       + len(ctx["vendors"])),
        offenders=bad,
        started_at_perf=t0,
    )


# --- P3 / Transfers -------------------------------------------------------


def _c_transfer_sides_valid(ctx: dict) -> dict:
    """Every transfer has exactly one from_side + one to_side, sides are
    distinct, party sides may ONLY use system_fathers_firm."""
    t0 = time.perf_counter()
    bad = []
    for t in ctx["transfers"]:
        fs = t.get("from_side") or {}
        ts = t.get("to_side") or {}
        if not fs or not ts:
            bad.append({"id": t.get("id"), "issue": "missing side"})
            continue
        # party side must be system FF only
        for tag, side in (("from", fs), ("to", ts)):
            if side.get("type") == "party" and side.get("party_id") not in (None, SYSTEM_FF_ID):
                bad.append({"id": t.get("id"), "issue": f"{tag} party is non-FF",
                            "party_id": side.get("party_id")})
        # distinct sides for account_to_account
        if (t.get("kind") == "account_to_account"
                and fs.get("account_id") and fs.get("account_id") == ts.get("account_id")):
            bad.append({"id": t.get("id"), "issue": "same account on both sides"})
    return _mk_invariant(
        id_="p3.transfers.sides_valid",
        phase="P3", severity="error",
        description="Every transfer has exactly one source + one destination; party sides use only system_fathers_firm; account_to_account sides are distinct.",
        ok=(len(bad) == 0),
        expected="0 malformed sides",
        actual=f"{len(bad)} malformed",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["transfers"]),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_transfer_reversals_valid(ctx: dict) -> dict:
    """For every reversed original, there is a paired reversal transfer
    whose amount matches and whose sides are swapped."""
    t0 = time.perf_counter()
    by_id = {t.get("id"): t for t in ctx["transfers"] if t.get("id")}
    bad = []
    for t in ctx["transfers"]:
        if (t.get("status") or "") != "reversed":
            continue
        # find the pair reversing THIS one
        pair = next((p for p in ctx["transfers"] if p.get("reverses_transfer_id") == t.get("id")), None)
        if not pair:
            bad.append({"id": t.get("id"), "issue": "no reversal pair"})
            continue
        if to_paise(pair.get("amount")) != to_paise(t.get("amount")):
            bad.append({"id": t.get("id"), "issue": "reversal amount mismatch",
                        "orig_amt": t.get("amount"), "rev_amt": pair.get("amount")})
            continue
        # sides swapped?
        orig_from = (t.get("from_side") or {})
        orig_to = (t.get("to_side") or {})
        rev_from = (pair.get("from_side") or {})
        rev_to = (pair.get("to_side") or {})
        if (orig_from.get("account_id") != rev_to.get("account_id")
                or orig_to.get("account_id") != rev_from.get("account_id")
                or orig_from.get("party_id") != rev_to.get("party_id")
                or orig_to.get("party_id") != rev_from.get("party_id")):
            bad.append({"id": t.get("id"), "issue": "sides not swapped in reversal"})
    return _mk_invariant(
        id_="p3.transfers.reversals_valid",
        phase="P3", severity="error",
        description="Every reversed transfer has a paired reversal with equal amount and swapped sides.",
        ok=(len(bad) == 0),
        expected="0 bad reversals",
        actual=f"{len(bad)} bad reversals",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["transfers"]),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_transfer_replacement_no_cycles(ctx: dict) -> dict:
    """Replacement chains (edit-via-reverse-and-replace) must be acyclic."""
    t0 = time.perf_counter()
    next_of = {t.get("id"): t.get("replaced_by_transfer_id") for t in ctx["transfers"]}
    bad = []
    for t in ctx["transfers"]:
        seen = set()
        cur = t.get("id")
        while cur:
            if cur in seen:
                bad.append({"id": t.get("id"), "cycle_via": list(seen)})
                break
            seen.add(cur)
            cur = next_of.get(cur)
    return _mk_invariant(
        id_="p3.transfers.replacement_no_cycle",
        phase="P3", severity="error",
        description="No transfer replacement chain contains a cycle.",
        ok=(len(bad) == 0),
        expected="0 cycles",
        actual=f"{len(bad)} cycles",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["transfers"]),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_transfer_idempotency_unique(ctx: dict) -> dict:
    t0 = time.perf_counter()
    seen: dict[str, list[str]] = {}
    for t in ctx["transfers"]:
        k = t.get("idempotency_key")
        if k:
            seen.setdefault(k, []).append(t.get("id"))
    dupes = [{"idempotency_key": k, "ids": v} for k, v in seen.items() if len(v) > 1]
    return _mk_invariant(
        id_="p3.transfers.idempotency_keys_unique",
        phase="P3", severity="error",
        description="No two transfers share the same idempotency_key.",
        ok=(len(dupes) == 0),
        expected="unique keys",
        actual=f"{len(dupes)} duplicates",
        difference=len(dupes),
        tolerance="exact",
        checked_count=sum(len(v) for v in seen.values()),
        offenders=dupes,
        started_at_perf=t0,
    )


def _c_transfer_migration_no_dupes(ctx: dict) -> dict:
    """A legacy cash_book_entries[kind=transfer] must be stamped
    migrated_to_transfer_id, and the referenced transfer must exist and
    be reachable exactly once."""
    t0 = time.perf_counter()
    t_ids = {t.get("id") for t in ctx["transfers"] if t.get("id")}
    stamped = [e for e in ctx["cash_book_entries"] if e.get("kind") == "transfer" and e.get("migrated_to_transfer_id")]
    bad = []
    for e in stamped:
        tid = e.get("migrated_to_transfer_id")
        if tid not in t_ids:
            bad.append({"id": e.get("id"), "issue": "stamped transfer id missing", "target": tid})
    return _mk_invariant(
        id_="p3.transfers.migration_no_dupes",
        phase="P3", severity="error",
        description="Every legacy transfer row references an existing db.transfers row exactly once.",
        ok=(len(bad) == 0),
        expected="0 dangling stamps",
        actual=f"{len(bad)} dangling",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(stamped),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_transfer_account_to_account_net_zero(ctx: dict) -> dict:
    """For each active account_to_account transfer, sum of from + to
    impact across accounts == 0 (tracked cash conservation)."""
    t0 = time.perf_counter()
    bad = []
    for t in ctx["transfers"]:
        if not is_transfer_active(t):
            continue
        if t.get("kind") != "account_to_account":
            continue
        amt = to_paise(t.get("amount"))
        # A2A: from account balance -amt, to account balance +amt → net 0.
        if amt <= 0:
            bad.append({"id": t.get("id"), "issue": "non-positive amount", "amount": t.get("amount")})
    return _mk_invariant(
        id_="p3.transfers.a2a_net_zero",
        phase="P3", severity="error",
        description="Every active account_to_account transfer has a positive amount and conserves tracked cash.",
        ok=(len(bad) == 0),
        expected="0 bad rows",
        actual=f"{len(bad)} bad rows",
        difference=len(bad),
        tolerance="1 paise",
        checked_count=sum(1 for t in ctx["transfers"]
                          if is_transfer_active(t) and t.get("kind") == "account_to_account"),
        offenders=bad,
        started_at_perf=t0,
    )


# --- P4 / Partial-shipment revenue ---------------------------------------


def _c_p4_per_order_identity(ctx: dict) -> dict:
    """For every active order:
        net_profit + unrealized_net_profit == estimated_net_profit  (paise-exact)
        realized costs ≤ estimated costs
    """
    t0 = time.perf_counter()
    bad = []
    active = [o for o in ctx["orders"] if is_order_active(o)]
    for o in active:
        r_np = to_paise(o.get("net_profit"))
        u_np = to_paise(o.get("unrealized_net_profit"))
        e_np = to_paise(o.get("estimated_net_profit"))
        if not money_eq(r_np + u_np, e_np):
            bad.append({"id": o.get("id"),
                        "realized_np": from_paise(r_np),
                        "unrealized_np": from_paise(u_np),
                        "estimated_np": from_paise(e_np),
                        "diff_paise": (r_np + u_np) - e_np})
            continue
        # realized cost ≤ estimated cost (paise allowance)
        r_c = to_paise(o.get("total_cost"))
        e_c = to_paise(o.get("estimated_total_cost"))
        if r_c - e_c > TOLERANCE_PAISE:
            bad.append({"id": o.get("id"), "issue": "realized cost > estimated cost",
                        "realized_cost": from_paise(r_c),
                        "estimated_cost": from_paise(e_c)})
    return _mk_invariant(
        id_="p4.orders.identities",
        phase="P4", severity="error",
        description="For every non-cancelled order: realized + unrealized net_profit == estimated net_profit, and realized cost ≤ estimated cost.",
        ok=(len(bad) == 0),
        expected="identity holds for every active order",
        actual=f"{len(bad)} orders drifted",
        difference=len(bad),
        tolerance="1 paise",
        checked_count=len(active),
        offenders=bad,
        started_at_perf=t0,
    )


# --- Cross-cutting: allocation integrity ---------------------------------


def _c_customer_alloc_orders_resolve(ctx: dict) -> dict:
    t0 = time.perf_counter()
    order_ids = {o.get("id") for o in ctx["orders"] if o.get("id")}
    bad = []
    for p in ctx["customer_payments"]:
        if not is_customer_payment_active(p):
            continue
        for a in (p.get("allocations") or []):
            oid = a.get("order_id")
            if oid and oid not in order_ids:
                bad.append({"payment_id": p.get("id"), "order_id": oid,
                            "amount": a.get("amount")})
    return _mk_invariant(
        id_="x.cust_alloc.order_resolves",
        phase="X", severity="error",
        description="Every customer_payments.allocations[].order_id resolves to an existing order.",
        ok=(len(bad) == 0),
        expected="0 unresolved order refs",
        actual=f"{len(bad)} unresolved",
        difference=len(bad),
        tolerance="exact",
        checked_count=sum(len(p.get("allocations") or []) for p in ctx["customer_payments"]
                          if is_customer_payment_active(p)),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_customer_alloc_nonneg_and_capped(ctx: dict) -> dict:
    t0 = time.perf_counter()
    bad = []
    checked = 0
    for p in ctx["customer_payments"]:
        if not is_customer_payment_active(p):
            continue
        checked += 1
        pay_amt = to_paise(p.get("amount"))
        alloc_total = 0
        for a in (p.get("allocations") or []):
            v = to_paise(a.get("amount"))
            if v < 0:
                bad.append({"payment_id": p.get("id"), "issue": "negative allocation",
                            "amount": a.get("amount"), "order_id": a.get("order_id")})
            alloc_total += v
        # allocation total may equal or be less than payment amount; the
        # difference is the unallocated advance held on the payment.
        if alloc_total - pay_amt > TOLERANCE_PAISE:
            bad.append({"payment_id": p.get("id"),
                        "issue": "allocations exceed payment amount",
                        "allocation_total": from_paise(alloc_total),
                        "payment_amount": from_paise(pay_amt),
                        "excess_paise": alloc_total - pay_amt})
        # stored allocated_total must equal recomputed sum (drift detector)
        stored_alloc = to_paise(p.get("allocated_total"))
        if p.get("allocated_total") is not None and not money_eq(stored_alloc, alloc_total):
            bad.append({"payment_id": p.get("id"),
                        "issue": "stored allocated_total drift",
                        "stored": from_paise(stored_alloc),
                        "recomputed": from_paise(alloc_total),
                        "delta_paise": stored_alloc - alloc_total})
    return _mk_invariant(
        id_="x.cust_alloc.nonneg_capped_and_cached",
        phase="X", severity="error",
        description="Customer allocations are non-negative, total does not exceed payment.amount, and stored allocated_total matches recomputed sum.",
        ok=(len(bad) == 0),
        expected="every allocation valid + cached total matches",
        actual=f"{len(bad)} offenders",
        difference=len(bad),
        tolerance="1 paise",
        checked_count=checked,
        offenders=bad,
        started_at_perf=t0,
    )


def _c_orders_total_received_matches(ctx: dict) -> dict:
    """Each order's stored `total_received` matches the sum of allocations
    from all active customer_payments targeting it."""
    t0 = time.perf_counter()
    bad = []
    active = [o for o in ctx["orders"] if is_order_active(o)]
    for o in active:
        stored = to_paise(o.get("total_received"))
        recomputed = sum_allocations_to_order(ctx["customer_payments"], o.get("id"))
        if not money_eq(stored, recomputed):
            bad.append({"order_id": o.get("id"),
                        "stored_total_received": from_paise(stored),
                        "recomputed": from_paise(recomputed),
                        "delta_paise": stored - recomputed})
    return _mk_invariant(
        id_="x.orders.total_received_matches",
        phase="X", severity="error",
        description="orders[].total_received == Σ customer_payment allocations targeting that order.",
        ok=(len(bad) == 0),
        expected="stored == recomputed for every order",
        actual=f"{len(bad)} orders drifted",
        difference=len(bad),
        tolerance="1 paise",
        checked_count=len(active),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_purchase_alloc_and_totals(ctx: dict) -> dict:
    t0 = time.perf_counter()
    purchase_ids = {p.get("id") for p in ctx["purchases"] if p.get("id")}
    bad = []
    checked = 0
    for pp in ctx["purchase_payments"]:
        if not is_purchase_payment_active(pp):
            continue
        checked += 1
        pay_amt = to_paise(pp.get("amount"))
        alloc_total = 0
        for a in (pp.get("allocations") or []):
            pid = a.get("purchase_id")
            v = to_paise(a.get("amount"))
            if pid and pid not in purchase_ids:
                bad.append({"payment_id": pp.get("id"),
                            "issue": "purchase missing", "purchase_id": pid})
            if v < 0:
                bad.append({"payment_id": pp.get("id"),
                            "issue": "negative allocation",
                            "amount": a.get("amount"),
                            "purchase_id": pid})
            alloc_total += v
        if alloc_total - pay_amt > TOLERANCE_PAISE:
            bad.append({"payment_id": pp.get("id"),
                        "issue": "allocations exceed payment amount",
                        "allocation_total": from_paise(alloc_total),
                        "payment_amount": from_paise(pay_amt),
                        "excess_paise": alloc_total - pay_amt})
    # purchases[].total_paid drift
    for pur in ctx["purchases"]:
        stored = to_paise(pur.get("total_paid"))
        recomputed = sum_allocations_to_purchase(ctx["purchase_payments"], pur.get("id"))
        if not money_eq(stored, recomputed):
            bad.append({"purchase_id": pur.get("id"),
                        "issue": "stored total_paid drift",
                        "stored": from_paise(stored),
                        "recomputed": from_paise(recomputed),
                        "delta_paise": stored - recomputed})
    return _mk_invariant(
        id_="x.purchase_alloc.and_totals",
        phase="X", severity="error",
        description="Purchase allocations resolve, are non-negative, do not exceed payment amount, and purchases[].total_paid matches the recomputed sum.",
        ok=(len(bad) == 0),
        expected="all valid + cached matches",
        actual=f"{len(bad)} offenders",
        difference=len(bad),
        tolerance="1 paise",
        checked_count=checked + len(ctx["purchases"]),
        offenders=bad,
        started_at_perf=t0,
    )


def _c_vendors_party_id_resolves(ctx: dict) -> dict:
    t0 = time.perf_counter()
    ids = {p.get("id") for p in ctx["parties"] if p.get("id")}
    bad = [{"vendor_id": v.get("id"), "party_id": v.get("party_id")}
           for v in ctx["vendors"] if v.get("party_id") and v.get("party_id") not in ids]
    return _mk_invariant(
        id_="p1.vendors.party_id_resolves",
        phase="P1", severity="error",
        description="Every vendors.party_id resolves to a parties row (when set).",
        ok=(len(bad) == 0),
        expected="0 dangling vendor→party refs",
        actual=f"{len(bad)} dangling",
        difference=len(bad),
        tolerance="exact",
        checked_count=len(ctx["vendors"]),
        offenders=bad,
        started_at_perf=t0,
    )


# ─── Master runner ─────────────────────────────────────────────────────────


CHECKS: list[tuple[str, Callable[[dict], dict]]] = [
    # P0 canonical Cash Book
    ("p0.payments.legacy_stamped",              _c_payments_legacy_stamped),
    ("p0.modes.no_unknown_mode",                _c_mode_totals_no_unknown),
    ("p0.cashbook.ids_unique",                  _c_cashbook_ids_unique),
    ("p0.cashbook.transfer_appears_once",       _c_transfer_appears_once_in_cashbook),
    # P1 party identity
    ("p1.parties.unique_active",                _c_parties_unique_active),
    ("p1.parties.normalized_names_current",     _c_parties_normalized_names),
    ("p1.parties.system_ff_intact",             _c_system_ff_intact),
    ("p1.parties.ff_aliases_only_system",       _c_ff_aliases_only_system),
    ("p1.parties.foreign_keys_resolve",         _c_party_id_refs_resolve),
    ("p1.vendors.party_id_resolves",            _c_vendors_party_id_resolves),
    # P3 transfers
    ("p3.transfers.sides_valid",                _c_transfer_sides_valid),
    ("p3.transfers.reversals_valid",            _c_transfer_reversals_valid),
    ("p3.transfers.replacement_no_cycle",       _c_transfer_replacement_no_cycles),
    ("p3.transfers.idempotency_keys_unique",    _c_transfer_idempotency_unique),
    ("p3.transfers.migration_no_dupes",         _c_transfer_migration_no_dupes),
    ("p3.transfers.a2a_net_zero",               _c_transfer_account_to_account_net_zero),
    # P4 partial-shipment revenue
    ("p4.orders.identities",                    _c_p4_per_order_identity),
    # Cross-cutting: allocations
    ("x.cust_alloc.order_resolves",             _c_customer_alloc_orders_resolve),
    ("x.cust_alloc.nonneg_capped_and_cached",   _c_customer_alloc_nonneg_and_capped),
    ("x.orders.total_received_matches",         _c_orders_total_received_matches),
    ("x.purchase_alloc.and_totals",             _c_purchase_alloc_and_totals),
]


async def run_reconcile(db) -> dict:
    """Execute every invariant and return a structured report.
    Read-only — never writes."""
    started = datetime.now(timezone.utc)
    perf0 = time.perf_counter()
    sizes_before = await _collection_sizes(db)
    ctx = await _snapshot(db)

    invariants: list[dict] = []
    for name, fn in CHECKS:
        inv = _run_check(name, lambda fn=fn: fn(ctx))
        invariants.append(inv)

    sizes_after = await _collection_sizes(db)
    ended = datetime.now(timezone.utc)
    duration_ms = round((time.perf_counter() - perf0) * 1000.0, 2)

    concurrent = any(sizes_before[k] != sizes_after[k] for k in sizes_before)
    warnings_list: list[dict] = []
    if concurrent:
        warnings_list.append({
            "code": "concurrent_modification",
            "message": ("One or more collections changed size during reconciliation. "
                        "Rerun for a stable snapshot."),
            "before": sizes_before,
            "after": sizes_after,
        })

    counters = {"total": len(invariants), "passed": 0, "failed": 0,
                "warnings": 0, "errors": 0}
    for inv in invariants:
        st = inv.get("status")
        if st == "passed":
            counters["passed"] += 1
        elif st == "failed":
            counters["failed"] += 1
        elif st == "warning":
            counters["warnings"] += 1
        elif st == "error":
            counters["errors"] += 1

    healthy = (counters["failed"] == 0 and counters["errors"] == 0)

    return {
        "report_version": REPORT_VERSION,
        "engine_version": ENGINE_VERSION,
        "run_status": "completed",
        "healthy": healthy,
        "generated_at": started.isoformat(),
        "started_at": started.isoformat(),
        "completed_at": ended.isoformat(),
        "duration_ms": duration_ms,
        "consistency": "best_effort" if concurrent else "stable",
        "warnings": warnings_list,
        "summary": counters,
        "invariants": invariants,
    }


def summarize(report: dict) -> dict:
    """Compact summary suitable for audit-log storage (no offenders)."""
    return {
        "report_version": report.get("report_version"),
        "engine_version": report.get("engine_version"),
        "run_status": report.get("run_status"),
        "healthy": report.get("healthy"),
        "generated_at": report.get("generated_at"),
        "duration_ms": report.get("duration_ms"),
        "consistency": report.get("consistency"),
        "summary": report.get("summary"),
        "failed_ids": [inv["id"] for inv in report.get("invariants", [])
                       if inv.get("status") in ("failed", "error")],
    }
