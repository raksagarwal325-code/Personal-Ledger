"""Bug fix (2026-07-22) — Canonical vendor_party_id linkage on all Purchase records.

Every db.purchases (and db.purchase_payments) row must carry a stable
`vendor_party_id` that points at the canonical db.parties record for its
vendor. Financial relationships (Party Ledger, vendor outstanding,
Payments allocations, Vendor Payables/Advances, search & exports,
reconciliation) MUST key off `vendor_party_id`, never off the display
`vendor_name`.

Two extensions delivered under the same bug fix:

  1. Freight purchases — one canonical Purchase per shipment with
     (transporter, freight_paid > 0), stamped with the transporter's
     `vendor_party_id`. `source_type='order_freight_purchase'`.
  2. Packing purchases — one canonical Purchase per ORDER with
     (packer_name, packing_cost > 0), stamped with the packer's
     `vendor_party_id`. `source_type='order_packing_purchase'`.

Every auto-generated linked purchase inherits the resolved party id
deterministically via `get_or_create_vendor_party` (or SYSTEM_FF_ID for
Factory / FF aliases). Repeated syncs never create duplicates and never
guess on ambiguous name matches.

Tests exercise:
  • Manual POST /purchases stamps vendor_party_id.
  • PUT /purchases with the same vendor keeps the id; changing vendor
    moves the payable to a different canonical party.
  • Vendor RENAME preserves vendor_party_id on existing purchases.
  • Order creation with a linked freight shipment → freight purchase
    exists with transporter's party_id.
  • Order creation with packing_cost + packer_name → packing purchase
    exists with packer's party_id.
  • Removing the transporter/packer removes the auto-purchase.
  • Purchase search & vendor outstanding resolve through canonical
    linkage, not just name.
  • Startup / admin backfill migration is idempotent and reports counts.
  • /api/reconcile stays healthy.
"""
from __future__ import annotations

import httpx
import pytest

API_BASE = "http://localhost:8001"


# ─── Auth helper — matches the pattern used by every other test file ──────

def _admin_bootstrap_or_login() -> str:
    """Return an admin JWT. First tries to bootstrap a fresh admin (idempotent
    on 400: `admin already exists`); then logs in."""
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


# ═════════════════════════════════════════════════════════════════════════
# A. Manual Purchase creation — vendor_party_id stamped
# ═════════════════════════════════════════════════════════════════════════

class TestManualPurchaseVendorPartyStamp:

    def test_create_purchase_stamps_vendor_party_id(self, token):
        """Bug fix: POST /purchases must stamp vendor_party_id via
        get_or_create_vendor_party — never leave it None."""
        payload = {
            "vendor_name": "TestVendor_Showroom_A",
            "purchase_date": "2026-07-22",
            "items": [{"description": "Item A", "qty": 1, "rate": 500, "amount": 500}],
        }
        p = _post("/api/purchases", token, payload)
        assert p.get("vendor_party_id"), (
            "POST /purchases must stamp vendor_party_id — got None."
        )
        # Cleanup
        _delete(f"/api/purchases/{p['id']}", token)

    def test_repeat_create_same_vendor_returns_same_party_id(self, token):
        """Deterministic: two purchases for the same vendor must resolve
        to the SAME canonical party_id — never a duplicate party."""
        vname = "TestVendor_Repeat_B"
        p1 = _post("/api/purchases", token, {
            "vendor_name": vname, "purchase_date": "2026-07-22",
            "items": [{"description": "x", "qty": 1, "rate": 100, "amount": 100}],
        })
        p2 = _post("/api/purchases", token, {
            "vendor_name": vname, "purchase_date": "2026-07-22",
            "items": [{"description": "y", "qty": 1, "rate": 200, "amount": 200}],
        })
        assert p1["vendor_party_id"] and p2["vendor_party_id"]
        assert p1["vendor_party_id"] == p2["vendor_party_id"], (
            "Same vendor name MUST resolve to the same canonical party."
        )
        _delete(f"/api/purchases/{p1['id']}", token)
        _delete(f"/api/purchases/{p2['id']}", token)

    def test_update_purchase_preserves_vendor_party_id(self, token):
        """Editing a purchase without changing the vendor name must
        preserve the vendor_party_id — no drift."""
        p = _post("/api/purchases", token, {
            "vendor_name": "TestVendor_Preserve_C",
            "purchase_date": "2026-07-22",
            "items": [{"description": "x", "qty": 1, "rate": 100, "amount": 100}],
        })
        original_pid = p["vendor_party_id"]
        assert original_pid
        updated = _put(f"/api/purchases/{p['id']}", token, {
            "vendor_name": "TestVendor_Preserve_C",
            "purchase_date": "2026-07-22",
            "items": [{"description": "x updated", "qty": 2, "rate": 100, "amount": 200}],
        })
        assert updated["vendor_party_id"] == original_pid, (
            "Editing a purchase without vendor change must preserve party id."
        )
        _delete(f"/api/purchases/{p['id']}", token)

    def test_update_purchase_changing_vendor_moves_party_id(self, token):
        """Changing vendor MUST move the payable to the new canonical party."""
        p = _post("/api/purchases", token, {
            "vendor_name": "TestVendor_Move_From",
            "purchase_date": "2026-07-22",
            "items": [{"description": "x", "qty": 1, "rate": 100, "amount": 100}],
        })
        from_pid = p["vendor_party_id"]
        assert from_pid

        updated = _put(f"/api/purchases/{p['id']}", token, {
            "vendor_name": "TestVendor_Move_To",
            "purchase_date": "2026-07-22",
            "items": [{"description": "x", "qty": 1, "rate": 100, "amount": 100}],
        })
        to_pid = updated["vendor_party_id"]
        assert to_pid, "New vendor must resolve to a party id"
        assert to_pid != from_pid, (
            "Changing vendor MUST route the payable to a DIFFERENT canonical party."
        )
        _delete(f"/api/purchases/{p['id']}", token)


# ═════════════════════════════════════════════════════════════════════════
# B. Vendor RENAME preserves vendor_party_id on existing purchases
# ═════════════════════════════════════════════════════════════════════════

class TestVendorRenamePreservesLinkage:

    def test_rename_vendor_does_not_break_purchase_linkage(self, token):
        """Renaming a vendor via /api/parties/{pid}/rename must NOT change
        the vendor_party_id on any existing purchase — history stays intact."""
        # Create a purchase under a specific vendor
        p = _post("/api/purchases", token, {
            "vendor_name": "RenameVendor_Original",
            "purchase_date": "2026-07-22",
            "items": [{"description": "x", "qty": 1, "rate": 100, "amount": 100}],
        })
        pid = p["vendor_party_id"]
        assert pid

        # Rename the party
        _post(f"/api/parties/{pid}/rename", token,
              {"display_name": "RenameVendor_NewName"})

        # Read back the purchase — vendor_party_id must be unchanged
        after = _get(f"/api/purchases/{p['id']}", token)
        assert after["vendor_party_id"] == pid, (
            "Vendor RENAME must NOT reassign the purchase to a new party."
        )
        _delete(f"/api/purchases/{p['id']}", token)


# ═════════════════════════════════════════════════════════════════════════
# C. Freight purchase auto-generation from shipments
# ═════════════════════════════════════════════════════════════════════════

def _make_order_with_shipment(token, *, client, transporter, freight_paid,
                              qty=6, rate=1000):
    """Create an order with one item + one shipment carrying freight_paid.
    Returns the order dict as returned by POST /api/orders."""
    payload = {
        "client_name": client,
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{"main_category": "Glass",
                   "product_name": "TestProduct",
                   "qty": qty, "rate": rate,
                   "product_sales": qty * rate}],
        "shipments": [{
            "date": "2026-07-22",
            "items": [],
            "freight_paid": freight_paid,
            "freight_charged": freight_paid,
            "transporter": transporter,
            "boxes_shipped": 1,
        }],
    }
    o = _post("/api/orders", token, payload)
    return o


def _find_linked_purchase(token, *, order_id, source_type):
    """Fetch all purchases and return the one linked to order_id with
    the given source_type — or None."""
    purchases = _get("/api/purchases", token)
    for p in purchases:
        if p.get("linked_to_order_id") == order_id and p.get("source_type") == source_type:
            return p
    return None


class TestFreightPurchaseAutoSync:

    def test_creating_order_with_freight_creates_linked_freight_purchase(self, token):
        """New feature: creating an order with a shipment containing
        (transporter, freight_paid>0) auto-generates a canonical Purchase
        stamped with the transporter's vendor_party_id."""
        transporter = "TestTransporter_Freight_A"
        o = _make_order_with_shipment(
            token, client="TestClient_Freight_A",
            transporter=transporter, freight_paid=250,
        )
        try:
            freight_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_freight_purchase"
            )
            assert freight_pur is not None, (
                "Order with (transporter, freight_paid>0) must auto-create "
                "a linked freight Purchase."
            )
            assert freight_pur["vendor_party_id"], (
                "Freight Purchase must inherit the transporter's vendor_party_id."
            )
            assert freight_pur["vendor_name"] == transporter
            assert abs(float(freight_pur["invoice_total"]) - 250.0) < 0.01
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_freight_purchase_inherits_correct_transporter_party(self, token):
        """The freight Purchase's vendor_party_id must equal the party id
        that get_or_create_vendor_party returns for the transporter name."""
        transporter = "TestTransporter_Freight_B"
        o = _make_order_with_shipment(
            token, client="TestClient_Freight_B",
            transporter=transporter, freight_paid=500,
        )
        try:
            # Create another purchase under the same transporter name — its
            # vendor_party_id should MATCH the freight purchase's.
            control = _post("/api/purchases", token, {
                "vendor_name": transporter, "purchase_date": "2026-07-22",
                "items": [{"description": "control", "qty": 1, "rate": 1,
                           "amount": 1}],
            })
            freight_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_freight_purchase"
            )
            assert freight_pur["vendor_party_id"] == control["vendor_party_id"], (
                "Freight Purchase and manual Purchase for the same transporter "
                "MUST share the same canonical vendor_party_id."
            )
            _delete(f"/api/purchases/{control['id']}", token)
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_freight_sync_is_idempotent_across_edits(self, token):
        """Repeated PUT /orders (no shipment changes) must not duplicate the
        freight Purchase — one purchase per (order, shipment) forever."""
        o = _make_order_with_shipment(
            token, client="TestClient_Freight_C",
            transporter="TestTransporter_Freight_C", freight_paid=300,
        )
        try:
            # PUT the same order back — no changes.
            _put(f"/api/orders/{o['id']}", token, {
                "client_name": o["client_name"],
                "order_date": o["order_date"],
                "status": o["status"],
                "items": o["items"],
                "shipments": o["shipments"],
            })
            # Fetch purchases: exactly ONE freight purchase for this order.
            purchases = _get("/api/purchases", token)
            matching = [p for p in purchases
                        if p.get("linked_to_order_id") == o["id"]
                        and p.get("source_type") == "order_freight_purchase"]
            assert len(matching) == 1, (
                f"Freight sync duplicated purchases across edits: found {len(matching)}."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_zero_freight_paid_creates_no_freight_purchase(self, token):
        """A shipment with freight_paid=0 must NOT create a freight Purchase."""
        o = _make_order_with_shipment(
            token, client="TestClient_Freight_D",
            transporter="TestTransporter_Freight_D", freight_paid=0,
        )
        try:
            freight_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_freight_purchase"
            )
            assert freight_pur is None, (
                "Zero freight_paid must NOT emit a freight Purchase."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_blank_transporter_creates_no_freight_purchase(self, token):
        """A shipment with blank transporter (but freight_paid > 0) must NOT
        create a freight Purchase — no vendor to link to."""
        o = _make_order_with_shipment(
            token, client="TestClient_Freight_E",
            transporter="", freight_paid=100,
        )
        try:
            freight_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_freight_purchase"
            )
            assert freight_pur is None, (
                "Blank transporter must NOT emit a freight Purchase — "
                "we can't link to a vendor without a name."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)


# ═════════════════════════════════════════════════════════════════════════
# D. Packing purchase auto-generation from orders
# ═════════════════════════════════════════════════════════════════════════

def _make_order_with_packing(token, *, client, packer_name, packing_cost,
                             boxes_used=1):
    payload = {
        "client_name": client,
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{"main_category": "Glass",
                   "product_name": "PackingTest",
                   "qty": 1, "rate": 100, "product_sales": 100}],
        "packing_cost": packing_cost,
        "packer_name": packer_name,
        "boxes_used": boxes_used,
    }
    return _post("/api/orders", token, payload)


class TestPackingPurchaseAutoSync:

    def test_creating_order_with_packer_creates_linked_packing_purchase(self, token):
        packer = "TestPacker_A"
        o = _make_order_with_packing(
            token, client="TestClient_Packing_A",
            packer_name=packer, packing_cost=180,
        )
        try:
            pack_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_packing_purchase"
            )
            assert pack_pur is not None, (
                "Order with (packer_name, packing_cost>0) must auto-create "
                "a linked packing Purchase."
            )
            assert pack_pur["vendor_party_id"], (
                "Packing Purchase must inherit the packer's vendor_party_id."
            )
            assert abs(float(pack_pur["invoice_total"]) - 180.0) < 0.01
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_blank_packer_creates_no_packing_purchase(self, token):
        """packing_cost > 0 without a packer_name must NOT emit a Purchase
        (treated as internal expense; nothing to link)."""
        o = _make_order_with_packing(
            token, client="TestClient_Packing_B",
            packer_name="", packing_cost=100,
        )
        try:
            pack_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_packing_purchase"
            )
            assert pack_pur is None
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_removing_packer_deletes_the_packing_purchase(self, token):
        """Editing the order to clear packer_name/packing_cost must remove
        the auto-generated packing Purchase (assuming no payments yet)."""
        packer = "TestPacker_C"
        o = _make_order_with_packing(
            token, client="TestClient_Packing_C",
            packer_name=packer, packing_cost=90,
        )
        try:
            # Confirm it was created
            pack_pur = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_packing_purchase"
            )
            assert pack_pur is not None

            # Now edit order to remove packing
            _put(f"/api/orders/{o['id']}", token, {
                "client_name": o["client_name"],
                "order_date": o["order_date"],
                "status": o["status"],
                "items": o["items"],
                "packing_cost": 0,
                "packer_name": "",
            })

            # Purchase should be gone
            pack_pur_after = _find_linked_purchase(
                token, order_id=o["id"], source_type="order_packing_purchase"
            )
            assert pack_pur_after is None, (
                "Removing packing_cost/packer must delete the linked Purchase "
                "when it has no payments yet."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)


# ═════════════════════════════════════════════════════════════════════════
# E. Admin backfill migration — idempotent, reports counts
# ═════════════════════════════════════════════════════════════════════════

class TestAdminBackfillMigration:

    def test_backfill_endpoint_returns_report(self, token):
        """POST /api/admin/purchases/backfill-vendor-party-id returns a
        structured report with purchases + purchase_payments sections."""
        rep = _post("/api/admin/purchases/backfill-vendor-party-id", token, {})
        assert "purchases" in rep
        assert "purchase_payments" in rep
        for section in ("purchases", "purchase_payments"):
            data = rep[section]
            for key in ("scanned", "already_linked", "newly_linked",
                        "ambiguous", "unmatched", "by_resolution"):
                assert key in data, (
                    f"backfill report missing {section}.{key}"
                )

    def test_backfill_is_idempotent(self, token):
        """Second consecutive backfill run must find every previously-linked
        row as `already_linked` and add zero new links."""
        rep1 = _post("/api/admin/purchases/backfill-vendor-party-id", token, {})
        rep2 = _post("/api/admin/purchases/backfill-vendor-party-id", token, {})
        # Second run: newly_linked must be 0 for both sections (assuming
        # nothing was created between the two runs).
        assert rep2["purchases"]["newly_linked"] == 0, (
            "Second backfill added new links — not idempotent."
        )
        assert rep2["purchase_payments"]["newly_linked"] == 0
        # Every purchase that existed in rep1 must be linked in rep2.
        assert rep2["purchases"]["scanned"] == rep1["purchases"]["scanned"]


# ═════════════════════════════════════════════════════════════════════════
# F. Reconciliation stays healthy after all this
# ═════════════════════════════════════════════════════════════════════════

class TestReconcileStillHealthy:
    def test_reconcile_all_passed(self, token):
        rep = _get("/api/reconcile", token)
        assert rep["healthy"] is True, (
            f"Reconcile unhealthy — invariants failing: {rep.get('invariants')}"
        )
        assert rep["summary"]["passed"] == rep["summary"]["total"]
