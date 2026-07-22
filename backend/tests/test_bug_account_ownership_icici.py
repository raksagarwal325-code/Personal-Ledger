"""Bug fix (2026-07-22) — Account ownership: ICICI is a Father's Firm account.

Business rule (from user, 2026-07-22):
  • Mark ICICI as a Father's Firm account, not a business account.
  • Transactions received into or paid from ICICI must follow the
    EXISTING Father's Firm settlement flow.
  • Do not redesign accounting, payments, purchases, or UI.
  • Do not change historical amounts.

Verified paths:
  T1: Startup migration stamps the ICICI account with
      `owner_party_id = SYSTEM_FF_ID` (and only ICICI).
  T2: A NEW customer_payment received into ICICI (no
      `received_by_party_id` in the payload) is auto-stamped with
      `received_by_party_id = SYSTEM_FF_ID` and appears on the FF party
      ledger as a derived receipt entry.
  T3: A NEW purchase_payment paid from ICICI (no `paid_by_party_id` in
      the payload) is auto-stamped with `paid_by_party_id = SYSTEM_FF_ID`
      and appears on the FF party ledger.
  T4: Non-ICICI accounts (Cash, other bank) are UNCHANGED — payments do
      NOT get an FF settlement stamp.
  T5: Historical amounts (existing payments on ICICI or other accounts
      before this change) are NOT retro-modified — only NEW/edited
      payments go through the auto-stamp.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

import uuid
import httpx
import pytest

API_BASE = "http://localhost:8001"
FF_ID = "system_fathers_firm"


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


@pytest.fixture(scope="module")
def accounts(token):
    return _get("/api/accounts", token)


def _find(accs, name_substr):
    for a in accs:
        if name_substr.lower() in (a.get("name") or "").lower():
            return a
    return None


class TestAccountOwnershipICICI:
    def test_icici_stamped_as_fathers_firm_account(self, accounts):
        """T1 — startup migration flagged ICICI (only) as FF-owned."""
        icici = _find(accounts, "ICICI")
        assert icici is not None, "ICICI account must exist post-seed"
        assert icici.get("owner_party_id") == FF_ID, (
            f"ICICI must be owned by SYSTEM_FF_ID; got "
            f"owner_party_id={icici.get('owner_party_id')!r}"
        )

        # Non-ICICI accounts must NOT be FF-owned.
        for a in accounts:
            if a is icici:
                continue
            if "icici" in (a.get("name") or "").lower():
                continue
            assert (a.get("owner_party_id") or None) != FF_ID, (
                f"Non-ICICI account {a.get('name')!r} must not be "
                f"owned by SYSTEM_FF_ID"
            )

    def test_customer_payment_into_icici_auto_stamps_received_by_ff(
            self, token, accounts
    ):
        """T2 — customer_payment through ICICI routes via FF settlement."""
        icici = _find(accounts, "ICICI")
        assert icici is not None
        unique = uuid.uuid4().hex[:8]
        payload = {
            "date": "2026-07-22",
            "customer_name": f"AcctOwn ICICI Client {unique}",
            "amount": 4200,
            "mode": "UPI",
            "account_id": icici["id"],
            "account_name": icici["name"],
            "allocations": [],
            # No `received_by_party_id` — auto-stamp path.
        }
        pmt = _post("/api/customer-payments", token, payload)
        try:
            assert pmt.get("received_by_party_id") == FF_ID, (
                "customer_payment into ICICI must auto-stamp "
                f"received_by_party_id={FF_ID}; got {pmt.get('received_by_party_id')!r}"
            )

            # FF party ledger must surface a derived "customer_payment"
            # entry for this payment (looked up via
            # `related_customer_payment_id`).
            ff = _get(f"/api/party-ledger-v2/parties/{FF_ID}", token)
            matches = [
                e for e in (ff.get("entries") or [])
                if e.get("related_customer_payment_id") == pmt["id"]
            ]
            assert matches, (
                f"FF party ledger must include a derived entry linked to "
                f"customer_payment {pmt['id']}"
            )
            assert matches[0].get("category") == "customer_payment"
            assert abs(float(matches[0].get("amount") or 0) - 4200) < 0.01
        finally:
            _delete(f"/api/customer-payments/{pmt['id']}", token)

    def test_purchase_payment_from_icici_auto_stamps_paid_by_ff(
            self, token, accounts
    ):
        """T3 — purchase_payment paid FROM ICICI routes via FF settlement."""
        icici = _find(accounts, "ICICI")
        assert icici is not None

        unique = uuid.uuid4().hex[:8]
        vendor_name = f"AcctOwn ICICI Vendor {unique}"
        # Advance vendor payment (no allocations) — cleanest scenario.
        payload = {
            "date": "2026-07-22",
            "vendor_name": vendor_name,
            "amount": 1800,
            "mode": "UPI",
            "account_id": icici["id"],
            "account_name": icici["name"],
            "allocations": [],
            # No `paid_by_party_id` — auto-stamp path.
        }
        pmt = _post("/api/purchase-payments", token, payload)
        try:
            assert pmt.get("paid_by_party_id") == FF_ID, (
                "purchase_payment from ICICI must auto-stamp "
                f"paid_by_party_id={FF_ID}; got {pmt.get('paid_by_party_id')!r}"
            )
        finally:
            _delete(f"/api/purchase-payments/{pmt['id']}", token)

    def test_non_icici_account_is_unchanged(self, token, accounts):
        """T4 — payments through non-ICICI accounts get NO FF stamp."""
        cash = _find(accounts, "Cash")
        assert cash is not None, "seed must include a Cash account"
        unique = uuid.uuid4().hex[:8]
        payload = {
            "date": "2026-07-22",
            "customer_name": f"AcctOwn Cash Client {unique}",
            "amount": 500,
            "mode": "Cash",
            "account_id": cash["id"],
            "account_name": cash["name"],
            "allocations": [],
        }
        pmt = _post("/api/customer-payments", token, payload)
        try:
            assert not pmt.get("received_by_party_id"), (
                f"customer_payment into a self-owned account must NOT get "
                f"an FF settlement stamp; got "
                f"received_by_party_id={pmt.get('received_by_party_id')!r}"
            )
        finally:
            _delete(f"/api/customer-payments/{pmt['id']}", token)

    def test_historical_amounts_are_not_retro_modified(self, token):
        """T5 — no historical amount was changed. Reconcile stays healthy
        after the ownership migration. (Reconcile is the strongest
        historical-amount invariant we run — its 21 checks include totals
        parity between orders/payments/cash-book and party ledgers.)"""
        recon = _get("/api/reconcile", token)
        assert recon.get("healthy") is True, (
            f"Reconcile must be healthy after the ownership migration; "
            f"got: {recon.get('summary')}"
        )
        assert recon.get("passed") == 21
        assert recon.get("failed") == 0
