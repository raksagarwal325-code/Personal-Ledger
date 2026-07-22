"""Bug fix (2026-07-22) — Packing default vendor = Father's Firm / Factory.

Business rule (from user, 2026-07-22):
  • Default packing vendor is Father's Firm / Factory. When packing_cost > 0
    and no explicit packer is selected, the packing purchase is
    auto-linked to SYSTEM_FF_ID.
  • Users can still override with any other vendor for exceptional cases.
  • Packing cost must create/update exactly ONE linked purchase per order
    (deterministic linked_source_key `{order_id}::order::packing`).
  • The FF-linked packing purchase reduces (increases in owed direction)
    the Father's Firm settlement balance — Rakshit owes FF the packing
    amount that FF/Factory pays on his behalf.
  • Preserve vendor payable linkage (vendor_party_id), idempotency,
    edits, reversals, reconciliation.
  • Historical orders (packing_ff_default=False, stamped by startup
    migration) MUST NOT be auto-backfilled — blank packer_name on a
    historical order continues to mean "internal expense, no vendor bill".
  • Only NEW orders (via POST /api/orders) opt in — POST forces
    packing_ff_default=True; PUT preserves the stored flag.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

import httpx
import pytest

API_BASE = "http://localhost:8001"
FF_ID = "system_fathers_firm"


def _admin_bootstrap_or_login() -> str:
    email = "admin@artisan.local"
    password = "Admin@12345"
    try:
        httpx.post(f"{API_BASE}/api/admin/bootstrap",
                   json={"email": email, "password": password, "name": "Admin"},
                   timeout=10.0)
    except Exception:
        pass
    r = httpx.post(f"{API_BASE}/api/auth/login",
                   json={"email": email, "password": password}, timeout=10.0)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, token: str):
    r = httpx.get(f"{API_BASE}{path}", headers=_headers(token), timeout=15.0)
    r.raise_for_status()
    return r.json()


def _post(path: str, token: str, payload):
    r = httpx.post(f"{API_BASE}{path}", headers=_headers(token),
                   json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _put(path: str, token: str, payload):
    r = httpx.put(f"{API_BASE}{path}", headers=_headers(token),
                  json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _delete(path: str, token: str):
    r = httpx.delete(f"{API_BASE}{path}", headers=_headers(token), timeout=15.0)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def token():
    return _admin_bootstrap_or_login()


def _make_order(token, *, client_name, packing_cost=0, packer_name="",
                boxes_used=0, cost_per_box=0):
    """POST a new order with configurable packing fields."""
    payload = {
        "client_name": client_name,
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "Pack test",
            "qty": 1, "rate": 1000, "product_sales": 1000,
        }],
        "boxes_used": boxes_used,
        "cost_per_box": cost_per_box,
        "packing_cost": packing_cost,
        "packer_name": packer_name,
    }
    return _post("/api/orders", token, payload)


def _linked_packing_purchase(token, order_id):
    """Return the (single) auto-linked packing Purchase row, or None."""
    key = f"{order_id}::order::packing"
    all_pur = _get("/api/purchases", token)
    rows = [p for p in all_pur if p.get("linked_source_key") == key]
    return rows[0] if rows else None


def _linked_packing_purchases_all(token, order_id):
    """Return ALL packing Purchase rows for the order (should be ≤1)."""
    key = f"{order_id}::order::packing"
    all_pur = _get("/api/purchases", token)
    return [p for p in all_pur if p.get("linked_source_key") == key]


def _ff_ledger(token):
    return _get(f"/api/party-ledger-v2/parties/{FF_ID}", token)


class TestPackingFfDefault:
    """1 — New order with packing_cost > 0 and blank packer_name auto-links
    to Father's Firm / Factory (default). Preserves vendor_party_id linkage.
    """

    def test_new_order_blank_packer_defaults_to_ff(self, token):
        order = _make_order(token, client_name="Pkg FF Default Client A",
                            packing_cost=500, packer_name="")
        assert order["packing_ff_default"] is True, (
            "New orders must opt in to packing_ff_default")
        pur = _linked_packing_purchase(token, order["id"])
        assert pur is not None, "packing Purchase must be auto-created for new orders"
        assert pur["vendor_party_id"] == FF_ID
        assert pur["source_type"] == "order_packing_purchase"
        assert abs(pur["invoice_total"] - 500) < 0.01
        # Cleanup
        _delete(f"/api/orders/{order['id']}", token)

    """2 — Explicit vendor override: user can select any other vendor for
    exceptional cases. The linked packing purchase is stamped with that
    vendor's canonical party_id (NOT FF)."""

    def test_new_order_explicit_packer_uses_that_vendor(self, token):
        order = _make_order(token, client_name="Pkg FF Default Client B",
                            packing_cost=750, packer_name="Rakesh Packers")
        pur = _linked_packing_purchase(token, order["id"])
        assert pur is not None
        assert pur["vendor_party_id"] != FF_ID, (
            "Explicit non-FF packer must NOT resolve to Father's Firm")
        assert pur["vendor_name"] == "Rakesh Packers"
        assert pur["vendor_party_id"], "must resolve to a canonical party id"
        assert abs(pur["invoice_total"] - 750) < 0.01
        _delete(f"/api/orders/{order['id']}", token)

    """3 — Exactly ONE linked packing purchase per order. Repeated syncs
    (from PUT and shipment writes) never duplicate."""

    def test_exactly_one_packing_purchase_across_edits(self, token):
        order = _make_order(token, client_name="Pkg FF Default Client C",
                            packing_cost=400, packer_name="")
        # First check: one row after create.
        rows = _linked_packing_purchases_all(token, order["id"])
        assert len(rows) == 1
        first_id = rows[0]["id"]

        # PUT — change unrelated field.
        payload = {**order, "notes": "edit-1"}
        _put(f"/api/orders/{order['id']}", token, payload)
        rows = _linked_packing_purchases_all(token, order["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == first_id, "row identity must persist (idempotent)"

        # PUT — change packing_cost. Same row, updated amount.
        payload = {**order, "packing_cost": 650}
        _put(f"/api/orders/{order['id']}", token, payload)
        rows = _linked_packing_purchases_all(token, order["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == first_id
        assert abs(rows[0]["invoice_total"] - 650) < 0.01
        assert rows[0]["vendor_party_id"] == FF_ID
        _delete(f"/api/orders/{order['id']}", token)

    """4 — FF settlement (payable) reflects the auto-linked packing
    purchase. Rakshit owes FF the packing amount FF/Factory pays."""

    def test_ff_settlement_increases_by_packing_amount(self, token):
        # Snapshot FF settlement summary before.
        before = _get("/api/party-ledger-v2/fathers-firm-settlement", token)
        before_bal = float(before.get("balance_signed") or 0)

        # Create an order with packing but no explicit packer → FF default.
        order = _make_order(token, client_name="Pkg FF Default Client D",
                            packing_cost=1200, packer_name="")

        after = _get("/api/party-ledger-v2/fathers-firm-settlement", token)
        after_bal = float(after.get("balance_signed") or 0)
        # Business rule: negative balance = Rakshit owes FF (status "you_pay").
        # Adding a 1200 packing purchase to FF must shift balance in the
        # "Rakshit owes FF" direction by exactly 1200 (or more).
        delta = abs(after_bal - before_bal)
        assert delta >= 1199.99, (
            f"FF settlement must shift by ≥ packing amount 1200; "
            f"got before={before_bal} after={after_bal} delta={delta}"
        )
        # Sanity: direction should be "you_pay" (Rakshit owes FF more).
        assert after_bal <= before_bal + 0.01, (
            f"FF balance_signed must move in the 'you_pay' direction "
            f"(negative): before={before_bal} after={after_bal}"
        )

        # Also verify the derived FF entry surfaces.
        ff_data = _get(f"/api/party-ledger-v2/parties/{FF_ID}", token)
        purchase_entries = [
            e for e in (ff_data.get("entries") or [])
            if e.get("related_order_id") == order["id"]
            or e.get("linked_to_order_id") == order["id"]
        ]
        assert any(e.get("category") == "purchase" for e in purchase_entries), (
            "FF ledger must contain a derived 'purchase' entry for the "
            "FF-default packing purchase"
        )

        pur = _linked_packing_purchase(token, order["id"])
        assert pur is not None
        assert pur["vendor_party_id"] == FF_ID
        _delete(f"/api/orders/{order['id']}", token)

    """5 — Reversal via zeroing packing_cost removes the auto-linked
    purchase (when no payments). Idempotent."""

    def test_zero_packing_cost_removes_linked_purchase(self, token):
        order = _make_order(token, client_name="Pkg FF Default Client E",
                            packing_cost=300, packer_name="")
        assert _linked_packing_purchase(token, order["id"]) is not None

        # Zero it out.
        payload = {**order, "packing_cost": 0}
        _put(f"/api/orders/{order['id']}", token, payload)
        assert _linked_packing_purchase(token, order["id"]) is None
        _delete(f"/api/orders/{order['id']}", token)

    """6 — Reversal via switching from blank → explicit packer moves the
    linkage. Still exactly ONE row per order."""

    def test_switch_from_ff_default_to_explicit_packer(self, token):
        order = _make_order(token, client_name="Pkg FF Default Client F",
                            packing_cost=800, packer_name="")
        pur1 = _linked_packing_purchase(token, order["id"])
        assert pur1 is not None
        assert pur1["vendor_party_id"] == FF_ID

        # Switch to explicit vendor.
        payload = {**order, "packer_name": "Alpha Packing Co"}
        _put(f"/api/orders/{order['id']}", token, payload)
        rows = _linked_packing_purchases_all(token, order["id"])
        assert len(rows) == 1
        assert rows[0]["vendor_party_id"] != FF_ID
        assert rows[0]["vendor_name"] == "Alpha Packing Co"

        # And switch back to blank → back to FF default.
        payload = {**order, "packer_name": ""}
        _put(f"/api/orders/{order['id']}", token, payload)
        rows = _linked_packing_purchases_all(token, order["id"])
        assert len(rows) == 1
        assert rows[0]["vendor_party_id"] == FF_ID
        _delete(f"/api/orders/{order['id']}", token)

    """7 — Historical orders (packing_ff_default=False) are NOT
    auto-backfilled. Blank packer_name on a historical order continues
    to mean "internal expense, no vendor bill"."""

    def test_historical_order_not_auto_backfilled(self, token):
        """Simulate a historical order via direct Mongo insert (bypassing
        POST /orders opt-in). Verify: (a) no auto-linked packing purchase
        exists after insert, and (b) a subsequent PUT preserves the
        packing_ff_default=False flag."""
        import uuid
        import pymongo
        pc = pymongo.MongoClient(os.environ["MONGO_URL"])
        pdb = pc[os.environ["DB_NAME"]]

        hist_id = str(uuid.uuid4())
        item_id = str(uuid.uuid4())
        pdb.orders.insert_one({
            "id": hist_id,
            "client_name": "Pkg FF Default Historical Client",
            "order_date": "2025-01-15",
            "status": "Confirmed",
            "payment_status": "Unpaid",
            "items": [{"id": item_id, "main_category": "Glass",
                       "product_name": "Historical", "qty": 1,
                       "rate": 1000, "product_sales": 1000}],
            "shipments": [],
            "packing_cost": 500,
            "packer_name": "",
            "packing_ff_default": False,   # historical opt-out
            "gst_ff_settle": False,
            "tax_applicable": False,
            "tax_type": "None",
            "tax_percent": 0,
            "tax_amount": 0,
        })
        try:
            # Verify: no auto-linked packing purchase exists (no sync ran).
            rows = _linked_packing_purchases_all(token, hist_id)
            assert rows == [], (
                "Historical order (packing_ff_default=False) must NOT get "
                "an auto-linked packing purchase"
            )

            # Now edit the order via PUT — flag must be preserved (still False).
            payload = {
                "client_name": "Pkg FF Default Historical Client",
                "order_date": "2025-01-15",
                "status": "Confirmed",
                "items": [{"id": item_id, "main_category": "Glass",
                           "product_name": "Historical", "qty": 1,
                           "rate": 1000, "product_sales": 1000}],
                "packing_cost": 500,
                "packer_name": "",
                # payload omits packing_ff_default → default False; PUT
                # preserves the existing stored False → still no linked row.
            }
            _put(f"/api/orders/{hist_id}", token, payload)

            # Re-check: still no auto-linked purchase.
            rows = _linked_packing_purchases_all(token, hist_id)
            assert rows == [], (
                "PUT must preserve packing_ff_default=False — no "
                "retroactive backfill of historical packing entries"
            )

            fetched = _get(f"/api/orders/{hist_id}", token)
            assert fetched["packing_ff_default"] is False
        finally:
            pdb.purchases.delete_many({"linked_to_order_id": hist_id})
            pdb.orders.delete_one({"id": hist_id})
            pc.close()

    """8 — Historical order with EXPLICIT packer_name still auto-links
    (the FF-default opt-out only affects the blank-packer path)."""

    def test_historical_order_with_explicit_packer_still_links(self, token):
        import uuid
        import pymongo
        pc = pymongo.MongoClient(os.environ["MONGO_URL"])
        pdb = pc[os.environ["DB_NAME"]]

        hist_id = str(uuid.uuid4())
        item_id = str(uuid.uuid4())
        pdb.orders.insert_one({
            "id": hist_id,
            "client_name": "Pkg FF Default Historical Client B",
            "order_date": "2025-01-15",
            "status": "Confirmed",
            "payment_status": "Unpaid",
            "items": [{"id": item_id, "main_category": "Glass",
                       "product_name": "Historical B", "qty": 1,
                       "rate": 1000, "product_sales": 1000}],
            "shipments": [],
            "packing_cost": 400,
            "packer_name": "Beta Packers",
            "packing_ff_default": False,
            "gst_ff_settle": False,
            "tax_applicable": False,
            "tax_type": "None",
            "tax_percent": 0,
            "tax_amount": 0,
        })
        try:
            # A PUT edit triggers a sync — explicit packer must still link.
            payload = {
                "client_name": "Pkg FF Default Historical Client B",
                "order_date": "2025-01-15",
                "status": "Confirmed",
                "items": [{"id": item_id, "main_category": "Glass",
                           "product_name": "Historical B", "qty": 1,
                           "rate": 1000, "product_sales": 1000}],
                "packing_cost": 400,
                "packer_name": "Beta Packers",
            }
            _put(f"/api/orders/{hist_id}", token, payload)
            rows = _linked_packing_purchases_all(token, hist_id)
            assert len(rows) == 1
            assert rows[0]["vendor_name"] == "Beta Packers"
            assert rows[0]["vendor_party_id"] != FF_ID
        finally:
            # Cleanup — also delete any auto-created purchase.
            pdb.purchases.delete_many({"linked_to_order_id": hist_id})
            pdb.orders.delete_one({"id": hist_id})
            pc.close()

    """9 — Reconciliation stays healthy after new FF-default packing rows."""

    def test_reconcile_healthy_after_packing_ff_writes(self, token):
        order = _make_order(token, client_name="Pkg FF Reconcile Client",
                            packing_cost=250, packer_name="")
        try:
            report = _get("/api/reconcile", token)
            assert report.get("healthy") is True, (
                f"Reconciliation must remain healthy; got: {report.get('summary')}"
            )
        finally:
            _delete(f"/api/orders/{order['id']}", token)

    """10 — Vendor payable linkage is preserved: the FF-default packing
    Purchase carries vendor_party_id=SYSTEM_FF_ID and shows in the
    outstanding-purchases feed for the FF party."""

    def test_ff_default_packing_appears_in_outstanding_purchases(self, token):
        order = _make_order(token, client_name="Pkg FF Payable Client",
                            packing_cost=650, packer_name="")
        try:
            pur = _linked_packing_purchase(token, order["id"])
            assert pur is not None
            assert pur["vendor_party_id"] == FF_ID
            assert pur["payment_status"] in ("Unpaid", "Partial"), \
                "Fresh packing purchase must not be marked Paid"
            assert abs(pur["outstanding_balance"] - 650) < 0.01
        finally:
            _delete(f"/api/orders/{order['id']}", token)
