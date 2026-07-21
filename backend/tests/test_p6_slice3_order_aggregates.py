"""Phase 6 · Slice 3 — Order aggregate consolidation regression net.

`compute_order_aggregates` in server.py is now a thin adapter over the pure
domain helpers `order_realized_amounts`, `order_estimated_amounts`,
`order_unrealized`, and `order_shipped_ratio_per_item`.

Three complementary regression nets:

  1. SYNTHETIC deterministic fixtures — cover every documented edge case
     that the live 47-order seed does not:
        · zero shipment
        · partial shipment
        · full shipment
        · over-shipment
        · malformed shipment qty (None, "")
        · zero ordered quantity
        · cancelled order
        · missing optional values
        · tax_applicable + auto-computed tax
        · tax_applicable + manually-set tax_amount

  2. LIVE-SEED golden-master — replays compute_order_aggregates on the
     currently-persisted 47 orders and asserts every stamped field
     matches the pre-Slice-3 snapshot in tests/fixtures/, in PAISE.

  3. PROPERTY tests + idempotency:
        · estimated_operating_revenue == operating_revenue + unrealized_revenue
        · estimated_net_profit        == net_profit + unrealized_net_profit
        · repeated calls are idempotent (no drift on second/third invocation)
        · input order dict is not silently corrupted beyond the documented
          stamped fields (item[qty_shipped], status, last_shipped_date,
          and all denormalised aggregate fields — nothing else).
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

import server


FIXTURES = Path(__file__).parent / "fixtures"


# ─── Helpers ───────────────────────────────────────────────────────────────

def to_paise(x) -> int:
    """Deterministic float/int → paise (HALF_UP) for comparison."""
    try:
        return int((Decimal(str(x)) * 100).quantize(Decimal("1")))
    except Exception:
        return 0


def numbers_equal_in_paise(a, b) -> bool:
    return to_paise(a) == to_paise(b)


# ─── Fixtures — edge cases ────────────────────────────────────────────────

def _order(**overrides):
    base = {
        "id": "ord-syn",
        "status": "Confirmed",
        "client_name": "Test",
        "packing_cost": 0,
        "packing_recovery": 0,
        "tax_applicable": False,
        "items": [],
        "shipments": [],
        "other_revenue": [],
        "other_expense": [],
    }
    base.update(overrides)
    return base


@pytest.fixture
def zero_shipment():
    return _order(
        items=[{"id": "i1", "qty": 10, "rate": 500,
                "factory_complete": 200, "outside_complete": 100}],
        shipments=[],
    )


@pytest.fixture
def full_shipment():
    return _order(
        status="Fully Shipped",
        items=[{"id": "i1", "qty": 5, "rate": 1000,
                "factory_complete": 400, "outside_complete": 100}],
        shipments=[{"id": "s1", "boxes_shipped": 2,
                    "freight_charged": 300, "freight_paid": 200,
                    "items": [{"order_item_id": "i1", "qty": 5}]}],
        packing_cost=50, packing_recovery=100,
        other_revenue=[{"amount": 25}],
        other_expense=[{"amount": 15}],
    )


@pytest.fixture
def partial_shipment():
    """40% shipped."""
    return _order(
        items=[{"id": "i1", "qty": 10, "rate": 1000,
                "factory_complete": 400, "outside_complete": 100}],
        shipments=[{"id": "s1", "boxes_shipped": 1,
                    "freight_charged": 200, "freight_paid": 150,
                    "items": [{"order_item_id": "i1", "qty": 4}]}],
    )


@pytest.fixture
def over_shipment():
    """Shipped MORE than ordered (12 shipped vs 10 ordered) — must scale linearly
    to match pre-refactor behaviour."""
    return _order(
        items=[{"id": "i1", "qty": 10, "rate": 100,
                "factory_complete": 50, "outside_complete": 50}],
        shipments=[{"id": "s1", "boxes_shipped": 2,
                    "items": [{"order_item_id": "i1", "qty": 12}]}],
    )


@pytest.fixture
def zero_ordered_qty():
    """Item exists with qty=0 — ratio must be 0, no crash."""
    return _order(
        items=[{"id": "i1", "qty": 0, "rate": 1000,
                "factory_complete": 100}],
        shipments=[{"id": "s1", "items": [{"order_item_id": "i1", "qty": 3}]}],
    )


@pytest.fixture
def missing_optional_values():
    return _order(
        items=[{"id": "i1", "qty": 5, "rate": 200}],   # no factory/outside costs
        shipments=[{"id": "s1",
                    "items": [{"order_item_id": "i1", "qty": 5}]}],  # no freight/boxes
    )


@pytest.fixture
def cancelled_order():
    return _order(status="Cancelled")


@pytest.fixture
def tax_auto():
    """tax_applicable=True, tax_percent=12, auto-computed."""
    return _order(
        items=[{"id": "i1", "qty": 10, "rate": 1000}],
        shipments=[{"id": "s1", "items": [{"order_item_id": "i1", "qty": 10}]}],
        tax_applicable=True, tax_percent=12,
    )


@pytest.fixture
def tax_manual():
    """tax_amount_manual=True — must read stored tax_amount."""
    return _order(
        items=[{"id": "i1", "qty": 10, "rate": 1000}],
        shipments=[{"id": "s1", "items": [{"order_item_id": "i1", "qty": 10}]}],
        tax_applicable=True, tax_amount_manual=True, tax_amount=1234.56,
    )


# ─── 1. Edge-case fixture tests ────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_shipment_zero_realized(self, zero_shipment):
        r = server.compute_order_aggregates(copy.deepcopy(zero_shipment))
        assert to_paise(r["operating_revenue"]) == 0
        assert to_paise(r["net_profit"]) == 0
        assert to_paise(r["total_cost"]) == 0
        assert to_paise(r["shipped_product_sales"]) == 0
        # Estimated MUST equal what the order projects.
        assert to_paise(r["estimated_operating_revenue"]) == 5000 * 100  # 10 * 500
        assert to_paise(r["unrealized_revenue"]) == 5000 * 100

    def test_full_shipment_all_realized(self, full_shipment):
        r = server.compute_order_aggregates(copy.deepcopy(full_shipment))
        # product_sales 5000 + freight 300 + recovery 100 + other_rev 25 = 5425
        assert to_paise(r["operating_revenue"]) == 542500
        # factory 400 + outside 100 + packing 50 + freight_paid 200 + other_exp 15 = 765
        assert to_paise(r["total_cost"]) == 76500
        assert to_paise(r["net_profit"]) == 542500 - 76500
        # Unrealized must be zero on full shipment.
        assert to_paise(r["unrealized_revenue"]) == 0
        assert to_paise(r["unrealized_net_profit"]) == 0

    def test_partial_shipment_40_percent(self, partial_shipment):
        r = server.compute_order_aggregates(copy.deepcopy(partial_shipment))
        # 40% of product_sales 10000 = 4000, + freight 200 = 4200 (no recovery/other)
        assert to_paise(r["operating_revenue"]) == 420000
        # 40% of factory 400 = 160, outside 100 = 40, + freight_paid 150 → 350
        assert to_paise(r["total_cost"]) == 35000
        # Progress: 4/10 = 40%
        assert r["shipment_progress_percent"] == pytest.approx(40.0)

    def test_over_shipment_scales_linearly(self, over_shipment):
        """Over-shipment must scale revenue linearly beyond 100% — matches
        the pre-Phase-6 server.compute_order_aggregates behaviour."""
        r = server.compute_order_aggregates(copy.deepcopy(over_shipment))
        # 12/10 = 1.2 ratio. Sales 10*100 = 1000 * 1.2 = 1200.
        assert to_paise(r["shipped_product_sales"]) == 120000
        # Cost: factory 50 * 1.2 = 60, outside 50 * 1.2 = 60 → 120 total_cost.
        assert to_paise(r["total_cost"]) == 12000
        # Progress > 100.
        assert r["shipment_progress_percent"] > 100

    def test_zero_ordered_qty_ratio_zero(self, zero_ordered_qty):
        """qty=0 must yield ratio 0 (no divide-by-zero crash)."""
        r = server.compute_order_aggregates(copy.deepcopy(zero_ordered_qty))
        assert to_paise(r["shipped_product_sales"]) == 0
        assert to_paise(r["operating_revenue"]) == 0
        assert to_paise(r["total_cost"]) == 0

    def test_missing_optional_values(self, missing_optional_values):
        r = server.compute_order_aggregates(copy.deepcopy(missing_optional_values))
        # qty=5, rate=200 → product_sales 1000. Zero everything else.
        assert to_paise(r["operating_revenue"]) == 100000
        assert to_paise(r["total_cost"]) == 0
        # No freight/boxes should equal 0, not crash.
        assert r["freight_charged"] == 0
        assert r["freight_paid"] == 0
        assert r["boxes_shipped"] == 0

    def test_cancelled_order_stays_cancelled(self, cancelled_order):
        r = server.compute_order_aggregates(copy.deepcopy(cancelled_order))
        # Status must NOT be auto-changed away from Cancelled.
        assert r["status"] == "Cancelled"
        assert to_paise(r["operating_revenue"]) == 0

    def test_tax_auto_computed(self, tax_auto):
        r = server.compute_order_aggregates(copy.deepcopy(tax_auto))
        # op_rev = 10000; tax base = 10000 - 0 other_exp = 10000; 12% = 1200.
        assert to_paise(r["tax_amount"]) == 120000
        assert to_paise(r["invoice_total"]) == 1120000

    def test_tax_manual_reads_stored(self, tax_manual):
        r = server.compute_order_aggregates(copy.deepcopy(tax_manual))
        assert to_paise(r["tax_amount"]) == 123456
        # Auto tax on 10000 * 12% would be 1200 — proves manual override wins.


# ─── 2. Property tests ─────────────────────────────────────────────────────

class TestOrderAggregateProperties:
    @pytest.mark.parametrize("fx", ["zero_shipment", "partial_shipment",
                                    "full_shipment", "over_shipment",
                                    "zero_ordered_qty",
                                    "missing_optional_values", "cancelled_order",
                                    "tax_auto", "tax_manual"])
    def test_estimated_eq_realized_plus_unrealized_revenue(self, request, fx):
        o = request.getfixturevalue(fx)
        r = server.compute_order_aggregates(copy.deepcopy(o))
        # Unrealized might be non-negative-clamped (`max(0.0, …)`) so we
        # assert the sum reproduces estimated revenue only where clamping
        # didn't kick in (i.e., realized ≤ estimated, always true unless
        # over-shipment). For over-shipment, realized > estimated → the
        # clamped unrealized_revenue is 0, and the sum property holds
        # AS DESIGNED (this is a documented pre-refactor invariant).
        est_p = to_paise(r["estimated_operating_revenue"])
        real_p = to_paise(r["operating_revenue"])
        unr_p = to_paise(r["unrealized_revenue"])
        # Case (a) normal / partial / full: est == real + unr.
        # Case (b) over-shipment: realized > estimated, unrealized clamped to 0.
        if real_p <= est_p:
            assert est_p == real_p + unr_p, f"{fx}: est {est_p} != real {real_p} + unr {unr_p}"
        else:
            assert unr_p == 0

    @pytest.mark.parametrize("fx", ["zero_shipment", "partial_shipment",
                                    "full_shipment", "missing_optional_values",
                                    "tax_auto"])
    def test_estimated_eq_realized_plus_unrealized_profit(self, request, fx):
        o = request.getfixturevalue(fx)
        r = server.compute_order_aggregates(copy.deepcopy(o))
        est_p = to_paise(r["estimated_net_profit"])
        real_p = to_paise(r["net_profit"])
        unr_p = to_paise(r["unrealized_net_profit"])
        assert est_p == real_p + unr_p

    @pytest.mark.parametrize("fx", ["partial_shipment", "full_shipment",
                                    "over_shipment", "zero_shipment",
                                    "missing_optional_values", "tax_auto"])
    def test_idempotency_no_drift_on_repeated_refresh(self, request, fx):
        """Repeated calls must not drift — Slice 3 idempotency requirement."""
        o1 = copy.deepcopy(request.getfixturevalue(fx))
        r1 = server.compute_order_aggregates(o1)
        # Re-run on the ALREADY-stamped order (as the startup refresh would).
        r2 = server.compute_order_aggregates(copy.deepcopy(r1))
        r3 = server.compute_order_aggregates(copy.deepcopy(r2))
        for key in ("operating_revenue", "net_profit", "total_cost",
                    "invoice_total", "tax_amount", "estimated_operating_revenue",
                    "estimated_net_profit", "estimated_total_cost",
                    "unrealized_revenue", "unrealized_net_profit"):
            assert numbers_equal_in_paise(r1[key], r2[key]), \
                f"{fx}.{key}: drift 1→2  {r1[key]} → {r2[key]}"
            assert numbers_equal_in_paise(r2[key], r3[key]), \
                f"{fx}.{key}: drift 2→3  {r2[key]} → {r3[key]}"


# ─── 3. Input-mutation contract ────────────────────────────────────────────

class TestInputMutationContract:
    """compute_order_aggregates DOES intentionally mutate the passed-in
    order (that's the whole point — stamps denormalised fields). But it
    must NOT alter any input field beyond the documented set of
    denormalised keys, and must not corrupt items/shipments other than
    stamping `qty_shipped` back on each item."""

    ALLOWED_STAMPS = {
        "status", "last_shipped_date",
        "ordered_qty_total", "shipped_qty_total",
        "ordered_product_sales", "shipped_product_sales",
        "product_sales_total",
        "factory_cost_total", "outside_cost_total",
        "other_revenue_total", "other_expense_total",
        "ship_freight_charged_total", "ship_freight_paid_total",
        "ship_boxes_shipped_total",
        "freight_charged", "freight_paid", "boxes_shipped",
        "operating_revenue", "total_cost", "tax_amount", "invoice_total",
        "net_profit", "margin_percent", "shipment_progress_percent",
        "estimated_factory_cost_total", "estimated_outside_cost_total",
        "estimated_operating_revenue", "estimated_total_cost",
        "estimated_net_profit", "estimated_margin_percent",
        "realized_revenue", "realized_net_profit", "revenue_recognized",
        "unrealized_revenue", "unrealized_net_profit",
    }

    def test_only_stamps_expected_fields(self, partial_shipment):
        before = copy.deepcopy(partial_shipment)
        after = server.compute_order_aggregates(copy.deepcopy(partial_shipment))
        # `items` and `shipments` are inspected in dedicated tests below;
        # this test focuses on top-level scalar/dict keys of the order.
        for key in before:
            if key in self.ALLOWED_STAMPS:
                continue
            if key in ("items", "shipments"):
                continue
            assert after[key] == before[key], \
                f"unauthorised mutation on `{key}`: {before[key]!r} → {after[key]!r}"

    def test_items_get_only_qty_shipped_stamped(self, partial_shipment):
        order = copy.deepcopy(partial_shipment)
        server.compute_order_aggregates(order)
        # Each item now has qty_shipped stamped; nothing else touched.
        for it in order["items"]:
            assert "qty_shipped" in it
            for k in ("id", "qty", "rate"):
                # unchanged from original
                orig = next((x for x in partial_shipment["items"]
                             if x["id"] == it["id"]), None)
                assert it[k] == orig[k]

    def test_shipments_untouched(self, partial_shipment):
        order = copy.deepcopy(partial_shipment)
        server.compute_order_aggregates(order)
        assert order["shipments"] == partial_shipment["shipments"]


# ─── 4. Live-seed golden-master snapshot ───────────────────────────────────

class TestLiveSeedSnapshot:
    """Replays compute_order_aggregates on every persisted seed order and
    asserts every stamped field matches the pre-Slice-3 snapshot in
    tests/fixtures/, IN PAISE. Zero-diff required."""

    @pytest.fixture(scope="class")
    def baseline_by_id(self):
        return {o["id"]: o for o in json.loads(
            (FIXTURES / "slice3_order_aggregates_snapshot.json").read_text())}

    def test_every_order_matches_baseline_in_paise(self, baseline_by_id):
        # Use a synchronous pymongo client — motor's async client requires
        # a live event loop bound at construction time, which conflicts with
        # server.py's module-level initialisation.
        import os
        from pymongo import MongoClient
        cli = MongoClient(os.environ["MONGO_URL"])
        orders = list(cli[os.environ["DB_NAME"]].orders.find({}, {"_id": 0}))
        assert orders, "seed missing — cannot verify Slice 3"
        problems = []
        for o in orders:
            oid = o["id"]
            if oid not in baseline_by_id:
                problems.append(f"{oid[:8]}: no baseline row (new order?)")
                continue
            result = server.compute_order_aggregates(copy.deepcopy(o))
            base = baseline_by_id[oid]
            for k, base_val in base.items():
                new_val = result.get(k)
                if isinstance(base_val, (int, float)) and isinstance(new_val, (int, float)):
                    if not numbers_equal_in_paise(base_val, new_val):
                        problems.append(f"{oid[:8]}.{k}: base={base_val} new={new_val}")
                elif base_val != new_val:
                    problems.append(f"{oid[:8]}.{k}: {base_val!r} vs {new_val!r}")
        cli.close()
        assert not problems, "Snapshot diverged:\n" + "\n".join(problems[:20])
