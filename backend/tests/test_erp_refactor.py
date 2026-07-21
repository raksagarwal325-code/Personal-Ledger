"""ERP Refactor tests — Shipment-based revenue recognition + CustomerPayments allocation.

Covers the review-request scope:
  * Revenue recognized only on shipped qty (0 on order creation without shipments)
  * Shipment CRUD (add/edit/delete) auto-flips order status and recomputes aggregates
  * Legacy 47 orders migrated with 1 auto-shipment, historical KPIs preserved
  * CustomerPayment CRUD with multi-order allocation; unallocated=advance
  * Allocation over-payment guard
  * /api/customer-payments filters incl. only_with_advance
  * /api/sales-payments now sources from customer_payments
  * /api/dashboard operating_revenue == sum of shipped-based aggregates
  * Order response shape contains new fields (shipments[], shipped_qty_total, etc)
"""
import os
import pytest
import requests
from pathlib import Path


def _base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        env = Path("/app/frontend/.env")
        for line in env.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                v = line.split("=", 1)[1].strip()
                break
    return v.rstrip("/") + "/api"


API = _base()


@pytest.fixture(scope="session")
def c():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ------------------------------------------------------------------
# 1. NEW ORDER RESPONSE FIELDS
# ------------------------------------------------------------------
class TestOrderResponseShape:
    def test_new_fields_present(self, c):
        arr = c.get(f"{API}/orders").json()
        assert len(arr) > 0
        o = arr[0]
        for k in ["status", "shipments", "ordered_qty_total", "shipped_qty_total",
                  "shipped_product_sales", "shipment_progress_percent",
                  "last_shipped_date", "total_received", "outstanding_balance"]:
            assert k in o, f"missing new field: {k}"
        assert isinstance(o["shipments"], list)


# ------------------------------------------------------------------
# 2. REVENUE ON SHIPMENT (not on order creation)
# ------------------------------------------------------------------
class TestRevenueOnShipment:
    order_id = None

    def test_create_confirmed_order_no_revenue(self, c):
        payload = {
            "client_name": "TEST_QA ShipRev",
            "order_date": "2026-01-15T00:00:00Z",
            "status": "Confirmed",
            "items": [{
                "main_category": "Chandelier", "sub_category": "Crystal",
                "product_name": "Test-ship", "qty": 100, "rate": 500,
                "product_sales": 50000, "factory_complete": 20000,
            }],
        }
        r = c.post(f"{API}/orders", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        TestRevenueOnShipment.order_id = d["id"]
        # Zero revenue since no shipments
        assert d["shipped_qty_total"] == 0
        assert d["operating_revenue"] == 0
        assert d["net_profit"] == 0
        assert d["ordered_qty_total"] == 100
        assert d["shipments"] == []
        assert d["shipment_progress_percent"] == 0

    def test_partial_shipment_flips_status_and_recognizes_40pct(self, c):
        oid = TestRevenueOnShipment.order_id
        assert oid
        order = c.get(f"{API}/orders/{oid}").json()
        item_id = order["items"][0]["id"]

        ship_payload = {
            "date": "2026-01-20T00:00:00Z",
            "items": [{"order_item_id": item_id, "qty": 40}],
            "boxes_shipped": 3, "freight_charged": 500, "freight_paid": 400,
        }
        r = c.post(f"{API}/orders/{oid}/shipments", json=ship_payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "Partially Shipped"
        assert d["shipped_qty_total"] == 40
        # 40/100 of 50000 = 20000
        assert d["shipped_product_sales"] == 20000
        # operating_revenue = shipped_sales + freight_charged
        assert d["operating_revenue"] == 20500
        # cost = factory_complete * 40/100 = 8000; plus freight_paid=400 => 8400
        assert abs(d["total_cost"] - 8400) < 0.5
        assert abs(d["net_profit"] - 12100) < 0.5
        assert abs(d["shipment_progress_percent"] - 40.0) < 0.01
        assert d["last_shipped_date"]

    def test_second_shipment_completes_and_flips_fully(self, c):
        oid = TestRevenueOnShipment.order_id
        order = c.get(f"{API}/orders/{oid}").json()
        item_id = order["items"][0]["id"]
        ship_payload = {
            "date": "2026-01-25T00:00:00Z",
            "items": [{"order_item_id": item_id, "qty": 60}],
            "boxes_shipped": 4, "freight_charged": 800, "freight_paid": 700,
        }
        r = c.post(f"{API}/orders/{oid}/shipments", json=ship_payload)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "Fully Shipped"
        assert d["shipped_qty_total"] == 100
        assert d["shipped_product_sales"] == 50000
        # Freight totals across both shipments: 500+800=1300 charged, 400+700=1100 paid
        assert abs(d["ship_freight_charged_total"] - 1300) < 0.5
        assert abs(d["ship_freight_paid_total"] - 1100) < 0.5
        assert d["operating_revenue"] == 51300
        # cost: factory_complete 20000 (100% shipped) + freight_paid 1100 = 21100
        assert abs(d["total_cost"] - 21100) < 0.5
        assert abs(d["net_profit"] - 30200) < 0.5

    def test_update_shipment_recomputes(self, c):
        oid = TestRevenueOnShipment.order_id
        order = c.get(f"{API}/orders/{oid}").json()
        sid = order["shipments"][0]["id"]
        item_id = order["items"][0]["id"]
        # Change first shipment qty from 40 → 30
        upd = {
            "id": sid,
            "date": order["shipments"][0]["date"],
            "items": [{"order_item_id": item_id, "qty": 30}],
            "boxes_shipped": 3, "freight_charged": 500, "freight_paid": 400,
        }
        r = c.put(f"{API}/orders/{oid}/shipments/{sid}", json=upd)
        assert r.status_code == 200
        d = r.json()
        # Now total shipped = 30 + 60 = 90 → Partially Shipped
        assert d["shipped_qty_total"] == 90
        assert d["status"] == "Partially Shipped"
        assert d["shipped_product_sales"] == 45000  # 90/100 of 50000

    def test_delete_shipment_recomputes(self, c):
        oid = TestRevenueOnShipment.order_id
        order = c.get(f"{API}/orders/{oid}").json()
        sid_to_delete = order["shipments"][0]["id"]
        r = c.delete(f"{API}/orders/{oid}/shipments/{sid_to_delete}")
        assert r.status_code == 200

        d = c.get(f"{API}/orders/{oid}").json()
        # Only 60-qty shipment remains
        assert d["shipped_qty_total"] == 60
        assert d["status"] == "Partially Shipped"
        assert len(d["shipments"]) == 1

    def test_cleanup(self, c):
        oid = TestRevenueOnShipment.order_id
        if oid:
            c.delete(f"{API}/orders/{oid}")


# ------------------------------------------------------------------
# 3. LEGACY 47 ORDERS MIGRATION
# ------------------------------------------------------------------
class TestLegacyMigration:
    def test_47_orders_fully_shipped(self, c):
        arr = c.get(f"{API}/orders").json()
        # Filter to legacy — no TEST_ prefixed
        legacy = [o for o in arr if not (o.get("client_name") or "").startswith("TEST_QA")]
        assert len(legacy) == 47, f"expected 47 legacy orders, got {len(legacy)}"

        for o in legacy:
            assert o["status"] == "Fully Shipped", \
                f"Order {o['id']} not Fully Shipped: {o['status']}"
            # Exactly 1 auto-shipment
            assert len(o["shipments"]) == 1, \
                f"Order {o['id']} has {len(o['shipments'])} shipments"
            # Shipped qty == ordered qty
            assert abs(o["shipped_qty_total"] - o["ordered_qty_total"]) < 0.01, \
                f"Order {o['id']}: shipped {o['shipped_qty_total']} != ordered {o['ordered_qty_total']}"

    def test_dashboard_kpis_preserved(self, c):
        # Sum legacy orders only (exclude concurrent TEST_QA test orders — this
        # test file runs under pytest-xdist and other classes may have live orders)
        arr = c.get(f"{API}/orders").json()
        legacy = [o for o in arr if not (o.get("client_name") or "").startswith("TEST_QA")]
        legacy_rev = sum(o.get("operating_revenue") or 0 for o in legacy)
        legacy_profit = sum(o.get("net_profit") or 0 for o in legacy)
        # Per PRD/review: ₹46,98,786 and ₹19,74,465
        assert abs(legacy_rev - 4698786.0) < 10.0, \
            f"legacy operating_revenue drift: {legacy_rev}"
        assert abs(legacy_profit - 1974465.0) < 10.0, \
            f"legacy net_profit drift: {legacy_profit}"
        assert len(legacy) == 47


# ------------------------------------------------------------------
# 4. CUSTOMER PAYMENTS + ALLOCATIONS
# ------------------------------------------------------------------
class TestCustomerPayments:
    order_id = None
    payment_id = None

    def test_setup_order(self, c):
        payload = {
            "client_name": "TEST_QA CPay",
            "order_date": "2026-02-01T00:00:00Z",
            "items": [{
                "main_category": "Wall Light", "product_name": "cp-item",
                "qty": 10, "rate": 50000, "product_sales": 500000,
                "factory_complete": 100000,
            }],
        }
        r = c.post(f"{API}/orders", json=payload)
        assert r.status_code == 200
        oid = r.json()["id"]
        # Add a full-shipment to make invoice_total > 0
        order = c.get(f"{API}/orders/{oid}").json()
        ship = {
            "date": "2026-02-02T00:00:00Z",
            "items": [{"order_item_id": order["items"][0]["id"], "qty": 10}],
        }
        c.post(f"{API}/orders/{oid}/shipments", json=ship)
        TestCustomerPayments.order_id = oid
        # Confirm invoice_total is 500000 for later allocation tests
        d = c.get(f"{API}/orders/{oid}").json()
        assert d["invoice_total"] == 500000

    def test_create_payment_with_partial_allocation_creates_advance(self, c):
        oid = TestCustomerPayments.order_id
        payload = {
            "customer_name": "TEST_QA C",
            "date": "2026-02-05",
            "amount": 500000,
            "mode": "UPI",
            "account_id": "",
            "account_name": "Cash",
            "allocations": [{"order_id": oid, "amount": 200000}],
        }
        r = c.post(f"{API}/customer-payments", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        TestCustomerPayments.payment_id = d["id"]
        assert d["allocated_total"] == 200000
        assert d["unallocated"] == 300000

        # Order aggregates recomputed
        o = c.get(f"{API}/orders/{oid}").json()
        assert o["total_received"] == 200000
        assert o["outstanding_balance"] == 300000  # invoice 500000 - 200000
        assert o["payment_status"] == "Partial"

    def test_update_payment_reallocation(self, c):
        pid = TestCustomerPayments.payment_id
        oid = TestCustomerPayments.order_id
        # Reallocate all 500000 to order → paid in full
        payload = {
            "customer_name": "TEST_QA C",
            "date": "2026-02-05",
            "amount": 500000,
            "mode": "UPI",
            "account_name": "Cash",
            "allocations": [{"order_id": oid, "amount": 500000}],
        }
        r = c.put(f"{API}/customer-payments/{pid}", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["allocated_total"] == 500000
        assert d["unallocated"] == 0

        o = c.get(f"{API}/orders/{oid}").json()
        assert o["total_received"] == 500000
        assert o["outstanding_balance"] == 0
        assert o["payment_status"] == "Paid"

    def test_over_allocation_rejected(self, c):
        oid = TestCustomerPayments.order_id
        payload = {
            "customer_name": "TEST_QA Over",
            "amount": 1000,
            "mode": "UPI",
            "allocations": [{"order_id": oid, "amount": 5000}],
        }
        r = c.post(f"{API}/customer-payments", json=payload)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_only_with_advance_filter(self, c):
        # Create a new payment with an advance
        oid = TestCustomerPayments.order_id
        payload = {
            "customer_name": "TEST_QA Adv",
            "date": "2026-02-10",
            "amount": 100000,
            "mode": "Cash",
            "allocations": [{"order_id": oid, "amount": 40000}],
        }
        r = c.post(f"{API}/customer-payments", json=payload)
        pid = r.json()["id"]

        # only_with_advance=true should return this one (advance=60000)
        r2 = c.get(f"{API}/customer-payments", params={"only_with_advance": True})
        assert r2.status_code == 200
        arr = r2.json()
        # Our TEST_QA Adv should appear
        adv_ids = [p["id"] for p in arr if p["customer_name"] == "TEST_QA Adv"]
        assert pid in adv_ids
        # All returned have unallocated>0
        for p in arr:
            assert p["unallocated"] > 0, f"leak: {p}"

        # cleanup this second payment
        c.delete(f"{API}/customer-payments/{pid}")

    def test_filters(self, c):
        # customer_name filter (case-insensitive regex)
        r = c.get(f"{API}/customer-payments", params={"customer_name": "TEST_QA C"})
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) >= 1
        for p in arr:
            assert "test_qa c" in p["customer_name"].lower()

        # mode filter
        r = c.get(f"{API}/customer-payments", params={"mode": "UPI"})
        for p in r.json():
            assert p["mode"] == "UPI"

    def test_delete_payment_drops_order_received(self, c):
        pid = TestCustomerPayments.payment_id
        oid = TestCustomerPayments.order_id
        r = c.delete(f"{API}/customer-payments/{pid}")
        assert r.status_code == 200
        o = c.get(f"{API}/orders/{oid}").json()
        assert o["total_received"] == 0
        assert o["outstanding_balance"] == 500000

    def test_cleanup(self, c):
        oid = TestCustomerPayments.order_id
        if oid:
            c.delete(f"{API}/orders/{oid}")


# ------------------------------------------------------------------
# 5. SALES-PAYMENTS report now uses customer_payments
# ------------------------------------------------------------------
class TestSalesPaymentsSource:
    pid = None

    def test_setup(self, c):
        # Create a fresh customer payment we can look up in the report
        payload = {
            "customer_name": "TEST_QA SP Source",
            "date": "2026-03-15",
            "amount": 15000,
            "mode": "UPI",
            "account_name": "Cash",
            "allocations": [],
        }
        r = c.post(f"{API}/customer-payments", json=payload)
        assert r.status_code == 200
        TestSalesPaymentsSource.pid = r.json()["id"]

    def test_report_contains_customer_payment(self, c):
        r = c.get(f"{API}/sales-payments")
        assert r.status_code == 200
        d = r.json()
        for k in ["count", "total", "payments", "by_account", "by_mode"]:
            assert k in d
        # Find our payment
        ours = [p for p in d["payments"] if p.get("customer_name") == "TEST_QA SP Source"]
        assert len(ours) == 1, f"payment not found in sales-payments: {[p.get('customer_name') for p in d['payments']][:5]}"
        row = ours[0]
        for k in ["amount", "allocated", "advance", "allocations", "mode", "account_name"]:
            assert k in row, f"row missing {k}"
        assert row["amount"] == 15000
        assert row["advance"] == 15000  # nothing allocated
        assert row["allocated"] == 0

    def test_cleanup(self, c):
        if TestSalesPaymentsSource.pid:
            c.delete(f"{API}/customer-payments/{TestSalesPaymentsSource.pid}")


# ------------------------------------------------------------------
# 6. DASHBOARD KPIs source from shipped aggregates
# ------------------------------------------------------------------
class TestDashboardShippedAggregates:
    def test_operating_revenue_equals_sum_of_orders(self, c):
        d = c.get(f"{API}/dashboard").json()
        arr = c.get(f"{API}/orders").json()
        expected = sum(o.get("operating_revenue") or 0 for o in arr)
        assert abs(d["kpis"]["operating_revenue"] - expected) < 1.0

    def test_operating_revenue_matches_shipped_product_sales_plus_freight(self, c):
        arr = c.get(f"{API}/orders").json()
        for o in arr[:20]:  # sample
            expected = ((o.get("shipped_product_sales") or 0)
                        + (o.get("ship_freight_charged_total") or 0)
                        + (o.get("packing_recovery") or 0)
                        + (o.get("other_revenue_total") or 0))
            actual = o.get("operating_revenue") or 0
            assert abs(actual - expected) < 0.5, \
                f"order {o['id']}: revenue {actual} != shipped_sales+freight ({expected})"
