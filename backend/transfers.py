"""Phase 3 (P1) — First-Class Transfers.

`db.transfers` is the SOLE source of truth for every transfer event.
Account balances and Party Ledger v2 effects are DERIVED / linked
projections — never independent transaction rows. Because Mongo runs
standalone here (no multi-doc transactions), the single `db.transfers`
insert is the atomic commit boundary; all downstream views recompute
idempotently on read.

Transfer philosophy
-------------------
A transfer is ONE real business event with TWO sides. Each side is
either an Account (from Rakshit's chart of accounts) or a protected
Party (currently only `system_fathers_firm`). Transfers are excluded
from Received / Paid / Revenue / Expense / Profit KPIs.

Transfer types
--------------
- `account_to_account`  : Rakshit-account → Rakshit-account (bank↔cash,
                          bank↔bank, etc.). Tracked-account cash total
                          is unchanged; the transfer sums to zero.
- `rakshit_to_ff`       : money leaves a Rakshit account and lands with
                          Father's Firm. Tracked-account cash goes DOWN
                          by `amount`. FF settlement moves the same
                          amount in the "Rakshit owes FF LESS" direction
                          (delta_you_pay = -amount).
- `ff_to_rakshit`       : money arrives from Father's Firm into a
                          Rakshit account. Tracked-account cash goes UP
                          by `amount`. FF settlement moves in the
                          "Rakshit owes FF MORE" direction
                          (delta_you_pay = +amount).

Father's Firm signed-balance convention (from party_ledger_v2)
--------------------------------------------------------------
delta_you_pay > 0  ⇒  Rakshit owes FF MORE.
delta_you_pay < 0  ⇒  Rakshit owes FF LESS  (equivalently, FF owes
                       Rakshit more).

Numeric example
    Start: Rakshit ICICI = ₹1,00,000; FF settlement net = ₹0.
    T1: rakshit_to_ff ₹10,000 from ICICI.
       → ICICI balance = ₹90,000.
       → FF net_balance = -₹10,000  (Rakshit paid FF; FF now owes
          Rakshit ₹10,000 back, or Rakshit's obligation to FF fell).
    T2: ff_to_rakshit ₹4,000 to Cash.
       → Cash balance += ₹4,000.
       → FF net_balance += +₹4,000  → -₹6,000  (FF still owes ₹6k).

Reversal & edits are IMMUTABLE
------------------------------
An edit is not a mutation — it emits a reversal transfer (which flips
`from_side` ↔ `to_side`) and then creates a new replacement transfer.
The original document is left untouched with `status='reversed'` and a
pointer to the reversal transfer. Reversals themselves cannot be
edited or reversed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from party_sync import SYSTEM_FF_ID


TransferKind = Literal["account_to_account", "rakshit_to_ff", "ff_to_rakshit"]
TransferSideType = Literal["account", "party"]
TransferStatus = Literal["active", "reversed"]


# ─── Models ─────────────────────────────────────────────────────────────────


class TransferSide(BaseModel):
    """Either an account row (Rakshit's chart) or a protected party."""
    model_config = ConfigDict(extra="ignore")
    type: TransferSideType
    account_id: Optional[str] = None
    account_name: Optional[str] = ""
    party_id: Optional[str] = None
    party_name: Optional[str] = ""


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    from_side: TransferSide
    to_side: TransferSide
    amount: float
    mode: str = "Bank Transfer"
    reference: Optional[str] = ""
    related_order_id: Optional[str] = ""
    notes: Optional[str] = ""
    idempotency_key: Optional[str] = None


class Transfer(BaseModel):
    """Canonical transfer document. Sole source of truth."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    txn_ref: str = ""                       # "transfer:<id>"
    date: str
    kind: TransferKind
    from_side: TransferSide
    to_side: TransferSide
    amount: float
    mode: str = "Bank Transfer"
    reference: str = ""
    related_order_id: str = ""
    notes: str = ""
    status: TransferStatus = "active"
    reversed_transfer_id: Optional[str] = None      # points to the reversal doc
    reverses_transfer_id: Optional[str] = None      # set on reversal docs
    idempotency_key: Optional[str] = None
    legacy_cbe_id: Optional[str] = None             # deterministic migration marker
    depends_on_transfer_ids: list[str] = []         # direct doc dependencies
    created_by: str = "system"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─── Validation ─────────────────────────────────────────────────────────────


def _side_key(s: TransferSide) -> str:
    """Stable comparable key for a side — used for same-source-and-destination checks."""
    if s.type == "account":
        return f"account:{s.account_id or ''}"
    return f"party:{s.party_id or ''}"


def classify_kind(from_side: TransferSide, to_side: TransferSide) -> TransferKind:
    """Derive the semantic kind from the two sides."""
    fa = from_side.type == "account"
    ta = to_side.type == "account"
    if fa and ta:
        return "account_to_account"
    if fa and to_side.type == "party" and to_side.party_id == SYSTEM_FF_ID:
        return "rakshit_to_ff"
    if from_side.type == "party" and from_side.party_id == SYSTEM_FF_ID and ta:
        return "ff_to_rakshit"
    raise HTTPException(400, "Unsupported transfer sides.")


async def _load_account(db, aid: str) -> dict:
    doc = await db.accounts.find_one({"id": aid}, {"_id": 0})
    if not doc:
        raise HTTPException(400, f"Account {aid!r} not found.")
    if doc.get("archived"):
        raise HTTPException(400, f"Account {doc.get('name') or aid!r} is archived; cannot transfer.")
    return doc


async def _validate_side(db, side: TransferSide) -> TransferSide:
    """Snapshot the display name and validate the side. Returns the side
    with denormalised name populated."""
    if side.type == "account":
        if not side.account_id:
            raise HTTPException(400, "Account side requires account_id.")
        acc = await _load_account(db, side.account_id)
        side.account_name = acc.get("name") or side.account_name or ""
    elif side.type == "party":
        if side.party_id != SYSTEM_FF_ID:
            raise HTTPException(400, "Only the protected system_fathers_firm party is a valid transfer side.")
        side.party_name = "Father's Firm"
    else:
        raise HTTPException(400, f"Unknown side type: {side.type!r}")
    return side


async def _validate_transfer(db, payload: TransferIn) -> tuple[TransferSide, TransferSide, TransferKind]:
    if payload.amount is None or float(payload.amount) <= 0:
        raise HTTPException(400, "Amount must be greater than zero.")
    fs = await _validate_side(db, payload.from_side)
    ts = await _validate_side(db, payload.to_side)
    if _side_key(fs) == _side_key(ts):
        raise HTTPException(400, "Transfer source and destination must differ.")
    kind = classify_kind(fs, ts)
    return fs, ts, kind


# ─── Idempotency ────────────────────────────────────────────────────────────


async def ensure_transfer_indexes(db) -> None:
    """Sparse unique index on idempotency_key + supporting query indexes."""
    await db.transfers.create_index(
        "idempotency_key",
        unique=True,
        name="transfer_idempotency_uidx",
        partialFilterExpression={"idempotency_key": {"$exists": True, "$type": "string"}},
    )
    await db.transfers.create_index([("date", -1)], name="transfer_date_idx")
    await db.transfers.create_index([("legacy_cbe_id", 1)],
                                    name="transfer_legacy_cbe_uidx",
                                    unique=True,
                                    partialFilterExpression={
                                        "legacy_cbe_id": {"$exists": True, "$type": "string"}
                                    })


# ─── Create / Reverse / Edit ────────────────────────────────────────────────


async def create_transfer(db, payload: TransferIn, *, created_by: str = "user",
                          legacy_cbe_id: Optional[str] = None) -> Transfer:
    """Insert one canonical Transfer document (atomic commit boundary).
    Ledger + account balance views recompute idempotently on read."""
    fs, ts, kind = await _validate_transfer(db, payload)

    # Idempotency: if the key was already used, return the original doc.
    if payload.idempotency_key:
        existing = await db.transfers.find_one(
            {"idempotency_key": payload.idempotency_key}, {"_id": 0}
        )
        if existing:
            return Transfer(**existing)

    tid = str(uuid.uuid4())
    doc = Transfer(
        id=tid,
        txn_ref=f"transfer:{tid}",
        date=payload.date,
        kind=kind,
        from_side=fs,
        to_side=ts,
        amount=float(payload.amount),
        mode=payload.mode or "Bank Transfer",
        reference=payload.reference or "",
        related_order_id=payload.related_order_id or "",
        notes=payload.notes or "",
        idempotency_key=payload.idempotency_key,
        legacy_cbe_id=legacy_cbe_id,
        created_by=created_by,
    ).model_dump()
    await db.transfers.insert_one(doc)
    return Transfer(**doc)


async def reverse_transfer(db, transfer_id: str, *, created_by: str = "user") -> Transfer:
    """Emit an IMMUTABLE reversal transfer — flips `from_side` ↔ `to_side`,
    marks the original `status='reversed'` and cross-links both docs.
    Reversal transfers themselves cannot be reversed or edited."""
    orig = await db.transfers.find_one({"id": transfer_id}, {"_id": 0})
    if not orig:
        raise HTTPException(404, "Transfer not found.")
    if orig.get("status") == "reversed":
        raise HTTPException(409, "Transfer is already reversed.")
    if orig.get("reverses_transfer_id"):
        raise HTTPException(400, "Reversal transfers are immutable.")

    # Block only if a DIRECT dependent transfer references this one.
    dependent = await db.transfers.find_one(
        {"depends_on_transfer_ids": transfer_id, "status": "active"},
        {"_id": 0, "id": 1},
    )
    if dependent:
        raise HTTPException(409, f"Cannot reverse — transfer {dependent['id']} directly depends on this one.")

    now = datetime.now(timezone.utc).isoformat()
    rid = str(uuid.uuid4())
    reversal = Transfer(
        id=rid,
        txn_ref=f"transfer:{rid}",
        date=orig["date"],
        kind={"account_to_account": "account_to_account",
              "rakshit_to_ff": "ff_to_rakshit",
              "ff_to_rakshit": "rakshit_to_ff"}[orig["kind"]],
        from_side=TransferSide(**orig["to_side"]),      # swapped
        to_side=TransferSide(**orig["from_side"]),      # swapped
        amount=orig["amount"],
        mode=orig.get("mode") or "Bank Transfer",
        reference=orig.get("reference") or "",
        related_order_id=orig.get("related_order_id") or "",
        notes=(orig.get("notes") or "") + " · REVERSAL",
        status="active",
        reverses_transfer_id=orig["id"],
        created_by=created_by,
    ).model_dump()
    reversal["created_at"] = now
    reversal["updated_at"] = now
    await db.transfers.insert_one(reversal)
    await db.transfers.update_one(
        {"id": orig["id"]},
        {"$set": {"status": "reversed", "reversed_transfer_id": rid,
                  "updated_at": now}},
    )
    return Transfer(**reversal)


async def edit_transfer(db, transfer_id: str, payload: TransferIn, *,
                        created_by: str = "user") -> Transfer:
    """Edits are `reverse + replace`. Original is immutable — a reversal
    transfer is emitted first, then a new active transfer is created
    with the new payload."""
    await reverse_transfer(db, transfer_id, created_by=created_by)
    return await create_transfer(db, payload, created_by=created_by)


# ─── Derived views ──────────────────────────────────────────────────────────


def _apply_transfer_to_account_balance(t: dict, account_id: str) -> float:
    """Return the signed delta this transfer produces on the given account.
    Includes both `active` originals AND `reversed` originals — the paired
    reversal transfer (which is itself active with swapped sides) cancels
    a reversed original, so summing both is correct. Only reversal docs
    that themselves have `reverses_transfer_id` set are still active and
    counted; the original stays counted so history is preserved."""
    fs = t.get("from_side") or {}
    ts = t.get("to_side") or {}
    delta = 0.0
    if fs.get("type") == "account" and fs.get("account_id") == account_id:
        delta -= float(t.get("amount") or 0)
    if ts.get("type") == "account" and ts.get("account_id") == account_id:
        delta += float(t.get("amount") or 0)
    return delta


async def derive_account_balance(db, account_id: str) -> dict:
    """Consolidated account balance: opening + customer_payments (in)
    − purchase_payments (out) + cash_book_entries (income − expense)
    ± transfers. All derived — no stored balance."""
    acc = await db.accounts.find_one({"id": account_id}, {"_id": 0})
    if not acc:
        raise HTTPException(404, "Account not found")

    opening = float(acc.get("opening_balance") or 0)

    incoming = 0.0
    async for p in db.customer_payments.find({"account_id": account_id}, {"_id": 0, "amount": 1}):
        incoming += float(p.get("amount") or 0)
    outgoing = 0.0
    async for p in db.purchase_payments.find({"account_id": account_id}, {"_id": 0, "amount": 1}):
        outgoing += float(p.get("amount") or 0)

    cbe_in = 0.0
    cbe_out = 0.0
    async for e in db.cash_book_entries.find(
        {"account_id": account_id,
         "source": {"$ne": "legacy_shim"},
         "migrated_to_transfer_id": {"$exists": False},
         "reversed": {"$ne": True},
         "kind": {"$ne": "transfer"}},   # transfers are handled below via db.transfers
        {"_id": 0, "kind": 1, "amount": 1},
    ):
        if e.get("kind") == "general_income":
            cbe_in += float(e.get("amount") or 0)
        elif e.get("kind") == "general_expense":
            cbe_out += float(e.get("amount") or 0)

    transfer_delta = 0.0
    # Include BOTH `active` and `reversed` originals. Reversals themselves
    # (which are `active` docs with `reverses_transfer_id` set) have swapped
    # sides and cancel their originals — the net delta across the pair is 0.
    async for t in db.transfers.find({"$or": [{"from_side.account_id": account_id},
                                              {"to_side.account_id": account_id}]},
                                     {"_id": 0}):
        transfer_delta += _apply_transfer_to_account_balance(t, account_id)

    return {
        "account_id": account_id,
        "account_name": acc.get("name"),
        "opening_balance": opening,
        "incoming": round(incoming + cbe_in, 2),
        "outgoing": round(outgoing + cbe_out, 2),
        "transfer_net": round(transfer_delta, 2),
        "balance": round(opening + incoming + cbe_in - outgoing - cbe_out + transfer_delta, 2),
    }


async def ff_settlement_delta_from_transfers(db) -> float:
    """Signed FF-side delta contributed by transfers. Consumed by the
    Party Ledger v2 FF settlement projection. Counts BOTH `active` and
    `reversed` originals — the reversal transfer (active, swapped sides)
    cancels its original via `classify_kind` flipping direction, so a
    reversed rakshit_to_ff pairs with an active ff_to_rakshit to net 0."""
    total = 0.0
    async for t in db.transfers.find(
        {"$or": [{"from_side.party_id": SYSTEM_FF_ID},
                 {"to_side.party_id": SYSTEM_FF_ID}]},
        {"_id": 0}
    ):
        # rakshit_to_ff  → Rakshit paid FF → FF is owed less → delta_you_pay = -amount
        # ff_to_rakshit  → FF paid Rakshit → Rakshit owes FF more → +amount
        amt = float(t.get("amount") or 0)
        if t.get("kind") == "rakshit_to_ff":
            total -= amt
        elif t.get("kind") == "ff_to_rakshit":
            total += amt
    return round(total, 2)


# ─── Migration ──────────────────────────────────────────────────────────────


async def run_transfer_migration(db) -> dict:
    """Deterministic migration keyed on the legacy CBE id. Never emits a
    duplicate migrated row and never leaves both a legacy transfer CBE
    and its migrated Transfer visible on the same timeline.

    For each cash_book_entries[kind='transfer'] row that has NOT yet been
    migrated (`migrated_to_transfer_id` unset):
      1. Insert one canonical Transfer with `legacy_cbe_id = <cbe.id>`.
      2. Stamp the legacy CBE with `migrated_to_transfer_id = <new_id>`.
    Idempotent — subsequent runs no-op.
    """
    created = 0
    skipped_no_account = 0
    already_migrated = 0
    async for cbe in db.cash_book_entries.find(
        {"kind": "transfer",
         "source": {"$ne": "legacy_shim"},
         "migrated_to_transfer_id": {"$exists": False}},
        {"_id": 0},
    ):
        fa = cbe.get("from_account_id") or ""
        ta = cbe.get("to_account_id") or ""
        if not fa or not ta:
            # Best-effort — old CBE rows without proper account references
            # are left in place but marked so they don't appear again.
            skipped_no_account += 1
            await db.cash_book_entries.update_one(
                {"id": cbe["id"]},
                {"$set": {"migrated_to_transfer_id": None,
                          "migration_note": "skipped_missing_account_ids"}},
            )
            continue

        # Deterministic check: was this already migrated in a prior run?
        prior = await db.transfers.find_one({"legacy_cbe_id": cbe["id"]}, {"_id": 0})
        if prior:
            already_migrated += 1
            await db.cash_book_entries.update_one(
                {"id": cbe["id"]},
                {"$set": {"migrated_to_transfer_id": prior["id"]}},
            )
            continue

        payload = TransferIn(
            date=cbe.get("date") or datetime.now(timezone.utc).date().isoformat(),
            from_side=TransferSide(type="account", account_id=fa,
                                   account_name=cbe.get("from_account_name") or ""),
            to_side=TransferSide(type="account", account_id=ta,
                                 account_name=cbe.get("to_account_name") or ""),
            amount=float(cbe.get("amount") or 0),
            mode=cbe.get("mode") or "Bank Transfer",
            reference=cbe.get("reference") or "",
            notes=cbe.get("notes") or "",
        )
        try:
            t = await create_transfer(db, payload,
                                      created_by="migration",
                                      legacy_cbe_id=cbe["id"])
        except HTTPException as e:
            skipped_no_account += 1
            await db.cash_book_entries.update_one(
                {"id": cbe["id"]},
                {"$set": {"migration_note": f"skipped: {e.detail}"}},
            )
            continue
        await db.cash_book_entries.update_one(
            {"id": cbe["id"]},
            {"$set": {"migrated_to_transfer_id": t.id}},
        )
        created += 1

    return {
        "phase": "P3_transfers",
        "created": created,
        "skipped_no_account": skipped_no_account,
        "already_migrated": already_migrated,
    }
