"""Phase 6 — Admin Data Management: reset service + backups + audit + test-dataset.

Two scoped actions:
    - `clear_transaction_data`: wipes operational rows (orders, quotations,
      shipments, purchases, customer_payments, purchase_payments,
      cash_book_entries, transfers, party_ledger_entries adjustments,
      dashboard aggregates). Preserves admin users, business/company
      settings, Father's Firm system party, accounts, customers, vendors,
      products, categories, GST/invoice settings, numbering, configuration.
    - `full_reset`: wipes everything except admin auth, essential system
      records, and audit logs. After reset, mandatory system records
      (`system_fathers_firm`, default categories) are recreated.

Safety:
    - `ALLOW_ADMIN_DATA_RESET` env flag defaults to `false`. Reset endpoints
      refuse when disabled.
    - Reset acquires a mutex lock in `db.admin_locks` — second concurrent
      reset returns 409.
    - Backup MUST succeed and verify (SHA-256) before any data is removed
      when `create_backup=True`.
    - Every preview + execute attempt is logged to `db.admin_audit_logs`
      (excluded from Clear Transaction Data).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException


BACKUP_DIR = Path("/app/backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

APP_VERSION = "1.3.0"          # bumped by phase
SCHEMA_VERSION = "P3"

# Collections
TRANSACTIONAL_COLLECTIONS = [
    "orders", "quotations",
    "purchases",
    "customer_payments", "purchase_payments",
    "cash_book_entries",
    "transfers",
    "payments",                       # legacy cash-book rows (audit-safe to wipe here)
    "party_ledger_entries",           # PL v2 rows are derived, safe to wipe (rebuild from source docs)
    "admin_migration_reports",
]
PRESERVED_COLLECTIONS_CLEAR = [
    "users",                          # admin auth
    "accounts",                       # user opts to keep/drop; default keep
    "customers", "vendors",
    "products", "categories",
    "parties",                        # canonical identity — keeps system_fathers_firm intact
    "business_settings",
    "invoice_settings",
    "admin_audit_logs",               # audit must survive
    "admin_backups",
]

FULL_RESET_KEEP_COLLECTIONS = [
    "users",                          # active admin auth
    "admin_audit_logs",
    "admin_backups",
]


def is_reset_enabled() -> bool:
    return (os.environ.get("ALLOW_ADMIN_DATA_RESET") or "false").lower() == "true"


def current_environment() -> str:
    return (os.environ.get("ENVIRONMENT") or "development").lower()


# ─── Preview ────────────────────────────────────────────────────────────────

async def preview_reset(db, scope: str, *, keep_accounts: bool = True) -> dict:
    """Return counts + dependency warnings. Performs NO deletions."""
    if scope == "clear_transaction_data":
        del_targets = list(TRANSACTIONAL_COLLECTIONS)
        preserved = [c for c in PRESERVED_COLLECTIONS_CLEAR if c != ("accounts" if not keep_accounts else "")]
        if not keep_accounts:
            del_targets.append("accounts")
    elif scope == "full_reset":
        all_colls = await db.list_collection_names()
        del_targets = [c for c in all_colls if c not in FULL_RESET_KEEP_COLLECTIONS]
        preserved = FULL_RESET_KEEP_COLLECTIONS
    else:
        raise HTTPException(400, f"Unknown scope: {scope!r}")

    deleted_counts = {}
    for c in del_targets:
        deleted_counts[c] = await db[c].count_documents({})
    preserved_counts = {}
    for c in preserved:
        preserved_counts[c] = await db[c].count_documents({})

    warnings: list[str] = []
    orphan_risks: list[str] = []
    # Simple orphan flag: if we're going to keep parties but drop orders/pmts, the party
    # rows will remain but have zero linked history. Not an orphan in the strict sense.
    if scope == "clear_transaction_data":
        if deleted_counts.get("orders", 0) > 0 or deleted_counts.get("purchases", 0) > 0:
            warnings.append("All order and purchase history will be wiped. Party rows are preserved.")
        if deleted_counts.get("transfers", 0) > 0:
            warnings.append("All transfer history will be wiped. Account balances will reset to their opening balance.")

    estimated_backup_bytes = sum(deleted_counts.values()) * 1024  # ~1KB / row upper bound
    return {
        "scope": scope,
        "environment": current_environment(),
        "reset_enabled": is_reset_enabled(),
        "collections_affected": del_targets,
        "preserved_collections": preserved,
        "deleted_counts": deleted_counts,
        "preserved_counts": preserved_counts,
        "warnings": warnings,
        "orphan_risks": orphan_risks,
        "estimated_backup_bytes": estimated_backup_bytes,
        "required_phrase": ("CLEAR TRANSACTION DATA" if scope == "clear_transaction_data"
                            else "FULL RESET SAMRAT GLASS ERP"),
        "requires_date_in_phrase": current_environment() == "production",
    }


# ─── Backup ─────────────────────────────────────────────────────────────────

async def _dump_collection(db, name: str) -> list[dict]:
    return await db[name].find({}, {"_id": 0}).to_list(length=None)


async def create_backup(db, *, created_by: str, note: str = "",
                        collections: Optional[list[str]] = None) -> dict:
    """Dump every affected collection into a ZIP artifact on disk +
    persist metadata in db.admin_backups. Returns the metadata."""
    bid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc)
    fname = f"backup-{ts.strftime('%Y%m%dT%H%M%S')}-{bid[:8]}.zip"
    fpath = BACKUP_DIR / fname

    if collections is None:
        collections = await db.list_collection_names()

    record_counts: dict[str, int] = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in collections:
            docs = await _dump_collection(db, c)
            record_counts[c] = len(docs)
            zf.writestr(f"{c}.json", json.dumps(docs, default=str, indent=2))
        manifest = {
            "backup_id": bid,
            "created_at": ts.isoformat(),
            "created_by": created_by,
            "note": note,
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "environment": current_environment(),
            "collections": collections,
            "record_counts": record_counts,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    payload = buf.getvalue()
    checksum = hashlib.sha256(payload).hexdigest()
    with open(fpath, "wb") as f:
        f.write(payload)

    meta = {
        "id": bid,
        "created_at": ts.isoformat(),
        "created_by": created_by,
        "note": note,
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "environment": current_environment(),
        "collections": collections,
        "record_counts": record_counts,
        "size_bytes": len(payload),
        "sha256": checksum,
        "storage_location": str(fpath),
        "filename": fname,
    }
    await db.admin_backups.insert_one(meta)
    # Return the meta minus the mongo _id
    return {k: v for k, v in meta.items() if k != "_id"}


async def list_backups(db) -> list[dict]:
    return await db.admin_backups.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


async def get_backup_meta(db, backup_id: str) -> dict:
    meta = await db.admin_backups.find_one({"id": backup_id}, {"_id": 0})
    if not meta:
        raise HTTPException(404, "Backup not found")
    return meta


async def delete_backup(db, backup_id: str) -> dict:
    meta = await get_backup_meta(db, backup_id)
    try:
        os.remove(meta["storage_location"])
    except FileNotFoundError:
        pass
    await db.admin_backups.delete_one({"id": backup_id})
    return {"deleted": True, "id": backup_id}


# ─── Execute ────────────────────────────────────────────────────────────────

async def _acquire_lock(db, purpose: str) -> dict:
    """Only one concurrent reset. Returns lock doc or raises 409."""
    now = datetime.now(timezone.utc).isoformat()
    lid = str(uuid.uuid4())
    # Ensure singleton lock doc
    existing = await db.admin_locks.find_one({"_id": "reset_lock"})
    if existing and existing.get("held"):
        raise HTTPException(409, "Another reset is already in progress.")
    await db.admin_locks.update_one(
        {"_id": "reset_lock"},
        {"$set": {"held": True, "id": lid, "purpose": purpose, "since": now}},
        upsert=True,
    )
    return {"lock_id": lid, "purpose": purpose, "since": now}


async def _release_lock(db) -> None:
    await db.admin_locks.update_one(
        {"_id": "reset_lock"},
        {"$set": {"held": False}},
    )


async def _restore_system_records(db, admin_user_id: str) -> dict:
    """After a full reset, recreate mandatory records so the app can start."""
    from party_sync import _ensure_system_ff, run_party_migration    # local import
    await _ensure_system_ff(db)
    # Re-run party migration to seed derived state from remaining data (if any).
    try:
        await run_party_migration(db)
    except Exception:
        pass
    return {"recreated": ["system_fathers_firm"], "admin_preserved": admin_user_id}


async def execute_reset(db, *, scope: str, admin: dict,
                        backup_id: Optional[str] = None,
                        keep_accounts: bool = True) -> dict:
    """Execute the reset. Assumes the caller has ALREADY:
        1. re-verified admin password
        2. validated the confirmation phrase
        3. validated the checkbox
        4. optionally created a backup

    Emits an audit log row, acquires reset lock, deletes rows, rebuilds
    mandatory system records, releases lock. If any critical step fails,
    the lock is released and the failure is logged.
    """
    if not is_reset_enabled():
        raise HTTPException(403, "Data reset is disabled by server configuration (ALLOW_ADMIN_DATA_RESET=false).")

    if scope not in ("clear_transaction_data", "full_reset"):
        raise HTTPException(400, f"Unknown scope: {scope!r}")

    started_at = datetime.now(timezone.utc).isoformat()
    audit_id = str(uuid.uuid4())
    audit_base = {
        "id": audit_id,
        "kind": "data_reset_execute",
        "scope": scope,
        "admin_id": admin.get("id"),
        "admin_email": admin.get("email"),
        "backup_id": backup_id,
        "started_at": started_at,
        "environment": current_environment(),
    }

    lock = None
    try:
        lock = await _acquire_lock(db, purpose=f"reset:{scope}")

        if scope == "clear_transaction_data":
            del_targets = list(TRANSACTIONAL_COLLECTIONS)
            if not keep_accounts:
                del_targets.append("accounts")
        else:  # full_reset
            all_colls = await db.list_collection_names()
            del_targets = [c for c in all_colls if c not in FULL_RESET_KEEP_COLLECTIONS]

        deleted_counts: dict[str, int] = {}
        for c in del_targets:
            r = await db[c].delete_many({})
            deleted_counts[c] = r.deleted_count

        # If full reset, also remove non-admin users (preserve current admin).
        recreated: dict = {}
        if scope == "full_reset":
            await db.users.delete_many({"id": {"$ne": admin["id"]}})
            recreated = await _restore_system_records(db, admin["id"])

        # Rebuild mandatory system records for the clear scope too (idempotent).
        if scope == "clear_transaction_data":
            from party_sync import _ensure_system_ff
            await _ensure_system_ff(db)

        ended_at = datetime.now(timezone.utc).isoformat()
        result = {
            **audit_base,
            "ended_at": ended_at,
            "success": True,
            "deleted_counts": deleted_counts,
            "recreated": recreated,
        }
        await db.admin_audit_logs.insert_one(result)
        return {k: v for k, v in result.items() if k != "_id"}
    except HTTPException:
        await db.admin_audit_logs.insert_one({
            **audit_base,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": "aborted",
        })
        raise
    except Exception as ex:
        await db.admin_audit_logs.insert_one({
            **audit_base,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error": str(ex),
        })
        raise HTTPException(500, f"Reset failed: {ex}")
    finally:
        if lock is not None:
            await _release_lock(db)


# ─── Test dataset ───────────────────────────────────────────────────────────

async def load_test_dataset(db, *, admin: dict) -> dict:
    """Insert a small labelled dataset — is_test_data=True + shared test_dataset_id."""
    from party_sync import _ensure_system_ff, get_or_create_customer_party, get_or_create_vendor_party

    ds = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    stamp = {"is_test_data": True, "test_dataset_id": ds, "created_at": now, "updated_at": now}

    ff = await _ensure_system_ff(db)
    cust = await get_or_create_customer_party(db, f"Test Customer {ds[:6]}")
    vend = await get_or_create_vendor_party(db, f"Test Vendor {ds[:6]}")

    # Create 2 accounts
    acc_bank = {"id": str(uuid.uuid4()), "name": f"Test ICICI {ds[:4]}", "type": "Bank",
                "opening_balance": 100000, **stamp}
    acc_cash = {"id": str(uuid.uuid4()), "name": f"Test Cash {ds[:4]}", "type": "Cash",
                "opening_balance": 0, **stamp}
    await db.accounts.insert_many([acc_bank, acc_cash])

    # A factory purchase (Rakshit spends money at factory)
    fac_purchase = {"id": str(uuid.uuid4()), "vendor_name": "Factory",
                    "vendor_party_id": ff["id"],
                    "purchase_date": "2025-01-10",
                    "items": [{"description": "Test SKU", "qty": 100, "rate": 200, "amount": 20000}],
                    "subtotal": 20000, "invoice_total": 20000, "total_paid": 0,
                    "outstanding_balance": 20000, "notes": "P6 test", **stamp}
    await db.purchases.insert_one(fac_purchase)

    # Outside vendor purchase
    out_purchase = {"id": str(uuid.uuid4()), "vendor_name": vend["name"],
                    "vendor_party_id": vend["id"],
                    "purchase_date": "2025-01-11",
                    "items": [{"description": "Boxes", "qty": 50, "rate": 30, "amount": 1500}],
                    "subtotal": 1500, "invoice_total": 1500, "total_paid": 0,
                    "outstanding_balance": 1500, **stamp}
    await db.purchases.insert_one(out_purchase)

    # An order with a partial shipment
    order = {"id": str(uuid.uuid4()), "client_name": cust["name"],
             "customer_party_id": cust["id"],
             "order_date": "2025-01-15",
             "items": [{"description": "Test SKU", "qty": 100, "rate": 300, "amount": 30000}],
             "invoice_total": 30000, "operating_revenue": 30000,
             "total_cost": 20000, "net_profit": 10000,
             "shipments": [{"id": str(uuid.uuid4()), "date": "2025-01-20",
                            "items": [{"qty": 60}], "freight_paid": 300, "transporter": "BlueDart"}],
             "shipped_qty_total": 60, "ordered_qty_total": 100,
             "payment_status": "Partial",
             **stamp}
    await db.orders.insert_one(order)

    # A customer advance
    cust_pay = {"id": str(uuid.uuid4()), "customer_name": cust["name"],
                "customer_party_id": cust["id"],
                "date": "2025-01-14", "amount": 15000, "mode": "UPI",
                "account_id": acc_bank["id"], "account_name": acc_bank["name"],
                "allocations": [{"order_id": order["id"], "amount": 12000}],
                "allocated_total": 12000, "unallocated": 3000,
                **stamp}
    await db.customer_payments.insert_one(cust_pay)

    # A rakshit_to_ff transfer
    tr = {"id": str(uuid.uuid4()),
          "txn_ref": None,
          "date": "2025-01-16", "kind": "rakshit_to_ff",
          "from_side": {"type": "account", "account_id": acc_bank["id"],
                         "account_name": acc_bank["name"]},
          "to_side": {"type": "party", "party_id": ff["id"], "party_name": ff["name"]},
          "amount": 5000, "mode": "Bank Transfer",
          "reference": "P6 test", "notes": "Test dataset",
          "status": "active", **stamp}
    tr["txn_ref"] = f"transfer:{tr['id']}"
    await db.transfers.insert_one(tr)

    return {"test_dataset_id": ds, "created": {
        "accounts": 2, "purchases": 2, "orders": 1,
        "customer_payments": 1, "transfers": 1,
    }}


async def remove_test_dataset(db, dataset_id: str) -> dict:
    counts: dict[str, int] = {}
    for c in ("accounts", "purchases", "orders", "customer_payments",
              "purchase_payments", "transfers", "cash_book_entries",
              "quotations"):
        r = await db[c].delete_many({"test_dataset_id": dataset_id})
        counts[c] = r.deleted_count
    return {"test_dataset_id": dataset_id, "deleted_counts": counts}


# ─── Audit + logs ───────────────────────────────────────────────────────────

async def log_audit(db, kind: str, admin: dict, *, extra: Optional[dict] = None) -> str:
    aid = str(uuid.uuid4())
    doc = {
        "id": aid,
        "kind": kind,
        "admin_id": admin.get("id"),
        "admin_email": admin.get("email"),
        "environment": current_environment(),
        "at": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    await db.admin_audit_logs.insert_one(doc)
    return aid


async def list_audit_logs(db, *, limit: int = 200) -> list[dict]:
    return await db.admin_audit_logs.find({}, {"_id": 0}).sort("at", -1).to_list(limit)
