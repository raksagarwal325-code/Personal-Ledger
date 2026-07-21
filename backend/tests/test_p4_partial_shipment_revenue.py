"""Phase 4 (P1) — Partial-shipment proportional revenue recognition +
Estimated vs Realized profit split.

Invariants under test
---------------------
For an order priced at `rate` per unit for `qty` units, with per-item
factory + outside costs and shipment-level freight/packing:

    * shipped = 0        → realized_revenue == 0
                           realized_net_profit == -(cost_incurred_upfront)
                           estimated_revenue > 0
    * shipped = qty      → realized_revenue == estimated_revenue
                           realized_net_profit == estimated_net_profit
                           unrealized_* == 0
    * 0 < shipped < qty  → realized_product_sales == ratio · estimated_product_sales
                           realized_factory + realized_outside cost also scaled by ratio
                           freight/packing (event-recorded) NOT proportioned

Dashboard aggregates: sum of realized ≤ sum of estimated, and
`unrealized_net_profit == estimated_net_profit - net_profit`.
"""
from __future__ import annotations

import uuid

import pytest
import requests

API = "http://localhost:8001/api"


def _post(p, body): return requests.post(f"{API}{p}", json=body, timeout=10)
def _get(p, params=None): return requests.get(f"{API}{p}", params=params, timeout=10)
def _put(p, body): return requests.put(f"{API}{p}", json=body, timeout=10)
def _delete(p): return requests.delete(f"{API}{p}", timeout=10)


def _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=0,
                freight_paid=0, freight_charged=0):
    """Create an order with a single item + optional shipment. Returns the created order.
    Costs are per-unit factory / outside; server multiplies by qty internally is
    NOT done — factory_complete etc. are absolute totals for that item at full
    ordered qty. So we pass total = per_unit_cost * qty.
    """
    item_id = str(uuid.uuid4())
    payload = {
        "client_name": f"P4 test cust {uuid.uuid4().hex[:6]}",
        "order_date": "2025-01-15",
        "items": [{
            "id": item_id,
            "main_category": "Test",
            "sub_category": "SubTest",
            "product_name": f"SKU-{uuid.uuid4().hex[:4]}",
            "qty": qty,
            "rate": rate,
            "product_sales": qty * rate,
            "purchase_sources": [],
            # Item-level costs are ABSOLUTE for the ordered qty. The refresh
            # applies ratio = shipped/ordered when computing realized cost.
            "factory_complete": factory_cost * qty,
            "factory_glass": 0, "factory_fitting": 0,
            "outside_complete": outside_cost * qty,
            "outside_glass": 0, "outside_fitting": 0,
        }],
        "shipments": ([{
            "id": str(uuid.uuid4()),
            "date": "2025-01-20",
            "items": [{"order_item_id": item_id, "qty": shipped}],
            "boxes_shipped": 0,
            "freight_charged": freight_charged,
            "freight_paid": freight_paid,
            "transporter": "TestExpress",
            "lr_number": "",
            "remarks": "",
        }] if shipped > 0 else []),
        "packing_cost": 0,
        "packing_recovery": 0,
    }
    r = _post("/orders", payload)
    assert r.status_code == 200, r.text
    return r.json()


def _get_order(oid):
    r = _get(f"/orders/{oid}")
    assert r.status_code == 200, r.text
    return r.json()


class TestSingleOrderInvariants:
    def test_no_shipment_realized_zero_estimated_positive(self):
        o = _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=0)
        # no shipments → realized revenue is 0
        assert o["operating_revenue"] == 0
        assert o["realized_revenue"] == 0
        assert o["revenue_recognized"] == 0
        # estimated_revenue = ordered_product_sales (=30000) + 0 freight
        # + 0 packing_recovery + 0 other_revenue = 30000
        assert o["estimated_operating_revenue"] == pytest.approx(30000)
        # estimated_total_cost = factory (5000) + outside (3000)
        assert o["estimated_total_cost"] == pytest.approx(8000)
        assert o["estimated_net_profit"] == pytest.approx(22000)
        # realized net profit == 0 (no revenue, no proportional cost, no other adjustments)
        assert o["net_profit"] == 0
        assert o["realized_net_profit"] == 0
        # unrealized == estimated - realized
        assert o["unrealized_revenue"] == pytest.approx(30000)
        assert o["unrealized_net_profit"] == pytest.approx(22000)
        _delete(f"/orders/{o['id']}")

    def test_full_shipment_realized_equals_estimated(self):
        o = _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=100,
                        freight_paid=200, freight_charged=250)
        # Realized === Estimated for a fully-shipped order.
        assert o["operating_revenue"] == pytest.approx(o["estimated_operating_revenue"])
        assert o["net_profit"] == pytest.approx(o["estimated_net_profit"])
        assert o["realized_revenue"] == pytest.approx(o["estimated_operating_revenue"])
        assert o["realized_net_profit"] == pytest.approx(o["estimated_net_profit"])
        assert o["unrealized_revenue"] == pytest.approx(0)
        assert o["unrealized_net_profit"] == pytest.approx(0)
        assert o["shipment_progress_percent"] == pytest.approx(100.0)
        _delete(f"/orders/{o['id']}")

    def test_partial_60_percent_product_sales_proportional(self):
        # qty=100, rate=300, shipped=60 → 60% product_sales realized
        o = _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=60,
                        freight_paid=200, freight_charged=250)
        # product_sales_total is realized (shipped) product sales
        assert o["product_sales_total"] == pytest.approx(0.6 * 30000)  # 18000
        # Realized costs: factory + outside proportioned; freight_paid recorded fully.
        # factory realized = 0.6 * 5000 = 3000; outside realized = 0.6 * 3000 = 1800
        # freight_paid = 200; total_cost = 5000
        assert o["factory_cost_total"] == pytest.approx(0.6 * 5000)
        assert o["outside_cost_total"] == pytest.approx(0.6 * 3000)
        assert o["total_cost"] == pytest.approx(0.6 * 5000 + 0.6 * 3000 + 200)  # 5000
        # Realized revenue = shipped_product_sales + freight_charged = 18000 + 250 = 18250
        assert o["operating_revenue"] == pytest.approx(18000 + 250)
        assert o["net_profit"] == pytest.approx(18250 - 5000)  # 13250
        # Estimated: full factory + full outside + full freight_paid (already
        # event-recorded) + 0 packing; full product_sales + freight_charged.
        assert o["estimated_factory_cost_total"] == pytest.approx(5000)
        assert o["estimated_outside_cost_total"] == pytest.approx(3000)
        assert o["estimated_total_cost"] == pytest.approx(5000 + 3000 + 200)  # 8200
        assert o["estimated_operating_revenue"] == pytest.approx(30000 + 250)  # 30250
        assert o["estimated_net_profit"] == pytest.approx(30250 - 8200)  # 22050
        # Unrealized deltas
        assert o["unrealized_revenue"] == pytest.approx(30250 - 18250)  # 12000
        assert o["unrealized_net_profit"] == pytest.approx(22050 - 13250)  # 8800
        # Aliases
        assert o["realized_revenue"] == pytest.approx(o["operating_revenue"])
        assert o["realized_net_profit"] == pytest.approx(o["net_profit"])
        assert o["revenue_recognized"] == pytest.approx(o["operating_revenue"])
        _delete(f"/orders/{o['id']}")

    def test_adding_shipment_reduces_unrealized(self):
        o = _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=40)
        unrealized_before = o["unrealized_net_profit"]
        item_id = o["items"][0]["id"]
        # Add another shipment for 30 more units → total shipped becomes 70
        r = _post(f"/orders/{o['id']}/shipments", {
            "id": str(uuid.uuid4()), "date": "2025-01-22",
            "items": [{"order_item_id": item_id, "qty": 30}],
            "boxes_shipped": 0, "freight_charged": 0, "freight_paid": 0,
            "transporter": "", "lr_number": "", "remarks": "",
        })
        assert r.status_code == 200, r.text
        o2 = _get_order(o["id"])
        assert o2["shipped_qty_total"] == pytest.approx(70)
        assert o2["unrealized_net_profit"] < unrealized_before
        assert o2["operating_revenue"] > o["operating_revenue"]
        _delete(f"/orders/{o['id']}")


class TestDashboardAggregates:
    def test_dashboard_exposes_estimated_and_unrealized(self):
        # Create an order with partial shipment so estimated > realized deterministically.
        o = _make_order(qty=100, rate=300, factory_cost=50, outside_cost=30, shipped=50)
        try:
            k = _get("/dashboard").json()["kpis"]
            for key in ("operating_revenue", "net_profit", "estimated_revenue",
                        "estimated_net_profit", "estimated_margin_percent",
                        "realized_revenue", "realized_net_profit",
                        "revenue_recognized",
                        "unrealized_revenue", "unrealized_net_profit"):
                assert key in k, f"dashboard KPI missing: {key}"
            # Aliases must equal the underlying realized values.
            assert k["realized_revenue"] == pytest.approx(k["operating_revenue"])
            assert k["realized_net_profit"] == pytest.approx(k["net_profit"])
            assert k["revenue_recognized"] == pytest.approx(k["operating_revenue"])
            # Sum invariant: unrealized_net_profit == estimated - realized
            assert k["unrealized_net_profit"] == pytest.approx(
                k["estimated_net_profit"] - k["net_profit"])
            # Estimated revenue >= realized revenue (always)
            assert k["estimated_revenue"] + 1e-6 >= k["operating_revenue"]
        finally:
            _delete(f"/orders/{o['id']}")

    def test_full_shipment_dashboard_no_unrealized_delta_from_that_order(self):
        # A fully-shipped order should itself contribute 0 to unrealized deltas.
        # (Delta on dashboard is not reliable under pytest-xdist parallelism, so
        # instead assert the property on the single order + on the invariants of
        # the dashboard response as a whole.)
        o = _make_order(qty=50, rate=100, factory_cost=20, outside_cost=10, shipped=50,
                        freight_paid=100)
        try:
            assert o["unrealized_net_profit"] == pytest.approx(0)
            assert o["unrealized_revenue"] == pytest.approx(0)
            k = _get("/dashboard").json()["kpis"]
            # Global invariant — always holds regardless of concurrent state.
            assert k["unrealized_net_profit"] == pytest.approx(
                k["estimated_net_profit"] - k["net_profit"])
            assert k["unrealized_revenue"] >= 0
        finally:
            _delete(f"/orders/{o['id']}")
