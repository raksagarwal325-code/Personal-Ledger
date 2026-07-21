"""
Backend tests for the unified Purchases-per-item refactor (Jan 2026).

Covers:
  - GET /api/purchase-sources returns Factory first.
  - POST /api/orders with mixed Factory + outside vendor purchase_sources.
  - Linked purchases are upserted (no duplicates) on repeated saves.
  - Zero-out with existing payments keeps a stale purchase, does not delete.
  - DELETE /api/orders blocked when any linked purchase has payments.
  - Validation: purchase row with amount > 0 but no supplier -> 400.
  - Factory row routes to Father's Firm ledger; outside vendor row updates vendor payable.
  - Legacy orders synthesise purchase_sources from factory_*/outside_* fields.
  - Quick-add vendor via POST /api/vendors is immediately usable.
  - Reconciliation: sum(purchase_sources) == legacy sums == sum(linked invoice_totals).
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

TEST_TAG = f"TEST_PS_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- helpers ----------------

def _item_with_sources(product_name, factory_amt=None, outside_vendor_id=None,
                       outside_vendor_name=None, outside_amt=None, rate=1000, qty=1):
    """Build an order item with a Factory row + optional outside vendor row."""
    sources = []
    if factory_amt:
        sources.append({
            "id": str(uuid.uuid4()),
            "supplier_id": "factory",
            "supplier_name": "Factory",
            "complete": factory_amt.get("complete", 0),
            "glass": factory_amt.get("glass", 0),
            "fitting": factory_amt.get("fitting", 0),
        })
    if outside_amt:
        sources.append({
            "id": str(uuid.uuid4()),
            "supplier_id": outside_vendor_id or "",
            "supplier_name": outside_vendor_name or "",
            "complete": outside_amt.get("complete", 0),
            "glass": outside_amt.get("glass", 0),
            "fitting": outside_amt.get("fitting", 0),
        })
    return {
        "id": str(uuid.uuid4()),
        "main_category": "Window", "sub_category": "Sliding",
        "product_name": product_name,
        "qty": qty, "rate": rate,
        "product_sales": qty * rate,
        "purchase_sources": sources,
    }


def _create_order(client, item, client_name=None, order_date="2026-01-15"):
    payload = {
        "client_name": client_name or f"{TEST_TAG}_Cust",
        "site": "Site 1",
        "order_date": order_date,
        "shipped_date": order_date,
        "items": [item],
        "packing_cost": 0, "freight_cost": 0, "other_costs": 0,
        "adjustments": [],
    }
    r = client.post(f"{API}/orders", json=payload)
    return r


created_orders = []
created_vendors = []


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    s = requests.Session()
    for oid in list(created_orders):
        try:
            # Best-effort delete; the API blocks delete when payments exist -> then remove payments/purchases first
            r = s.delete(f"{API}/orders/{oid}")
            if r.status_code == 400:
                # Force cleanup by hitting internal purchases delete
                purs = s.get(f"{API}/purchases").json()
                for p in purs.get("purchases", purs if isinstance(purs, list) else []):
                    if p.get("linked_to_order_id") == oid:
                        pid = p.get("id")
                        try:
                            # try clearing payments then delete
                            s.delete(f"{API}/purchases/{pid}/payments")
                        except Exception:
                            pass
                        s.delete(f"{API}/purchases/{pid}")
                s.delete(f"{API}/orders/{oid}")
        except Exception:
            pass
    for vid in list(created_vendors):
        try:
            s.delete(f"{API}/vendors/{vid}")
        except Exception:
            pass


# ================================================================
# 1. GET /api/purchase-sources
# ================================================================
class TestPurchaseSourcesEndpoint:
    def test_factory_is_first(self, client):
        r = client.get(f"{API}/purchase-sources")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "sources" in data and isinstance(data["sources"], list)
        assert len(data["sources"]) >= 1
        first = data["sources"][0]
        assert first["id"] == "factory"
        assert first.get("protected") is True
        assert first["type"] == "factory"

    def test_all_other_sources_are_vendors(self, client):
        data = client.get(f"{API}/purchase-sources").json()
        for row in data["sources"][1:]:
            assert row["type"] == "vendor"
            assert row.get("protected") is False


# ================================================================
# 2. POST /orders with mixed Factory + outside vendor rows
# ================================================================
class TestOrderCreateWithMixedSources:

    @pytest.fixture(scope="class")
    def outside_vendor(self, client):
        name = f"{TEST_TAG}_Vendor_A"
        r = client.post(f"{API}/vendors", json={"name": name})
        assert r.status_code == 200, r.text
        v = r.json()
        created_vendors.append(v["id"])
        return v

    @pytest.fixture(scope="class")
    def mixed_order(self, client, outside_vendor):
        item = _item_with_sources(
            "TEST_PS_Product",
            factory_amt={"complete": 500, "glass": 200, "fitting": 100},
            outside_vendor_id=outside_vendor["id"],
            outside_vendor_name=outside_vendor["name"],
            outside_amt={"complete": 300, "glass": 100, "fitting": 50},
            rate=5000, qty=1,
        )
        r = _create_order(client, item, client_name=f"{TEST_TAG}_MixedCust")
        assert r.status_code == 200, r.text
        o = r.json()
        created_orders.append(o["id"])
        return o

    def test_response_echoes_purchase_sources(self, mixed_order):
        item = mixed_order["items"][0]
        assert len(item["purchase_sources"]) == 2
        supplier_ids = {s["supplier_id"] for s in item["purchase_sources"]}
        assert "factory" in supplier_ids

    def test_legacy_sums_reflect_factory_row(self, mixed_order):
        item = mixed_order["items"][0]
        assert item["factory_complete"] == 500
        assert item["factory_glass"] == 200
        assert item["factory_fitting"] == 100

    def test_legacy_sums_reflect_outside_row(self, mixed_order):
        item = mixed_order["items"][0]
        assert item["outside_complete"] == 300
        assert item["outside_glass"] == 100
        assert item["outside_fitting"] == 50

    def test_linked_purchases_created(self, client, mixed_order):
        oid = mixed_order["id"]
        purs = client.get(f"{API}/purchases").json()
        rows = purs.get("purchases", purs) if isinstance(purs, dict) else purs
        linked = [p for p in rows if p.get("linked_to_order_id") == oid]
        # 3 categories * 2 sources = 6 rows
        assert len(linked) == 6, f"Expected 6 linked purchases, got {len(linked)}"
        ffs = [p for p in linked if p["vendor_name"] == "Father\u2019s Firm" or p["vendor_name"] == "Father's Firm"]
        assert len(ffs) == 3
        for p in linked:
            assert p["source_type"] == "order_product_purchase"


# ================================================================
# 3. PUT /orders updates linked purchases in place; no duplicates
# ================================================================
class TestOrderUpdateNoDuplicates:

    @pytest.fixture(scope="class")
    def vendor_b(self, client):
        name = f"{TEST_TAG}_Vendor_B"
        r = client.post(f"{API}/vendors", json={"name": name})
        assert r.status_code == 200
        v = r.json()
        created_vendors.append(v["id"])
        return v

    @pytest.fixture(scope="class")
    def order(self, client, vendor_b):
        item = _item_with_sources(
            "TEST_PS_Upd",
            factory_amt={"complete": 400, "glass": 0, "fitting": 0},
            outside_vendor_id=vendor_b["id"], outside_vendor_name=vendor_b["name"],
            outside_amt={"complete": 200, "glass": 0, "fitting": 0},
            rate=1000,
        )
        r = _create_order(client, item, client_name=f"{TEST_TAG}_UpdCust")
        assert r.status_code == 200, r.text
        o = r.json()
        created_orders.append(o["id"])
        return o

    def _linked_for(self, client, oid):
        rows = client.get(f"{API}/purchases").json()
        rows = rows.get("purchases", rows) if isinstance(rows, dict) else rows
        return [p for p in rows if p.get("linked_to_order_id") == oid]

    def test_update_changes_amount_in_place(self, client, order):
        oid = order["id"]
        before = self._linked_for(client, oid)
        # capture factory-complete purchase id
        factory_before = next(p for p in before if (p["vendor_name"].startswith("Father") and p.get("linked_cost_category") == "complete"))
        original_pid = factory_before["id"]

        # PUT with factory complete changed to 700 and outside vendor row removed
        item = order["items"][0]
        item["purchase_sources"] = [s for s in item["purchase_sources"] if s["supplier_id"] == "factory"]
        item["purchase_sources"][0]["complete"] = 700
        payload = {
            "client_name": order["client_name"], "site": order.get("site", ""),
            "order_date": order["order_date"], "shipped_date": order["shipped_date"],
            "items": [item], "packing_cost": 0, "freight_cost": 0, "other_costs": 0,
            "adjustments": [],
        }
        r = client.put(f"{API}/orders/{oid}", json=payload)
        assert r.status_code == 200, r.text

        after = self._linked_for(client, oid)
        # only 1 linked purchase remains (factory complete)
        active = [p for p in after if not p.get("stale")]
        assert len(active) == 1
        assert active[0]["id"] == original_pid  # same doc
        assert abs(active[0]["invoice_total"] - 700) < 0.01

    def test_repeated_put_does_not_duplicate(self, client, order):
        oid = order["id"]
        current = client.get(f"{API}/orders/{oid}").json()
        payload = {
            "client_name": current["client_name"], "site": current.get("site", ""),
            "order_date": current["order_date"], "shipped_date": current["shipped_date"],
            "items": current["items"], "packing_cost": current.get("packing_cost", 0),
            "freight_cost": current.get("freight_cost", 0), "other_costs": current.get("other_costs", 0),
            "adjustments": current.get("adjustments", []),
        }
        before_count = len(self._linked_for(client, oid))
        for _ in range(3):
            r = client.put(f"{API}/orders/{oid}", json=payload)
            assert r.status_code == 200, r.text
        after_count = len(self._linked_for(client, oid))
        assert before_count == after_count


# ================================================================
# 4. Zero-out with payments -> keep as stale
# ================================================================
class TestZeroOutWithPayments:
    @pytest.fixture(scope="class")
    def vendor_c(self, client):
        name = f"{TEST_TAG}_Vendor_C"
        r = client.post(f"{API}/vendors", json={"name": name})
        assert r.status_code == 200
        v = r.json()
        created_vendors.append(v["id"])
        return v

    def test_stale_marked_when_paid(self, client, vendor_c):
        item = _item_with_sources(
            "TEST_PS_Stale",
            factory_amt={"complete": 0, "glass": 0, "fitting": 0},
            outside_vendor_id=vendor_c["id"], outside_vendor_name=vendor_c["name"],
            outside_amt={"complete": 500, "glass": 0, "fitting": 0},
            rate=1000,
        )
        # remove factory row (zero amounts anyway) — build minimal single-source
        item["purchase_sources"] = [s for s in item["purchase_sources"] if s["supplier_id"] != "factory"]
        r = _create_order(client, item, client_name=f"{TEST_TAG}_StaleCust")
        assert r.status_code == 200, r.text
        order = r.json()
        oid = order["id"]
        created_orders.append(oid)

        # Find linked purchase and record a payment on it
        rows = client.get(f"{API}/purchases").json()
        rows = rows.get("purchases", rows) if isinstance(rows, dict) else rows
        linked = [p for p in rows if p.get("linked_to_order_id") == oid]
        assert len(linked) == 1
        pid = linked[0]["id"]

        # Record payment via /api/purchase-payments with allocation
        pay_resp = client.post(f"{API}/purchase-payments", json={
            "vendor_name": vendor_c["name"],
            "amount": 200, "mode": "Cash", "date": "2026-01-16",
            "allocations": [{"purchase_id": pid, "amount": 200}],
            "notes": "TEST_PS partial",
        })
        assert pay_resp.status_code in (200, 201), pay_resp.text

        # Now zero out that source via PUT
        item["purchase_sources"][0]["complete"] = 0
        payload = {
            "client_name": order["client_name"], "site": order.get("site", ""),
            "order_date": order["order_date"], "shipped_date": order["shipped_date"],
            "items": [item], "packing_cost": 0, "freight_cost": 0, "other_costs": 0,
            "adjustments": [],
        }
        r = client.put(f"{API}/orders/{oid}", json=payload)
        assert r.status_code == 200, r.text

        # Check purchase still exists, stale=true, notes has REMOVED FROM ORDER
        rows = client.get(f"{API}/purchases").json()
        rows = rows.get("purchases", rows) if isinstance(rows, dict) else rows
        still = [p for p in rows if p.get("id") == pid]
        assert len(still) == 1
        assert still[0].get("stale") is True
        assert "REMOVED FROM ORDER" in (still[0].get("notes") or "")

        # DELETE order should now be blocked
        r = client.delete(f"{API}/orders/{oid}")
        assert r.status_code == 400
        detail = r.json().get("detail")
        if isinstance(detail, dict):
            assert detail.get("kept_paid", 0) >= 1


# ================================================================
# 5. DELETE order removes unpaid linked purchases
# ================================================================
class TestDeleteOrderRemovesUnpaid:
    def test_delete_unpaid_order(self, client):
        item = _item_with_sources(
            "TEST_PS_Del",
            factory_amt={"complete": 100, "glass": 50, "fitting": 25},
            rate=500,
        )
        r = _create_order(client, item, client_name=f"{TEST_TAG}_DelCust")
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        # don't add to cleanup list since we're deleting here

        r = client.delete(f"{API}/orders/{oid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("deleted") is True
        assert body.get("linked_purchases_removed", 0) >= 1


# ================================================================
# 6. Validation: blank supplier + non-zero amount -> 400
# ================================================================
class TestBlankSupplierValidation:
    def test_blank_supplier_rejected(self, client):
        item = {
            "id": str(uuid.uuid4()),
            "main_category": "Window", "sub_category": "",
            "product_name": "TEST_PS_Blank",
            "qty": 1, "rate": 1000, "product_sales": 1000,
            "purchase_sources": [{
                "id": str(uuid.uuid4()),
                "supplier_id": "", "supplier_name": "",
                "complete": 300, "glass": 0, "fitting": 0,
            }],
        }
        r = _create_order(client, item, client_name=f"{TEST_TAG}_BlankCust")
        assert r.status_code == 400, r.text
        detail = r.json().get("detail")
        if isinstance(detail, dict):
            errs = detail.get("errors") or []
            joined = " ".join(errs).lower()
            assert "supplier" in joined or "needs" in joined
            # cleanup the order that was inserted
            oid = detail.get("order_id")
            if oid:
                created_orders.append(oid)


# ================================================================
# 7. Factory row updates Father's Firm settlement
# ================================================================
class TestFactorySettlement:
    def test_ffs_moves_after_factory_order(self, client):
        before = client.get(f"{API}/party-ledger-v2/fathers-firm-settlement").json()
        before_signed = float(before.get("balance_signed") or 0)

        factory_sum = 300 + 200 + 100  # complete + glass + fitting
        item = _item_with_sources(
            "TEST_PS_FF",
            factory_amt={"complete": 300, "glass": 200, "fitting": 100},
            rate=2000,
        )
        r = _create_order(client, item, client_name=f"{TEST_TAG}_FFCust")
        assert r.status_code == 200, r.text
        created_orders.append(r.json()["id"])

        after = client.get(f"{API}/party-ledger-v2/fathers-firm-settlement").json()
        after_signed = float(after.get("balance_signed") or 0)

        # Factory purchase → Rakshit owes Father's Firm more → you_pay direction (signed goes more negative)
        delta = after_signed - before_signed
        assert abs(abs(delta) - factory_sum) < 1.0, f"Expected FF balance to move by {factory_sum}, got delta={delta}"


# ================================================================
# 8. Outside vendor row updates vendor payables via /purchases
# ================================================================
class TestOutsideVendorPayable:
    def test_vendor_payable_increases(self, client):
        vendor_name = f"{TEST_TAG}_Vendor_D"
        r = client.post(f"{API}/vendors", json={"name": vendor_name})
        assert r.status_code == 200
        vid = r.json()["id"]
        created_vendors.append(vid)

        item = _item_with_sources(
            "TEST_PS_OutsideVendor",
            factory_amt=None,
            outside_vendor_id=vid, outside_vendor_name=vendor_name,
            outside_amt={"complete": 250, "glass": 0, "fitting": 0},
            rate=800,
        )
        # only outside row (factory None)
        item["purchase_sources"] = [s for s in item["purchase_sources"] if s["supplier_id"] != "factory"]
        r = _create_order(client, item, client_name=f"{TEST_TAG}_OutVCust")
        assert r.status_code == 200, r.text
        created_orders.append(r.json()["id"])

        r = client.get(f"{API}/purchases", params={"vendor_name": vendor_name})
        assert r.status_code == 200
        data = r.json()
        rows = data.get("purchases", data) if isinstance(data, dict) else data
        assert any(abs(float(p.get("invoice_total") or 0) - 250) < 0.01 for p in rows)


# ================================================================
# 9. Legacy order -> synthesised purchase_sources on GET
# ================================================================
class TestLegacySynthesis:
    def test_legacy_order_get_returns_synthesised_sources(self, client):
        # Simulate a legacy order: post an order but with old-style factory_*/outside_* fields
        # and no purchase_sources. Then check GET returns synthesised sources.
        # Since API accepts purchase_sources, we manually construct via the model_dump path.
        # Best route: create via API with empty purchase_sources but set the legacy fields via items.
        # OrderItem model accepts factory_*/outside_* directly.
        item = {
            "id": str(uuid.uuid4()),
            "main_category": "Door", "sub_category": "",
            "product_name": "TEST_PS_Legacy",
            "qty": 1, "rate": 5000, "product_sales": 5000,
            "purchase_sources": [],
            "factory_complete": 400, "factory_glass": 100, "factory_fitting": 0,
            "outside_complete": 200, "outside_glass": 0, "outside_fitting": 50,
        }
        r = _create_order(client, item, client_name=f"{TEST_TAG}_LegacyCust")
        # Because purchase_sources is empty, no linked purchases created, no validation errors.
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        created_orders.append(oid)

        # Directly clear purchase_sources in DB via re-fetch and re-put with sources=[]
        # Actually the response will not have synthesised sources since _prep_item was
        # called on create. On GET the code checks `if not it.get("purchase_sources")`
        # and synthesises. Test the GET behaviour.
        r = client.get(f"{API}/orders/{oid}")
        assert r.status_code == 200
        item_g = r.json()["items"][0]
        sources = item_g.get("purchase_sources") or []
        # We should see 2 rows: 1 Factory + 1 Outside (empty supplier)
        assert len(sources) == 2, f"Expected 2 synthesised rows, got {sources}"
        factory_row = next((s for s in sources if s["supplier_id"] == "factory"), None)
        outside_row = next((s for s in sources if s["supplier_id"] == ""), None)
        assert factory_row is not None
        assert factory_row["complete"] == 400 and factory_row["glass"] == 100
        assert outside_row is not None
        assert outside_row["complete"] == 200 and outside_row["fitting"] == 50


# ================================================================
# 10. Quick-add vendor -> immediately in purchase-sources
# ================================================================
class TestQuickAddVendor:
    def test_new_vendor_appears(self, client):
        vname = f"{TEST_TAG}_QuickVendor"
        r = client.post(f"{API}/vendors", json={"name": vname})
        assert r.status_code == 200
        vid = r.json()["id"]
        created_vendors.append(vid)

        r = client.get(f"{API}/purchase-sources")
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["sources"]]
        assert vname in names

        # Use it on an order
        item = _item_with_sources(
            "TEST_PS_UsingQuick",
            outside_vendor_id=vid, outside_vendor_name=vname,
            outside_amt={"complete": 100, "glass": 0, "fitting": 0},
            rate=500,
        )
        item["purchase_sources"] = [s for s in item["purchase_sources"] if s["supplier_id"] != "factory"]
        r = _create_order(client, item, client_name=f"{TEST_TAG}_QuickCust")
        assert r.status_code == 200, r.text
        created_orders.append(r.json()["id"])


# ================================================================
# 11. Reconciliation: sums line up
# ================================================================
class TestReconciliation:
    def test_sums_equal(self, client):
        vname = f"{TEST_TAG}_ReconVendor"
        r = client.post(f"{API}/vendors", json={"name": vname})
        assert r.status_code == 200
        vid = r.json()["id"]
        created_vendors.append(vid)

        item = _item_with_sources(
            "TEST_PS_Recon",
            factory_amt={"complete": 300, "glass": 150, "fitting": 50},
            outside_vendor_id=vid, outside_vendor_name=vname,
            outside_amt={"complete": 200, "glass": 100, "fitting": 25},
            rate=3000,
        )
        r = _create_order(client, item, client_name=f"{TEST_TAG}_ReconCust")
        assert r.status_code == 200, r.text
        o = r.json()
        oid = o["id"]
        created_orders.append(oid)

        item_r = o["items"][0]
        ps_sum = sum(float(s.get("complete") or 0) + float(s.get("glass") or 0) + float(s.get("fitting") or 0)
                     for s in item_r["purchase_sources"])
        legacy_sum = (item_r["factory_complete"] + item_r["factory_glass"] + item_r["factory_fitting"]
                      + item_r["outside_complete"] + item_r["outside_glass"] + item_r["outside_fitting"])
        assert abs(ps_sum - legacy_sum) < 0.01

        rows = client.get(f"{API}/purchases").json()
        rows = rows.get("purchases", rows) if isinstance(rows, dict) else rows
        linked = [p for p in rows if p.get("linked_to_order_id") == oid]
        linked_sum = sum(float(p.get("invoice_total") or 0) for p in linked)
        assert abs(linked_sum - ps_sum) < 0.01
