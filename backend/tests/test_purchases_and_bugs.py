"""Iteration 9 tests — Vendors + Purchases + Purchase Payments module (Feature A),
Customer Advances KPI (Feature C), and 3 bug fixes (Bug 1: shipment KPI update,
Bug 3: outstanding total). Bug 2 is a frontend UX flow tested via Playwright.

All test data uses TEST_ prefix and is torn down. Legacy 47 orders untouched.
"""
import os
import time
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture
def cleanup_registry():
    reg = {"orders": [], "vendors": [], "purchases": [], "purchase_payments": []}
    yield reg
    # teardown - reverse dependencies
    for pid in reg["purchase_payments"]:
        try: requests.delete(f"{API}/purchase-payments/{pid}", timeout=10)
        except Exception: pass
    for pid in reg["purchases"]:
        try: requests.delete(f"{API}/purchases/{pid}", timeout=10)
        except Exception: pass
    for vid in reg["vendors"]:
        try: requests.delete(f"{API}/vendors/{vid}", timeout=10)
        except Exception: pass
    for oid in reg["orders"]:
        try: requests.delete(f"{API}/orders/{oid}", timeout=10)
        except Exception: pass


def _dash(s):
    r = s.get(f"{API}/dashboard", timeout=15)
    assert r.status_code == 200
    return r.json()["kpis"]


# ================================================================ Bug 1

class TestBug1_ShipmentKpiUpdate:
    def test_shipment_add_updates_dashboard(self, s, cleanup_registry):
        before = _dash(s)
        oid = _create_order(s, "TEST_BoxesBug1_add", "Wall Lights", 5, 1000, cleanup_registry)
        r = s.post(f"{API}/orders/{oid}/shipments", json={
            "date": "2026-02-10", "items": [],
            "boxes_shipped": 8, "freight_charged": 200, "freight_paid": 100,
        }, timeout=15)
        assert r.status_code == 200, r.text
        after = _dash(s)
        assert round(after["boxes_shipped"] - before["boxes_shipped"], 2) == 8
        assert round(after["freight_paid"] - before["freight_paid"], 2) == 100
        assert round(after["freight_charged"] - before["freight_charged"], 2) == 200

    def test_shipment_delete_reverses_dashboard(self, s, cleanup_registry):
        """Regression: dashboard KPI should drop when shipment is deleted."""
        before = _dash(s)
        oid = _create_order(s, "TEST_BoxesBug1_del", "Wall Lights", 5, 1000, cleanup_registry)
        r = s.post(f"{API}/orders/{oid}/shipments", json={
            "date": "2026-02-10", "items": [],
            "boxes_shipped": 8, "freight_charged": 200, "freight_paid": 100,
        }, timeout=15)
        assert r.status_code == 200
        sid = r.json()["shipments"][0]["id"]

        r = s.delete(f"{API}/orders/{oid}/shipments/{sid}", timeout=10)
        assert r.status_code == 200

        rev = _dash(s)
        assert round(rev["boxes_shipped"] - before["boxes_shipped"], 2) == 0, \
            f"boxes_shipped did not drop back after shipment delete (delta {rev['boxes_shipped'] - before['boxes_shipped']})"
        assert round(rev["freight_paid"] - before["freight_paid"], 2) == 0
        assert round(rev["freight_charged"] - before["freight_charged"], 2) == 0


def _create_order(s, client_name, product_name, qty, rate, reg):
    payload = {
        "client_name": client_name,
        "order_date": "2026-02-10",
        "status": "Confirmed",
        "items": [{
            "main_category": "Wall Light",
            "sub_category": "",
            "product_name": product_name,
            "qty": qty, "rate": rate,
        }],
    }
    r = s.post(f"{API}/orders", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    reg["orders"].append(oid)
    return oid


# ================================================================ Feature C

class TestFeatureC_CustomerAdvancesKpi:
    def test_dashboard_has_customer_advances_field(self, s):
        k = _dash(s)
        assert "customer_advances" in k
        assert isinstance(k["customer_advances"], (int, float))
        # also purchase KPIs
        for f in ("purchase_value", "purchase_paid", "purchase_outstanding", "purchase_count"):
            assert f in k, f"missing kpi {f}"

    def test_advance_reflects_unallocated_customer_payment(self, s, cleanup_registry):
        before = _dash(s)["customer_advances"]

        # create a small order so we can allocate against nothing (pure advance)
        cname = f"TEST_ADVKPI_{int(time.time())}"
        pay = {
            "customer_name": cname,
            "date": "2026-02-11",
            "amount": 500,
            "mode": "Cash",
            "allocations": [],
        }
        r = s.post(f"{API}/customer-payments", json=pay, timeout=15)
        assert r.status_code == 200, r.text
        pay_id = r.json()["id"]

        after = _dash(s)["customer_advances"]
        assert round(after - before, 2) == 500, \
            f"customer_advances delta expected +500, got {after - before}"

        # cleanup
        s.delete(f"{API}/customer-payments/{pay_id}", timeout=10)


# ================================================================ Feature A - Vendors

class TestVendorsCrud:
    def test_vendor_crud_full(self, s, cleanup_registry):
        vname = f"TEST_Vendor_{uuid.uuid4().hex[:6]}"
        r = s.post(f"{API}/vendors", json={"name": vname, "phone": "999", "gstin": "ABC"}, timeout=10)
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["name"] == vname
        assert v["phone"] == "999"
        assert v["gstin"] == "ABC"
        assert "id" in v
        vid = v["id"]
        cleanup_registry["vendors"].append(vid)

        # LIST
        r = s.get(f"{API}/vendors", timeout=10)
        assert r.status_code == 200
        assert any(x["id"] == vid for x in r.json())

        # UPDATE
        upd = {"name": vname, "phone": "8888", "gstin": "ABC"}
        r = s.put(f"{API}/vendors/{vid}", json=upd, timeout=10)
        assert r.status_code == 200
        assert r.json()["phone"] == "8888"

        # verify persisted
        r = s.get(f"{API}/vendors", timeout=10)
        assert any(x["id"] == vid and x["phone"] == "8888" for x in r.json())

        # DELETE
        r = s.delete(f"{API}/vendors/{vid}", timeout=10)
        assert r.status_code == 200
        cleanup_registry["vendors"].remove(vid)

        r = s.get(f"{API}/vendors", timeout=10)
        assert not any(x["id"] == vid for x in r.json())


# ================================================================ Feature A - Purchases

class TestPurchases:
    def test_purchase_create_computes_totals(self, s, cleanup_registry):
        vname = f"TEST_Vendor2_{uuid.uuid4().hex[:6]}"
        payload = {
            "vendor_name": vname,
            "purchase_date": "2026-02-15",
            "invoice_no": "INV-1",
            "items": [{"description": "Bolt", "qty": 10, "rate": 20}],
            "freight": 50,
            "tax_applicable": True,
            "tax_percent": 18,
        }
        r = s.post(f"{API}/purchases", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        pid = p["id"]
        cleanup_registry["purchases"].append(pid)

        assert p["subtotal"] == 200, f"subtotal expected 200, got {p['subtotal']}"
        # (200 + 50) * 1.18 = 295
        assert round(p["invoice_total"], 2) == 295.0, f"invoice_total expected 295, got {p['invoice_total']}"
        assert p["payment_status"] == "Unpaid"
        assert p["total_paid"] == 0
        assert round(p["outstanding_balance"], 2) == 295.0

        # a payment of 100
        pay_payload = {
            "vendor_name": vname,
            "date": "2026-02-16",
            "amount": 100,
            "mode": "Cash",
            "allocations": [{"purchase_id": pid, "amount": 100}],
        }
        r = s.post(f"{API}/purchase-payments", json=pay_payload, timeout=15)
        assert r.status_code == 200, r.text
        pay = r.json()
        cleanup_registry["purchase_payments"].append(pay["id"])
        assert pay["allocated_total"] == 100
        assert pay["unallocated"] == 0

        # GET purchase => should be Partial, outstanding 195
        r = s.get(f"{API}/purchases/{pid}", timeout=10)
        assert r.status_code == 200
        p2 = r.json()
        assert p2["total_paid"] == 100
        assert round(p2["outstanding_balance"], 2) == 195.0
        assert p2["payment_status"] == "Partial"

    def test_purchase_payment_advance(self, s, cleanup_registry):
        """Create purchase of 500, pay 800 → allocated 500, unallocated 300 (advance)."""
        vname = f"TEST_VenAdv_{uuid.uuid4().hex[:6]}"
        # snapshot BEFORE creating the purchase so we can measure delta
        before = _dash(s)
        # create purchase with subtotal 500, no tax
        r = s.post(f"{API}/purchases", json={
            "vendor_name": vname,
            "purchase_date": "2026-02-20",
            "invoice_no": "INV-ADV",
            "items": [{"description": "Item", "qty": 1, "rate": 500}],
            "freight": 0,
            "tax_applicable": False,
        }, timeout=15)
        assert r.status_code == 200, r.text
        purchase = r.json()
        pid = purchase["id"]
        cleanup_registry["purchases"].append(pid)
        assert purchase["invoice_total"] == 500

        # payment of 800 with 500 allocated
        r = s.post(f"{API}/purchase-payments", json={
            "vendor_name": vname,
            "date": "2026-02-21",
            "amount": 800,
            "mode": "Cash",
            "allocations": [{"purchase_id": pid, "amount": 500}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        pay = r.json()
        cleanup_registry["purchase_payments"].append(pay["id"])
        assert pay["allocated_total"] == 500
        assert pay["unallocated"] == 300

        # verify purchase is Paid
        p2 = s.get(f"{API}/purchases/{pid}", timeout=10).json()
        assert p2["payment_status"] == "Paid"
        assert round(p2["outstanding_balance"], 2) == 0

        # dashboard KPIs
        after = _dash(s)
        assert round(after["purchase_value"] - before["purchase_value"], 2) == 500
        assert round(after["purchase_paid"] - before["purchase_paid"], 2) == 800
        # outstanding should not change (this purchase is fully paid)
        assert round(after["purchase_outstanding"] - before["purchase_outstanding"], 2) == 0

        # outstanding-purchases for this vendor should be empty
        r = s.get(f"{API}/vendors/{vname}/outstanding-purchases", timeout=10)
        assert r.status_code == 200
        assert r.json() == [], f"expected empty, got {r.json()}"


# ================================================================ Existing regression

class TestRegression:
    def test_dashboard_legacy_kpis_intact(self, s):
        k = _dash(s)
        assert k["order_count"] == 47, f"legacy 47 orders count changed! got {k['order_count']}"
        # revenue ~46.98L
        assert 4600000 <= k["operating_revenue"] <= 4800000, \
            f"revenue drifted: {k['operating_revenue']}"

    def test_orders_list_loads(self, s):
        r = s.get(f"{API}/orders", timeout=15)
        assert r.status_code == 200
        assert len(r.json()) >= 47

    def test_customer_payments_endpoint(self, s):
        r = s.get(f"{API}/customer-payments", timeout=15)
        assert r.status_code == 200

    def test_accounts_endpoint(self, s):
        r = s.get(f"{API}/accounts", timeout=15)
        assert r.status_code == 200
