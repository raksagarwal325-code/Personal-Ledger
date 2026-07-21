"""Backend tests for the Jan 2026 workflow/settlement iteration.

Covers:
- Enhanced GET /api/orders/{oid}/payments (advance, payment_status, received_by)
- POST /api/orders/{oid}/allocate-advance (in-place, no dup document)
- GET /api/orders/{oid}/timeline
- GET /api/party-ledger-v2/fathers-firm-settlement (single signed balance)
- customer_payments visibility on order after POST/PUT/DELETE
- Dashboard consistency
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
    ship_items = [{"order_item_id": it["id"], "qty": it["qty"]} for it in order["items"]]
    r = client.post(f"{API}/orders/{order['id']}/shipments", json={
        "date": "2026-01-16", "items": ship_items,
        "boxes_shipped": 1, "freight_charged": 0, "freight_paid": 0,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _create_and_ship(client, name, rate=10000):
    payload = {
        "client_name": name,
        "items": [{
            "main_category": "Wall Light", "product_name": "R",
            "qty": 1, "rate": rate, "product_sales": rate,
            "factory_complete": rate * 0.3,
        }],
    }
    r = client.post(f"{API}/orders", json=payload)
    assert r.status_code == 200, r.text
    return _ship_full(client, r.json())


# ==============================================================
# 1. Order payments enrichment + allocate-advance
# ==============================================================
class TestOrderPaymentsEnrichmentAndAdvance:
    order_id = None
    invoice = None
    customer = "TEST_ADV_FLOW"
    payments_created = []

    def test_setup_order(self, client):
        o = _create_and_ship(client, self.customer, rate=10000)
        TestOrderPaymentsEnrichmentAndAdvance.order_id = o["id"]
        TestOrderPaymentsEnrichmentAndAdvance.invoice = o["invoice_total"]
        assert o["invoice_total"] == 10000

    def test_allocated_payment_visible_with_enriched_fields(self, client):
        oid = self.order_id
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": self.customer,
            "date": "2026-02-01",
            "amount": 4000, "mode": "UPI",
            "reference": "TEST-REF-ALLOC-1",
            "allocations": [{"order_id": oid, "amount": 4000}],
        })
        assert r.status_code == 200, r.text
        TestOrderPaymentsEnrichmentAndAdvance.payments_created.append(r.json()["id"])

        p = client.get(f"{API}/orders/{oid}/payments").json()
        assert p["count"] == 1
        assert abs(p["total_received"] - 4000) < 0.5
        row = p["payments"][0]
        assert "payment_status" in row and row["payment_status"] in ("Full", "Partial", "Advance")
        # 4000 == 4000 full allocated -> Full
        assert row["payment_status"] == "Full"
        assert row["allocated_to_this_order"] == 4000
        assert "received_by_party_name" in row

    def test_unallocated_creates_advance_pool(self, client):
        oid = self.order_id
        # Unallocated payment -> advance
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": self.customer,
            "date": "2026-02-02",
            "amount": 3000, "mode": "Cash",
            "reference": "TEST-REF-ADV-1",
            "allocations": [],
        })
        assert r.status_code == 200, r.text
        adv_id = r.json()["id"]
        TestOrderPaymentsEnrichmentAndAdvance.payments_created.append(adv_id)

        p = client.get(f"{API}/orders/{oid}/payments").json()
        assert p["customer_advance_available"] >= 3000 - 0.5
        assert p["advance_payment_id"] is not None
        # Advance payment is not counted as a payment row on the order
        assert p["count"] == 1  # only the earlier allocated one

    def test_allocate_advance_no_duplicate_document(self, client):
        oid = self.order_id
        before = client.get(f"{API}/customer-payments",
                            params={"customer_name": self.customer}).json()
        before_count = len(before)

        p_before = client.get(f"{API}/orders/{oid}/payments").json()
        recv_before = p_before["total_received"]

        r = client.post(f"{API}/orders/{oid}/allocate-advance")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["allocated"] > 0

        after = client.get(f"{API}/customer-payments",
                           params={"customer_name": self.customer}).json()
        assert len(after) == before_count, "No new customer_payments doc must be created"

        p_after = client.get(f"{API}/orders/{oid}/payments").json()
        assert p_after["total_received"] > recv_before + 0.5
        # advance now consumed (fully allocated up to outstanding of 6000, we had 3000 advance)
        assert p_after["customer_advance_available"] < p_before["customer_advance_available"]

    def test_allocate_advance_rejects_when_no_advance(self, client):
        oid = self.order_id
        # No advance left now (consumed above) — expect 400
        r = client.post(f"{API}/orders/{oid}/allocate-advance")
        assert r.status_code == 400, r.text

    def test_allocate_advance_rejects_when_no_outstanding(self, client):
        # Create a fully paid order, then try to allocate an advance to it
        o = _create_and_ship(client, "TEST_NO_OUT", rate=5000)
        oid = o["id"]
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": "TEST_NO_OUT",
            "date": "2026-02-01",
            "amount": 5000, "mode": "UPI",
            "allocations": [{"order_id": oid, "amount": 5000}],
        })
        assert r.status_code == 200
        pay_id = r.json()["id"]
        # Now create a leftover advance for same customer
        r2 = client.post(f"{API}/customer-payments", json={
            "customer_name": "TEST_NO_OUT",
            "date": "2026-02-02", "amount": 1000, "mode": "Cash",
            "allocations": [],
        })
        assert r2.status_code == 200
        adv_pay_id = r2.json()["id"]

        r3 = client.post(f"{API}/orders/{oid}/allocate-advance")
        assert r3.status_code == 400, r3.text

        # cleanup
        client.delete(f"{API}/customer-payments/{pay_id}")
        client.delete(f"{API}/customer-payments/{adv_pay_id}")
        client.delete(f"{API}/orders/{oid}")

    def test_cleanup(self, client):
        for pid in self.payments_created:
            client.delete(f"{API}/customer-payments/{pid}")
        # And any residual for this customer
        pays = client.get(f"{API}/customer-payments",
                          params={"customer_name": self.customer}).json()
        for p in pays:
            client.delete(f"{API}/customer-payments/{p['id']}")
        if self.order_id:
            client.delete(f"{API}/orders/{self.order_id}")


# ==============================================================
# 2. Timeline
# ==============================================================
class TestOrderTimeline:
    order_id = None
    customer = "TEST_TIMELINE"
    pay_id = None

    def test_setup(self, client):
        o = _create_and_ship(client, self.customer, rate=5000)
        TestOrderTimeline.order_id = o["id"]
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": self.customer,
            "date": "2026-02-05", "amount": 2000, "mode": "UPI",
            "allocations": [{"order_id": o["id"], "amount": 2000}],
        })
        assert r.status_code == 200
        TestOrderTimeline.pay_id = r.json()["id"]

    def test_timeline_has_event_types(self, client):
        r = client.get(f"{API}/orders/{self.order_id}/timeline")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["count"] >= 3
        types = [e["type"] for e in j["events"]]
        assert "order_created" in types
        assert "shipment" in types
        assert "payment" in types
        # Sorted chronologically (by date string)
        dates = [e.get("date") or "" for e in j["events"]]
        assert dates == sorted(dates)

    def test_cleanup(self, client):
        if self.pay_id:
            client.delete(f"{API}/customer-payments/{self.pay_id}")
        if self.order_id:
            client.delete(f"{API}/orders/{self.order_id}")


# ==============================================================
# 3. Father's Firm settlement single-signed balance
# ==============================================================
class TestFathersFirmSettlement:
    def test_shape_and_status(self, client):
        r = client.get(f"{API}/party-ledger-v2/fathers-firm-settlement")
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("balance_signed", "amount", "status"):
            assert k in j
        assert j["status"] in ("you_pay", "you_receive", "settled")
        assert j["amount"] >= 0
        # Sign convention: positive signed => you_receive, negative => you_pay
        b = j["balance_signed"]
        if b > 0.5:
            assert j["status"] == "you_receive"
        elif b < -0.5:
            assert j["status"] == "you_pay"
        else:
            assert j["status"] == "settled"
        assert abs(abs(b) - j["amount"]) < 0.5


# ==============================================================
# 4. Reallocation & deletion of a customer_payment
# ==============================================================
class TestReallocationAndDeletion:
    a_id = None
    b_id = None
    pay_id = None
    customer = "TEST_REALLOC"

    def test_setup(self, client):
        a = _create_and_ship(client, self.customer, rate=6000)
        b = _create_and_ship(client, self.customer, rate=4000)
        TestReallocationAndDeletion.a_id = a["id"]
        TestReallocationAndDeletion.b_id = b["id"]

    def test_create_payment_visible_on_order_a(self, client):
        r = client.post(f"{API}/customer-payments", json={
            "customer_name": self.customer,
            "date": "2026-02-10", "amount": 3000, "mode": "UPI",
            "allocations": [{"order_id": self.a_id, "amount": 3000}],
        })
        assert r.status_code == 200, r.text
        TestReallocationAndDeletion.pay_id = r.json()["id"]

        pa = client.get(f"{API}/orders/{self.a_id}/payments").json()
        assert pa["count"] == 1
        assert abs(pa["total_received"] - 3000) < 0.5

    def test_reallocate_to_order_b(self, client):
        # Fetch existing then PUT with allocation moved to B
        existing = client.get(f"{API}/customer-payments/{self.pay_id}").json()
        existing["allocations"] = [{"order_id": self.b_id, "amount": 3000}]
        r = client.put(f"{API}/customer-payments/{self.pay_id}", json=existing)
        assert r.status_code == 200, r.text

        pa = client.get(f"{API}/orders/{self.a_id}/payments").json()
        pb = client.get(f"{API}/orders/{self.b_id}/payments").json()
        assert abs(pa["total_received"]) < 0.5, pa
        assert abs(pb["total_received"] - 3000) < 0.5, pb

    def test_delete_payment_resets_order_b(self, client):
        r = client.delete(f"{API}/customer-payments/{self.pay_id}")
        assert r.status_code == 200
        TestReallocationAndDeletion.pay_id = None
        pb = client.get(f"{API}/orders/{self.b_id}/payments").json()
        assert abs(pb["total_received"]) < 0.5, pb

    def test_cleanup(self, client):
        if self.pay_id:
            client.delete(f"{API}/customer-payments/{self.pay_id}")
        for oid in (self.a_id, self.b_id):
            if oid:
                client.delete(f"{API}/orders/{oid}")


# ==============================================================
# 5. Dashboard consistency
# ==============================================================
class TestDashboardConsistency:
    def test_dashboard_and_party_summary_consistent(self, client):
        d = client.get(f"{API}/dashboard")
        assert d.status_code == 200, d.text
        s = client.get(f"{API}/party-ledger-v2/summary")
        assert s.status_code == 200, s.text
        summary = s.json()
        assert "net_position" in summary

        # Verify net_position ≈ sum of every party's signed balance
        parties = client.get(f"{API}/party-ledger-v2/parties",
                             params={"include_settled": "true"}).json()
        signed_sum = sum(p.get("net_balance", 0) for p in parties.get("parties", []))
        assert abs(signed_sum - summary["net_position"]) < 1.0, (
            signed_sum, summary["net_position"]
        )


# ==============================================================
# 6. Seed-data sanity — Shri Agarwal advance
# ==============================================================
def test_shri_agarwal_has_advance_or_at_least_orders(client):
    """Non-fatal check the seed customer referenced by main agent exists."""
    r = client.get(f"{API}/customers/Shri Agarwal/outstanding-orders")
    assert r.status_code == 200, r.text
