"""
Backend tests for the NEW Party Ledger + Customer Payment allocation workflow
(iteration 8 review request).

Covers:
 - GET /api/party-ledger/summary : list + totals
 - GET /api/party-ledger?party=<name> : chronological events, running_balance
 - POST /api/customer-payments   : account_id/name persisted, allocated_total/unallocated
 - Order.total_received / outstanding_balance / payment_status recompute
 - Advance-only payment path
 - Multi-order allocation & multiple payments to one order
 - Shipment CRUD roll-up (revenue only on shipments)
 - Historical data preservation

All test data uses a unique customer prefix so cleanup is safe.
"""
import os
import time
import uuid
import pytest
import requests

# Load from frontend/.env (that's the real Kubernetes-ingressed URL)
def _load_backend_url():
    import re
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                m = re.match(r"^\s*REACT_APP_BACKEND_URL\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip().strip('"').rstrip("/")
    except FileNotFoundError:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set and /app/frontend/.env missing")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

# Unique run identifier so parallel/repeat runs never collide.
STAMP = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
CUST_PREFIX = f"TEST_CUST_QA_{STAMP}"


# ------------------------------------------------------------------ helpers
def _cust(suffix: str = "") -> str:
    return f"{CUST_PREFIX}{('_' + suffix) if suffix else ''}"


def _mk_order(client: str, items, packing=0, shipped_date="2026-01-05"):
    """Create an order + immediately ship all items so invoice_total > 0 (revenue-on-shipment)."""
    payload = {
        "client_name": client,
        "order_date": shipped_date,
        "shipped_date": shipped_date,
        "status": "Confirmed",
        "items": items,
        "packing_cost": packing,
    }
    r = requests.post(f"{API}/orders", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    order = r.json()

    # Ship everything so invoice_total is populated
    ship_items = [{"order_item_id": it["id"], "qty": it["qty"]} for it in order["items"]]
    r2 = requests.post(
        f"{API}/orders/{order['id']}/shipments",
        json={"date": shipped_date, "items": ship_items, "freight_paid": 0, "boxes_shipped": 0},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    return r2.json()


def _make_item(name, qty, rate):
    return {
        "main_category": "Lamps",
        "sub_category": "Table",
        "product_name": name,
        "qty": qty,
        "rate": rate,
        "product_sales": qty * rate,
        "factory_complete": 0,
        "factory_glass": 0,
        "factory_fitting": 0,
        "outside_complete": 0,
        "outside_glass": 0,
        "outside_fitting": 0,
    }


@pytest.fixture(scope="session")
def created_ids():
    ids = {"orders": [], "payments": []}
    yield ids
    # Teardown — remove test-scoped data only.
    for pid in ids["payments"]:
        try:
            requests.delete(f"{API}/customer-payments/{pid}", timeout=10)
        except Exception:
            pass
    for oid in ids["orders"]:
        try:
            requests.delete(f"{API}/orders/{oid}", timeout=10)
        except Exception:
            pass


# ============================================================
#   1. Party Ledger summary
# ============================================================
class TestPartyLedgerSummary:
    def test_summary_returns_shape_and_totals(self, created_ids):
        r = requests.get(f"{API}/party-ledger/summary", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "parties" in data and "total_outstanding" in data and "total_advance" in data
        assert isinstance(data["parties"], list)
        for p in data["parties"][:5]:
            for k in ("party", "total_billed", "total_received", "allocated",
                      "advance", "outstanding", "orders", "payments", "last_txn_date"):
                assert k in p, f"Missing '{k}' in party row: {p}"

    def test_totals_are_consistent(self, created_ids):
        r = requests.get(f"{API}/party-ledger/summary", timeout=15)
        d = r.json()
        sum_out = sum(p["outstanding"] for p in d["parties"] if p["outstanding"] > 0)
        sum_adv = sum(p["advance"] for p in d["parties"])
        # small tolerance for float rounding
        assert abs(sum_out - d["total_outstanding"]) < 1.0
        assert abs(sum_adv - d["total_advance"]) < 1.0


# ============================================================
#   2. Party Ledger detail (chronological)
# ============================================================
class TestPartyLedgerDetail:
    def test_detail_chronological_with_running_balance(self, created_ids):
        cust = _cust("PL_DETAIL")
        # 1st order: 10 × 100 = 1000 (billed)
        o1 = _mk_order(cust, [_make_item("P1", 10, 100)], shipped_date="2026-01-01")
        created_ids["orders"].append(o1["id"])
        # 2nd order: 5 × 200 = 1000 (billed) — later date
        o2 = _mk_order(cust, [_make_item("P2", 5, 200)], shipped_date="2026-01-15")
        created_ids["orders"].append(o2["id"])

        # Payment allocated to o1 for 600 on 2026-01-05
        p = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust,
            "date": "2026-01-05",
            "amount": 600, "mode": "UPI",
            "allocations": [{"order_id": o1["id"], "amount": 600}],
        }, timeout=15).json()
        created_ids["payments"].append(p["id"])

        r = requests.get(f"{API}/party-ledger", params={"party": cust}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["party"] == cust
        assert d["total_billed"] == pytest.approx(2000, abs=1)
        assert d["total_received"] == pytest.approx(600, abs=1)
        assert d["allocated"] == pytest.approx(600, abs=1)
        assert d["advance"] == pytest.approx(0, abs=1)
        assert d["outstanding"] == pytest.approx(1400, abs=1)

        events = d["entries"]
        # 2 invoices + 1 payment
        assert len(events) == 3
        # Chronological order
        dates = [e["date"] for e in events]
        assert dates == sorted(dates)
        # Running balance: +1000, -600, +1000 → 400, 1400
        bals = [e["running_balance"] for e in events]
        assert bals[0] == pytest.approx(1000)
        assert bals[1] == pytest.approx(400)
        assert bals[2] == pytest.approx(1400)

        # Types present
        types = {e["type"] for e in events}
        assert "invoice" in types and "payment" in types


# ============================================================
#   3. Customer Payment CRUD + allocation flow
# ============================================================
class TestCustomerPaymentAllocations:
    def test_create_payment_persists_account_and_computes_split(self, created_ids):
        cust = _cust("ACC_FIELDS")
        o = _mk_order(cust, [_make_item("Lamp", 4, 500)])
        created_ids["orders"].append(o["id"])
        r = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust,
            "date": "2026-01-10",
            "amount": 3000,
            "mode": "UPI",
            "account_id": "acc-test-1",
            "account_name": "HDFC 2222",
            "reference": "UTR12345",
            "allocations": [{"order_id": o["id"], "amount": 2000}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        created_ids["payments"].append(p["id"])
        assert p["account_id"] == "acc-test-1"
        assert p["account_name"] == "HDFC 2222"
        assert p["allocated_total"] == pytest.approx(2000)
        assert p["unallocated"] == pytest.approx(1000)  # advance

    def test_payment_updates_order_status_progression(self, created_ids):
        cust = _cust("PROGRESS")
        o = _mk_order(cust, [_make_item("Chandelier", 1, 5000)])
        oid = o["id"]
        created_ids["orders"].append(oid)
        # Initially unpaid
        got = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got["payment_status"] == "Unpaid"
        assert got["invoice_total"] == pytest.approx(5000)

        # Partial payment 2000 -> Partial
        p1 = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-11", "amount": 2000, "mode": "Cash",
            "allocations": [{"order_id": oid, "amount": 2000}],
        }, timeout=15).json()
        created_ids["payments"].append(p1["id"])
        got = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got["payment_status"] == "Partial"
        assert got["total_received"] == pytest.approx(2000)
        assert got["outstanding_balance"] == pytest.approx(3000)

        # Final payment 3000 -> Paid
        p2 = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-12", "amount": 3000, "mode": "UPI",
            "allocations": [{"order_id": oid, "amount": 3000}],
        }, timeout=15).json()
        created_ids["payments"].append(p2["id"])
        got = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got["payment_status"] == "Paid"
        assert got["total_received"] == pytest.approx(5000)
        assert got["outstanding_balance"] == pytest.approx(0, abs=1)

        # Party ledger shows both payments as Credit events, invoice as Debit
        pl = requests.get(f"{API}/party-ledger", params={"party": cust}, timeout=15).json()
        payment_events = [e for e in pl["entries"] if e["type"] == "payment"]
        assert len(payment_events) == 2
        for pe in payment_events:
            assert pe["credit"] > 0 and pe["debit"] == 0
        # Final running balance ~0
        assert pl["entries"][-1]["running_balance"] == pytest.approx(0, abs=1)

    def test_delete_payment_reverses_order_aggregates(self, created_ids):
        cust = _cust("DEL")
        o = _mk_order(cust, [_make_item("Sconce", 2, 1000)])
        oid = o["id"]
        created_ids["orders"].append(oid)

        p = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-08", "amount": 1500, "mode": "UPI",
            "allocations": [{"order_id": oid, "amount": 1500}],
        }, timeout=15).json()
        pid = p["id"]

        got = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got["payment_status"] == "Partial"
        assert got["total_received"] == pytest.approx(1500)

        r = requests.delete(f"{API}/customer-payments/{pid}", timeout=10)
        assert r.status_code == 200

        got2 = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got2["total_received"] == pytest.approx(0, abs=0.1)
        assert got2["outstanding_balance"] == pytest.approx(2000, abs=0.1)
        assert got2["payment_status"] == "Unpaid"

    def test_split_one_payment_across_two_orders(self, created_ids):
        cust = _cust("SPLIT")
        oa = _mk_order(cust, [_make_item("A", 1, 1000)])
        ob = _mk_order(cust, [_make_item("B", 1, 2000)])
        created_ids["orders"] += [oa["id"], ob["id"]]

        p = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-09",
            "amount": 2500, "mode": "UPI",
            "allocations": [
                {"order_id": oa["id"], "amount": 1000},
                {"order_id": ob["id"], "amount": 1500},
            ],
        }, timeout=15).json()
        created_ids["payments"].append(p["id"])

        ga = requests.get(f"{API}/orders/{oa['id']}", timeout=10).json()
        gb = requests.get(f"{API}/orders/{ob['id']}", timeout=10).json()
        assert ga["total_received"] == pytest.approx(1000)
        assert ga["outstanding_balance"] == pytest.approx(0, abs=1)
        assert ga["payment_status"] == "Paid"
        assert gb["total_received"] == pytest.approx(1500)
        assert gb["outstanding_balance"] == pytest.approx(500, abs=1)
        assert gb["payment_status"] == "Partial"

    def test_advance_payment_no_allocation(self, created_ids):
        cust = _cust("ADV")
        # Create one order so party has an entry — but pay without allocation
        o = _mk_order(cust, [_make_item("Pendant", 1, 800)])
        created_ids["orders"].append(o["id"])
        pre = requests.get(f"{API}/orders/{o['id']}", timeout=10).json()
        pre_outstanding = pre["outstanding_balance"]

        p = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-13",
            "amount": 500, "mode": "UPI", "allocations": [],
        }, timeout=15).json()
        created_ids["payments"].append(p["id"])
        assert p["unallocated"] == pytest.approx(500)
        assert p["allocated_total"] == pytest.approx(0)

        # Order outstanding not reduced by pure advance
        got = requests.get(f"{API}/orders/{o['id']}", timeout=10).json()
        assert got["outstanding_balance"] == pytest.approx(pre_outstanding)

        # Summary reflects advance for this party
        summ = requests.get(f"{API}/party-ledger/summary", timeout=15).json()
        row = next((r for r in summ["parties"] if r["party"] == cust), None)
        assert row is not None
        assert row["advance"] >= 500 - 0.5


# ============================================================
#   4. Outstanding-orders endpoint
# ============================================================
class TestOutstandingOrders:
    def test_returns_only_outstanding_and_sorted_asc(self, created_ids):
        cust = _cust("OS")
        o_old = _mk_order(cust, [_make_item("Old", 1, 100)], shipped_date="2026-01-02")
        o_new = _mk_order(cust, [_make_item("New", 1, 100)], shipped_date="2026-01-20")
        created_ids["orders"] += [o_old["id"], o_new["id"]]

        r = requests.get(f"{API}/customers/{cust}/outstanding-orders", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 2
        ids_in_order = [o["id"] for o in d["orders"]]
        # older order must appear before newer
        assert ids_in_order.index(o_old["id"]) < ids_in_order.index(o_new["id"])

        # Fully pay the old order -> should disappear from outstanding
        p = requests.post(f"{API}/customer-payments", json={
            "customer_name": cust, "date": "2026-01-05", "amount": 100, "mode": "Cash",
            "allocations": [{"order_id": o_old["id"], "amount": 100}],
        }, timeout=15).json()
        created_ids["payments"].append(p["id"])

        d2 = requests.get(f"{API}/customers/{cust}/outstanding-orders", timeout=10).json()
        remaining_ids = [o["id"] for o in d2["orders"]]
        assert o_old["id"] not in remaining_ids
        assert o_new["id"] in remaining_ids


# ============================================================
#   5. Shipments CRUD roll-up
# ============================================================
class TestShipmentsRollup:
    def test_shipment_crud_updates_aggregates(self, created_ids):
        cust = _cust("SHIP")
        # Create an ORDER without shipping (skip the helper)
        payload = {
            "client_name": cust, "order_date": "2026-01-04",
            "status": "Confirmed",
            "items": [_make_item("Wick", 10, 300)],
        }
        o = requests.post(f"{API}/orders", json=payload, timeout=15).json()
        oid = o["id"]
        created_ids["orders"].append(oid)
        assert o.get("operating_revenue", 0) == 0

        item_id = o["items"][0]["id"]

        # Add a shipment for 4 units
        s1 = requests.post(f"{API}/orders/{oid}/shipments", json={
            "date": "2026-01-04",
            "items": [{"order_item_id": item_id, "qty": 4}],
            "freight_paid": 100, "boxes_shipped": 1,
        }, timeout=15).json()
        assert s1["shipped_qty_total"] == pytest.approx(4)
        assert s1["operating_revenue"] > 0
        assert s1["status"] in ("Partially Shipped", "Fully Shipped")

        # Update to 5 units
        sid = s1["shipments"][0]["id"]
        s2 = requests.put(f"{API}/orders/{oid}/shipments/{sid}", json={
            "date": "2026-01-04",
            "items": [{"order_item_id": item_id, "qty": 5}],
            "freight_paid": 100, "boxes_shipped": 1,
        }, timeout=15).json()
        assert s2["shipped_qty_total"] == pytest.approx(5)

        # Delete — revenue drops to 0
        rd = requests.delete(f"{API}/orders/{oid}/shipments/{sid}", timeout=10)
        assert rd.status_code == 200
        got = requests.get(f"{API}/orders/{oid}", timeout=10).json()
        assert got["shipped_qty_total"] == pytest.approx(0)
        assert got["operating_revenue"] == pytest.approx(0)


# ============================================================
#   6. Historical data preservation
# ============================================================
class TestHistoricalPreservation:
    def test_legacy_orders_still_present(self):
        r = requests.get(f"{API}/orders", timeout=15)
        assert r.status_code == 200
        orders = r.json()
        # Filter out any test data — expect legacy set is still ~47
        legacy = [o for o in orders if not (o.get("client_name") or "").startswith("TEST_CUST_QA_")]
        assert len(legacy) >= 40, f"Expected ≥40 legacy orders, got {len(legacy)}"

    def test_customer_payments_endpoint_returns_data(self):
        r = requests.get(f"{API}/customer-payments", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_migrate_is_idempotent(self):
        # calling migrate without force must skip because orders already exist
        r = requests.post(f"{API}/migrate", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "skipped"
