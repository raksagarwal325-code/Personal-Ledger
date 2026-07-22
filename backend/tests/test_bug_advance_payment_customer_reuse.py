"""Bug fix (2026-07-22) — Advance-payment customer reuse.

Business rule (from user, 2026-07-22):
  • When a NEW customer name is entered on an advance / customer payment:
      (1) create or resolve the canonical customer party,
      (2) save `customer_party_id` on the payment,
      (3) make that customer available in the customer dropdown for
          future payments (surface via `/api/meta` → `clients`),
      (4) reuse the same party on exact / normalized-name match instead
          of creating duplicates.
  • Do NOT change payment allocation logic.

Two focused tests:
  T1: A brand-new customer entered through an advance payment becomes
      reusable — the name appears in `/api/meta` → `clients` and
      `customer_party_id` is persisted on the payment.
  T2: Re-entering the SAME NORMALIZED name (varied casing / whitespace)
      on a second payment resolves to the SAME customer_party_id — no
      duplicate parties are created.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

import uuid
import httpx
import pytest

API_BASE = "http://localhost:8001"


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


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _post(path: str, token: str, payload):
    r = httpx.post(f"{API_BASE}{path}", headers=_hdr(token),
                   json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _get(path: str, token: str):
    r = httpx.get(f"{API_BASE}{path}", headers=_hdr(token), timeout=15.0)
    r.raise_for_status()
    return r.json()


def _delete(path: str, token: str):
    r = httpx.delete(f"{API_BASE}{path}", headers=_hdr(token), timeout=15.0)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def token():
    return _admin_bootstrap_or_login()


def _make_advance_payment(token, *, customer_name: str, amount: float = 5000):
    """POST an advance customer payment (no order allocations)."""
    return _post("/api/customer-payments", token, {
        "date": "2026-07-22",
        "customer_name": customer_name,
        "amount": amount,
        "mode": "UPI",
        "account_id": "",
        "account_name": "",
        "allocations": [],
        "notes": "packing_ff_default_test advance",
    })


class TestAdvancePaymentCustomerReuse:
    def test_new_customer_via_advance_payment_becomes_reusable(self, token):
        """T1 — A brand-new customer entered through an advance payment:
          • gets a `customer_party_id` stamped on the payment,
          • appears in `/api/meta` → `clients` for future payments.
        """
        unique = uuid.uuid4().hex[:8]
        cust_name = f"AdvReuse Client {unique}"

        # Snapshot clients before.
        before = _get("/api/meta", token)
        assert cust_name not in (before.get("clients") or []), (
            "test-precondition: unique customer must not exist yet")

        payment = _make_advance_payment(token, customer_name=cust_name,
                                        amount=7500)
        try:
            assert payment.get("customer_party_id"), (
                "customer_party_id must be persisted on the advance payment")
            party_id = payment["customer_party_id"]

            # Verify meta.clients now includes this customer.
            after = _get("/api/meta", token)
            clients_after = after.get("clients") or []
            assert cust_name in clients_after, (
                f"'{cust_name}' must appear in /api/meta clients dropdown "
                f"after being introduced via an advance payment. "
                f"Got: {clients_after[-10:]}"
            )

            # Verify the canonical party exists with type=customer.
            parties = _get(
                f"/api/party-ledger-v2/parties?type=customer", token
            )
            plist = parties.get("parties") if isinstance(parties, dict) else parties
            ids = [p.get("id") for p in (plist or [])]
            assert party_id in ids, (
                "canonical customer party must exist after advance payment"
            )
        finally:
            _delete(f"/api/customer-payments/{payment['id']}", token)

    def test_same_normalized_name_reuses_customer_party_id(self, token):
        """T2 — Entering the same normalized name (varied case / whitespace)
        on a second payment resolves to the SAME party_id — no duplicates."""
        unique = uuid.uuid4().hex[:8]
        base_name = f"AdvReuse Norm {unique}"
        variants = [
            base_name,                        # canonical
            base_name.upper(),                # different case
            f"  {base_name.lower()}  ",       # padded + lowercased
            f"{base_name}\t\t",               # trailing whitespace
        ]

        payments = []
        try:
            party_ids = set()
            for i, v in enumerate(variants):
                p = _make_advance_payment(
                    token, customer_name=v, amount=1000 + i
                )
                payments.append(p)
                pid = p.get("customer_party_id")
                assert pid, f"payment for variant {v!r} must carry a party id"
                party_ids.add(pid)

            assert len(party_ids) == 1, (
                f"All normalized-equal variants must reuse the same "
                f"customer_party_id — got {len(party_ids)} distinct ids: "
                f"{party_ids} for variants {variants!r}"
            )

            # Cross-check: the parties directory has exactly ONE customer
            # party for this normalized name (not four).
            parties = _get(
                f"/api/party-ledger-v2/parties?type=customer", token
            )
            plist = parties.get("parties") if isinstance(parties, dict) else parties
            matches = [
                p for p in (plist or [])
                if (p.get("display_name") or p.get("name") or "")
                   .strip().casefold() == base_name.casefold()
            ]
            assert len(matches) == 1, (
                f"Exactly one canonical customer party expected for "
                f"'{base_name}', found {len(matches)}: "
                f"{[(m.get('id'), m.get('display_name')) for m in matches]}"
            )
        finally:
            for p in payments:
                try:
                    _delete(f"/api/customer-payments/{p['id']}", token)
                except Exception:
                    pass
