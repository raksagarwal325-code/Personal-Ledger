"""Phase 6 · Slice 2 — Dashboard consolidation regression net.

Two complementary regression nets:

  1. SYNTHETIC deterministic golden-master (pure) — feeds a scripted
     minimal DB shape into `build_dashboard_kpis` and asserts every
     paise-integer field, ensuring the pure domain composition is
     mathematically stable regardless of the seed.

  2. LIVE-SEED SNAPSHOT (integration, network) — GET /api/dashboard and
     /api/dashboard/breakdown, compare every monetary value to the
     pre-Slice-2 snapshot in tests/fixtures/, IN PAISE. Per the Slice 2
     spec, comparison is paise-integer equality; float/int Python type
     variation is not a semantic difference.

Slice 2 intentional differences (reported to reviewer, accepted):
  * Zero-valued monetary KPIs may now be typed as `float` (0.0) instead
    of `int` (0). Numerical equivalence in paise is preserved.
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

import domain as D


FIXTURES = Path(__file__).parent / "fixtures"
API_BASE = os.environ.get("API_BASE") or "http://localhost:8001"


# ─── Helpers ───────────────────────────────────────────────────────────────

def _to_paise(x: Any) -> int:
    """Rounds to paise via Decimal HALF_UP. Non-numeric → 0."""
    try:
        return int((Decimal(str(x)) * 100).quantize(Decimal("1")))
    except Exception:
        return 0


def _numbers_equivalent_in_paise(a: Any, b: Any) -> bool:
    """Two floats/ints are equivalent iff their paise integers match."""
    return _to_paise(a) == _to_paise(b)


def _walk_and_diff(a: Any, b: Any, path: str = ""):
    """Yield (path, description) for every non-paise-equivalent point.

    * Numbers compared in paise (int/float irrelevant).
    * Dicts must have identical key sets.
    * Lists must have identical length AND identical elements at each index
      (order-preserving comparison; the dashboard already returns lists in
      deterministic sort order).
    * Non-numeric leaves must be exactly equal.
    """
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if not _numbers_equivalent_in_paise(a, b):
                yield path, f"NUM {a!r} vs {b!r} (paise {_to_paise(a)} vs {_to_paise(b)})"
        else:
            yield path, f"TYPE {type(a).__name__} vs {type(b).__name__}: {a!r} vs {b!r}"
        return
    if isinstance(a, dict):
        ak, bk = set(a.keys()), set(b.keys())
        if ak != bk:
            yield path, f"KEY DIFF only-baseline={ak-bk} only-after={bk-ak}"
        for k in ak & bk:
            yield from _walk_and_diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            yield path, f"LEN DIFF {len(a)} vs {len(b)}"
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                yield from _walk_and_diff(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)):
        if not _numbers_equivalent_in_paise(a, b):
            yield path, f"NUM {a} vs {b} (paise diff {_to_paise(b)-_to_paise(a)})"
    else:
        if a != b:
            yield path, f"VAL {a!r} vs {b!r}"


# ─── 1. Synthetic golden-master (PURE, deterministic) ──────────────────────

class TestSyntheticDashboardGoldenMaster:
    """Feeds a scripted fixture directly to `build_dashboard_kpis` and
    asserts every paise-int field. No Mongo, no HTTP. This test remains
    valid regardless of any change to the seed dataset."""

    @pytest.fixture
    def scripted(self):
        orders = [
            {
                "id": "o1", "status": "Fully Shipped", "client_name": "Acme",
                "invoice_total": 12500, "packing_cost": 200, "packing_recovery": 300,
                "tax_applicable": True, "tax_percent": 12,
                "items": [{"id": "i1", "qty": 10, "rate": 1000,
                           "factory_complete": 400, "factory_glass": 100,
                           "factory_fitting": 50}],
                "shipments": [{"id": "s1", "boxes_shipped": 2,
                               "freight_charged": 500, "freight_paid": 300,
                               "items": [{"order_item_id": "i1", "qty": 10}]}],
                "other_revenue": [{"amount": 100}],
                "other_expense": [{"amount": 50}],
                "boxes_used": 3,
            },
            {"id": "o2", "status": "Cancelled", "items": [], "shipments": []},  # excluded
        ]
        cust_pays = [
            {"id": "cp1", "amount": 3000, "mode": "UPI", "unallocated": 0,
             "allocations": [{"order_id": "o1", "amount": 3000}]},
            {"id": "cp2", "amount": 1500, "mode": "",  "unallocated": 200,  # blank → "Other"
             "allocations": [{"order_id": "o1", "amount": 1300}]},
            {"id": "cp3", "amount": 999, "voided": True, "mode": "UPI",
             "unallocated": 0, "allocations": []},                              # excluded
        ]
        purchase_pays = [
            {"id": "pp1", "amount": 2000, "mode": "ICICI",
             "allocations": [{"purchase_id": "pu1", "amount": 2000}]},
            {"id": "pp2", "amount": 1, "reversed": True, "mode": "UPI",
             "allocations": []},                                                # excluded
        ]
        cb_entries = [
            {"id": "cb1", "kind": "general_income", "amount": 400,
             "mode": "Cash", "account_id": "acc-1"},
            {"id": "cb2", "kind": "general_expense", "amount": 150,
             "mode": "UPI", "account_id": "acc-1"},
            {"id": "cb3", "kind": "general_income", "amount": 999,
             "source": "legacy_shim"},                                          # excluded
            {"id": "cb4", "kind": "transfer", "amount": 5000},                  # excluded
        ]
        purchases = [
            {"id": "pu1", "invoice_total": 2500,
             "items": [{"qty": 5, "rate": 500}], "packing_total": 0,
             "freight_total": 0},
        ]
        transfers = [
            {"id": "t1", "kind": "account_to_account", "amount": 1000,
             "from": {"account_id": "a1"}, "to": {"account_id": "a2"}},
            {"id": "t2", "kind": "rakshit_to_ff", "amount": 500,
             "from": {"account_id": "a1"}},
        ]
        return dict(orders=orders, cust_pays=cust_pays,
                    purchase_pays=purchase_pays, cb_entries=cb_entries,
                    purchases=purchases, transfers=transfers)

    def test_composed_kpis_are_exact_paise_integers(self, scripted):
        k = D.build_dashboard_kpis(**scripted)
        # order_count excludes the Cancelled order.
        assert k["order_count"] == 1
        # Receipts: cp1 (3000) + cp2 (1500) + cb1 (400) = 4900 → 490_000
        assert k["received_paise"] == 490_000
        # Payments: pp1 (2000) + cb2 (150) = 2150 → 215_000
        assert k["paid_paise"] == 215_000
        # Advances: cp2 unallocated 200 → 20_000 (cp3 excluded)
        assert k["customer_advances_paise"] == 20_000
        # Purchases: value 2500 → 250_000; paid 2000; outstanding 500 → 50_000
        assert k["purchase_value_paise"] == 250_000
        assert k["purchase_paid_paise"] == 200_000
        assert k["purchase_outstanding_paise"] == 50_000
        # Transfers: 2 active, FF delta = +500 → +50_000 paise
        assert k["transfer_count_active"] == 2
        assert k["ff_settlement_delta_paise"] == 50_000
        # Modes: UPI received = 3000 → 300_000; blank/"Other" (`""`) received = 1500 → 150_000
        assert k["modes_paise"]["UPI"]["received_paise"] == 300_000
        assert k["modes_paise"][""]["received_paise"] == 150_000
        assert k["modes_paise"]["ICICI"]["paid_paise"] == 200_000
        assert k["modes_paise"]["Cash"]["received_paise"] == 40_000  # cb1
        assert k["modes_paise"]["UPI"]["paid_paise"] == 15_000       # cb2

    def test_property_estimated_equals_realized_plus_unrealized(self, scripted):
        # This assertion must hold for the composite too — otherwise the
        # dashboard is showing inconsistent numbers.
        k = D.build_dashboard_kpis(**scripted)
        assert k["estimated_revenue_paise"] == (
            k["operating_revenue_paise"] + k["unrealized_revenue_paise"]
        )
        assert k["estimated_net_profit_paise"] == (
            k["net_profit_paise"] + k["unrealized_net_profit_paise"]
        )

    def test_no_transaction_silently_dropped_by_mode_bucketing(self, scripted):
        """Slice-2 requirement §7: explicit unknown/blank bucket must exist."""
        modes = D.sum_mode_totals(scripted["cust_pays"], scripted["purchase_pays"],
                                  scripted["cb_entries"])
        total_received_via_modes = sum(v["received_paise"] for v in modes.values())
        total_paid_via_modes = sum(v["paid_paise"] for v in modes.values())
        # Compare to sum_received_kpi / sum_paid_kpi — should exactly match.
        assert total_received_via_modes == D.sum_received_kpi(
            scripted["cust_pays"], scripted["cb_entries"])
        assert total_paid_via_modes == D.sum_paid_kpi(
            scripted["purchase_pays"], scripted["cb_entries"])
        # Explicit blank/unknown bucket present.
        assert "" in modes


# ─── 2. Live-seed snapshot comparison (integration) ────────────────────────

def _api_reachable() -> bool:
    try:
        r = httpx.get(f"{API_BASE}/api/", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


API_UP = _api_reachable()


@pytest.mark.skipif(not API_UP, reason=f"API not reachable at {API_BASE}")
class TestLiveDashboardSnapshotAgainstBaseline:
    """Hits the live /api/dashboard + /api/dashboard/breakdown endpoints and
    asserts every monetary value matches the pre-Slice-2 snapshot in
    tests/fixtures/, WITH PAISE-INTEGER COMPARISON.

    Zero-valued fields whose Python type flipped from int → float across
    the refactor are treated as equivalent (paise equality holds).
    """

    def test_dashboard_matches_pre_slice2_snapshot(self):
        baseline = json.loads((FIXTURES / "slice2_dashboard_snapshot.json").read_text())
        # Bug fix (2026-07-22) · Dashboard month filter added the params
        # `month=all|current|previous|YYYY-MM` (default `current`). Snapshot
        # was captured pre-filter (equivalent to `all`), so pin that here.
        r = httpx.get(f"{API_BASE}/api/dashboard",
                      params={"month": "all"}, timeout=15.0)
        assert r.status_code == 200, r.text
        current = r.json()
        # Strip the additive filter-metadata keys so they don't diff
        # against a snapshot captured before the filter existed.
        current = {k: v for k, v in current.items()
                   if k not in ("applied_month", "available_months")}
        problems = list(_walk_and_diff(baseline, current))
        assert not problems, "Live dashboard diverged from pre-Slice-2 snapshot:\n" + \
            "\n".join(f"  {p}: {d}" for p, d in problems)

    def test_dashboard_breakdown_matches_pre_slice2_snapshot(self):
        baseline = json.loads((FIXTURES / "slice2_dashboard_breakdown_snapshot.json").read_text())
        r = httpx.get(f"{API_BASE}/api/dashboard/breakdown", timeout=15.0)
        assert r.status_code == 200, r.text
        current = r.json()
        problems = list(_walk_and_diff(baseline, current))
        assert not problems, "Live dashboard/breakdown diverged from pre-Slice-2 snapshot:\n" + \
            "\n".join(f"  {p}: {d}" for p, d in problems)

    def test_dashboard_endpoint_still_uses_domain_layer(self):
        """Sanity: the dashboard response's mode-series must include an
        'Other' bucket when there are blank/None modes in the source data,
        OR omit it when there aren't. In either case, the total received
        via `modes` must equal the top-level `received` KPI to the paise."""
        r = httpx.get(f"{API_BASE}/api/dashboard",
                      params={"month": "all"}, timeout=15.0).json()
        modes = r.get("modes") or []
        total_received_from_modes = sum(_to_paise(m.get("received")) for m in modes)
        total_paid_from_modes = sum(_to_paise(m.get("paid")) for m in modes)
        assert total_received_from_modes == _to_paise(r["kpis"]["received"])
        assert total_paid_from_modes == _to_paise(r["kpis"]["paid"])

    def test_reconcile_remains_healthy_after_slice2(self):
        # Slice 2 exit criterion: reconcile stays HEALTHY.
        r = httpx.post(f"{API_BASE}/api/auth/login",
                       json={"email": "admin@artisan.local",
                             "password": "Admin@12345"}, timeout=10.0)
        assert r.status_code == 200
        tok = r.json()["access_token"]
        rr = httpx.get(f"{API_BASE}/api/reconcile",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15.0)
        assert rr.status_code == 200
        j = rr.json()
        assert j["healthy"] is True
        assert j["summary"]["failed"] == 0
        assert j["engine_version"] == "P5"  # refactor, not bump


# ─── 3. Endpoint thinness — no duplicated logic left ───────────────────────

class TestEndpointsAreThin:
    """Reads server.py and asserts the dashboard()/dashboard_breakdown()
    functions no longer contain the two banned duplicated patterns:
      * inline `{"reversed":{"$ne":True}, ...}` filter
      * inline mode-bucketing loop
    These now live exclusively in domain.py."""

    def _dashboard_source(self) -> str:
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
        # Extract everything from `async def dashboard(...)` to the next
        # section banner. Accepts any argument list so query params added
        # in later bug fixes (e.g. month filter) don't break the assertion.
        m = re.search(r"async def dashboard\([^)]*\):", src)
        assert m, "async def dashboard(...) not found in server.py"
        start = m.start()
        end = src.index("\n# ==", start)
        return src[start:end]

    def _breakdown_source(self) -> str:
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
        m = re.search(r"async def dashboard_breakdown\([^)]*\):", src)
        assert m, "async def dashboard_breakdown(...) not found in server.py"
        start = m.start()
        end = src.index("\n# ==", start)
        return src[start:end]

    def test_dashboard_has_no_inline_reversed_filter(self):
        assert '"reversed"' not in self._dashboard_source() or \
               '"$ne"' not in self._dashboard_source()

    def test_dashboard_has_no_inline_source_filter(self):
        assert '"legacy_shim"' not in self._dashboard_source()

    def test_dashboard_has_no_manual_mode_bucketing(self):
        # `mode_map = defaultdict` was the previous smoking gun.
        assert "mode_map = defaultdict" not in self._dashboard_source()

    def test_breakdown_has_no_inline_reversed_filter(self):
        assert '"reversed"' not in self._breakdown_source() or \
               '"$ne"' not in self._breakdown_source()

    def test_breakdown_has_no_inline_source_filter(self):
        assert '"legacy_shim"' not in self._breakdown_source()

    def test_dashboard_imports_domain_helpers(self):
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
        for name in ("sum_received_kpi", "sum_paid_kpi", "sum_mode_totals",
                     "is_customer_payment_active", "is_purchase_payment_active",
                     "is_cash_book_entry_canonical", "compute_party_metrics",
                     "from_paise", "to_paise"):
            assert name in src, f"server.py should import `{name}` from domain"
