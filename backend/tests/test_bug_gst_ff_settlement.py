"""Bug fix (2026-07-22) — GST settlement with Father's Firm on invoice.

Business rule (from user, 2026-07-22):
  • When a taxable invoice is raised, the GST portion accrues against
    Father's Firm (FF remits GST to the government on Rakshit's behalf).
    Rakshit owes FF → FF card `you_pay` increases by the shipped-portion
    tax_amount.
  • Customer ledgers, sign conventions, and reconciliation invariants
    stay unchanged. Business revenue = taxable sale (unchanged).
  • When payment is received by FF (received_by_party_id = FF_ID),
    the existing full-payment linked entry is preserved. GST is NOT
    re-recorded on payment.
  • Only NEW orders opt in (`gst_ff_settle=True`). Historical orders keep
    `gst_ff_settle=False` (stamped by startup migration).
  • Fully DERIVED — no new storage. tax_amount edits / shipment changes
    / cancellation auto-adjust the FF ledger on next read (idempotent,
    same pattern as freight/packing linked purchases).
"""
from __future__ import annotations

import httpx
import pytest

API_BASE = "http://localhost:8001"
FF_ID = "system_fathers_firm"


def _admin_login() -> str:
    r = httpx.post(f"{API_BASE}/api/auth/login",
                   json={"email": "admin@artisan.local",
                         "password": "Admin@12345"}, timeout=10.0)
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
    return _admin_login()


def _make_taxable_order(token, *, client_name, tax_pct=18,
                        product_sales=1000, qty=1, rate=1000,
                        with_shipment=True, ship_qty=None):
    """POST a new order with GST enabled. If `with_shipment` is True,
    add a shipment covering `ship_qty` (defaults to full qty) via the
    dedicated shipment endpoint so shipped_ratio > 0 and tax accrues."""
    payload = {
        "client_name": client_name,
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "GST test",
            "qty": qty, "rate": rate, "product_sales": product_sales,
        }],
        "tax_applicable": True,
        "tax_type": "CGST_SGST",
        "tax_percent": tax_pct,
    }
    o = _post("/api/orders", token, payload)
    if with_shipment:
        item_id = (o.get("items") or [{}])[0].get("id")
        _post(f"/api/orders/{o['id']}/shipments", token, {
            "date": "2026-07-22",
            "items": [{"order_item_id": item_id, "qty": ship_qty or qty}],
            "boxes_shipped": 1, "freight_paid": 0, "freight_charged": 0,
            "transporter": "",
        })
        # Refetch the order to see the computed tax + shipment.
        o = _get(f"/api/orders/{o['id']}", token)
    return o


def _ff_ledger(token):
    """GET the FF party-ledger v2 payload."""
    return _get(f"/api/party-ledger-v2/parties/{FF_ID}", token)


def _gst_entries_for_order(ff_data, order_id):
    """Filter the GST-settlement entries specific to a given order.
    Derived entry id has format `GST-<order_id>`."""
    return [e for e in (ff_data.get("entries") or [])
            if e.get("category") == "gst_settlement"
            and (e.get("related_order_id") == order_id
                 or e.get("id") == f"GST-{order_id}")]


class TestGstFfSettlement:

    def test_new_taxable_order_creates_ff_gst_entry(self, token):
        """A new order with tax + at least one shipment must produce
        exactly ONE `gst_settlement` derived row on FF's ledger."""
        o = _make_taxable_order(token, client_name="GST_Test_A")
        try:
            assert o.get("gst_ff_settle") is True, (
                "New orders MUST default to gst_ff_settle=True."
            )
            assert float(o.get("tax_amount") or 0) > 0, (
                "Order must have a computed tax_amount."
            )
            ff = _ff_ledger(token)
            entries = _gst_entries_for_order(ff, o["id"])
            assert len(entries) == 1, (
                f"Expected exactly 1 GST entry for order {o['id']}, got {len(entries)}."
            )
            expected_gst = round(float(o["tax_amount"]), 2)
            actual = round(float(entries[0]["delta_you_pay"]), 2)
            assert actual == expected_gst, (
                f"GST derived entry delta_you_pay {actual} ≠ order tax_amount {expected_gst}."
            )
            # Sign — Rakshit owes FF → you_pay POSITIVE.
            assert actual > 0, (
                "GST entry must be POSITIVE (you-pay direction — Rakshit owes FF)."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_order_without_shipment_does_not_accrue_gst(self, token):
        """Invoice NOT raised (no shipments yet) → no GST entry on FF."""
        o = _make_taxable_order(token, client_name="GST_Test_B", with_shipment=False)
        try:
            ff = _ff_ledger(token)
            entries = _gst_entries_for_order(ff, o["id"])
            assert len(entries) == 0, (
                "Order without any shipment must NOT accrue GST on FF "
                "(invoice not yet raised)."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_editing_tax_amount_auto_adjusts_ff_entry(self, token):
        """Change tax_percent from 18 → 12 → FF entry must reflect the
        new realized tax, not the old one. DERIVED = idempotent."""
        o = _make_taxable_order(token, client_name="GST_Test_C", tax_pct=18)
        try:
            ff0 = _ff_ledger(token)
            e0 = _gst_entries_for_order(ff0, o["id"])[0]
            gst_before = round(float(e0["delta_you_pay"]), 2)

            updated = _put(f"/api/orders/{o['id']}", token, {
                **o,
                "tax_percent": 12,
                "tax_amount_manual": False,
            })
            assert updated.get("gst_ff_settle") is True, (
                "PUT must PRESERVE the existing gst_ff_settle=True."
            )
            ff1 = _ff_ledger(token)
            e1 = _gst_entries_for_order(ff1, o["id"])
            assert len(e1) == 1, "Still exactly 1 GST entry after edit."
            gst_after = round(float(e1[0]["delta_you_pay"]), 2)
            assert gst_after != gst_before, (
                f"Editing tax_percent must move the FF entry — "
                f"before {gst_before}, after {gst_after}."
            )
            assert round(float(updated["tax_amount"]), 2) == gst_after
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_cancelling_order_removes_gst_entry(self, token):
        """Cancelled orders must NOT accrue GST — the derived entry
        disappears on next read."""
        o = _make_taxable_order(token, client_name="GST_Test_D")
        try:
            ff0 = _ff_ledger(token)
            assert len(_gst_entries_for_order(ff0, o["id"])) == 1

            _put(f"/api/orders/{o['id']}", token, {**o, "status": "Cancelled"})

            ff1 = _ff_ledger(token)
            assert len(_gst_entries_for_order(ff1, o["id"])) == 0, (
                "Cancelling an order must remove its GST entry from FF."
            )
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_deleting_order_removes_gst_entry(self, token):
        """Deleting an order removes its GST entry (derived, no residue)."""
        o = _make_taxable_order(token, client_name="GST_Test_E")
        ff0 = _ff_ledger(token)
        assert len(_gst_entries_for_order(ff0, o["id"])) == 1

        _delete(f"/api/orders/{o['id']}", token)

        ff1 = _ff_ledger(token)
        assert len(_gst_entries_for_order(ff1, o["id"])) == 0

    def test_non_taxable_order_produces_no_gst_entry(self, token):
        """Zero tax → no GST entry."""
        o = _post("/api/orders", token, {
            "client_name": "GST_Test_F",
            "order_date": "2026-07-22",
            "status": "Confirmed",
            "items": [{"main_category": "Glass", "product_name": "NoTax",
                       "qty": 1, "rate": 100, "product_sales": 100}],
            "tax_applicable": False,
            "shipments": [{"date": "2026-07-22", "items": [], "boxes_shipped": 1,
                           "freight_paid": 0, "freight_charged": 0,
                           "transporter": ""}],
        })
        try:
            ff = _ff_ledger(token)
            assert len(_gst_entries_for_order(ff, o["id"])) == 0
        finally:
            _delete(f"/api/orders/{o['id']}", token)

    def test_historical_orders_never_opt_in(self, token):
        """Historical orders were stamped gst_ff_settle=False by the
        startup migration. Even if they have tax_amount, they must NOT
        appear on FF's ledger with a `gst_settlement` category.
        (Note: we identify historical rows as any order in DB with
        gst_ff_settle=False and tax_amount>0.)"""
        ff = _ff_ledger(token)
        gst_rows = [e for e in (ff.get("entries") or [])
                    if e.get("category") == "gst_settlement"]
        for row in gst_rows:
            oid = row.get("related_order_id")
            if not oid:
                continue
            # Fetch the underlying order via the orders API.
            try:
                o = _get(f"/api/orders/{oid}", token)
            except httpx.HTTPStatusError:
                continue
            assert o.get("gst_ff_settle") is True, (
                f"Order {oid} appears on FF as gst_settlement but is "
                f"gst_ff_settle={o.get('gst_ff_settle')} — must be True."
            )

    def test_payment_flow_unchanged_no_double_gst(self, token):
        """Existing customer_payment flow (received_by_party_id = FF)
        must NOT create an extra GST row. Only the payment row appears
        on FF; the invoice-time GST accrual is the ONLY GST row for the
        order."""
        o = _make_taxable_order(token, client_name="GST_Test_H")
        try:
            # Make a small customer payment received by FF.
            pay = _post("/api/customer-payments", token, {
                "customer_name": "GST_Test_H",
                "date": "2026-07-22",
                "amount": 500,
                "mode": "Cash",
                "received_by_party_id": FF_ID,
                "allocations": [],
            })
            try:
                ff = _ff_ledger(token)
                gst_for_order = _gst_entries_for_order(ff, o["id"])
                assert len(gst_for_order) == 1, (
                    "Making a customer payment must NOT duplicate the "
                    "invoice-time GST entry."
                )
                # Payment-linked entry exists too (category = customer_payment).
                cp_linked = [e for e in (ff.get("entries") or [])
                             if e.get("category") == "customer_payment"
                             and e.get("related_customer_payment_id") == pay.get("id")]
                assert len(cp_linked) == 1, (
                    "Existing payment flow must remain intact — "
                    "customer_payment linked entry expected exactly once."
                )
            finally:
                _delete(f"/api/customer-payments/{pay['id']}", token)
        finally:
            _delete(f"/api/orders/{o['id']}", token)


class TestReconcileStaysHealthyWithGstRule:
    def test_reconcile_all_passed(self, token):
        rep = _get("/api/reconcile", token)
        assert rep["healthy"] is True, (
            f"Reconcile unhealthy — failing invariants: "
            f"{[i for i in rep['invariants'] if i.get('status') != 'passed']}"
        )
        assert rep["summary"]["passed"] == rep["summary"]["total"]
