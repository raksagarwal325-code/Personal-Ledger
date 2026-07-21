"""Reconciliation tests for the Unified Party Ledger v2 integration with
existing payment endpoints (customer-payments, purchase-payments).

Ensures:
 - `paid_by_party_id` / `received_by_party_id` on the existing payment
   endpoints produce EXACTLY the same ledger result as Quick Entry.
 - No entry is duplicated between the derived and manual layers.
 - Editing, deleting and changing the payer/receiver keep both sides in sync
   without leaving orphan entries.
 - Party balances always reconcile against source-of-truth totals.
"""

import os
import asyncio
import pytest
import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_API = "http://localhost:8001/api"
try:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_API = line.split("=", 1)[1].strip() + "/api"
                break
except Exception:
    pass


@pytest.fixture(scope="module")
def client():
    return httpx.Client(base_url=BASE_API, timeout=30.0)


@pytest.fixture
def clean(client):
    """Purge manual ledger entries, dummy payments, reset system opening."""
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _clean():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.party_ledger_entries.delete_many({})
        # remove any residual test purchase_payments / customer_payments referencing test payer
        await db.purchase_payments.delete_many({"reference": {"$regex": "^RECON-"}})
        await db.customer_payments.delete_many({"reference": {"$regex": "^RECON-"}})
        await db.parties.update_many({"is_system": True}, {"$set": {"opening_balance": 0}})
    asyncio.run(_clean())


def _party(client, ptype):
    r = client.get("/party-ledger-v2/parties").json()
    return next(p for p in r["parties"] if p["type"] == ptype)


def _bal(client, pid):
    r = client.get(f"/party-ledger-v2/parties/{pid}").json()
    return r["net_balance"]


# ------------------------------------------------------------------
# purchase-payments with paid_by_party_id
# ------------------------------------------------------------------
def test_purchase_payment_with_paid_by_shifts_both(client, clean):
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")
    ff_before, v_before = _bal(client, ff["id"]), _bal(client, vendor["id"])

    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 5000, "mode": "UPI",
        "date": "2026-08-01",
        "paid_by_party_id": ff["id"], "paid_by_party_name": ff["name"],
        "reference": "RECON-PP-1",
    })
    assert pp.status_code == 200, pp.text
    ff_after, v_after = _bal(client, ff["id"]), _bal(client, vendor["id"])
    assert v_after == pytest.approx(v_before - 5000)
    assert ff_after == pytest.approx(ff_before + 5000)
    # Cleanup
    client.delete(f"/purchase-payments/{pp.json()['id']}")


# ------------------------------------------------------------------
# Deleting the payment reverses BOTH sides
# ------------------------------------------------------------------
def test_delete_purchase_payment_reverses_both(client, clean):
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")
    ff0, v0 = _bal(client, ff["id"]), _bal(client, vendor["id"])
    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 3333, "mode": "UPI",
        "date": "2026-08-01",
        "paid_by_party_id": ff["id"], "reference": "RECON-PP-2",
    }).json()
    assert _bal(client, vendor["id"]) == pytest.approx(v0 - 3333)
    assert _bal(client, ff["id"]) == pytest.approx(ff0 + 3333)
    client.delete(f"/purchase-payments/{pp['id']}").raise_for_status()
    assert _bal(client, vendor["id"]) == pytest.approx(v0)
    assert _bal(client, ff["id"]) == pytest.approx(ff0)


# ------------------------------------------------------------------
# Split payment: Rakshit + Father's Firm cover a vendor bill together
# ------------------------------------------------------------------
def test_split_payment_purchase_endpoint(client, clean):
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")
    ff0, v0 = _bal(client, ff["id"]), _bal(client, vendor["id"])
    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 10000, "mode": "UPI",
        "date": "2026-08-01",
        "paid_by_party_id": ff["id"], "split_paid_by_amount": 4000,
        "reference": "RECON-PP-3",
    }).json()
    # Vendor payable drops by FULL amount
    assert _bal(client, vendor["id"]) == pytest.approx(v0 - 10000)
    # FF only shifts by the split portion
    assert _bal(client, ff["id"]) == pytest.approx(ff0 + 4000)
    client.delete(f"/purchase-payments/{pp['id']}")


# ------------------------------------------------------------------
# Changing the payer on an existing payment recomputes both sides
# ------------------------------------------------------------------
def test_edit_purchase_payment_reassigns_payer(client, clean):
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")
    ff0, v0 = _bal(client, ff["id"]), _bal(client, vendor["id"])
    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 7000, "mode": "UPI",
        "date": "2026-08-01",
        "reference": "RECON-PP-4",
    }).json()  # Rakshit paid — no FF impact
    assert _bal(client, ff["id"]) == pytest.approx(ff0)
    assert _bal(client, vendor["id"]) == pytest.approx(v0 - 7000)

    # Edit: now FF paid
    client.put(f"/purchase-payments/{pp['id']}", json={
        "vendor_name": vendor["name"], "amount": 7000, "mode": "UPI",
        "date": "2026-08-01",
        "paid_by_party_id": ff["id"], "reference": "RECON-PP-4",
    }).raise_for_status()
    assert _bal(client, ff["id"]) == pytest.approx(ff0 + 7000)
    assert _bal(client, vendor["id"]) == pytest.approx(v0 - 7000)
    client.delete(f"/purchase-payments/{pp['id']}")


# ------------------------------------------------------------------
# customer-payments with received_by_party_id
# ------------------------------------------------------------------
def test_customer_payment_received_by_ff(client, clean):
    ff = _party(client, "fathers_firm")
    r = client.get("/party-ledger-v2/parties").json()
    cust = next(p for p in r["parties"] if p["type"] == "customer")
    c0, ff0 = _bal(client, cust["id"]), _bal(client, ff["id"])

    cp = client.post("/customer-payments", json={
        "customer_name": cust["name"], "amount": 40000, "mode": "UPI",
        "date": "2026-08-01",
        "received_by_party_id": ff["id"], "reference": "RECON-CP-1",
    })
    assert cp.status_code == 200, cp.text
    # Customer paid → they owe less (balance shifts +40k toward zero from negative)
    assert _bal(client, cust["id"]) == pytest.approx(c0 + 40000)
    # FF now holds Rakshit's money → they owe Rakshit → balance shifts by −40k
    assert _bal(client, ff["id"]) == pytest.approx(ff0 - 40000)
    client.delete(f"/customer-payments/{cp.json()['id']}")


# ------------------------------------------------------------------
# Quick Entry vs Payment Endpoint produce identical ledger results
# ------------------------------------------------------------------
def test_quick_entry_equivalent_to_payment_endpoint(client, clean):
    """Same real-world event via Quick Entry vs the /purchase-payments
    endpoint must land the same net delta on every party."""
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")

    ff0, v0 = _bal(client, ff["id"]), _bal(client, vendor["id"])

    # Route 1: Quick Entry
    qe = client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 2500, "paid_by_party_id": ff["id"],
        "reference": "RECON-QE-A",
    }).json()
    ff_qe, v_qe = _bal(client, ff["id"]) - ff0, _bal(client, vendor["id"]) - v0

    # Route 2: Payment endpoint (isolate by reversing quick entry first)
    client.delete(f"/party-ledger-v2/transactions/{qe['txn_ref']}").raise_for_status()
    assert _bal(client, ff["id"]) == pytest.approx(ff0)
    assert _bal(client, vendor["id"]) == pytest.approx(v0)

    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 2500, "mode": "UPI",
        "paid_by_party_id": ff["id"], "reference": "RECON-QE-B",
    }).json()
    ff_pp, v_pp = _bal(client, ff["id"]) - ff0, _bal(client, vendor["id"]) - v0

    assert ff_qe == pytest.approx(ff_pp), f"FF delta differs: QE={ff_qe} PP={ff_pp}"
    assert v_qe == pytest.approx(v_pp),  f"Vendor delta differs: QE={v_qe} PP={v_pp}"
    client.delete(f"/purchase-payments/{pp['id']}")


# ------------------------------------------------------------------
# Deduplication guarantee: derived and manual layers don't double-count
# ------------------------------------------------------------------
def test_no_duplicate_entry_in_ff_ledger(client, clean):
    """A single purchase_payment with paid_by_party_id must show up exactly
    ONCE in Father's Firm's ledger (from the derived layer, not manual)."""
    ff = _party(client, "fathers_firm")
    vendor = _party(client, "vendor")
    pp = client.post("/purchase-payments", json={
        "vendor_name": vendor["name"], "amount": 800, "mode": "UPI",
        "paid_by_party_id": ff["id"], "reference": "RECON-DEDUP-1",
    }).json()

    ff_detail = client.get(f"/party-ledger-v2/parties/{ff['id']}").json()
    ppid = pp["id"]
    matches = [e for e in ff_detail["entries"]
               if e.get("related_purchase_payment_id") == ppid]
    assert len(matches) == 1, f"expected exactly 1 entry linked to {ppid}, got {len(matches)}"
    client.delete(f"/purchase-payments/{ppid}")


# ------------------------------------------------------------------
# Source totals reconcile with party ledger totals
# ------------------------------------------------------------------
def test_source_totals_reconcile_with_party_ledger(client, clean):
    """Sum of purchase_payments where paid_by_party_id == FF should equal
    the total 'You Pay' effect contributed to FF from those payments."""
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _get_source_total():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        total = 0.0
        async for pay in db.purchase_payments.find({"paid_by_party_id": {"$ne": None}}, {"_id": 0}):
            if not pay.get("paid_by_party_id"): continue
            split = pay.get("split_paid_by_amount")
            total += float(split if split is not None else pay.get("amount") or 0)
        return total

    ff = _party(client, "fathers_firm")
    baseline_ff = _bal(client, ff["id"])

    # Create three linked purchase_payments
    for i, amt in enumerate([1100, 2200, 3300]):
        client.post("/purchase-payments", json={
            "vendor_name": _party(client, "vendor")["name"], "amount": amt, "mode": "UPI",
            "paid_by_party_id": ff["id"], "reference": f"RECON-RECON-{i}",
        }).raise_for_status()

    source_total = asyncio.run(_get_source_total())
    ff_bal = _bal(client, ff["id"])
    ff_effect_from_source = ff_bal - baseline_ff
    assert ff_effect_from_source == pytest.approx(source_total), \
        f"FF effect ({ff_effect_from_source}) does not match source total ({source_total})"

    # Cleanup
    async def _rm():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.purchase_payments.delete_many({"reference": {"$regex": "^RECON-RECON-"}})
    asyncio.run(_rm())
