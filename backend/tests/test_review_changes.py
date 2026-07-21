"""Backend tests for review-request change set (Jan 2026):
1. Other Revenue/Expense before tax: tax_base = max(0, operating_revenue - other_expense_total).
2. Tax clamps at 0 when expenses > revenue.
3. Customer payment allocation drives /orders/{id}/payments outstanding & auto payment_status.

NOTE: revenue is only recognized on SHIPPED qty, so we must create a shipment with
matching order_item_id + qty for each order to test tax/invoice numbers.
"""
import os
import pytest
import requests
from pathlib import Path


def _base():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                v = line.split("=", 1)[1].strip()
                break
    return v.rstrip("/")

API = f"{_base()}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _ship_full(client, order):
    """Post a shipment covering all ordered qty (recognises revenue)."""
    ship_items = [{"order_item_id": it["id"], "qty": it["qty"]} for it in order["items"]]
    payload = {
        "date": "2026-01-16",
        "items": ship_items,
        "boxes_shipped": 1,
        "freight_charged": 0,
        "freight_paid": 0,
    }
    r = client.post(f"{API}/orders/{order['id']}/shipments", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ---- Scenario 1: revenue 11000 (10000 product + 1000 other_rev), other_expense 2000, 18% tax
class TestTaxAfterOtherAdjustments:
    order_id = None

    def test_create_order_and_ship(self, client):
        payload = {
            "client_name": "TEST_REV_TAX",
            "order_date": "2026-01-15T00:00:00Z",
            "items": [{
                "main_category": "Chandelier",
                "sub_category": "Crystal",
                "product_name": "T",
                "qty": 1, "rate": 10000, "product_sales": 10000,
                "factory_complete": 3000,
            }],
            "other_revenue": [{"description": "Install", "amount": 1000}],
            "other_expense": [{"description": "Labour", "amount": 2000}],
            "tax_applicable": True,
            "tax_type": "GST",
            "tax_percent": 18,
        }
        r = client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        TestTaxAfterOtherAdjustments.order_id = created["id"]

        # Now ship the full order and re-check aggregates
        d = _ship_full(client, created)

        # operating_revenue = 10000 shipped product + 1000 other_revenue = 11000
        assert d["operating_revenue"] == 11000, d["operating_revenue"]
        assert d["other_expense_total"] == 2000
        # tax_base = 11000 - 2000 = 9000 → tax_amount = 9000 * 0.18 = 1620
        assert d["tax_amount"] == 1620, d["tax_amount"]
        # invoice_total = operating_revenue + tax_amount = 11000 + 1620 = 12620
        assert d["invoice_total"] == 12620, d["invoice_total"]
        # net_profit invariant: revenue - cost (no tax influence)
        assert d["net_profit"] == d["operating_revenue"] - d["total_cost"]

    def test_cleanup(self, client):
        oid = TestTaxAfterOtherAdjustments.order_id
        if oid:
            r = client.delete(f"{API}/orders/{oid}")
            assert r.status_code == 200


# ---- Scenario 2: other_expense > revenue → tax_base clamps to 0
class TestTaxBaseClampsNonNegative:
    def test_expense_exceeds_revenue(self, client):
        payload = {
            "client_name": "TEST_TAX_CLAMP",
            "items": [{
                "main_category": "Wall Light",
                "product_name": "C",
                "qty": 1, "rate": 5000, "product_sales": 5000,
                "factory_complete": 1000,
            }],
            "other_expense": [{"description": "Big", "amount": 10000}],
            "tax_applicable": True,
            "tax_type": "GST",
            "tax_percent": 18,
        }
        r = client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        d = _ship_full(client, created)

        assert d["operating_revenue"] == 5000, d["operating_revenue"]
        assert d["other_expense_total"] == 10000
        assert d["tax_amount"] == 0, f"tax should clamp to 0, got {d['tax_amount']}"
        assert d["invoice_total"] == 5000, d["invoice_total"]

        client.delete(f"{API}/orders/{d['id']}")


# ---- Scenario 3: customer payment allocation → outstanding, total_received, auto payment_status
class TestCustomerPaymentAllocation:
    order_id = None
    invoice_total = None

    def test_create_order_and_ship(self, client):
        payload = {
            "client_name": "TEST_CPAY_ALLOC",
            "items": [{
                "main_category": "Wall Light",
                "product_name": "P",
                "qty": 1, "rate": 8000, "product_sales": 8000,
                "factory_complete": 2000,
            }],
            "tax_applicable": True,
            "tax_type": "GST",
            "tax_percent": 18,
        }
        r = client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        d = _ship_full(client, created)

        TestCustomerPaymentAllocation.order_id = d["id"]
        TestCustomerPaymentAllocation.invoice_total = d["invoice_total"]
        assert d["invoice_total"] == round(8000 * 1.18, 2), d["invoice_total"]
        assert d["payment_status"] == "Unpaid"

    def test_partial_payment_marks_partial(self, client):
        oid = TestCustomerPaymentAllocation.order_id
        inv = TestCustomerPaymentAllocation.invoice_total
        half = round(inv / 2, 2)
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": "TEST_CPAY_ALLOC",
            "date": "2026-02-01",
            "amount": half,
            "mode": "UPI",
            "allocations": [{"order_id": oid, "amount": half}],
        })
        assert r.status_code == 200, r.text

        o = client.get(f"{API}/orders/{oid}").json()
        assert o["payment_status"] == "Partial", o["payment_status"]

        p = client.get(f"{API}/orders/{oid}/payments").json()
        assert abs(p["total_received"] - half) < 0.5, p
        assert abs(p["outstanding"] - (inv - half)) < 0.5, p

    def test_full_payment_marks_paid(self, client):
        oid = TestCustomerPaymentAllocation.order_id
        inv = TestCustomerPaymentAllocation.invoice_total
        p_now = client.get(f"{API}/orders/{oid}/payments").json()
        remaining = round(inv - p_now["total_received"], 2)
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": "TEST_CPAY_ALLOC",
            "date": "2026-02-02",
            "amount": remaining,
            "mode": "Cash",
            "allocations": [{"order_id": oid, "amount": remaining}],
        })
        assert r.status_code == 200, r.text

        o = client.get(f"{API}/orders/{oid}").json()
        assert o["payment_status"] == "Paid", o["payment_status"]

        p = client.get(f"{API}/orders/{oid}/payments").json()
        assert abs(p["outstanding"]) < 0.5, p
        assert abs(p["total_received"] - inv) < 0.5, p

    def test_cleanup(self, client):
        # Delete any customer_payments we created, then the order
        pays = client.get(f"{API}/customer-payments",
                          params={"customer_name": "TEST_CPAY_ALLOC"})
        if pays.status_code == 200:
            for p in pays.json():
                client.delete(f"{API}/customer-payments/{p['id']}")
        oid = TestCustomerPaymentAllocation.order_id
        if oid:
            client.delete(f"{API}/orders/{oid}")
