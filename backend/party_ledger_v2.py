"""
Unified Party Ledger — v2
=========================

Every counterparty in the workshop is modelled as a Party (vendor, customer,
father's firm, or self / Rakshit). Rakshit is the implicit point-of-view: every
balance is reported as either "You Pay" (Rakshit owes this party) or
"You Receive" (this party owes Rakshit) or "Settled".

Data model
----------
    parties collection: {
        id, name, type ('self'|'fathers_firm'|'vendor'|'customer'|'other'),
        is_system, archived,
        legacy_vendor_id (nullable), legacy_customer_name (nullable),
        opening_balance, opening_date, opening_notes,
        contact { phone, email, gstin, address },
        created_at, updated_at
    }

    party_ledger_entries collection (manual + linked only): {
        id, txn_ref (shared across linked entries of one event),
        party_id, party_name,                    # denormalized
        date (ISO), category, amount,            # amount is always positive
        delta_you_pay,                           # signed: +ve → Rakshit owes party more
        notes, direction_label,
        paid_by_party_id, received_by_party_id,
        account_id, account_name,
        related_order_id, related_purchase_id,
        related_customer_payment_id, related_purchase_payment_id,
        origin ('manual'|'migration'|'reversal'),
        reversal_of, reversed_by, reversed_at,
        created_at, source_note
    }

Derived entries (orders, purchases, customer_payments, purchase_payments) are
NOT stored — they are merged in at read time so the derived ledger always
reflects the current source-of-truth data.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

# Phase 6 · Slice 5 — the sign convention, settled threshold, and
# paise-safe money conversion all live in the shared domain layer now.
from domain import (
    to_paise, from_paise,
    party_delta_for_row as _domain_party_delta,
    party_status_from_paise as _domain_party_status,
    CATEGORY_SIGN_MAP as _DOMAIN_CATEGORY_SIGN,
)
from pydantic import BaseModel, ConfigDict, Field


router = APIRouter(prefix="/party-ledger-v2", tags=["party-ledger"])


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------
PartyType = Literal["self", "fathers_firm", "vendor", "customer", "other"]

# Categories in the unified ledger. All are user-facing labels (no debit/credit).
CATEGORY_LABELS = {
    "opening_balance":  "Opening balance",
    "purchase":         "Purchase",
    "purchase_return":  "Purchase return",
    "packing":          "Packing charges",
    "sale_invoice":     "Sale / invoice",
    "customer_payment": "Customer payment",
    "vendor_payment":   "Vendor payment",
    "expense":          "Expense (on their behalf)",
    "income":           "Income",
    "transfer":         "Transfer",
    "advance":          "Advance",
    "credit_note":      "Credit note",
    "discount":         "Discount",
    "adjustment":       "Adjustment",
}


class PartyContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phone: Optional[str] = ""
    email: Optional[str] = ""
    gstin: Optional[str] = ""
    address: Optional[str] = ""


class Party(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: PartyType = "other"
    is_system: bool = False
    archived: bool = False
    legacy_vendor_id: Optional[str] = None
    legacy_customer_name: Optional[str] = None
    opening_balance: float = 0.0   # +ve = you owe them from day-1, -ve = they owe you
    opening_date: Optional[str] = None
    opening_notes: Optional[str] = ""
    contact: PartyContact = Field(default_factory=PartyContact)
    notes: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PartyTransactionIn(BaseModel):
    """Payload for POST /party-transactions — the unified quick-entry form."""
    model_config = ConfigDict(extra="ignore")
    party_id: str
    category: str                        # one of CATEGORY_LABELS keys
    amount: float                        # always positive; sign is derived from category
    date: Optional[str] = None
    notes: Optional[str] = ""
    # Linked posting hints:
    paid_by_party_id: Optional[str] = None       # e.g. 'Father's Firm' pays vendor for me
    received_by_party_id: Optional[str] = None   # customer money received via Father's Firm
    # For transfers / adjustments where the direction isn't implied by category
    direction: Optional[Literal["you_pay", "you_receive"]] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = ""
    # Optional relationships
    related_order_id: Optional[str] = None
    related_purchase_id: Optional[str] = None
    reference: Optional[str] = ""
    # Split payment support: split.amount is what the *paid_by_party* covers,
    # the remainder (amount − split.amount) is treated as Rakshit paying.
    split_paid_by_amount: Optional[float] = None


# ------------------------------------------------------------------
# Sign / delta rules — Phase 6 · Slice 5: signs live in domain.py now.
# ------------------------------------------------------------------
# +ve delta = Rakshit owes party MORE. -ve = party owes Rakshit MORE.
# Vendor party ⇒ purchases push +, payments push −.
# Customer party ⇒ sales push −, receipts push +.
#
# The canonical CATEGORY_SIGN map now lives in domain.CATEGORY_SIGN_MAP;
# this local alias exists only for existing imports (`from party_ledger_v2
# import CATEGORY_SIGN`) that some tests may reference.
CATEGORY_SIGN = _DOMAIN_CATEGORY_SIGN


def _resolve_delta(cat: str, amount: float, direction: Optional[str]) -> float:
    """Thin adapter over domain.party_delta_for_row. Preserves the exact
    pre-Phase-6 float signature — internally routes through paise HALF_UP
    so precision is preserved and drift-free."""
    return from_paise(_domain_party_delta(cat, to_paise(amount), direction))


def _status_from_balance(bal: float) -> str:
    """Thin adapter over domain.party_status_from_paise. Preserves the
    exact pre-Phase-6 `< 0.5` semantics — a balance of exactly ₹0.50 is
    NOT Settled, it's the labelled direction."""
    return _domain_party_status(to_paise(bal))


# ------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------
async def _party_by_id(db, pid: str) -> Optional[dict]:
    return await db.parties.find_one({"id": pid}, {"_id": 0})


async def _get_or_create_party(db, *, name: str, ptype: PartyType,
                               legacy_vendor_id: Optional[str] = None,
                               legacy_customer_name: Optional[str] = None,
                               is_system: bool = False) -> dict:
    """Idempotent — match by legacy id first, then case-insensitive name."""
    if not name:
        raise ValueError("party name required")
    # Try legacy vendor id first
    if legacy_vendor_id:
        p = await db.parties.find_one({"legacy_vendor_id": legacy_vendor_id}, {"_id": 0})
        if p:
            return p
    # Then case-insensitive name match
    p = await db.parties.find_one(
        {"name": {"$regex": f"^{name.strip()}$", "$options": "i"}},
        {"_id": 0},
    )
    if p:
        # If we now know a legacy id or type, backfill it
        updates = {}
        if legacy_vendor_id and not p.get("legacy_vendor_id"):
            updates["legacy_vendor_id"] = legacy_vendor_id
        if legacy_customer_name and not p.get("legacy_customer_name"):
            updates["legacy_customer_name"] = legacy_customer_name
        if p.get("type") == "other" and ptype != "other":
            updates["type"] = ptype
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.parties.update_one({"id": p["id"]}, {"$set": updates})
            p.update(updates)
        return p
    # Create
    party = Party(
        name=name.strip(),
        type=ptype,
        is_system=is_system,
        legacy_vendor_id=legacy_vendor_id,
        legacy_customer_name=legacy_customer_name,
    ).model_dump()
    await db.parties.insert_one(party)
    return party


# ------------------------------------------------------------------
# Derived entries — computed live at read-time from source collections
# ------------------------------------------------------------------
async def _derived_entries_for_party(db, party: dict) -> List[dict]:
    """Build derived ledger lines from orders/purchases/customer_payments/
    purchase_payments. These are NOT stored, they are merged with the manual
    entries in party_ledger_entries at read time."""
    out: List[dict] = []
    ptype = party.get("type")
    pname = party.get("name")

    if ptype == "customer":
        # Sales invoices — one line per order (uses stored invoice_total which
        # already reflects shipped-portion tax).
        async for o in db.orders.find({"client_name": pname}, {"_id": 0}):
            inv = float(o.get("invoice_total") or 0)
            if inv <= 0 and not (o.get("shipments") or []):
                continue
            out.append({
                "id": f"ORD-{o.get('id')}",
                "txn_ref": f"order:{o.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": o.get("last_shipped_date") or o.get("shipped_date") or o.get("order_date"),
                "category": "sale_invoice",
                "amount": inv,
                "delta_you_pay": -inv,
                "notes": f"Order #{(o.get('id') or '')[:8]}",
                "related_order_id": o.get("id"),
                "origin": "auto",
                "created_at": o.get("created_at"),
            })
        # Customer receipts
        async for pay in db.customer_payments.find({"customer_name": pname}, {"_id": 0}):
            amt = from_paise(to_paise(pay.get("amount")))
            out.append({
                "id": f"CP-{pay.get('id')}",
                "txn_ref": f"cust_payment:{pay.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pay.get("date"),
                "category": "customer_payment",
                "amount": amt,
                "delta_you_pay": +amt,
                "notes": f"Payment · {pay.get('mode') or 'Cash'}"
                         + (f" → {pay.get('account_name')}" if pay.get("account_name") else "")
                         + (f" · Ref {pay.get('reference')}" if pay.get("reference") else ""),
                "related_customer_payment_id": pay.get("id"),
                "account_id": pay.get("account_id"),
                "account_name": pay.get("account_name"),
                "origin": "auto",
                "created_at": pay.get("created_at"),
            })

    elif ptype == "vendor":
        # Purchase invoices
        query = {"vendor_name": pname}
        if party.get("legacy_vendor_id"):
            query = {"$or": [{"vendor_id": party["legacy_vendor_id"]}, {"vendor_name": pname}]}
        async for pur in db.purchases.find(query, {"_id": 0}):
            inv = float(pur.get("invoice_total") or 0)
            out.append({
                "id": f"PUR-{pur.get('id')}",
                "txn_ref": f"purchase:{pur.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pur.get("purchase_date") or pur.get("date") or pur.get("created_at"),
                "category": "purchase",
                "amount": inv,
                "delta_you_pay": +inv,
                "notes": f"Purchase #{(pur.get('id') or '')[:8]}"
                         + (f" · Bill {pur.get('bill_number')}" if pur.get("bill_number") else ""),
                "related_purchase_id": pur.get("id"),
                "origin": "auto",
                "created_at": pur.get("created_at"),
            })
        # Vendor payments
        async for pay in db.purchase_payments.find({"vendor_name": pname}, {"_id": 0}):
            amt = from_paise(to_paise(pay.get("amount")))
            out.append({
                "id": f"PP-{pay.get('id')}",
                "txn_ref": f"purchase_payment:{pay.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pay.get("date"),
                "category": "vendor_payment",
                "amount": amt,
                "delta_you_pay": -amt,
                "notes": f"Payment · {pay.get('mode') or 'Cash'}"
                         + (f" ← {pay.get('account_name')}" if pay.get("account_name") else "")
                         + (f" · Ref {pay.get('reference')}" if pay.get("reference") else ""),
                "related_purchase_payment_id": pay.get("id"),
                "account_id": pay.get("account_id"),
                "account_name": pay.get("account_name"),
                "origin": "auto",
                "created_at": pay.get("created_at"),
            })

    elif ptype == "fathers_firm":
        # Father's Firm acts as the "Factory" supplier on Order → Purchases:
        # auto-linked purchase docs land here with vendor_name = FACTORY_PARTY_NAME
        # ("Father's Firm"). Each such purchase increases what Rakshit owes FF,
        # and any purchase payment against them reduces that same balance —
        # mirroring the vendor branch above.
        async for pur in db.purchases.find(
            {"vendor_name": pname}, {"_id": 0},
        ):
            inv = float(pur.get("invoice_total") or 0)
            if inv <= 0:
                continue
            out.append({
                "id": f"PUR-{pur.get('id')}",
                "txn_ref": f"purchase:{pur.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pur.get("purchase_date") or pur.get("date") or pur.get("created_at"),
                "category": "purchase",
                "amount": inv,
                "delta_you_pay": +inv,
                "notes": f"Factory purchase #{(pur.get('id') or '')[:8]}"
                         + (f" · Order {(pur.get('linked_to_order_id') or '')[:8]}"
                            if pur.get("linked_to_order_id") else "")
                         + (f" · {pur.get('linked_cost_category') or ''}".rstrip(" ·")
                            if pur.get("linked_cost_category") else ""),
                "related_purchase_id": pur.get("id"),
                "linked_to_order_id": pur.get("linked_to_order_id"),
                "origin": "auto",
                "created_at": pur.get("created_at"),
            })
        async for pay in db.purchase_payments.find({"vendor_name": pname}, {"_id": 0}):
            amt = from_paise(to_paise(pay.get("amount")))
            if amt <= 0:
                continue
            out.append({
                "id": f"PP-{pay.get('id')}",
                "txn_ref": f"purchase_payment:{pay.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pay.get("date"),
                "category": "vendor_payment",
                "amount": amt,
                "delta_you_pay": -amt,
                "notes": f"Payment to Father's Firm · {pay.get('mode') or 'Cash'}"
                         + (f" ← {pay.get('account_name')}" if pay.get("account_name") else "")
                         + (f" · Ref {pay.get('reference')}" if pay.get("reference") else ""),
                "related_purchase_payment_id": pay.get("id"),
                "account_id": pay.get("account_id"),
                "account_name": pay.get("account_name"),
                "origin": "auto",
                "created_at": pay.get("created_at"),
            })

    # Opening balance as a synthetic first entry
    ob = float(party.get("opening_balance") or 0)
    if abs(ob) >= 0.01:
        out.append({
            "id": f"OPEN-{party['id']}",
            "txn_ref": f"opening:{party['id']}",
            "party_id": party["id"], "party_name": pname,
            "date": party.get("opening_date") or party.get("created_at"),
            "category": "opening_balance",
            "amount": abs(ob),
            "delta_you_pay": ob,
            "notes": party.get("opening_notes") or "Opening balance",
            "origin": "auto",
            "created_at": party.get("created_at"),
        })

    # ------------------------------------------------------------------
    # LINKED-PARTY effects derived from customer/purchase payment fields.
    # These fire for ANY party (Father's Firm, other) whenever a payment
    # was recorded with paid_by_party_id / received_by_party_id pointing
    # to *this* party. This keeps derived + manual layers deduplicated —
    # linked effects are re-computed live from the source payment row
    # instead of being copied into party_ledger_entries.
    # ------------------------------------------------------------------
    if ptype != "self":
        # Purchase payments where THIS party fronted the money on Rakshit's behalf
        async for pay in db.purchase_payments.find(
            {"paid_by_party_id": party["id"]}, {"_id": 0},
        ):
            full_amt = from_paise(to_paise(pay.get("amount")))
            split = pay.get("split_paid_by_amount")
            eff_amt = float(split) if split is not None else full_amt
            if eff_amt <= 0:
                continue
            out.append({
                "id": f"PP-LINK-{pay.get('id')}",
                "txn_ref": f"purchase_payment:{pay.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pay.get("date"),
                "category": "vendor_payment",
                "amount": eff_amt,
                "delta_you_pay": +eff_amt,   # you now owe this party more
                "notes": f"Paid to {pay.get('vendor_name')} on your behalf"
                         + (f" · Ref {pay.get('reference')}" if pay.get("reference") else ""),
                "related_purchase_payment_id": pay.get("id"),
                "account_id": pay.get("account_id"),
                "account_name": pay.get("account_name"),
                "paid_by_party_id": None,
                "received_by_party_id": None,
                "origin": "auto",
                "created_at": pay.get("created_at"),
            })
        # Customer payments where THIS party received the money on Rakshit's behalf
        async for pay in db.customer_payments.find(
            {"received_by_party_id": party["id"]}, {"_id": 0},
        ):
            amt = from_paise(to_paise(pay.get("amount")))
            if amt <= 0:
                continue
            out.append({
                "id": f"CP-LINK-{pay.get('id')}",
                "txn_ref": f"cust_payment:{pay.get('id')}",
                "party_id": party["id"], "party_name": pname,
                "date": pay.get("date"),
                "category": "customer_payment",
                "amount": amt,
                "delta_you_pay": -amt,   # you now hold Rakshit's money → they owe you back
                "notes": f"Collected from {pay.get('customer_name')} on your behalf"
                         + (f" · Ref {pay.get('reference')}" if pay.get("reference") else ""),
                "related_customer_payment_id": pay.get("id"),
                "account_id": pay.get("account_id"),
                "account_name": pay.get("account_name"),
                "paid_by_party_id": None,
                "received_by_party_id": None,
                "origin": "auto",
                "created_at": pay.get("created_at"),
            })

    return out


async def _manual_entries_for_party(db, party_id: str, include_reversed: bool = False) -> List[dict]:
    """Non-reversed manual/linked entries.
    Reversals + their originals are excluded from balance calc but returned in
    the audit view (include_reversed=True).
    """
    if include_reversed:
        return await db.party_ledger_entries.find(
            {"party_id": party_id}, {"_id": 0},
        ).to_list(20000)
    return await db.party_ledger_entries.find(
        {"party_id": party_id,
         "reversed_at": None,
         "origin": {"$ne": "reversal"}},
        {"_id": 0},
    ).to_list(20000)


async def _party_full_ledger(db, party: dict, include_reversed: bool = False) -> dict:
    derived = await _derived_entries_for_party(db, party)
    manual = await _manual_entries_for_party(db, party["id"], include_reversed=include_reversed)
    entries = derived + manual

    def _sort_key(e):
        d = e.get("date") or e.get("created_at") or ""
        return (d, e.get("created_at") or "")

    entries.sort(key=_sort_key)

    balance = 0.0
    for e in entries:
        # reversed / reversal entries are excluded from balance running but shown in audit view
        counts_in_balance = not (e.get("origin") == "reversal" or e.get("reversed_at"))
        if counts_in_balance:
            balance += float(e.get("delta_you_pay") or 0)
        e["running_balance"] = round(balance, 2)
        e["running_status"] = _status_from_balance(balance)
        e["counts_in_balance"] = counts_in_balance
        e["category_label"] = CATEGORY_LABELS.get(e.get("category"), e.get("category"))

    bal_r = round(balance, 2)
    return {
        "party": party,
        "entries": entries,
        "net_balance": bal_r,
        "status": _status_from_balance(bal_r),
        "you_pay": bal_r if bal_r > 0 else 0.0,
        "you_receive": -bal_r if bal_r < 0 else 0.0,
    }


# ------------------------------------------------------------------
# Migration / seeding (idempotent)
# ------------------------------------------------------------------
async def ensure_bootstrap(db):
    """Called on server startup. Seeds system parties and derived parties.
    Idempotent — safe to run repeatedly.
    """
    # 1. System parties
    await _get_or_create_party(db, name="Rakshit", ptype="self", is_system=True)
    await _get_or_create_party(db, name="Father's Firm", ptype="fathers_firm", is_system=True)

    # 2. Vendors
    async for v in db.vendors.find({}, {"_id": 0}):
        name = (v.get("name") or "").strip()
        if not name:
            continue
        await _get_or_create_party(
            db, name=name, ptype="vendor",
            legacy_vendor_id=v.get("id"),
        )

    # 3. Customers (from unique client_name in orders)
    client_names = await db.orders.distinct("client_name")
    for name in client_names:
        if not name:
            continue
        await _get_or_create_party(
            db, name=str(name).strip(), ptype="customer",
            legacy_customer_name=str(name).strip(),
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
def make_router(db):
    r = APIRouter(prefix="/party-ledger-v2", tags=["party-ledger"])

    @r.get("/parties")
    async def list_parties(
        q: Optional[str] = None,
        type: Optional[str] = None,
        include_settled: bool = True,
    ):
        query = {"archived": False}
        if type and type != "all":
            query["type"] = type
        if q:
            query["name"] = {"$regex": q, "$options": "i"}
        docs = await db.parties.find(query, {"_id": 0}).sort("name", 1).to_list(5000)

        # Compute balance for each (light-weight — no full ledger)
        results = []
        for p in docs:
            data = await _party_full_ledger(db, p)
            bal = data["net_balance"]
            status = data["status"]
            if not include_settled and status == "Settled":
                continue
            entries = data["entries"]
            you_pay = sum(e["delta_you_pay"] for e in entries if e["delta_you_pay"] > 0)
            you_receive = -sum(e["delta_you_pay"] for e in entries if e["delta_you_pay"] < 0)
            results.append({
                **p,
                "net_balance": bal,
                "status": status,
                "abs_balance": abs(bal),
                "entries_count": len(entries),
                "total_you_pay_side": round(you_pay, 2),
                "total_you_receive_side": round(you_receive, 2),
                "last_activity": entries[-1]["date"] if entries else None,
            })

        # Sort by absolute balance DESC (biggest exposure first)
        results.sort(key=lambda x: -x["abs_balance"])
        return {
            "count": len(results),
            "parties": results,
        }

    @r.get("/summary")
    async def dashboard_summary():
        """Aggregate cards for the dashboard."""
        parties = await db.parties.find({"archived": False}, {"_id": 0}).to_list(5000)
        totals = {
            "fathers_firm_you_pay": 0.0,
            "fathers_firm_you_receive": 0.0,
            "vendor_you_pay": 0.0,
            "vendor_advances_you_receive": 0.0,
            "customer_you_receive": 0.0,
            "customer_advances_you_pay": 0.0,
            "net_position": 0.0,   # positive = you pay overall, negative = you receive overall
        }
        for p in parties:
            data = await _party_full_ledger(db, p)
            bal = data["net_balance"]
            totals["net_position"] += bal
            if p["type"] == "fathers_firm":
                if bal > 0:
                    totals["fathers_firm_you_pay"] += bal
                else:
                    totals["fathers_firm_you_receive"] += -bal
            elif p["type"] == "vendor":
                if bal > 0:
                    totals["vendor_you_pay"] += bal
                else:
                    totals["vendor_advances_you_receive"] += -bal
            elif p["type"] == "customer":
                if bal < 0:
                    totals["customer_you_receive"] += -bal
                else:
                    totals["customer_advances_you_pay"] += bal
        return {k: round(v, 2) for k, v in totals.items()}

    @r.get("/parties/{pid}")
    async def get_party(pid: str, include_reversed: bool = False):
        p = await _party_by_id(db, pid)
        if not p:
            raise HTTPException(404, "Party not found")
        return await _party_full_ledger(db, p, include_reversed=include_reversed)

    @r.post("/parties")
    async def create_party(payload: Party):
        # Validate unique name
        clash = await db.parties.find_one(
            {"name": {"$regex": f"^{payload.name.strip()}$", "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        if clash:
            raise HTTPException(400, f"A party named '{payload.name}' already exists.")
        doc = payload.model_dump()
        doc["created_at"] = datetime.now(timezone.utc).isoformat()
        doc["updated_at"] = doc["created_at"]
        await db.parties.insert_one(doc)
        doc.pop("_id", None)
        return doc

    @r.put("/parties/{pid}")
    async def update_party(pid: str, payload: Party):
        existing = await _party_by_id(db, pid)
        if not existing:
            raise HTTPException(404, "Party not found")
        if existing.get("is_system"):
            # Allow editing contact/opening only, not type/name
            payload.name = existing["name"]
            payload.type = existing["type"]
            payload.is_system = True
        doc = payload.model_dump()
        doc["id"] = pid
        doc["created_at"] = existing.get("created_at")
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.parties.replace_one({"id": pid}, doc)
        return doc

    @r.delete("/parties/{pid}")
    async def archive_party(pid: str):
        existing = await _party_by_id(db, pid)
        if not existing:
            raise HTTPException(404, "Party not found")
        if existing.get("is_system"):
            raise HTTPException(400, "System parties cannot be archived.")
        await db.parties.update_one({"id": pid}, {"$set": {"archived": True, "updated_at": datetime.now(timezone.utc).isoformat()}})
        return {"archived": True}

    # ---------- Party transactions (manual / linked) ----------
    async def _create_entry(db, *, txn_ref: str, party_id: str, party_name: str,
                            date: str, category: str, amount: float,
                            delta_you_pay: float, notes: str = "",
                            paid_by_party_id: Optional[str] = None,
                            received_by_party_id: Optional[str] = None,
                            account_id: Optional[str] = None,
                            account_name: Optional[str] = "",
                            related_order_id: Optional[str] = None,
                            related_purchase_id: Optional[str] = None,
                            reference: Optional[str] = "",
                            origin: str = "manual",
                            reversal_of: Optional[str] = None):
        entry = {
            "id": str(uuid.uuid4()),
            "txn_ref": txn_ref,
            "party_id": party_id,
            "party_name": party_name,
            "date": date,
            "category": category,
            "amount": round(abs(float(amount or 0)), 2),
            "delta_you_pay": round(float(delta_you_pay or 0), 2),
            "notes": notes or "",
            "paid_by_party_id": paid_by_party_id,
            "received_by_party_id": received_by_party_id,
            "account_id": account_id,
            "account_name": account_name or "",
            "related_order_id": related_order_id,
            "related_purchase_id": related_purchase_id,
            "reference": reference or "",
            "origin": origin,
            "reversal_of": reversal_of,
            "reversed_by": None,
            "reversed_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.party_ledger_entries.insert_one(entry)
        entry.pop("_id", None)
        return entry

    async def _post_linked_transaction(db, payload: PartyTransactionIn) -> dict:
        """Atomic — build all entries in memory, then insert together.
        Returns the list of created entries + the shared txn_ref."""
        party = await _party_by_id(db, payload.party_id)
        if not party:
            raise HTTPException(404, "Party not found")

        # Idempotency guard — if this exact reference has already been posted, reject
        if payload.reference:
            dupe = await db.party_ledger_entries.find_one(
                {"reference": payload.reference, "reversed_at": None},
                {"_id": 0, "txn_ref": 1},
            )
            if dupe:
                raise HTTPException(409, f"A transaction with reference '{payload.reference}' already exists.")

        cat = payload.category
        if cat not in CATEGORY_LABELS:
            raise HTTPException(400, f"Unknown category '{cat}'.")
        amt = round(abs(float(payload.amount or 0)), 2)
        if amt <= 0:
            raise HTTPException(400, "Amount must be greater than zero.")

        txn_ref = str(uuid.uuid4())
        date = payload.date or datetime.now(timezone.utc).isoformat()

        # -------- Primary delta for the target party --------
        primary_delta = _resolve_delta(cat, amt, payload.direction)

        # -------- Linked entry — paid_by / received_by --------
        # Split payment: split_paid_by_amount is what paid_by covers, rest is Rakshit's direct hit.
        linked_amt = amt
        primary_amt = amt
        if payload.paid_by_party_id and payload.split_paid_by_amount is not None:
            linked_amt = round(min(amt, max(0.0, float(payload.split_paid_by_amount))), 2)
            primary_amt = amt   # primary still reduces vendor's payable by full amt

        # Fetch linked party lazily
        linked_party = None
        if payload.paid_by_party_id:
            linked_party = await _party_by_id(db, payload.paid_by_party_id)
            if not linked_party:
                raise HTTPException(404, "paid_by party not found")

        received_by_party = None
        if payload.received_by_party_id:
            received_by_party = await _party_by_id(db, payload.received_by_party_id)
            if not received_by_party:
                raise HTTPException(404, "received_by party not found")

        entries_to_create: list[dict] = []

        # 1) Primary entry on the target party
        primary_notes = payload.notes or ""
        if payload.paid_by_party_id and linked_party and linked_party["type"] != "self":
            primary_notes = (primary_notes + f" · Paid by {linked_party['name']}").strip(" ·")
        if payload.received_by_party_id and received_by_party and received_by_party["type"] != "self":
            primary_notes = (primary_notes + f" · Received via {received_by_party['name']}").strip(" ·")

        entries_to_create.append({
            "kwargs": dict(
                txn_ref=txn_ref, party_id=party["id"], party_name=party["name"],
                date=date, category=cat, amount=primary_amt,
                delta_you_pay=primary_delta if primary_amt == amt else (primary_delta / amt) * primary_amt,
                notes=primary_notes,
                paid_by_party_id=payload.paid_by_party_id,
                received_by_party_id=payload.received_by_party_id,
                account_id=payload.account_id, account_name=payload.account_name,
                related_order_id=payload.related_order_id,
                related_purchase_id=payload.related_purchase_id,
                reference=payload.reference,
            ),
        })

        # 2) Linked entry — Father's Firm (or any other non-self party) pays on my behalf
        # Applicable when the primary category represents money flowing OUT (payment/expense/purchase/packing/advance)
        outward_categories = {"vendor_payment", "purchase", "packing", "expense", "advance"}
        if payload.paid_by_party_id and linked_party and linked_party["type"] != "self" and cat in outward_categories:
            # linked party has fronted `linked_amt` on Rakshit's behalf → Rakshit owes linked party more
            entries_to_create.append({
                "kwargs": dict(
                    txn_ref=txn_ref, party_id=linked_party["id"], party_name=linked_party["name"],
                    date=date, category="vendor_payment" if cat == "vendor_payment" else cat,
                    amount=linked_amt,
                    delta_you_pay=+linked_amt,   # you now owe linked party
                    notes=f"Paid to {party['name']} on your behalf"
                          + (f" · {payload.notes}" if payload.notes else ""),
                    paid_by_party_id=None, received_by_party_id=None,
                    account_id=payload.account_id, account_name=payload.account_name,
                    related_order_id=payload.related_order_id,
                    related_purchase_id=payload.related_purchase_id,
                    reference=payload.reference,
                ),
            })

        # 3) Linked entry — Customer money received via Father's Firm
        # Applicable when primary category = customer_payment / income and received_by is non-self
        inward_categories = {"customer_payment", "income"}
        if payload.received_by_party_id and received_by_party and received_by_party["type"] != "self" and cat in inward_categories:
            # linked party is HOLDING money that Rakshit is due → they owe Rakshit
            entries_to_create.append({
                "kwargs": dict(
                    txn_ref=txn_ref, party_id=received_by_party["id"], party_name=received_by_party["name"],
                    date=date, category="customer_payment" if cat == "customer_payment" else cat,
                    amount=amt,
                    delta_you_pay=-amt,     # they owe you
                    notes=f"Collected from {party['name']} on your behalf"
                          + (f" · {payload.notes}" if payload.notes else ""),
                    paid_by_party_id=None, received_by_party_id=None,
                    account_id=payload.account_id, account_name=payload.account_name,
                    reference=payload.reference,
                ),
            })

        # 4) Transfer between Rakshit and a non-self party
        # Category = transfer. Direction 'you_pay' means Rakshit → party (money out).
        if cat == "transfer":
            # the primary entry handles the balance change on target party;
            # we didn't add a delta from CATEGORY_SIGN so use resolved primary_delta.
            pass   # nothing additional

        # ---- Atomic insert ----
        created = []
        try:
            for e in entries_to_create:
                doc = await _create_entry(db, **e["kwargs"])
                created.append(doc)
        except Exception as ex:
            # Rollback: delete anything we've inserted for this txn_ref
            await db.party_ledger_entries.delete_many({"txn_ref": txn_ref})
            raise HTTPException(500, f"Failed to post transaction: {ex}")

        return {"txn_ref": txn_ref, "entries": created}

    @r.post("/transactions")
    async def create_transaction(payload: PartyTransactionIn):
        return await _post_linked_transaction(db, payload)

    @r.delete("/transactions/{txn_ref}")
    async def reverse_transaction(txn_ref: str):
        """Soft-reverse an entire linked transaction — creates opposite entries,
        preserving audit trail."""
        entries = await db.party_ledger_entries.find(
            {"txn_ref": txn_ref, "reversed_at": None, "origin": {"$ne": "reversal"}},
            {"_id": 0},
        ).to_list(20)
        if not entries:
            raise HTTPException(404, "Transaction not found or already reversed.")
        now = datetime.now(timezone.utc).isoformat()
        reversal_txn = f"REV-{txn_ref}"
        for e in entries:
            reversal = {
                **e,
                "id": str(uuid.uuid4()),
                "txn_ref": reversal_txn,
                "delta_you_pay": -float(e["delta_you_pay"]),
                "notes": (e.get("notes") or "") + " · REVERSAL",
                "origin": "reversal",
                "reversal_of": e["id"],
                "created_at": now,
                "reversed_at": None,
            }
            await db.party_ledger_entries.insert_one(reversal)
            await db.party_ledger_entries.update_one(
                {"id": e["id"]},
                {"$set": {"reversed_at": now, "reversed_by": reversal["id"]}},
            )
        return {"reversed_txn_ref": txn_ref, "reversal_txn_ref": reversal_txn, "count": len(entries)}

    @r.put("/transactions/{txn_ref}")
    async def edit_transaction(txn_ref: str, payload: PartyTransactionIn):
        """Reverse the old posting and create a fresh one — preserves audit trail."""
        await reverse_transaction(txn_ref)
        return await _post_linked_transaction(db, payload)

    @r.get("/transactions/{txn_ref}")
    async def get_transaction(txn_ref: str):
        entries = await db.party_ledger_entries.find(
            {"txn_ref": txn_ref}, {"_id": 0}
        ).sort("created_at", 1).to_list(20)
        if not entries:
            raise HTTPException(404, "Transaction not found.")
        return {"txn_ref": txn_ref, "entries": entries}

    # ---------- CSV exports ----------
    def _stream_csv(rows: list[dict], filename: str) -> StreamingResponse:
        if not rows:
            rows = [{"info": "no rows"}]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if v is None else v) for k, v in row.items()})
        buf.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)

    def _flatten_entry(e: dict) -> dict:
        impact = float(e.get("delta_you_pay") or 0)
        return {
            "date":               (e.get("date") or "")[:10],
            "txn_ref":            e.get("txn_ref") or "",
            "party":              e.get("party_name") or "",
            "category":           CATEGORY_LABELS.get(e.get("category"), e.get("category")) or "",
            "description":        e.get("notes") or "",
            "amount":             e.get("amount") or 0,
            "effect":             "You Pay" if impact > 0 else ("You Receive" if impact < 0 else "No change"),
            "effect_amount":      abs(impact),
            "running_balance":    e.get("running_balance"),
            "running_status":     e.get("running_status"),
            "payment_source":     e.get("account_name") or "",
            "paid_by_party_id":   e.get("paid_by_party_id") or "",
            "received_by_party_id": e.get("received_by_party_id") or "",
            "related_order_id":   e.get("related_order_id") or "",
            "related_purchase_id": e.get("related_purchase_id") or "",
            "related_customer_payment_id": e.get("related_customer_payment_id") or "",
            "related_purchase_payment_id": e.get("related_purchase_payment_id") or "",
            "reversal_status":    ("Reversed" if e.get("reversed_at") else ("Reversal" if e.get("origin") == "reversal" else "Active")),
            "origin":             e.get("origin") or "",
            "created_at":         e.get("created_at") or "",
        }

    @r.get("/parties/{pid}/ledger.csv")
    async def export_party_ledger_csv(pid: str, include_reversed: bool = True):
        p = await _party_by_id(db, pid)
        if not p:
            raise HTTPException(404, "Party not found")
        data = await _party_full_ledger(db, p, include_reversed=include_reversed)
        rows = [_flatten_entry(e) for e in data["entries"]]
        # Ensure at least a header row on empty ledgers
        if not rows:
            rows = [_flatten_entry({})]
        safe = "".join(c for c in p["name"] if c.isalnum() or c in " -_").strip() or "party"
        return _stream_csv(rows, f"ledger_{safe.replace(' ', '_')}.csv")

    @r.get("/exports/vendors.csv")
    async def export_all_vendor_balances_csv():
        parties = await db.parties.find({"type": "vendor", "archived": False}, {"_id": 0}).sort("name", 1).to_list(5000)
        rows = []
        for p in parties:
            data = await _party_full_ledger(db, p)
            rows.append({
                "party":            p["name"],
                "status":           data["status"],
                "you_pay":          data["you_pay"],
                "you_receive":      data["you_receive"],
                "net_balance":      data["net_balance"],
                "entries":          len(data["entries"]),
                "opening_balance":  p.get("opening_balance") or 0,
                "last_activity":    (data["entries"][-1]["date"] if data["entries"] else ""),
                "phone":            (p.get("contact") or {}).get("phone", ""),
                "gstin":            (p.get("contact") or {}).get("gstin", ""),
            })
        if not rows:
            rows = [{"party": "", "status": "", "you_pay": 0, "you_receive": 0}]
        return _stream_csv(rows, "vendor_balances.csv")

    @r.get("/exports/customers.csv")
    async def export_all_customer_balances_csv():
        parties = await db.parties.find({"type": "customer", "archived": False}, {"_id": 0}).sort("name", 1).to_list(5000)
        rows = []
        for p in parties:
            data = await _party_full_ledger(db, p)
            rows.append({
                "party":            p["name"],
                "status":           data["status"],
                "you_pay":          data["you_pay"],
                "you_receive":      data["you_receive"],
                "net_balance":      data["net_balance"],
                "entries":          len(data["entries"]),
                "last_activity":    (data["entries"][-1]["date"] if data["entries"] else ""),
                "phone":            (p.get("contact") or {}).get("phone", ""),
                "gstin":            (p.get("contact") or {}).get("gstin", ""),
            })
        if not rows:
            rows = [{"party": "", "status": "", "you_pay": 0, "you_receive": 0}]
        return _stream_csv(rows, "customer_balances.csv")

    @r.get("/fathers-firm-settlement")
    async def fathers_firm_settlement():
        """Single signed settlement for Father's Firm — replaces the two-card
        You Pay / You Receive split on the dashboard.

        Returns exactly one signed balance and a status string:
          - Positive → status = "you_receive" (they owe Rakshit)
          - Negative → status = "you_pay"     (Rakshit owes them)
          - Zero     → status = "settled"

        Uses the SAME `_party_full_ledger` logic as the ledger detail view so
        there is no drift or double-counting. Also returns the underlying
        signed balance from the party ledger so the frontend can display a
        single card without doing any calculation itself.
        """
        p = await db.parties.find_one({"type": "fathers_firm", "archived": False}, {"_id": 0})
        if not p:
            return {"balance_signed": 0.0, "amount": 0.0, "status": "settled",
                    "label": "Father's Firm Settlement", "party_id": None}
        data = await _party_full_ledger(db, p)
        # In this ledger convention, delta_you_pay > 0 means Rakshit owes party
        # (you_pay), and < 0 means party owes Rakshit (you_receive). Convert to a
        # single signed "amount" where +ve = you_receive, -ve = you_pay to match
        # the UI spec (Positive → You Receive).
        bal = float(data.get("net_balance") or 0.0)
        # Phase 3: fold in derived transfer effects. `db.transfers` is the sole
        # source of truth for account-level transfers involving FF, so its
        # signed contribution must be added to the ledger-entry-derived total.
        try:
            from transfers import ff_settlement_delta_from_transfers
            bal += await ff_settlement_delta_from_transfers(db)
        except Exception:
            pass
        signed = -bal  # flip sign so +ve = you_receive
        if signed > 0.5:
            status = "you_receive"
        elif signed < -0.5:
            status = "you_pay"
        else:
            status = "settled"
        return {
            "party_id": p.get("id"),
            "party_name": p.get("name"),
            "balance_signed": round(signed, 2),
            "amount": round(abs(signed), 2),
            "status": status,
            "label": "Father's Firm Settlement",
        }

    @r.get("/exports/fathers-firm.csv")
    async def export_fathers_firm_ledger_csv(include_reversed: bool = True):
        p = await db.parties.find_one({"type": "fathers_firm"}, {"_id": 0})
        if not p:
            raise HTTPException(404, "Father's Firm party not found")
        data = await _party_full_ledger(db, p, include_reversed=include_reversed)
        rows = [_flatten_entry(e) for e in data["entries"]] or [_flatten_entry({})]
        return _stream_csv(rows, "fathers_firm_ledger.csv")

    @r.get("/exports/summary.csv")
    async def export_summary_csv():
        # Reuse the same aggregation logic as /summary
        parties = await db.parties.find({"archived": False}, {"_id": 0}).to_list(5000)
        totals = {
            "fathers_firm_you_pay": 0.0, "fathers_firm_you_receive": 0.0,
            "vendor_you_pay": 0.0, "vendor_advances_you_receive": 0.0,
            "customer_you_receive": 0.0, "customer_advances_you_pay": 0.0,
            "net_position": 0.0,
        }
        for p in parties:
            data = await _party_full_ledger(db, p)
            bal = data["net_balance"]
            totals["net_position"] += bal
            if p["type"] == "fathers_firm":
                (totals.__setitem__("fathers_firm_you_pay", totals["fathers_firm_you_pay"] + bal) if bal > 0
                 else totals.__setitem__("fathers_firm_you_receive", totals["fathers_firm_you_receive"] + (-bal)))
            elif p["type"] == "vendor":
                (totals.__setitem__("vendor_you_pay", totals["vendor_you_pay"] + bal) if bal > 0
                 else totals.__setitem__("vendor_advances_you_receive", totals["vendor_advances_you_receive"] + (-bal)))
            elif p["type"] == "customer":
                (totals.__setitem__("customer_you_receive", totals["customer_you_receive"] + (-bal)) if bal < 0
                 else totals.__setitem__("customer_advances_you_pay", totals["customer_advances_you_pay"] + bal))
        rows = [
            {"metric": "You Pay Father's Firm",       "amount": round(totals["fathers_firm_you_pay"], 2)},
            {"metric": "You Receive from Father's Firm", "amount": round(totals["fathers_firm_you_receive"], 2)},
            {"metric": "Total vendor payables",       "amount": round(totals["vendor_you_pay"], 2)},
            {"metric": "Vendor advances",             "amount": round(totals["vendor_advances_you_receive"], 2)},
            {"metric": "Customer receivables",        "amount": round(totals["customer_you_receive"], 2)},
            {"metric": "Customer advances",           "amount": round(totals["customer_advances_you_pay"], 2)},
            {"metric": "Net settlement position",     "amount": round(totals["net_position"], 2)},
        ]
        return _stream_csv(rows, "party_ledger_summary.csv")

    return r
