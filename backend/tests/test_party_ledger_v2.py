"""End-to-end tests for the unified Party Ledger v2.

Covers every settlement combination from the product brief:
 - user's example: FF owes Rakshit ₹1L, FF pays vendor ₹25k → FF owes ₹75k
 - mirror: Rakshit owes FF ₹1L, FF pays vendor ₹25k → Rakshit owes ₹1.25L
 - dashboard totals aggregate correctly
 - reversal fully undoes both effects
 - direct vendor payment reduces payable
 - split payment (Rakshit + FF cover a vendor bill together)
 - customer receipt via Father's Firm creates linked FF receivable
 - transfer between Rakshit and FF
 - duplicate reference is blocked
 - reversal is idempotent-safe
"""

import os
import asyncio
import pytest
import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE = os.environ["REACT_APP_BACKEND_URL"] if os.environ.get("REACT_APP_BACKEND_URL") else "http://localhost:8001"
if not BASE.endswith("/api"):
    BASE_API = BASE.rstrip("/") + "/api"
else:
    BASE_API = BASE

# Read REACT_APP_BACKEND_URL from frontend .env if available
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
def clean_ledger(client):
    """Purge all party_ledger_entries, reset Rakshit + Father's Firm opening to 0."""
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _clean():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.party_ledger_entries.delete_many({})
        await db.parties.update_many(
            {"is_system": True},
            {"$set": {"opening_balance": 0}},
        )
    asyncio.run(_clean())


def _party_by_type(client, ptype):
    r = client.get("/party-ledger-v2/parties")
    r.raise_for_status()
    for p in r.json()["parties"]:
        if p["type"] == ptype:
            return p
    return None


def _set_opening(client, pid, amount):
    p = client.get(f"/party-ledger-v2/parties/{pid}").json()["party"]
    p["opening_balance"] = amount
    r = client.put(f"/party-ledger-v2/parties/{pid}", json=p)
    r.raise_for_status()


def _get_balance(client, pid):
    r = client.get(f"/party-ledger-v2/parties/{pid}").json()
    return r["net_balance"], r["status"]


# --------------------------------------------------------------
# User's spec examples
# --------------------------------------------------------------
def test_ff_owed_rakshit_1L_pays_vendor_25k(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    vendor = _party_by_type(client, "vendor")
    assert ff and vendor, "system parties must be seeded"
    # Set FF opening = -100000 (FF owes Rakshit ₹1L)
    _set_opening(client, ff["id"], -100000)
    bal, status = _get_balance(client, ff["id"])
    assert status == "You Receive" and bal == -100000

    # Post: FF pays vendor ₹25000
    r = client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 25000, "paid_by_party_id": ff["id"],
    })
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 2

    ff_bal, ff_status = _get_balance(client, ff["id"])
    assert ff_status == "You Receive", f"got {ff_status}"
    assert abs(ff_bal - (-75000)) < 0.01, f"expected -75000, got {ff_bal}"


def test_rakshit_owed_ff_1L_ff_pays_vendor_25k(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    vendor = _party_by_type(client, "vendor")
    _set_opening(client, ff["id"], 100000)   # Rakshit owes FF ₹1L
    bal, status = _get_balance(client, ff["id"])
    assert status == "You Pay" and bal == 100000

    client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 25000, "paid_by_party_id": ff["id"],
    }).raise_for_status()

    ff_bal, ff_status = _get_balance(client, ff["id"])
    assert ff_status == "You Pay"
    assert abs(ff_bal - 125000) < 0.01, f"expected 125000, got {ff_bal}"


# --------------------------------------------------------------
# Direct vendor payment (no FF linkage)
# --------------------------------------------------------------
def test_direct_vendor_payment_reduces_payable(client, clean_ledger):
    vendor = _party_by_type(client, "vendor")
    bal_before, _ = _get_balance(client, vendor["id"])   # from existing purchase
    client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment", "amount": 10000,
    }).raise_for_status()
    bal_after, _ = _get_balance(client, vendor["id"])
    assert abs((bal_before - 10000) - bal_after) < 0.01


# --------------------------------------------------------------
# Split payment
# --------------------------------------------------------------
def test_split_payment_between_rakshit_and_ff(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    vendor = _party_by_type(client, "vendor")
    ff_before, _ = _get_balance(client, ff["id"])
    v_before, _ = _get_balance(client, vendor["id"])

    # Vendor bill ₹50,000 paid: ₹30k by Rakshit + ₹20k by FF
    client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 50000, "paid_by_party_id": ff["id"],
        "split_paid_by_amount": 20000,
    }).raise_for_status()

    ff_after, _ = _get_balance(client, ff["id"])
    v_after, _ = _get_balance(client, vendor["id"])
    assert abs((v_before - 50000) - v_after) < 0.01, "vendor payable should drop by full ₹50k"
    assert abs((ff_before + 20000) - ff_after) < 0.01, "FF settlement should shift by only the ₹20k it fronted"


# --------------------------------------------------------------
# Customer receipt via Father's Firm
# --------------------------------------------------------------
def test_customer_receipt_via_ff(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    r = client.get("/party-ledger-v2/parties").json()
    customer = next(p for p in r["parties"] if p["type"] == "customer")
    c_before, _ = _get_balance(client, customer["id"])
    ff_before, _ = _get_balance(client, ff["id"])

    client.post("/party-ledger-v2/transactions", json={
        "party_id": customer["id"], "category": "customer_payment",
        "amount": 50000, "received_by_party_id": ff["id"],
    }).raise_for_status()

    c_after, _ = _get_balance(client, customer["id"])
    ff_after, _ = _get_balance(client, ff["id"])
    # customer's balance shifts by +50k (they paid, so they owe less)
    assert abs((c_before + 50000) - c_after) < 0.01
    # FF now owes Rakshit that money — shift by -50k
    assert abs((ff_before - 50000) - ff_after) < 0.01


# --------------------------------------------------------------
# Reversal
# --------------------------------------------------------------
def test_reversal_undoes_both_sides(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    vendor = _party_by_type(client, "vendor")
    ff_before, _ = _get_balance(client, ff["id"])
    v_before, _ = _get_balance(client, vendor["id"])

    r = client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 12345, "paid_by_party_id": ff["id"],
    })
    txn_ref = r.json()["txn_ref"]
    # confirm the deltas landed
    assert abs(_get_balance(client, ff["id"])[0] - (ff_before + 12345)) < 0.01
    assert abs(_get_balance(client, vendor["id"])[0] - (v_before - 12345)) < 0.01

    # Reverse
    rev = client.delete(f"/party-ledger-v2/transactions/{txn_ref}")
    assert rev.status_code == 200
    assert _get_balance(client, ff["id"])[0] == pytest.approx(ff_before)
    assert _get_balance(client, vendor["id"])[0] == pytest.approx(v_before)
    # Second reversal should 404
    r2 = client.delete(f"/party-ledger-v2/transactions/{txn_ref}")
    assert r2.status_code == 404


# --------------------------------------------------------------
# Duplicate-reference guard
# --------------------------------------------------------------
def test_duplicate_reference_blocked(client, clean_ledger):
    vendor = _party_by_type(client, "vendor")
    payload = {
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 500, "reference": "UNIQ-REF-42",
    }
    a = client.post("/party-ledger-v2/transactions", json=payload)
    assert a.status_code == 200
    b = client.post("/party-ledger-v2/transactions", json=payload)
    assert b.status_code == 409


# --------------------------------------------------------------
# Transfer (no P&L impact — only shifts party balance)
# --------------------------------------------------------------
def test_transfer_rakshit_to_ff(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    ff_before, _ = _get_balance(client, ff["id"])
    client.post("/party-ledger-v2/transactions", json={
        "party_id": ff["id"], "category": "transfer",
        "amount": 30000, "direction": "you_receive",
        "notes": "Rakshit transferred cash to FF",
    }).raise_for_status()
    ff_after, _ = _get_balance(client, ff["id"])
    # Rakshit sent cash to FF → FF owes Rakshit more → delta -30000
    assert abs((ff_before - 30000) - ff_after) < 0.01


# --------------------------------------------------------------
# Dashboard totals reflect all effects
# --------------------------------------------------------------
def test_dashboard_totals_after_transactions(client, clean_ledger):
    ff = _party_by_type(client, "fathers_firm")
    vendor = _party_by_type(client, "vendor")
    _set_opening(client, ff["id"], 50000)
    client.post("/party-ledger-v2/transactions", json={
        "party_id": vendor["id"], "category": "vendor_payment",
        "amount": 8000, "paid_by_party_id": ff["id"],
    })
    s = client.get("/party-ledger-v2/summary").json()
    # FF opening 50k + linked 8k = 58k on the you_pay side
    assert s["fathers_firm_you_pay"] == pytest.approx(58000)
    # vendor payable dropped by 8k
    # (rest of vendor payables depend on seed — we check only relative)
    assert s["vendor_you_pay"] >= 0


# --------------------------------------------------------------
# Cleanup after suite
# --------------------------------------------------------------
def test_zzz_final_cleanup(client, clean_ledger):
    """Explicit clean-up test that runs last (alphabetically)."""
    ff = _party_by_type(client, "fathers_firm")
    _set_opening(client, ff["id"], 0)
    assert True
