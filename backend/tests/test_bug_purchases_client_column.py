"""Bug fix (2026-07-22) — Purchases table gains a Client column.

Frontend adds a Client column using the existing `linked_to_order_id`
linkage on Purchase rows. Standalone purchases (no order linkage) show
"—".

Focused BACKEND contract test:
  • `/api/purchases` continues to return `linked_to_order_id` for
    order-linked auto-generated Purchases (packing / freight / order
    purchase).
  • `/api/orders/{oid}` returns `client_name` for the linked order, so
    the frontend can resolve `linked_to_order_id → client_name`.
  • Standalone purchases carry `linked_to_order_id=null` (or missing).

We deliberately don't test the React table markup here — the frontend
change is a small `<td>` render off the same data contract. Adding a
JSX unit test file would require the `@testing-library/react` +
`jest-dom` scaffolding that CRA sets up with `resetMocks: true`, which
we chose to avoid touching in this scoped change.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

import uuid
import httpx
import pytest

API_BASE = "http://localhost:8001"


def _login() -> str:
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


def _hdr(t): return {"Authorization": f"Bearer {t}"}


def _get(path, t, **params):
    r = httpx.get(f"{API_BASE}{path}", headers=_hdr(t), params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _post(path, t, payload):
    r = httpx.post(f"{API_BASE}{path}", headers=_hdr(t), json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _delete(path, t):
    r = httpx.delete(f"{API_BASE}{path}", headers=_hdr(t), timeout=15.0)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def token():
    return _login()


class TestPurchasesClientColumnContract:
    def test_order_linked_purchase_carries_linked_to_order_id(self, token):
        """Order-linked auto Purchases (packing) MUST carry
        `linked_to_order_id` that matches the parent order id, and the
        parent `/api/orders/{oid}` must return the `client_name` needed
        by the frontend to render the new Client column."""
        unique = uuid.uuid4().hex[:8]
        client_name = f"PurchClientCol Client {unique}"
        order = _post("/api/orders", token, {
            "client_name": client_name,
            "order_date": "2026-07-22",
            "status": "Confirmed",
            "items": [{
                "main_category": "Glass",
                "product_name": "Purch client col test",
                "qty": 1, "rate": 1000, "product_sales": 1000,
            }],
            "packing_cost": 250,
            "packer_name": "",  # → auto-FF packing purchase
        })
        try:
            purch = _get("/api/purchases", token)
            linked = [
                p for p in purch
                if p.get("linked_to_order_id") == order["id"]
            ]
            assert linked, (
                f"No purchases returned with linked_to_order_id={order['id']!r}. "
                f"Expected at least one auto-generated packing purchase."
            )
            # Cross-check the order fetch endpoint used by the frontend
            # lookup returns the client_name.
            ord_fetched = _get(f"/api/orders/{order['id']}", token)
            assert ord_fetched.get("client_name") == client_name, (
                "GET /api/orders/{oid} must return the client_name so the "
                "Purchases frontend can resolve the Client column."
            )
        finally:
            _delete(f"/api/orders/{order['id']}", token)

    def test_standalone_purchase_has_no_linked_to_order_id(self, token):
        """Direct-entered Purchases (no order) MUST have
        `linked_to_order_id` empty/null so the frontend renders "—"
        in the Client column."""
        unique = uuid.uuid4().hex[:8]
        vendor_name = f"PurchClientCol Vendor {unique}"
        payload = {
            "vendor_name": vendor_name,
            "purchase_date": "2026-07-22",
            "invoice_no": f"INV-{unique}",
            "items": [{
                "description": "Direct purchase test",
                "qty": 1, "rate": 500, "amount": 500,
            }],
            "invoice_total": 500,
        }
        r = httpx.post(f"{API_BASE}/api/purchases", headers=_hdr(token),
                       json=payload, timeout=15.0)
        assert r.status_code == 200, r.text
        pur = r.json()
        try:
            assert not pur.get("linked_to_order_id"), (
                f"Standalone Purchase must NOT carry linked_to_order_id; "
                f"got {pur.get('linked_to_order_id')!r}"
            )
        finally:
            httpx.delete(f"{API_BASE}/api/purchases/{pur['id']}",
                         headers=_hdr(token), timeout=10.0)
