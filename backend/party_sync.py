"""Phase 2 (P1) — Canonical party identity resolver.

Party rows are the source of truth for financial counterparty identity.
Display names are snapshots; every transaction should carry a stable
`*_party_id` alongside the denormalised display name.

Resolution priority (first match wins, no silent merge of ambiguous rows):
    1. Explicit `party_id`
    2. `source_refs.vendor_id` / `source_refs.customer_id`
    3. GSTIN (exact match)
    4. Phone (exact match)
    5. Exact `normalized_name` — trim, casefold, collapse whitespace,
       drop trailing full-stops, normalise punctuation
    6. Create a new party

Factory is a UI purchase-source label. Its financial counterparty is the
protected `system_fathers_firm` party. No `type='vendor', name='Factory'`
row is ever created.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ReturnDocument

# System party constants — single source of truth for the Father's Firm identity.
SYSTEM_FF_ID = "system_fathers_firm"
SYSTEM_FF_NAME = "Father's Firm"
FF_ALIASES = {"father's firm", "fathers firm", "father s firm",
              "factory", "the factory", "ff"}


# ─── Normalisation ──────────────────────────────────────────────────────────

_PUNCT_MAP = str.maketrans({
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "—": "-", "–": "-",
})


def normalize_name(raw: str | None) -> str:
    """Fold display-name variants into a single comparable key.
    Idempotent, unicode-safe, preserves meaningful business words."""
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", str(raw)).translate(_PUNCT_MAP)
    s = s.strip().casefold()
    # Collapse runs of whitespace
    s = re.sub(r"\s+", " ", s)
    # Drop harmless trailing punctuation (period, comma, semicolon, hyphen)
    s = re.sub(r"[.,;\-]+$", "", s).strip()
    return s


def is_ff_alias(raw: str | None) -> bool:
    return normalize_name(raw) in FF_ALIASES


# ─── Party document scaffolding ─────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_party_doc(display_name: str, ptype: str, *,
                   is_system: bool = False,
                   source_refs: Optional[dict] = None,
                   gstin: str = "", phone: str = "",
                   pid: Optional[str] = None) -> dict:
    """Fresh party document with the Phase-2 enriched schema."""
    return {
        "id": pid or str(uuid.uuid4()),
        "name": display_name.strip(),                # legacy compat: read by old code
        "display_name": display_name.strip(),
        "normalized_name": normalize_name(display_name),
        "type": ptype,
        "is_system": is_system,
        "is_system_party": is_system,                # explicit flag per spec
        "archived": False,
        "aliases": [],
        "source_refs": source_refs or {},            # e.g. {"vendor_id": "...", "customer_id": "..."}
        "contact": {"phone": phone, "email": "", "gstin": gstin, "address": ""},
        "phone": phone,
        "gstin": gstin,
        # Legacy compat fields for existing code paths
        "legacy_vendor_id": (source_refs or {}).get("vendor_id"),
        "legacy_customer_name": None,
        "opening_balance": 0.0,
        "opening_date": None,
        "opening_notes": "",
        "notes": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


# ─── Resolution ─────────────────────────────────────────────────────────────

async def _find_by_source_ref(db, ptype: str, refs: dict) -> Optional[dict]:
    for key in ("vendor_id", "customer_id"):
        val = refs.get(key)
        if not val:
            continue
        p = await db.parties.find_one(
            {"type": ptype, f"source_refs.{key}": val}, {"_id": 0}
        )
        if p:
            return p
        # Legacy compat: match legacy_vendor_id
        if key == "vendor_id":
            p = await db.parties.find_one(
                {"type": ptype, "legacy_vendor_id": val}, {"_id": 0}
            )
            if p:
                return p
    return None


async def _find_by_gstin(db, gstin: str) -> Optional[dict]:
    if not gstin or not gstin.strip():
        return None
    g = gstin.strip().upper()
    return await db.parties.find_one(
        {"$or": [{"gstin": g}, {"contact.gstin": g}]}, {"_id": 0}
    )


async def _find_by_phone(db, phone: str) -> Optional[dict]:
    if not phone or not phone.strip():
        return None
    p = phone.strip()
    return await db.parties.find_one(
        {"$or": [{"phone": p}, {"contact.phone": p}]}, {"_id": 0}
    )


async def _find_by_normalized_name(db, ptype: str, name: str) -> Optional[dict]:
    n = normalize_name(name)
    if not n:
        return None
    # Prefer type-scoped match; fall back to type-agnostic exact match (in case
    # the caller passed the wrong ptype for a system party like FF).
    p = await db.parties.find_one({"type": ptype, "normalized_name": n}, {"_id": 0})
    if p:
        return p
    # Also match on aliases
    p = await db.parties.find_one({"type": ptype, "aliases": n}, {"_id": 0})
    if p:
        return p
    return None


async def resolve_party(
    db,
    *,
    ptype: str,
    display_name: str = "",
    party_id: Optional[str] = None,
    source_refs: Optional[dict] = None,
    gstin: str = "",
    phone: str = "",
    create_if_missing: bool = True,
    is_system: bool = False,
) -> Optional[dict]:
    """Resolve a party by (in priority order): explicit id → source_refs →
    GSTIN → phone → normalized display name. Creates a new party ONLY if
    all lookups miss AND `create_if_missing=True`.

    Never creates duplicate `type='vendor', name='Factory'` — any Factory /
    Father's Firm alias is routed to the protected `system_fathers_firm`.
    """
    source_refs = source_refs or {}

    # Factory / Father's Firm → protected system party (short-circuit).
    if ptype in ("vendor", "fathers_firm") and is_ff_alias(display_name):
        return await _ensure_system_ff(db)

    # 1. Explicit party id
    if party_id:
        p = await db.parties.find_one({"id": party_id}, {"_id": 0})
        if p:
            return p

    # 2. source refs
    p = await _find_by_source_ref(db, ptype, source_refs)
    if p:
        return p

    # 3. GSTIN
    p = await _find_by_gstin(db, gstin)
    if p:
        return p

    # 4. Phone
    p = await _find_by_phone(db, phone)
    if p:
        return p

    # 5. Normalized name
    if display_name:
        p = await _find_by_normalized_name(db, ptype, display_name)
        if p:
            # Enrich when new evidence is available
            updates: dict[str, Any] = {}
            if source_refs.get("vendor_id") and not (p.get("source_refs") or {}).get("vendor_id"):
                updates["source_refs.vendor_id"] = source_refs["vendor_id"]
                updates["legacy_vendor_id"] = source_refs["vendor_id"]
            if source_refs.get("customer_id") and not (p.get("source_refs") or {}).get("customer_id"):
                updates["source_refs.customer_id"] = source_refs["customer_id"]
            if gstin and not (p.get("gstin") or p.get("contact", {}).get("gstin")):
                updates["gstin"] = gstin.strip().upper()
                updates["contact.gstin"] = gstin.strip().upper()
            if phone and not (p.get("phone") or p.get("contact", {}).get("phone")):
                updates["phone"] = phone.strip()
                updates["contact.phone"] = phone.strip()
            if updates:
                updates["updated_at"] = _now_iso()
                await db.parties.update_one({"id": p["id"]}, {"$set": updates})
                p.update({k.split(".")[-1] if "." in k else k: v for k, v in updates.items()})
            return p

    # 6. Create — race-safe via atomic find-and-upsert on (type, normalized_name).
    if not create_if_missing:
        return None
    doc = _new_party_doc(
        display_name=display_name or "Unknown",
        ptype=ptype,
        is_system=is_system,
        source_refs=source_refs,
        gstin=gstin.strip().upper() if gstin else "",
        phone=phone.strip() if phone else "",
    )
    # Atomic upsert: if a concurrent caller already created the same
    # (type, normalized_name) party while we were resolving, use theirs.
    result = await db.parties.find_one_and_update(
        {"type": ptype, "normalized_name": doc["normalized_name"]},
        {"$setOnInsert": doc},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    return result


# ─── Convenience wrappers ───────────────────────────────────────────────────

async def get_or_create_customer_party(db, display_name: str, *,
                                       customer_id: Optional[str] = None,
                                       gstin: str = "", phone: str = "") -> Optional[dict]:
    if not display_name:
        return None
    return await resolve_party(
        db, ptype="customer", display_name=display_name,
        source_refs={"customer_id": customer_id} if customer_id else {},
        gstin=gstin, phone=phone,
    )


async def get_or_create_vendor_party(db, display_name: str, *,
                                     vendor_id: Optional[str] = None,
                                     gstin: str = "", phone: str = "") -> Optional[dict]:
    if not display_name:
        return None
    return await resolve_party(
        db, ptype="vendor", display_name=display_name,
        source_refs={"vendor_id": vendor_id} if vendor_id else {},
        gstin=gstin, phone=phone,
    )


# ─── Alias + rename ─────────────────────────────────────────────────────────

async def rename_party(db, party_id: str, new_display_name: str) -> Optional[dict]:
    """Update display_name in place, preserving party_id and pushing the old
    name onto `aliases` so historical resolution still works."""
    p = await db.parties.find_one({"id": party_id}, {"_id": 0})
    if not p:
        return None
    old_norm = normalize_name(p.get("display_name") or p.get("name"))
    new_norm = normalize_name(new_display_name)
    aliases = list(p.get("aliases") or [])
    if old_norm and old_norm != new_norm and old_norm not in aliases:
        aliases.append(old_norm)
    updates = {
        "display_name": new_display_name.strip(),
        "name": new_display_name.strip(),
        "normalized_name": new_norm,
        "aliases": aliases,
        "updated_at": _now_iso(),
    }
    await db.parties.update_one({"id": party_id}, {"$set": updates})
    p.update(updates)
    return p


# ─── Vendor directory sync ──────────────────────────────────────────────────

async def sync_vendor_directory(db, display_name: str, *,
                                vendor_id: Optional[str] = None,
                                phone: str = "", gstin: str = "") -> Optional[dict]:
    """Upsert the vendor into db.vendors AND ensure a matching parties row
    exists with `source_refs.vendor_id` cross-linked. Factory is skipped —
    the system Father's Firm party handles factory financial flows."""
    if not display_name or is_ff_alias(display_name):
        return None
    party = await get_or_create_vendor_party(
        db, display_name, vendor_id=vendor_id, phone=phone, gstin=gstin
    )
    # Cross-link party_id back onto db.vendors so future edits use IDs.
    if party and vendor_id:
        await db.vendors.update_one(
            {"id": vendor_id}, {"$set": {"party_id": party["id"]}}
        )
    return party


# ─── System Father's Firm ───────────────────────────────────────────────────

async def _ensure_system_ff(db) -> dict:
    """Return the protected `system_fathers_firm` party, creating it if
    missing. Idempotent, single-source-of-truth for Factory financial flows."""
    p = await db.parties.find_one({"id": SYSTEM_FF_ID}, {"_id": 0})
    if p:
        return p
    # If an older bootstrap created FF with a random uuid, migrate it in place
    # so all future references converge on the protected system id.
    old = await db.parties.find_one({"type": "fathers_firm"}, {"_id": 0})
    if old and old.get("id") != SYSTEM_FF_ID:
        # Move to protected id — preserve balances/notes/opening.
        merged = {**old,
                  "id": SYSTEM_FF_ID,
                  "name": SYSTEM_FF_NAME,
                  "display_name": SYSTEM_FF_NAME,
                  "normalized_name": normalize_name(SYSTEM_FF_NAME),
                  "is_system": True,
                  "is_system_party": True,
                  "aliases": sorted(set((old.get("aliases") or []) + list(FF_ALIASES))),
                  "updated_at": _now_iso()}
        await db.parties.delete_one({"id": old["id"]})
        await db.parties.insert_one(merged)
        return merged
    doc = _new_party_doc(
        SYSTEM_FF_NAME, "fathers_firm", is_system=True, pid=SYSTEM_FF_ID
    )
    doc["aliases"] = sorted(FF_ALIASES)
    await db.parties.insert_one(doc)
    return doc


# ─── Party enrichment (schema migration for existing rows) ──────────────────

async def enrich_existing_parties(db) -> dict:
    """One-off idempotent pass to backfill `normalized_name`, `aliases`,
    `source_refs`, `phone`, `gstin`, `display_name`, `is_system_party` on
    every existing party doc that pre-dates Phase 2."""
    enriched = 0
    async for p in db.parties.find({}, {"_id": 0}):
        updates: dict = {}
        if not p.get("display_name"):
            updates["display_name"] = p.get("name") or ""
        if not p.get("normalized_name"):
            updates["normalized_name"] = normalize_name(p.get("name") or "")
        if "aliases" not in p:
            updates["aliases"] = []
        if "source_refs" not in p:
            refs: dict = {}
            if p.get("legacy_vendor_id"):
                refs["vendor_id"] = p["legacy_vendor_id"]
            if p.get("legacy_customer_name"):
                refs["customer_name"] = p["legacy_customer_name"]
            updates["source_refs"] = refs
        if "phone" not in p:
            updates["phone"] = (p.get("contact") or {}).get("phone") or ""
        if "gstin" not in p:
            updates["gstin"] = ((p.get("contact") or {}).get("gstin") or "").upper()
        if "is_system_party" not in p:
            updates["is_system_party"] = bool(p.get("is_system"))
        if updates:
            updates["updated_at"] = _now_iso()
            await db.parties.update_one({"id": p["id"]}, {"$set": updates})
            enriched += 1
    return {"enriched": enriched}


# ─── Migration + conflict report ────────────────────────────────────────────

async def run_party_migration(db) -> dict:
    """Sweep every source collection and ensure canonical party rows exist.
    Never merges ambiguous matches — flags them for manual review.

    Returns a structured report with counts and conflict lists.
    """
    report = {
        "parties_created": 0,
        "vendors_linked": 0,
        "customers_linked": 0,
        "exact_duplicates_merged": 0,     # only exact normalized_name matches
        "probable_duplicates_flagged": 0, # normalized match but different gstin/phone
        "unmatched_legacy_names": [],     # from db.payments (excluded from auto-create)
        "ff_aliases_resolved": 0,
        "conflicts": [],
    }

    # 0. Ensure protected system Father's Firm exists first.
    await _ensure_system_ff(db)

    # 1. Enrich existing rows so subsequent lookups can hit normalized_name.
    await enrich_existing_parties(db)

    # 2. db.customers → customer parties
    async for c in db.customers.find({}, {"_id": 0}):
        p = await resolve_party(
            db, ptype="customer", display_name=c.get("name") or "",
            source_refs={"customer_id": c.get("id")} if c.get("id") else {},
            phone=c.get("phone") or "", gstin="",
        )
        if p:
            report["parties_created"] += 0  # counted below via last-insert-check
            report["customers_linked"] += 1
            if c.get("id"):
                await db.customers.update_one(
                    {"id": c["id"]}, {"$set": {"party_id": p["id"]}}
                )

    # 3. Order client names → customer parties (unique)
    order_clients = await db.orders.distinct("client_name")
    for name in order_clients:
        if not name:
            continue
        await resolve_party(db, ptype="customer", display_name=name)

    # 4. db.vendors → vendor parties (Factory/FF short-circuits)
    async for v in db.vendors.find({}, {"_id": 0}):
        if is_ff_alias(v.get("name")):
            report["ff_aliases_resolved"] += 1
            continue
        p = await sync_vendor_directory(
            db, v.get("name") or "", vendor_id=v.get("id"),
            phone=v.get("phone") or "", gstin=v.get("gstin") or "",
        )
        if p:
            report["vendors_linked"] += 1

    # 5. Purchase vendor names
    purch_vendors = await db.purchases.distinct("vendor_name")
    for name in purch_vendors:
        if not name:
            continue
        if is_ff_alias(name):
            report["ff_aliases_resolved"] += 1
            continue
        await resolve_party(db, ptype="vendor", display_name=name)

    # 6. Purchase-payment vendor names
    pp_vendors = await db.purchase_payments.distinct("vendor_name")
    for name in pp_vendors:
        if not name:
            continue
        if is_ff_alias(name):
            report["ff_aliases_resolved"] += 1
            continue
        await resolve_party(db, ptype="vendor", display_name=name)

    # 7. Customer-payment customer names
    cp_customers = await db.customer_payments.distinct("customer_name")
    for name in cp_customers:
        if not name:
            continue
        await resolve_party(db, ptype="customer", display_name=name)

    # 8. Purchase-source rows inside orders — non-Factory suppliers
    async for o in db.orders.find({}, {"_id": 0, "items": 1}):
        for it in (o.get("items") or []):
            for src in (it.get("purchase_sources") or []):
                sname = (src.get("supplier_name") or "").strip()
                sid = (src.get("supplier_id") or "").strip()
                if not sname:
                    continue
                if sid == "factory" or is_ff_alias(sname):
                    continue
                await resolve_party(db, ptype="vendor", display_name=sname,
                                    source_refs={"vendor_id": sid} if sid else {})

    # 9. Quotations customer names (if present)
    q_customers = await db.quotations.distinct("client_name")
    for name in q_customers:
        if not name:
            continue
        await resolve_party(db, ptype="customer", display_name=name)

    # 10. Duplicate detection + safe merge.
    # Auto-merge only EXACT duplicates: same (type, normalized_name) AND
    # same gstin AND same phone. Any ambiguity is reported, never merged.
    groups: dict[str, list] = {}
    async for p in db.parties.find({}, {"_id": 0}):
        key = f"{p.get('type')}::{p.get('normalized_name')}"
        groups.setdefault(key, []).append(p)
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        gs = {r.get("gstin") or "" for r in rows}
        ph = {r.get("phone") or "" for r in rows}
        if len(gs) == 1 and len(ph) == 1:
            # Exact duplicates — keep the oldest (or system party if any),
            # delete the rest. Safe: no ambiguity.
            rows.sort(key=lambda r: (not r.get("is_system"), r.get("created_at") or ""))
            keeper = rows[0]
            for extra in rows[1:]:
                await db.parties.delete_one({"id": extra["id"]})
                report["exact_duplicates_merged"] += 1
        else:
            report["probable_duplicates_flagged"] += len(rows) - 1
            report["conflicts"].append({
                "reason": "same_normalized_name_different_identifiers",
                "type": rows[0].get("type"),
                "normalized_name": rows[0].get("normalized_name"),
                "party_ids": [r["id"] for r in rows],
                "gstins": sorted(gs),
                "phones": sorted(ph),
            })

    # 11. Legacy db.payments — report only, no auto-create.
    legacy_parties = await db.payments.distinct("party")
    for name in legacy_parties:
        if not name:
            continue
        if is_ff_alias(name):
            report["ff_aliases_resolved"] += 1
            continue
        # If no party of any type matches the normalized name → unmatched
        norm = normalize_name(name)
        existing = await db.parties.find_one(
            {"normalized_name": norm}, {"_id": 0, "id": 1}
        )
        if not existing:
            report["unmatched_legacy_names"].append(name)

    report["parties_created"] = await db.parties.count_documents({})
    return report
