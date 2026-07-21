from fastapi import FastAPI, APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import csv
import json
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
import uuid
from datetime import datetime, timezone
from collections import defaultdict
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Artisan Ledger — Order-based P&L")
api_router = APIRouter(prefix="/api")


# ================================================================
# MODELS
# ================================================================
FACTORY_SUPPLIER_ID = "factory"
FACTORY_PARTY_NAME = "Father's Firm"


class PurchaseSource(BaseModel):
    """One purchase source row inside an OrderItem — a single supplier that
    contributed some or all of the item's Complete / Glass / Fitting cost.

    supplier_id == FACTORY_SUPPLIER_ID means the item's Factory (Father's Firm)
    provided that portion — the backend maps it to the canonical Father's Firm
    party for settlement purposes.
    """
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    supplier_id: str = ""
    supplier_name: str = ""
    complete: float = 0
    glass: float = 0
    fitting: float = 0


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    main_category: str
    sub_category: Optional[str] = ""
    product_name: str
    model: Optional[str] = ""  # future: model/design
    qty: float = 0
    rate: float = 0
    product_sales: float = 0
    # Unified per-supplier purchase rows. When present + non-empty, the legacy
    # factory_*/outside_* fields are recomputed from these on every save so
    # dashboard KPIs and cost aggregates stay in lock-step with the new UI.
    purchase_sources: List[PurchaseSource] = []
    # Legacy split — retained as denormalised sums for aggregate/dashboard code.
    factory_complete: float = 0
    factory_glass: float = 0
    factory_fitting: float = 0
    outside_complete: float = 0
    outside_glass: float = 0
    outside_fitting: float = 0


class AdjustmentEntry(BaseModel):
    """Generic revenue or expense adjustment. Future-ready — attach `kind`
    later (e.g. discount, tip, loose_sale) without changing schema."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    amount: float = 0


PaymentStatus = Literal["Paid", "Partial", "Unpaid"]
TaxType = Literal["None", "GST", "IGST", "CGST_SGST"]

PAYMENT_MODES = ["Cash", "UPI", "Bank Transfer", "Cheque", "Credit Card", "Debit Card", "Other"]
ACCOUNT_TYPES = ["Bank", "Cash", "PettyCash", "UPI", "Wallet", "Gateway", "Other"]
ORDER_STATUSES = ["Draft", "Confirmed", "Packed", "Partially Shipped", "Fully Shipped", "Delivered", "Cancelled"]


class ShipmentItem(BaseModel):
    """A line item inside a Shipment — references an Order item by id."""
    model_config = ConfigDict(extra="ignore")
    order_item_id: str
    qty: float = 0


class Shipment(BaseModel):
    """A single dispatch event against an Order. Multiple allowed per order."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: Optional[str] = None
    items: List[ShipmentItem] = []
    boxes_shipped: float = 0
    freight_charged: float = 0
    freight_paid: float = 0
    transporter: Optional[str] = ""
    lr_number: Optional[str] = ""
    remarks: Optional[str] = ""


class Account(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: str = "Bank"
    notes: Optional[str] = ""
    archived: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PaymentAllocation(BaseModel):
    """One-payment-to-many-orders allocation. Stored embedded on CustomerPayment."""
    model_config = ConfigDict(extra="ignore")
    order_id: str
    amount: float = 0


class CustomerPaymentBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    customer_name: str
    date: Optional[str] = None
    amount: float = 0
    mode: str = "UPI"
    account_id: Optional[str] = ""
    account_name: Optional[str] = ""
    reference: Optional[str] = ""
    remarks: Optional[str] = ""
    allocations: List[PaymentAllocation] = []
    # Party-ledger linkage — when the money was received by a third party
    # (e.g. Father's Firm), the party ledger will auto-post a matching
    # linked effect against that party's settlement.
    received_by_party_id: Optional[str] = None
    received_by_party_name: Optional[str] = None


class CustomerPayment(CustomerPaymentBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # computed
    allocated_total: float = 0
    unallocated: float = 0  # advance
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OrderBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_name: str
    order_date: Optional[str] = None
    shipped_date: Optional[str] = None  # deprecated (now derived from shipments) but kept
    status: str = "Confirmed"  # new: Draft/Confirmed/Packed/Partially Shipped/Fully Shipped/Delivered/Cancelled
    payment_status: PaymentStatus = "Unpaid"  # derived from customer_payments allocations
    notes: Optional[str] = ""

    items: List[OrderItem] = []
    shipments: List[Shipment] = []

    # Packing (order-level — same as before)
    boxes_used: float = 0
    cost_per_box: float = 0
    packing_cost: float = 0

    # Freight — legacy order-level values, kept for backward-compat but shipments own the source of truth
    boxes_shipped: float = 0
    freight_charged: float = 0
    freight_paid: float = 0
    transporter: Optional[str] = ""
    lr_number: Optional[str] = ""

    # Future-ready adjustments — generic descriptor+amount rows
    other_revenue: List[AdjustmentEntry] = []
    other_expense: List[AdjustmentEntry] = []

    # Legacy revenue placeholders (kept for backwards-compat)
    packing_recovery: float = 0
    other_charges: float = 0

    # Tax
    tax_applicable: bool = False
    tax_type: TaxType = "None"
    tax_percent: float = 0
    tax_amount: float = 0
    tax_amount_manual: bool = False


class Order(OrderBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # ORDERED aggregates (potential — informational)
    ordered_qty_total: float = 0
    ordered_product_sales: float = 0

    # SHIPPED aggregates (recognized — used everywhere for revenue/profit)
    shipped_qty_total: float = 0
    shipped_product_sales: float = 0
    factory_cost_total: float = 0
    outside_cost_total: float = 0
    other_revenue_total: float = 0
    other_expense_total: float = 0
    ship_freight_charged_total: float = 0
    ship_freight_paid_total: float = 0
    ship_boxes_shipped_total: float = 0
    operating_revenue: float = 0
    total_cost: float = 0
    invoice_total: float = 0
    net_profit: float = 0
    margin_percent: float = 0
    shipment_progress_percent: float = 0  # shipped_qty / ordered_qty * 100

    # Payment aggregates (from customer_payments allocations)
    total_received: float = 0
    outstanding_balance: float = 0

    # Auto-derived latest shipped date (for month bucketing)
    last_shipped_date: Optional[str] = None

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PaymentBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: Optional[str] = None
    received_by_me: float = 0
    received_by_fac: float = 0
    payment_by_me: float = 0
    payment_by_fac: float = 0
    party: str
    mode: str
    note: Optional[str] = ""


class Payment(PaymentBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Customer(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    address: Optional[str] = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ================================================================
# COMPUTATIONS
# ================================================================
def _item_cost(it: dict) -> float:
    return float(sum(it.get(k, 0) or 0 for k in [
        "factory_complete", "factory_glass", "factory_fitting",
        "outside_complete", "outside_glass", "outside_fitting",
    ]))


def _item_factory(it: dict) -> float:
    return float(sum(it.get(k, 0) or 0 for k in [
        "factory_complete", "factory_glass", "factory_fitting",
    ]))


def _item_outside(it: dict) -> float:
    return float(sum(it.get(k, 0) or 0 for k in [
        "outside_complete", "outside_glass", "outside_fitting",
    ]))


def compute_order_aggregates(order: dict) -> dict:
    """Recalculate stored aggregates. Revenue & profit are recognized ONLY on shipped qty.

    Ordered totals are informational (potential); shipped totals drive P&L.
    """
    items = order.get("items") or []
    shipments = order.get("shipments") or []

    # Build ordered lookup by id
    item_by_id = {i.get("id"): i for i in items if i.get("id")}

    # Shipped qty per order-item
    shipped_qty_by_item: dict = {}
    for sh in shipments:
        for si in (sh.get("items") or []):
            iid = si.get("order_item_id")
            if not iid:
                continue
            shipped_qty_by_item[iid] = shipped_qty_by_item.get(iid, 0) + float(si.get("qty") or 0)

    # Aggregate per item, allocate costs proportionally (shipped_qty / ordered_qty)
    ordered_qty_total = 0.0
    shipped_qty_total = 0.0
    ordered_product_sales = 0.0
    shipped_product_sales = 0.0
    factory_cost_total = 0.0
    outside_cost_total = 0.0

    for it in items:
        ordered_qty = float(it.get("qty") or 0)
        rate = float(it.get("rate") or 0)
        # Ordered product_sales prefers stored product_sales, else qty*rate
        item_ordered_sales = float(it.get("product_sales") or 0) or ordered_qty * rate
        shipped_qty = shipped_qty_by_item.get(it.get("id"), 0)
        ratio = (shipped_qty / ordered_qty) if ordered_qty else 0
        # Also stamp shipped_qty back onto the item (denormalised)
        it["qty_shipped"] = shipped_qty

        ordered_qty_total += ordered_qty
        shipped_qty_total += shipped_qty
        ordered_product_sales += item_ordered_sales
        shipped_product_sales += item_ordered_sales * ratio

        for k in ("factory_complete", "factory_glass", "factory_fitting"):
            factory_cost_total += float(it.get(k) or 0) * ratio
        for k in ("outside_complete", "outside_glass", "outside_fitting"):
            outside_cost_total += float(it.get(k) or 0) * ratio

    other_revenue_total = sum(float((e or {}).get("amount") or 0) for e in (order.get("other_revenue") or []))
    other_expense_total = sum(float((e or {}).get("amount") or 0) for e in (order.get("other_expense") or []))
    packing_cost = float(order.get("packing_cost") or 0)
    packing_recovery = float(order.get("packing_recovery") or 0)

    # Freight & boxes now sourced from shipments only. Legacy migration on startup
    # backfills a synthetic shipment for every pre-existing order, so no order in
    # production should have an empty shipments array. If it is empty here, treat
    # everything as zero — do NOT fall back to (potentially stale) order-level fields.
    ship_freight_charged = sum(float((s or {}).get("freight_charged") or 0) for s in shipments)
    ship_freight_paid = sum(float((s or {}).get("freight_paid") or 0) for s in shipments)
    ship_boxes = sum(float((s or {}).get("boxes_shipped") or 0) for s in shipments)

    operating_revenue = shipped_product_sales + ship_freight_charged + packing_recovery + other_revenue_total
    total_cost = factory_cost_total + outside_cost_total + packing_cost + ship_freight_paid + other_expense_total

    tax_applicable = bool(order.get("tax_applicable"))
    tax_percent = float(order.get("tax_percent") or 0) if tax_applicable else 0
    tax_manual = bool(order.get("tax_amount_manual"))
    # Tax base factors in Other Revenue (already in operating_revenue) and
    # Other Expense (subtracted here) so the taxable amount reflects the true
    # net revenue after these adjustments.
    tax_base = max(0.0, operating_revenue - other_expense_total)
    if tax_applicable:
        if tax_manual:
            tax_amount = float(order.get("tax_amount") or 0)
        else:
            tax_amount = round(tax_base * tax_percent / 100.0, 2)
    else:
        tax_amount = 0

    invoice_total = operating_revenue + tax_amount
    net_profit = operating_revenue - total_cost
    margin = (net_profit / operating_revenue * 100.0) if operating_revenue else 0
    progress = (shipped_qty_total / ordered_qty_total * 100.0) if ordered_qty_total else 0

    # Auto-update status based on shipment progress (only if not Cancelled/Draft manual overrides)
    manual_states = {"Draft", "Confirmed", "Cancelled", "Delivered"}
    cur = order.get("status") or "Confirmed"
    if cur not in manual_states or cur == "Confirmed":
        if shipped_qty_total <= 0:
            order["status"] = "Packed" if cur in ("Packed", "Partially Shipped", "Fully Shipped") else cur
        elif shipped_qty_total + 0.0001 >= ordered_qty_total and ordered_qty_total > 0:
            order["status"] = "Fully Shipped"
        else:
            order["status"] = "Partially Shipped"

    # Latest shipped date for monthly bucketing
    last = max([(s.get("date") or "") for s in shipments], default="") if shipments else ""
    order["last_shipped_date"] = last or order.get("shipped_date")

    order["ordered_qty_total"] = ordered_qty_total
    order["shipped_qty_total"] = shipped_qty_total
    order["ordered_product_sales"] = ordered_product_sales
    order["shipped_product_sales"] = shipped_product_sales
    order["factory_cost_total"] = factory_cost_total
    order["outside_cost_total"] = outside_cost_total
    order["other_revenue_total"] = other_revenue_total
    order["other_expense_total"] = other_expense_total
    order["ship_freight_charged_total"] = ship_freight_charged
    order["ship_freight_paid_total"] = ship_freight_paid
    order["ship_boxes_shipped_total"] = ship_boxes
    # keep legacy freight_* on order in sync too for back-compat
    order["freight_charged"] = ship_freight_charged
    order["freight_paid"] = ship_freight_paid
    order["boxes_shipped"] = ship_boxes
    order["operating_revenue"] = operating_revenue
    order["total_cost"] = total_cost
    order["tax_amount"] = tax_amount
    order["invoice_total"] = invoice_total
    order["net_profit"] = net_profit
    order["margin_percent"] = margin
    order["shipment_progress_percent"] = progress
    # legacy compatibility fields expected by dashboard/breakdown
    order["product_sales_total"] = shipped_product_sales
    return order


async def _recompute_payment_aggregates_for_orders(order_ids: List[str]):
    """Recompute total_received and outstanding_balance for a set of orders,
    using the CustomerPayment.allocations table as source of truth."""
    if not order_ids:
        return
    # Sum allocations per order
    pipeline = [
        {"$match": {"allocations.order_id": {"$in": order_ids}}},
        {"$unwind": "$allocations"},
        {"$match": {"allocations.order_id": {"$in": order_ids}}},
        {"$group": {"_id": "$allocations.order_id", "total": {"$sum": "$allocations.amount"}}},
    ]
    totals = {r["_id"]: r["total"] async for r in db.customer_payments.aggregate(pipeline)}
    for oid in order_ids:
        total_recv = float(totals.get(oid, 0))
        doc = await db.orders.find_one({"id": oid}, {"_id": 0})
        if not doc:
            continue
        invoice = float(doc.get("invoice_total") or 0)
        outstanding = invoice - total_recv
        # Payment status: only auto if there ARE payments; else preserve user-set
        pstatus = doc.get("payment_status") or "Unpaid"
        if total_recv > 0:
            pstatus = "Paid" if total_recv + 0.5 >= invoice else "Partial"
        elif not doc.get("_had_legacy_payment_status"):
            pstatus = "Unpaid"
        await db.orders.update_one({"id": oid}, {"$set": {
            "total_received": total_recv,
            "outstanding_balance": outstanding,
            "payment_status": pstatus,
        }})


COST_CATEGORIES = ("complete", "glass", "fitting")


def _prep_item(raw: dict) -> dict:
    it = OrderItem(**raw).model_dump()
    if not it.get("product_sales"):
        it["product_sales"] = float(it.get("qty") or 0) * float(it.get("rate") or 0)

    # If purchase_sources are provided, they are the single source of truth
    # for this item's cost — recompute legacy factory_*/outside_* sums from them
    # so compute_order_aggregates + dashboard KPIs stay accurate without
    # touching those code paths.
    sources = it.get("purchase_sources") or []
    if sources:
        fc = fg = ff = oc = og = of = 0.0
        for s in sources:
            comp = float(s.get("complete") or 0)
            gla = float(s.get("glass") or 0)
            fit = float(s.get("fitting") or 0)
            if s.get("supplier_id") == FACTORY_SUPPLIER_ID:
                fc += comp; fg += gla; ff += fit
            else:
                oc += comp; og += gla; of += fit
        it["factory_complete"] = round(fc, 2)
        it["factory_glass"]    = round(fg, 2)
        it["factory_fitting"]  = round(ff, 2)
        it["outside_complete"] = round(oc, 2)
        it["outside_glass"]    = round(og, 2)
        it["outside_fitting"]  = round(of, 2)
    return it


def _synthesise_purchase_sources(it: dict) -> list:
    """For orders migrated from the legacy schema (no purchase_sources) — expose
    the existing factory_*/outside_* fields as two implicit rows so the new UI
    can render + edit them. This is READ-only; on save the frontend echoes
    the (possibly-edited) rows back and the model persists them properly."""
    if it.get("purchase_sources"):
        return it["purchase_sources"]
    rows = []
    fc, fg, ff = (float(it.get(k) or 0) for k in ("factory_complete", "factory_glass", "factory_fitting"))
    if fc + fg + ff > 0:
        rows.append({
            "id": f"legacy-factory-{it.get('id')}",
            "supplier_id": FACTORY_SUPPLIER_ID,
            "supplier_name": "Factory",
            "complete": fc, "glass": fg, "fitting": ff,
        })
    oc, og, of = (float(it.get(k) or 0) for k in ("outside_complete", "outside_glass", "outside_fitting"))
    if oc + og + of > 0:
        rows.append({
            "id": f"legacy-outside-{it.get('id')}",
            "supplier_id": "",   # user must pick a vendor before saving
            "supplier_name": "",
            "complete": oc, "glass": og, "fitting": of,
        })
    return rows


async def _resolve_supplier(supplier_id: str, supplier_name: str) -> tuple[str, str]:
    """Return (canonical_supplier_id, canonical_vendor_name) for a purchase row.
    Factory → canonical Father's Firm identity so vendor payables and party
    ledger balance updates route through the FF party."""
    if supplier_id == FACTORY_SUPPLIER_ID:
        return FACTORY_SUPPLIER_ID, FACTORY_PARTY_NAME
    return supplier_id or "", (supplier_name or "").strip()


def _linked_source_key(order_id: str, item_id: str, source_row_id: str, category: str) -> str:
    return f"{order_id}::{item_id}::{source_row_id}::{category}"


async def _sync_order_linked_purchases(order: dict) -> dict:
    """Mirror every non-zero (item, purchase_source, category) tuple into the
    Purchases collection as an auto-managed `order_product_purchase` row.

    - Stable key ⇒ repeated saves NEVER create duplicates.
    - Amount → 0 or row/source removed ⇒ delete the linked purchase, UNLESS it
      already has payments. In that case the purchase is preserved but marked
      `stale=True` so the UI can prompt for a manual adjustment.
    - Factory rows post under the Father's Firm supplier so the FF settlement
      balance updates through the same derived-ledger path as any other vendor.
    """
    order_id = order.get("id")
    if not order_id:
        return {"created": 0, "updated": 0, "deleted": 0, "kept_paid": 0, "errors": []}

    keep_keys: set[str] = set()
    created = updated = deleted = kept_paid = 0
    errors: list[str] = []
    order_date = (order.get("order_date") or order.get("shipped_date") or
                  datetime.now(timezone.utc).date().isoformat())

    for it in (order.get("items") or []):
        for src in (it.get("purchase_sources") or []):
            supplier_id_raw = (src.get("supplier_id") or "").strip()
            supplier_name_raw = (src.get("supplier_name") or "").strip()
            if not supplier_id_raw and not supplier_name_raw:
                # Blank supplier — validation error only if there's a non-zero amount.
                if any(float(src.get(c) or 0) > 0.005 for c in COST_CATEGORIES):
                    errors.append(f"Item '{it.get('product_name') or it.get('id')}' has a purchase row without a supplier.")
                continue
            supplier_id, vendor_name = await _resolve_supplier(supplier_id_raw, supplier_name_raw)
            if not vendor_name:
                continue
            for cat in COST_CATEGORIES:
                amt = float(src.get(cat) or 0)
                if amt <= 0.005:
                    continue
                key = _linked_source_key(order_id, it.get("id") or "", src.get("id") or "", cat)
                keep_keys.add(key)

                pur_item = {
                    "id": str(uuid.uuid4()),
                    "category": cat.title(),  # Complete / Glass / Fitting
                    "description": f"{it.get('product_name') or 'Product'} — {cat.title()}",
                    "qty": 1, "rate": amt, "amount": amt,
                }
                base_doc = {
                    "vendor_name": vendor_name,
                    "purchase_date": order_date,
                    "items": [pur_item],
                    "freight": 0, "other_charges": 0,
                    "tax_applicable": False, "tax_type": "None", "tax_percent": 0,
                    "tax_amount": 0, "tax_amount_manual": False,
                    "notes": f"Auto-linked from Order {order_id[:8]} · Item {(it.get('product_name') or '').strip()}",
                    "linked_to_order_id": order_id,
                    "linked_source_key": key,
                    "linked_supplier_id": supplier_id,
                    "linked_source_row_id": src.get("id"),
                    "linked_order_item_id": it.get("id"),
                    "linked_cost_category": cat,
                    "source_type": "order_product_purchase",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

                existing = await db.purchases.find_one({"linked_source_key": key}, {"_id": 0})
                if existing:
                    total_paid = float(existing.get("total_paid") or 0)
                    invoice_total = amt
                    outstanding = round(invoice_total - total_paid, 2)
                    payment_status = "Paid" if total_paid + 0.005 >= invoice_total \
                                    else ("Partial" if total_paid > 0.005 else "Unpaid")
                    upd = {
                        **base_doc,
                        "subtotal": amt, "invoice_total": amt,
                        "outstanding_balance": outstanding,
                        "payment_status": payment_status,
                        "stale": False,
                    }
                    # Preserve identity + payment history
                    upd["items"][0]["id"] = (existing.get("items") or [{}])[0].get("id") or upd["items"][0]["id"]
                    upd["id"] = existing.get("id")
                    await db.purchases.update_one({"id": existing["id"]}, {"$set": upd})
                    updated += 1
                else:
                    doc = {
                        **base_doc,
                        "subtotal": amt, "invoice_total": amt,
                        "total_paid": 0, "outstanding_balance": amt,
                        "payment_status": "Unpaid",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "stale": False,
                    }
                    doc["id"] = str(uuid.uuid4())
                    await db.purchases.insert_one(doc)
                    # Ensure vendor exists in vendor directory (skip for Factory)
                    if supplier_id != FACTORY_SUPPLIER_ID and vendor_name:
                        await db.vendors.update_one(
                            {"name": vendor_name},
                            {"$setOnInsert": Vendor(name=vendor_name).model_dump()},
                            upsert=True,
                        )
                    created += 1

    # Purge / mark stale any linked purchases for this order that are no longer needed
    async for old in db.purchases.find(
        {"linked_to_order_id": order_id, "source_type": "order_product_purchase"}, {"_id": 0}
    ):
        if old.get("linked_source_key") in keep_keys:
            continue
        total_paid = float(old.get("total_paid") or 0)
        if total_paid > 0.005:
            await db.purchases.update_one({"id": old["id"]}, {"$set": {
                "stale": True,
                "notes": (old.get("notes") or "") + " · REMOVED FROM ORDER — has payments, needs adjustment.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }})
            kept_paid += 1
        else:
            await db.purchases.delete_one({"id": old["id"]})
            deleted += 1

    return {"created": created, "updated": updated, "deleted": deleted,
            "kept_paid": kept_paid, "errors": errors}


async def _delete_order_linked_purchases(order_id: str) -> dict:
    """Called when an order is deleted — same policy as sync but for full removal:
    delete unpaid linked purchases, keep the ones with payments as stale."""
    deleted = kept_paid = 0
    async for old in db.purchases.find(
        {"linked_to_order_id": order_id, "source_type": "order_product_purchase"}, {"_id": 0}
    ):
        total_paid = float(old.get("total_paid") or 0)
        if total_paid > 0.005:
            await db.purchases.update_one({"id": old["id"]}, {"$set": {
                "stale": True,
                "notes": (old.get("notes") or "") + " · SOURCE ORDER DELETED — paid; kept for adjustment.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }})
            kept_paid += 1
        else:
            await db.purchases.delete_one({"id": old["id"]})
            deleted += 1
    return {"deleted": deleted, "kept_paid": kept_paid}


# ================================================================
# ORDERS
# ================================================================
def _validate_purchase_sources(order: dict) -> list[str]:
    """Fail-fast validation used BEFORE the order is inserted / updated so a
    validation error can never leave a half-written document behind."""
    errors: list[str] = []
    for it in (order.get("items") or []):
        for src in (it.get("purchase_sources") or []):
            has_amount = any(float(src.get(c) or 0) > 0.005 for c in COST_CATEGORIES)
            has_supplier = bool((src.get("supplier_id") or "").strip() or (src.get("supplier_name") or "").strip())
            if has_amount and not has_supplier:
                errors.append(
                    f"Item '{it.get('product_name') or it.get('id')}' has a purchase row without a supplier."
                )
    return errors


@api_router.post("/orders", response_model=Order)
async def create_order(payload: OrderBase):
    data = payload.model_dump()
    data["items"] = [_prep_item(i) for i in data.get("items", [])]
    validation_errors = _validate_purchase_sources(data)
    if validation_errors:
        raise HTTPException(400, {"detail": "Some purchase rows are missing a supplier.",
                                  "errors": validation_errors})
    order = Order(**data).model_dump()
    compute_order_aggregates(order)
    order["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.orders.insert_one(order)
    # Ensure customer exists
    if data.get("client_name"):
        await db.customers.update_one(
            {"name": data["client_name"]},
            {"$setOnInsert": Customer(name=data["client_name"]).model_dump()},
            upsert=True,
        )
    await _sync_order_linked_purchases(order)
    return Order(**order)


@api_router.get("/orders", response_model=List[Order])
async def list_orders(
    client_name: Optional[str] = None,
    payment_status: Optional[str] = None,
    main_category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    q: dict = {}
    if client_name:
        q["client_name"] = {"$regex": client_name, "$options": "i"}
    if payment_status and payment_status != "all":
        q["payment_status"] = payment_status
    if main_category and main_category != "all":
        q["items.main_category"] = main_category
    if start_date or end_date:
        d: dict = {}
        if start_date:
            d["$gte"] = start_date
        if end_date:
            d["$lte"] = end_date
        q["shipped_date"] = d
    docs = await db.orders.find(q, {"_id": 0}).sort([("last_shipped_date", -1), ("shipped_date", -1)]).to_list(5000)
    for d in docs:
        for it in (d.get("items") or []):
            if not it.get("purchase_sources"):
                it["purchase_sources"] = _synthesise_purchase_sources(it)
    return [Order(**d) for d in docs]


@api_router.get("/orders/{oid}", response_model=Order)
async def get_order(oid: str):
    d = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Order not found")
    for it in (d.get("items") or []):
        if not it.get("purchase_sources"):
            it["purchase_sources"] = _synthesise_purchase_sources(it)
    return Order(**d)


@api_router.put("/orders/{oid}", response_model=Order)
async def update_order(oid: str, payload: OrderBase):
    existing = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Order not found")
    data = payload.model_dump()
    data["items"] = [_prep_item(i) for i in data.get("items", [])]
    validation_errors = _validate_purchase_sources(data)
    if validation_errors:
        raise HTTPException(400, {"detail": "Some purchase rows are missing a supplier.",
                                  "errors": validation_errors})
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    compute_order_aggregates(data)
    await db.orders.update_one({"id": oid}, {"$set": data})
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    await _sync_order_linked_purchases(updated)
    return Order(**updated)


@api_router.delete("/orders/{oid}")
async def delete_order(oid: str):
    existing = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Order not found")
    linked_report = await _delete_order_linked_purchases(oid)
    if linked_report["kept_paid"] > 0:
        raise HTTPException(400, {
            "detail": f"{linked_report['kept_paid']} linked purchase(s) already have payments. "
                      "Reverse those payments before deleting the order.",
            "kept_paid": linked_report["kept_paid"],
        })
    await db.orders.delete_one({"id": oid})
    return {"deleted": True, "linked_purchases_removed": linked_report["deleted"]}


# ================================================================
# PAYMENTS (unchanged from before)
# ================================================================
@api_router.post("/payments", response_model=Payment)
async def create_payment(payload: PaymentBase):
    p = Payment(**payload.model_dump())
    await db.payments.insert_one(p.model_dump())
    return p


@api_router.get("/payments", response_model=List[Payment])
async def list_payments(
    party: Optional[str] = None,
    mode: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    q: dict = {}
    if party:
        q["party"] = {"$regex": party, "$options": "i"}
    if mode and mode != "all":
        q["mode"] = mode
    if start_date or end_date:
        d: dict = {}
        if start_date:
            d["$gte"] = start_date
        if end_date:
            d["$lte"] = end_date
        q["date"] = d
    docs = await db.payments.find(q, {"_id": 0}).sort("date", 1).to_list(5000)
    return [Payment(**d) for d in docs]


@api_router.put("/payments/{pid}", response_model=Payment)
async def update_payment(pid: str, payload: PaymentBase):
    existing = await db.payments.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Payment not found")
    await db.payments.update_one({"id": pid}, {"$set": payload.model_dump()})
    updated = await db.payments.find_one({"id": pid}, {"_id": 0})
    return Payment(**updated)


@api_router.delete("/payments/{pid}")
async def delete_payment(pid: str):
    res = await db.payments.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Payment not found")
    return {"deleted": True}


# ================================================================
# CUSTOMERS
# ================================================================
@api_router.get("/orders/{oid}/payments")
async def order_payments_for(oid: str):
    """List every customer payment that has an allocation to THIS order.
    Also returns the parent payment's account/mode/reference and this customer's
    unallocated advance so the OrderDialog can display receipts + one-click
    advance allocation without duplicating payment records."""
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    pays = await db.customer_payments.find(
        {"allocations.order_id": oid}, {"_id": 0}
    ).sort("date", 1).to_list(2000)
    rows = []
    for p in pays:
        alloc = next((a for a in (p.get("allocations") or []) if a.get("order_id") == oid), None)
        if not alloc:
            continue
        pay_amt = float(p.get("amount") or 0)
        alloc_amt = float(alloc.get("amount") or 0)
        # Rough per-order status derived from the parent payment
        if alloc_amt + 0.5 >= pay_amt:
            pstatus = "Full"
        elif alloc_amt > 0.5:
            pstatus = "Partial"
        else:
            pstatus = "Advance"
        rows.append({
            "payment_id": p.get("id"),
            "date": p.get("date"),
            "customer_name": p.get("customer_name"),
            "allocated_to_this_order": alloc_amt,
            "total_amount": pay_amt,
            "mode": p.get("mode"),
            "account_id": p.get("account_id"),
            "account_name": p.get("account_name"),
            "reference": p.get("reference"),
            "remarks": p.get("remarks"),
            "received_by_party_name": p.get("received_by_party_name"),
            "payment_status": pstatus,
        })
    total_received = sum(r["allocated_to_this_order"] for r in rows)
    invoice_total = float(order.get("invoice_total") or 0)

    # Any unallocated advance from this same customer — pointer to the oldest
    # advance payment so the UI can call POST /allocate-advance to top-up.
    cust = order.get("client_name") or ""
    advance_total = 0.0
    advance_payment_id = None
    if cust:
        adv_docs = await db.customer_payments.find(
            {"customer_name": cust, "unallocated": {"$gt": 0.5}}, {"_id": 0}
        ).sort("date", 1).to_list(200)
        for a in adv_docs:
            advance_total += float(a.get("unallocated") or 0)
        if adv_docs:
            advance_payment_id = adv_docs[0].get("id")

    return {
        "order_id": oid,
        "customer_name": cust,
        "invoice_total": invoice_total,
        "total_received": round(total_received, 2),
        "outstanding": round(invoice_total - total_received, 2),
        "customer_advance_available": round(advance_total, 2),
        "advance_payment_id": advance_payment_id,
        "count": len(rows),
        "payments": rows,
    }


class AllocateAdvanceIn(BaseModel):
    amount: Optional[float] = None


@api_router.post("/orders/{oid}/allocate-advance")
async def allocate_customer_advance_to_order(oid: str, body: Optional[AllocateAdvanceIn] = None):
    """Reduce this customer's unallocated advance and top-up the allocation to THIS
    order — WITHOUT creating a new payment record. If `amount` is omitted, it uses
    min(advance_available, outstanding_on_order). Consumes advances FIFO."""
    amount = body.amount if body is not None else None
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    cust = order.get("client_name") or ""
    if not cust:
        raise HTTPException(400, "Order has no customer")

    invoice = float(order.get("invoice_total") or 0)
    total_recv = float(order.get("total_received") or 0)
    outstanding = max(0.0, invoice - total_recv)

    adv_docs = await db.customer_payments.find(
        {"customer_name": cust, "unallocated": {"$gt": 0.5}}, {"_id": 0}
    ).sort("date", 1).to_list(200)
    if not adv_docs:
        raise HTTPException(400, "No advance available for this customer")

    total_advance = sum(float(p.get("unallocated") or 0) for p in adv_docs)
    if outstanding <= 0.5:
        raise HTTPException(400, "This order has no outstanding balance")

    want = float(amount) if amount is not None else min(total_advance, outstanding)
    want = max(0.0, min(want, total_advance, outstanding))
    if want <= 0.5:
        raise HTTPException(400, "Nothing to allocate")

    allocated_from_advances = 0.0
    touched_payment_ids: List[str] = []
    for p in adv_docs:
        if allocated_from_advances + 0.001 >= want:
            break
        avail = float(p.get("unallocated") or 0)
        take = min(avail, want - allocated_from_advances)
        if take <= 0.001:
            continue
        # Update existing allocation on this payment or push a new one
        allocs = list(p.get("allocations") or [])
        found = False
        for a in allocs:
            if a.get("order_id") == oid:
                a["amount"] = float(a.get("amount") or 0) + take
                found = True
                break
        if not found:
            allocs.append({"order_id": oid, "amount": take})
        pay_amt = float(p.get("amount") or 0)
        alloc_total = sum(float((a or {}).get("amount") or 0) for a in allocs)
        await db.customer_payments.update_one(
            {"id": p["id"]},
            {"$set": {
                "allocations": allocs,
                "allocated_total": round(alloc_total, 2),
                "unallocated": round(max(0.0, pay_amt - alloc_total), 2),
            }},
        )
        touched_payment_ids.append(p["id"])
        allocated_from_advances += take

    await _recompute_payment_aggregates_for_orders([oid])
    return {
        "allocated": round(allocated_from_advances, 2),
        "order_id": oid,
        "touched_payment_ids": touched_payment_ids,
    }


@api_router.get("/orders/{oid}/timeline")
async def order_timeline(oid: str):
    """Chronological list of events for this order — order creation, shipments,
    customer payments (allocations), and status changes. Frontend-friendly."""
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")

    events: List[dict] = []

    created = order.get("order_date") or (order.get("created_at") or "")[:10]
    events.append({
        "type": "order_created",
        "date": created,
        "title": "Order Confirmed",
        "detail": f"{len(order.get('items') or [])} items · {float(order.get('ordered_qty_total') or 0):.0f} pcs",
    })

    for i, sh in enumerate(sorted((order.get("shipments") or []), key=lambda s: s.get("date") or "")):
        qty = sum(float((si or {}).get("qty") or 0) for si in (sh.get("items") or []))
        events.append({
            "type": "shipment",
            "date": sh.get("date"),
            "title": f"Shipment {i + 1}",
            "detail": f"{qty:.0f} pcs · {sh.get('transporter') or 'Transport pending'}"
                      + (f" · LR {sh.get('lr_number')}" if sh.get("lr_number") else ""),
            "shipment_id": sh.get("id"),
        })

    pays = await db.customer_payments.find(
        {"allocations.order_id": oid}, {"_id": 0}
    ).sort("date", 1).to_list(2000)
    for p in pays:
        alloc = next((a for a in (p.get("allocations") or []) if a.get("order_id") == oid), None)
        if not alloc:
            continue
        events.append({
            "type": "payment",
            "date": p.get("date"),
            "title": f"Customer Payment · {p.get('mode') or 'Cash'}",
            "detail": f"₹{float(alloc.get('amount') or 0):,.0f} allocated"
                      + (f" · via {p.get('received_by_party_name')}" if p.get("received_by_party_name") else "")
                      + (f" · Ref {p.get('reference')}" if p.get("reference") else ""),
            "payment_id": p.get("id"),
        })

    events.sort(key=lambda e: (e.get("date") or ""))
    return {"order_id": oid, "count": len(events), "events": events}


@api_router.get("/customers/{name}/outstanding-orders")
async def customer_outstanding_orders(name: str):
    """Return this customer's orders with an outstanding balance, oldest first — used
    to allocate a new payment across invoices."""
    orders = await db.orders.find({"client_name": name}, {"_id": 0}).to_list(5000)
    rows = []
    for o in orders:
        outstanding = float(o.get("outstanding_balance") or 0)
        if outstanding > 0.5 or (o.get("payment_status") in ("Unpaid", "Partial")):
            rows.append({
                "id": o.get("id"),
                "date": o.get("last_shipped_date") or o.get("shipped_date") or o.get("order_date"),
                "invoice_total": float(o.get("invoice_total") or 0),
                "total_received": float(o.get("total_received") or 0),
                "outstanding": max(0.0, outstanding),
                "status": o.get("status"),
                "payment_status": o.get("payment_status"),
                "short_id": (o.get("id") or "")[:8],
            })
    rows.sort(key=lambda r: r.get("date") or "")
    return {"count": len(rows), "orders": rows}


@api_router.get("/customers", response_model=List[Customer])
async def list_customers():
    docs = await db.customers.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    return [Customer(**d) for d in docs]


# ================================================================
# DASHBOARD
# ================================================================
@api_router.get("/dashboard")
async def dashboard():
    orders = await db.orders.find({}, {"_id": 0}).to_list(10000)
    pays = await db.payments.find({}, {"_id": 0}).to_list(10000)

    operating_revenue = sum(o.get("operating_revenue") or 0 for o in orders)
    invoice_value = sum(o.get("invoice_total") or 0 for o in orders)
    total_cost = sum(o.get("total_cost") or 0 for o in orders)
    net_profit = sum(o.get("net_profit") or 0 for o in orders)
    gst_collected = sum(o.get("tax_amount") or 0 for o in orders)
    margin = (net_profit / operating_revenue * 100.0) if operating_revenue else 0

    received = sum((p.get("received_by_me") or 0) + (p.get("received_by_fac") or 0) for p in pays)
    paid = sum((p.get("payment_by_me") or 0) + (p.get("payment_by_fac") or 0) for p in pays)

    # Outstanding by payment_status on orders (simple proxy)
    outstanding_receivable = sum(
        (o.get("invoice_total") or 0) for o in orders
        if o.get("payment_status") in ("Unpaid", "Partial")
    )
    # Payables here = negative net across payments (money we owe suppliers). Simple:
    outstanding_payable = max(0.0, paid - received) if False else 0
    # More useful: total payments made TO factory (payment_by_me + payment_by_fac) as running expense.
    outstanding_payable = paid  # we owe = we paid out (kept simple)

    # Boxes and freight
    boxes_used = sum(o.get("boxes_used") or 0 for o in orders)
    boxes_shipped = sum(o.get("boxes_shipped") or 0 for o in orders)
    freight_charged = sum(o.get("freight_charged") or 0 for o in orders)
    freight_paid = sum(o.get("freight_paid") or 0 for o in orders)
    packing_cost = sum(o.get("packing_cost") or 0 for o in orders)

    # Customer advances (unallocated portion of customer payments)
    cust_pays = await db.customer_payments.find({}, {"_id": 0}).to_list(20000)
    customer_advances = sum(float(p.get("unallocated") or 0) for p in cust_pays)

    # Purchase KPIs (vendor bills & payments)
    purchases = await db.purchases.find({}, {"_id": 0}).to_list(20000)
    purchase_pays = await db.purchase_payments.find({}, {"_id": 0}).to_list(20000)
    purchase_value = sum(float(p.get("invoice_total") or 0) for p in purchases)
    purchase_paid = sum(float(p.get("amount") or 0) for p in purchase_pays)
    purchase_outstanding = sum(
        float(p.get("outstanding_balance") or 0) for p in purchases
        if p.get("payment_status") in ("Unpaid", "Partial")
    )

    # Monthly (by shipped_date)
    monthly = defaultdict(lambda: {"revenue": 0, "profit": 0, "cost": 0})
    for o in orders:
        d = o.get("shipped_date")
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d.replace("Z", ""))
            key = dt.strftime("%Y-%m")
        except Exception:
            continue
        monthly[key]["revenue"] += o.get("operating_revenue") or 0
        monthly[key]["profit"] += o.get("net_profit") or 0
        monthly[key]["cost"] += o.get("total_cost") or 0
    monthly_series = [{"month": k, **v} for k, v in sorted(monthly.items())]

    # By main category (over items)
    main_cat = defaultdict(lambda: {"sales": 0, "profit_share": 0, "count": 0})
    # profit share requires allocation of order-level costs proportionally
    for o in orders:
        rev = o.get("operating_revenue") or 0
        prof = o.get("net_profit") or 0
        item_sales_sum = sum(i.get("product_sales") or 0 for i in o.get("items") or [])
        for it in o.get("items") or []:
            mc = it.get("main_category") or "Uncategorised"
            main_cat[mc]["sales"] += it.get("product_sales") or 0
            main_cat[mc]["count"] += 1
            share = 0
            if item_sales_sum > 0:
                share = prof * (it.get("product_sales") or 0) / item_sales_sum
            main_cat[mc]["profit_share"] += share
    main_categories = sorted(
        [{"main_category": k, **v} for k, v in main_cat.items()],
        key=lambda x: -x["profit_share"],
    )

    # Sub category drill-down within main
    sub_cat = defaultdict(lambda: defaultdict(lambda: {"sales": 0, "profit_share": 0, "count": 0}))
    for o in orders:
        prof = o.get("net_profit") or 0
        item_sales_sum = sum(i.get("product_sales") or 0 for i in o.get("items") or [])
        for it in o.get("items") or []:
            mc = it.get("main_category") or "Uncategorised"
            sc = it.get("sub_category") or "—"
            sub_cat[mc][sc]["sales"] += it.get("product_sales") or 0
            sub_cat[mc][sc]["count"] += 1
            if item_sales_sum > 0:
                sub_cat[mc][sc]["profit_share"] += prof * (it.get("product_sales") or 0) / item_sales_sum
    sub_categories = {
        mc: sorted([{"sub_category": s, **v} for s, v in subs.items()],
                   key=lambda x: -x["sales"])
        for mc, subs in sub_cat.items()
    }

    # Top customers by profit
    cust = defaultdict(lambda: {"revenue": 0, "profit": 0, "orders": 0})
    for o in orders:
        c = o.get("client_name") or "Unknown"
        cust[c]["revenue"] += o.get("operating_revenue") or 0
        cust[c]["profit"] += o.get("net_profit") or 0
        cust[c]["orders"] += 1
    top_customers = sorted(
        [{"client": k, **v} for k, v in cust.items()],
        key=lambda x: -x["profit"],
    )[:10]

    # Top products by sales (item-level)
    prod = defaultdict(lambda: {"sales": 0, "qty": 0, "orders": 0, "main_category": ""})
    for o in orders:
        for it in o.get("items") or []:
            pkey = f"{it.get('main_category','')}/{it.get('product_name','')}"
            prod[pkey]["sales"] += it.get("product_sales") or 0
            prod[pkey]["qty"] += it.get("qty") or 0
            prod[pkey]["orders"] += 1
            prod[pkey]["main_category"] = it.get("main_category", "")
    top_products = sorted(
        [{"product": k.split("/", 1)[-1], **v} for k, v in prod.items()],
        key=lambda x: -x["sales"],
    )[:10]

    # Payments by mode
    mode_map = defaultdict(lambda: {"received": 0, "paid": 0})
    for p in pays:
        m = p.get("mode") or "Other"
        mode_map[m]["received"] += (p.get("received_by_me") or 0) + (p.get("received_by_fac") or 0)
        mode_map[m]["paid"] += (p.get("payment_by_me") or 0) + (p.get("payment_by_fac") or 0)
    mode_series = [{"mode": k, **v} for k, v in mode_map.items()]

    return {
        "kpis": {
            "operating_revenue": operating_revenue,
            "invoice_value": invoice_value,
            "total_cost": total_cost,
            "net_profit": net_profit,
            "margin_percent": margin,
            "gst_collected": gst_collected,
            "outstanding_receivable": outstanding_receivable,
            "outstanding_payable": outstanding_payable,
            "received": received,
            "paid": paid,
            "order_count": len(orders),
            "boxes_used": boxes_used,
            "boxes_shipped": boxes_shipped,
            "freight_charged": freight_charged,
            "freight_paid": freight_paid,
            "packing_cost": packing_cost,
            "customer_advances": customer_advances,
            "purchase_value": purchase_value,
            "purchase_paid": purchase_paid,
            "purchase_outstanding": purchase_outstanding,
            "purchase_count": len(purchases),
        },
        "monthly": monthly_series,
        "main_categories": main_categories,
        "sub_categories": sub_categories,
        "top_customers": top_customers,
        "top_products": top_products,
        "modes": mode_series,
    }


# ================================================================
# DASHBOARD BREAKDOWN (drill-down data for interactive KPIs)
# ================================================================
@api_router.get("/dashboard/breakdown")
async def dashboard_breakdown():
    orders = await db.orders.find({}, {"_id": 0}).to_list(10000)
    pays = await db.payments.find({}, {"_id": 0}).to_list(10000)

    # ---- Revenue ----
    product_sales_total = sum(o.get("product_sales_total") or 0 for o in orders)
    freight_charged_total = sum(o.get("freight_charged") or 0 for o in orders)
    packing_recovery_total = sum(o.get("packing_recovery") or 0 for o in orders)
    other_revenue_total = sum(o.get("other_revenue_total") or 0 for o in orders)

    # collect other-revenue entries grouped by description
    other_rev_by_desc = defaultdict(lambda: {"amount": 0, "count": 0})
    for o in orders:
        for e in (o.get("other_revenue") or []):
            k = (e.get("description") or "Unlabelled").strip() or "Unlabelled"
            other_rev_by_desc[k]["amount"] += float(e.get("amount") or 0)
            other_rev_by_desc[k]["count"] += 1

    rev_by_main = defaultdict(float)
    rev_sub_by_main = defaultdict(lambda: defaultdict(float))
    for o in orders:
        for it in o.get("items") or []:
            mc = it.get("main_category") or "Uncategorised"
            sc = it.get("sub_category") or "—"
            rev_by_main[mc] += it.get("product_sales") or 0
            rev_sub_by_main[mc][sc] += it.get("product_sales") or 0

    revenue = {
        "product_sales": product_sales_total,
        "freight_charged": freight_charged_total,
        "packing_charged": packing_recovery_total,
        "other_revenue": other_revenue_total,
        "total": product_sales_total + freight_charged_total + packing_recovery_total + other_revenue_total,
        "by_main_category": sorted(
            [{"main_category": k, "amount": v} for k, v in rev_by_main.items()],
            key=lambda x: -x["amount"],
        ),
        "by_sub_category": {
            mc: sorted([{"sub_category": s, "amount": a} for s, a in subs.items()],
                       key=lambda x: -x["amount"])
            for mc, subs in rev_sub_by_main.items()
        },
        "other_revenue_by_description": sorted(
            [{"description": k, **v} for k, v in other_rev_by_desc.items()],
            key=lambda x: -x["amount"],
        ),
    }

    # ---- Invoice / Tax ----
    tax_buckets = defaultdict(lambda: {"count": 0, "tax_amount": 0, "invoice_total": 0, "revenue": 0})
    non_tax_revenue = 0
    for o in orders:
        if o.get("tax_applicable"):
            key = f"{o.get('tax_type') or 'GST'} @ {o.get('tax_percent') or 0}%"
            tax_buckets[key]["count"] += 1
            tax_buckets[key]["tax_amount"] += o.get("tax_amount") or 0
            tax_buckets[key]["invoice_total"] += o.get("invoice_total") or 0
            tax_buckets[key]["revenue"] += o.get("operating_revenue") or 0
        else:
            non_tax_revenue += o.get("operating_revenue") or 0

    invoice = {
        "operating_revenue": revenue["total"],
        "tax_amount": sum(o.get("tax_amount") or 0 for o in orders),
        "invoice_total": sum(o.get("invoice_total") or 0 for o in orders),
        "non_taxable_revenue": non_tax_revenue,
        "by_tax_type": sorted(
            [{"label": k, **v} for k, v in tax_buckets.items()],
            key=lambda x: -x["invoice_total"],
        ),
    }

    # ---- Cost breakdown (6-way factory/outside + packing + freight) ----
    def item_sum(key):
        return sum((it.get(key) or 0) for o in orders for it in (o.get("items") or []))

    factory_complete = item_sum("factory_complete")
    factory_glass = item_sum("factory_glass")
    factory_fitting = item_sum("factory_fitting")
    outside_complete = item_sum("outside_complete")
    outside_glass = item_sum("outside_glass")
    outside_fitting = item_sum("outside_fitting")
    packing_cost_total = sum(o.get("packing_cost") or 0 for o in orders)
    freight_paid_total = sum(o.get("freight_paid") or 0 for o in orders)
    other_expense_total = sum(o.get("other_expense_total") or 0 for o in orders)

    # Other expenses grouped by description
    other_exp_by_desc = defaultdict(lambda: {"amount": 0, "count": 0})
    for o in orders:
        for e in (o.get("other_expense") or []):
            k = (e.get("description") or "Unlabelled").strip() or "Unlabelled"
            other_exp_by_desc[k]["amount"] += float(e.get("amount") or 0)
            other_exp_by_desc[k]["count"] += 1

    cost = {
        "factory": {
            "total": factory_complete + factory_glass + factory_fitting,
            "complete": factory_complete,
            "glass": factory_glass,
            "fitting": factory_fitting,
        },
        "outside": {
            "total": outside_complete + outside_glass + outside_fitting,
            "complete": outside_complete,
            "glass": outside_glass,
            "fitting": outside_fitting,
        },
        "packing": packing_cost_total,
        "freight": freight_paid_total,
        "other_expense": other_expense_total,
        "other_expense_by_description": sorted(
            [{"description": k, **v} for k, v in other_exp_by_desc.items()],
            key=lambda x: -x["amount"],
        ),
        "total": (factory_complete + factory_glass + factory_fitting
                  + outside_complete + outside_glass + outside_fitting
                  + packing_cost_total + freight_paid_total + other_expense_total),
    }

    # ---- Profit by category ----
    prof_by_main = defaultdict(lambda: {"revenue": 0, "cost": 0, "profit": 0, "orders": 0})
    prof_sub_by_main = defaultdict(lambda: defaultdict(lambda: {"revenue": 0, "profit": 0}))
    for o in orders:
        rev = o.get("operating_revenue") or 0
        prof = o.get("net_profit") or 0
        item_sales = sum(i.get("product_sales") or 0 for i in o.get("items") or [])
        for it in o.get("items") or []:
            mc = it.get("main_category") or "Uncategorised"
            sc = it.get("sub_category") or "—"
            ratio = ((it.get("product_sales") or 0) / item_sales) if item_sales else 0
            r = rev * ratio
            p = prof * ratio
            prof_by_main[mc]["revenue"] += r
            prof_by_main[mc]["profit"] += p
            prof_by_main[mc]["cost"] += (r - p)
            prof_sub_by_main[mc][sc]["revenue"] += r
            prof_sub_by_main[mc][sc]["profit"] += p
            prof_by_main[mc]["orders"] += 1

    profit = {
        "operating_revenue": revenue["total"],
        "total_cost": cost["total"],
        "net_profit": revenue["total"] - cost["total"],
        "margin_percent": ((revenue["total"] - cost["total"]) / revenue["total"] * 100) if revenue["total"] else 0,
        "by_main_category": sorted(
            [{"main_category": k, **v,
              "margin_percent": (v["profit"] / v["revenue"] * 100) if v["revenue"] else 0}
             for k, v in prof_by_main.items()],
            key=lambda x: -x["profit"],
        ),
        "by_sub_category": {
            mc: sorted([{"sub_category": s, **v} for s, v in subs.items()],
                       key=lambda x: -x["profit"])
            for mc, subs in prof_sub_by_main.items()
        },
    }

    # ---- Receivable (unpaid / partial orders) ----
    by_status = {"Unpaid": {"count": 0, "amount": 0}, "Partial": {"count": 0, "amount": 0}, "Paid": {"count": 0, "amount": 0}}
    receivable_orders = []
    for o in orders:
        st = o.get("payment_status") or "Unpaid"
        amt = o.get("invoice_total") or 0
        by_status.setdefault(st, {"count": 0, "amount": 0})
        by_status[st]["count"] += 1
        by_status[st]["amount"] += amt
        if st in ("Unpaid", "Partial"):
            receivable_orders.append({
                "id": o.get("id"),
                "client_name": o.get("client_name"),
                "shipped_date": o.get("shipped_date"),
                "invoice_total": amt,
                "payment_status": st,
            })
    receivable_orders.sort(key=lambda x: -(x["invoice_total"] or 0))

    # aggregate receivable by client
    recv_by_client = defaultdict(lambda: {"amount": 0, "orders": 0})
    for o in orders:
        if (o.get("payment_status") or "") in ("Unpaid", "Partial"):
            recv_by_client[o.get("client_name") or "Unknown"]["amount"] += o.get("invoice_total") or 0
            recv_by_client[o.get("client_name") or "Unknown"]["orders"] += 1

    receivable = {
        "total": by_status.get("Unpaid", {}).get("amount", 0) + by_status.get("Partial", {}).get("amount", 0),
        "by_status": [{"status": k, **v} for k, v in by_status.items() if k in ("Unpaid", "Partial", "Paid")],
        "by_client": sorted(
            [{"client": k, **v} for k, v in recv_by_client.items()],
            key=lambda x: -x["amount"],
        )[:20],
        "orders": receivable_orders[:50],
    }

    # ---- Payable (money paid out — grouped by party / mode) ----
    payable_by_party = defaultdict(lambda: {"paid": 0, "received": 0, "net": 0})
    payable_by_mode = defaultdict(lambda: {"paid": 0, "received": 0})
    total_paid = 0
    total_received = 0
    for p in pays:
        r = (p.get("received_by_me") or 0) + (p.get("received_by_fac") or 0)
        pd = (p.get("payment_by_me") or 0) + (p.get("payment_by_fac") or 0)
        total_paid += pd
        total_received += r
        party = p.get("party") or "Unknown"
        payable_by_party[party]["paid"] += pd
        payable_by_party[party]["received"] += r
        payable_by_party[party]["net"] = payable_by_party[party]["received"] - payable_by_party[party]["paid"]
        mode = p.get("mode") or "Other"
        payable_by_mode[mode]["paid"] += pd
        payable_by_mode[mode]["received"] += r

    payable = {
        "total_paid": total_paid,
        "total_received": total_received,
        "net_out": total_paid - total_received,
        "by_party": sorted(
            [{"party": k, **v} for k, v in payable_by_party.items()],
            key=lambda x: -x["paid"],
        )[:25],
        "by_mode": [{"mode": k, **v} for k, v in payable_by_mode.items()],
    }

    # ---- Boxes ----
    boxes_used = sum(o.get("boxes_used") or 0 for o in orders)
    boxes_shipped = sum(o.get("boxes_shipped") or 0 for o in orders)
    boxes_by_transporter = defaultdict(lambda: {"boxes_shipped": 0, "orders": 0, "freight_paid": 0})
    for o in orders:
        t = o.get("transporter") or "Not set"
        boxes_by_transporter[t]["boxes_shipped"] += o.get("boxes_shipped") or 0
        boxes_by_transporter[t]["orders"] += 1
        boxes_by_transporter[t]["freight_paid"] += o.get("freight_paid") or 0

    boxes = {
        "used": boxes_used,
        "shipped": boxes_shipped,
        "gap": boxes_used - boxes_shipped,
        "packing_cost": packing_cost_total,
        "avg_cost_per_box": (packing_cost_total / boxes_used) if boxes_used else 0,
        "by_transporter": sorted(
            [{"transporter": k, **v} for k, v in boxes_by_transporter.items()],
            key=lambda x: -x["boxes_shipped"],
        ),
    }

    # ---- Freight ----
    freight_by_transporter = defaultdict(lambda: {"charged": 0, "paid": 0, "orders": 0, "boxes": 0})
    for o in orders:
        t = o.get("transporter") or "Not set"
        freight_by_transporter[t]["charged"] += o.get("freight_charged") or 0
        freight_by_transporter[t]["paid"] += o.get("freight_paid") or 0
        freight_by_transporter[t]["orders"] += 1
        freight_by_transporter[t]["boxes"] += o.get("boxes_shipped") or 0

    freight = {
        "charged": freight_charged_total,
        "paid": freight_paid_total,
        "recovery_gap": freight_charged_total - freight_paid_total,
        "by_transporter": sorted(
            [{"transporter": k, **v,
              "gap": v["charged"] - v["paid"]}
             for k, v in freight_by_transporter.items()],
            key=lambda x: -x["paid"],
        ),
    }

    return {
        "revenue": revenue,
        "invoice": invoice,
        "profit": profit,
        "cost": cost,
        "receivable": receivable,
        "payable": payable,
        "boxes": boxes,
        "freight": freight,
    }


# ================================================================
# META
# ================================================================
DEFAULT_MAIN_CATEGORIES = [
    "Chandelier", "Hanging Light", "Wall Light", "Table Lamp",
    "Ceiling Light", "Floor Lamp", "Candle Stand", "Glass",
]
DEFAULT_MODES = ["RHUF", "ICICI", "UPI", "Cash", "Raks"]
DEFAULT_TRANSPORTERS = ["Delhivery", "DTDC", "Gati", "VRL", "By Road", "Rail", "Self"]
TAX_TYPES = ["None", "GST", "IGST", "CGST_SGST"]
PAYMENT_STATUSES = ["Unpaid", "Partial", "Paid"]


@api_router.get("/meta")
async def meta():
    orders = await db.orders.find({}, {"_id": 0}).to_list(10000)
    pays = await db.payments.find({}, {"_id": 0}).to_list(10000)

    main_cats = set(DEFAULT_MAIN_CATEGORIES)
    sub_by_main = defaultdict(set)
    products_by_sub = defaultdict(set)
    transporters = set(DEFAULT_TRANSPORTERS)
    clients = set()

    for o in orders:
        if o.get("client_name"):
            clients.add(o["client_name"])
        if o.get("transporter"):
            transporters.add(o["transporter"])
        for it in o.get("items") or []:
            mc = it.get("main_category")
            sc = it.get("sub_category") or ""
            pn = it.get("product_name") or ""
            if mc:
                main_cats.add(mc)
                if sc:
                    sub_by_main[mc].add(sc)
                    if pn:
                        products_by_sub[f"{mc}/{sc}"].add(pn)

    parties = sorted({p.get("party") for p in pays if p.get("party")})
    modes = sorted(set(DEFAULT_MODES) | {p.get("mode") for p in pays if p.get("mode")})

    accounts = await db.accounts.find({"archived": {"$ne": True}}, {"_id": 0}).sort("name", 1).to_list(500)

    vendor_docs = await db.vendors.find({}, {"_id": 0}).sort("name", 1).to_list(2000)
    vendors = [v.get("name") for v in vendor_docs if v.get("name")]
    # Also include vendors that appear on purchases even if not saved
    purch = await db.purchases.find({}, {"_id": 0, "vendor_name": 1}).to_list(5000)
    for p in purch:
        if p.get("vendor_name") and p["vendor_name"] not in vendors:
            vendors.append(p["vendor_name"])

    return {
        "main_categories": sorted(main_cats),
        "sub_categories_by_main": {k: sorted(v) for k, v in sub_by_main.items()},
        "products_by_sub": {k: sorted(v) for k, v in products_by_sub.items()},
        "clients": sorted(clients),
        "transporters": sorted(transporters),
        "parties": parties,
        "modes": modes,
        "tax_types": TAX_TYPES,
        "payment_statuses": PAYMENT_STATUSES,
        "payment_modes": PAYMENT_MODES,
        "account_types": ACCOUNT_TYPES,
        "accounts": accounts,
        "vendors": sorted(set(vendors)),
    }


# ================================================================
# EXPORTS
# ================================================================
INR_FMT = '"₹"#,##0'
DATE_FMT = "dd-mmm-yyyy"


def _autofit(ws):
    for col in ws.columns:
        max_len = 0
        letter = col[0].column_letter
        for cell in col:
            v = cell.value
            if v is None:
                continue
            length = len(str(v))
            if length > max_len:
                max_len = length
        ws.column_dimensions[letter].width = min(max_len + 3, 42)


def _style_header(ws, ncols):
    header_fill = PatternFill("solid", fgColor="F5F3EC")
    header_font = Font(name="Calibri", size=11, bold=True, color="2C2A29")
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"


def _xlsx_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _parse_date(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "")).date()
    except Exception:
        return None


def _csv_response(rows: List[dict], fieldnames: List[str], filename: str):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@api_router.get("/export/orders.xlsx")
async def export_orders_xlsx():
    orders = await db.orders.find({}, {"_id": 0}).sort("shipped_date", 1).to_list(10000)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"

    headers = ["Order Date", "Shipped Date", "Client", "Payment Status", "Items",
               "Product Sales", "Freight Charged", "Packing Charged", "Other Revenue", "Operating Revenue",
               "Factory Cost", "Outside Cost", "Packing Cost", "Freight Paid",
               "Other Expense", "Total Cost",
               "Net Profit", "Margin %",
               "Tax Type", "Tax %", "Tax Amount", "Tax Manual?", "Invoice Total",
               "Boxes Used", "Boxes Shipped", "Transporter", "LR/Tracking", "Notes"]
    ws.append(headers)
    _style_header(ws, len(headers))

    for o in orders:
        ws.append([
            _parse_date(o.get("order_date")),
            _parse_date(o.get("shipped_date")),
            o.get("client_name"),
            o.get("payment_status"),
            len(o.get("items") or []),
            o.get("product_sales_total") or 0,
            o.get("freight_charged") or 0,
            o.get("packing_recovery") or 0,
            o.get("other_revenue_total") or 0,
            o.get("operating_revenue") or 0,
            o.get("factory_cost_total") or 0,
            o.get("outside_cost_total") or 0,
            o.get("packing_cost") or 0,
            o.get("freight_paid") or 0,
            o.get("other_expense_total") or 0,
            o.get("total_cost") or 0,
            o.get("net_profit") or 0,
            round(o.get("margin_percent") or 0, 2),
            o.get("tax_type") or "None",
            o.get("tax_percent") or 0,
            o.get("tax_amount") or 0,
            "Yes" if o.get("tax_amount_manual") else "Auto",
            o.get("invoice_total") or 0,
            o.get("boxes_used") or 0,
            o.get("boxes_shipped") or 0,
            o.get("transporter") or "",
            o.get("lr_number") or "",
            o.get("notes") or "",
        ])

    money_cols = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 21, 23]
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[0].number_format = DATE_FMT
        row[1].number_format = DATE_FMT
        for i in money_cols:
            row[i - 1].number_format = INR_FMT
        row[17].number_format = '0.0"%"'  # margin (col 18)
        row[19].number_format = '0.0"%"'  # tax % (col 20)

    _autofit(ws)
    return _xlsx_response(wb, "orders.xlsx")


@api_router.get("/export/order-items.xlsx")
async def export_order_items_xlsx():
    """One row per line item, denormalised with order info — most detailed export."""
    orders = await db.orders.find({}, {"_id": 0}).sort("shipped_date", 1).to_list(10000)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Order Items"

    headers = ["Shipped Date", "Client", "Main Category", "Sub Category", "Product",
               "Qty", "Rate", "Product Sales",
               "Factory Complete", "Factory Glass", "Factory Fitting",
               "Outside Complete", "Outside Glass", "Outside Fitting"]
    ws.append(headers)
    _style_header(ws, len(headers))

    for o in orders:
        for it in o.get("items") or []:
            ws.append([
                _parse_date(o.get("shipped_date")),
                o.get("client_name"),
                it.get("main_category"),
                it.get("sub_category") or "",
                it.get("product_name"),
                it.get("qty") or 0,
                it.get("rate") or 0,
                it.get("product_sales") or 0,
                it.get("factory_complete") or 0,
                it.get("factory_glass") or 0,
                it.get("factory_fitting") or 0,
                it.get("outside_complete") or 0,
                it.get("outside_glass") or 0,
                it.get("outside_fitting") or 0,
            ])

    money_cols = list(range(7, 15))
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[0].number_format = DATE_FMT
        for i in money_cols:
            row[i - 1].number_format = INR_FMT
    _autofit(ws)
    return _xlsx_response(wb, "order-items.xlsx")


@api_router.get("/export/orders.csv")
async def export_orders_csv():
    orders = await db.orders.find({}, {"_id": 0}).sort("shipped_date", 1).to_list(10000)
    rows = []
    for o in orders:
        rows.append({
            "order_date": o.get("order_date"),
            "shipped_date": o.get("shipped_date"),
            "client_name": o.get("client_name"),
            "payment_status": o.get("payment_status"),
            "item_count": len(o.get("items") or []),
            "product_sales_total": o.get("product_sales_total") or 0,
            "freight_charged": o.get("freight_charged") or 0,
            "operating_revenue": o.get("operating_revenue") or 0,
            "factory_cost_total": o.get("factory_cost_total") or 0,
            "outside_cost_total": o.get("outside_cost_total") or 0,
            "packing_cost": o.get("packing_cost") or 0,
            "freight_paid": o.get("freight_paid") or 0,
            "total_cost": o.get("total_cost") or 0,
            "net_profit": o.get("net_profit") or 0,
            "tax_type": o.get("tax_type"),
            "tax_percent": o.get("tax_percent"),
            "tax_amount": o.get("tax_amount") or 0,
            "invoice_total": o.get("invoice_total") or 0,
            "boxes_used": o.get("boxes_used") or 0,
            "boxes_shipped": o.get("boxes_shipped") or 0,
            "transporter": o.get("transporter"),
            "lr_number": o.get("lr_number"),
            "notes": o.get("notes"),
        })
    fields = list(rows[0].keys()) if rows else ["order_date"]
    return _csv_response(rows, fields, "orders.csv")


@api_router.get("/export/payments.csv")
async def export_payments_csv():
    docs = await db.payments.find({}, {"_id": 0}).sort("date", 1).to_list(10000)
    fields = ["date", "party", "mode", "received_by_me", "received_by_fac",
              "payment_by_me", "payment_by_fac", "note"]
    return _csv_response(docs, fields, "payments.csv")


@api_router.get("/export/payments.xlsx")
async def export_payments_xlsx():
    docs = await db.payments.find({}, {"_id": 0}).sort("date", 1).to_list(10000)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payments"

    headers = ["Date", "Party", "Mode", "Received by Me", "Received by Factory",
               "Payment by Me", "Payment by Factory", "Net", "Note"]
    ws.append(headers)
    _style_header(ws, len(headers))

    for d in docs:
        received = (d.get("received_by_me") or 0) + (d.get("received_by_fac") or 0)
        paid = (d.get("payment_by_me") or 0) + (d.get("payment_by_fac") or 0)
        ws.append([
            _parse_date(d.get("date")),
            d.get("party"),
            d.get("mode"),
            d.get("received_by_me") or 0,
            d.get("received_by_fac") or 0,
            d.get("payment_by_me") or 0,
            d.get("payment_by_fac") or 0,
            received - paid,
            d.get("note") or "",
        ])

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        row[0].number_format = DATE_FMT
        for i in range(4, 9):
            row[i - 1].number_format = INR_FMT
    _autofit(ws)
    return _xlsx_response(wb, "payments.xlsx")


# ================================================================
# PARTY LEDGER — single source of truth
# ================================================================
def _short_id(x: Optional[str]) -> str:
    return (x or "")[:8]


@api_router.get("/party-ledger/summary")
async def party_ledger_summary():
    """Return a list of every party with its current outstanding / advance / last txn.
    Sources:
      - orders.invoice_total → debit (billed)
      - customer_payments.amount → credit (paid)
      - customer_payments.unallocated → advance
    """
    orders = await db.orders.find({}, {"_id": 0}).to_list(20000)
    payments = await db.customer_payments.find({}, {"_id": 0}).to_list(20000)
    known = {c["name"] async for c in db.customers.find({}, {"_id": 0, "name": 1})}

    parties: dict = {}

    def _get(name):
        n = name or "Unknown"
        if n not in parties:
            parties[n] = {
                "party": n, "total_billed": 0.0, "total_received": 0.0,
                "allocated": 0.0, "advance": 0.0, "outstanding": 0.0,
                "orders": 0, "payments": 0, "last_txn_date": None,
            }
        return parties[n]

    for o in orders:
        p = _get(o.get("client_name"))
        p["total_billed"] += float(o.get("invoice_total") or 0)
        p["orders"] += 1
        d = o.get("last_shipped_date") or o.get("shipped_date") or o.get("order_date")
        if d and (p["last_txn_date"] is None or d > p["last_txn_date"]):
            p["last_txn_date"] = d

    for pay in payments:
        p = _get(pay.get("customer_name"))
        amt = float(pay.get("amount") or 0)
        adv = float(pay.get("unallocated") or 0)
        p["total_received"] += amt
        p["allocated"] += (amt - adv)
        p["advance"] += adv
        p["payments"] += 1
        d = pay.get("date")
        if d and (p["last_txn_date"] is None or d > p["last_txn_date"]):
            p["last_txn_date"] = d

    for name in known:
        _get(name)

    for p in parties.values():
        # outstanding = billed - allocated (advance is a separate positive credit)
        p["outstanding"] = round(p["total_billed"] - p["allocated"], 2)

    rows = sorted(
        parties.values(),
        key=lambda x: (-abs(x["outstanding"]), -(x["advance"] or 0), x["party"]),
    )
    return {
        "count": len(rows),
        "total_outstanding": round(sum(p["outstanding"] for p in rows if p["outstanding"] > 0), 2),
        "total_advance": round(sum(p["advance"] for p in rows), 2),
        "parties": rows,
    }


@api_router.get("/party-ledger")
async def party_ledger(party: str = Query(..., min_length=1)):
    """Chronological statement for one party.
    Events:
      - Invoice (Debit) — one per order (uses invoice_total, dated by last shipment date)
      - Payment (Credit) — from customer_payments; includes allocation details
    Also includes legacy cash-book payments (`payments` collection) for parity.
    """
    orders = await db.orders.find({"client_name": party}, {"_id": 0}).to_list(5000)
    cust_pays = await db.customer_payments.find({"customer_name": party}, {"_id": 0}).sort("date", 1).to_list(5000)
    legacy = await db.payments.find({"party": party}, {"_id": 0}).sort("date", 1).to_list(5000)

    order_by_id = {o.get("id"): o for o in orders}
    events: List[dict] = []

    for o in orders:
        inv = float(o.get("invoice_total") or 0)
        if inv <= 0 and not (o.get("shipments") or []):
            continue
        # one aggregate invoice line per order (uses stored invoice_total which already
        # reflects only shipped qty). Show # of shipments in meta.
        events.append({
            "type": "invoice",
            "date": o.get("last_shipped_date") or o.get("shipped_date") or o.get("order_date"),
            "ref": _short_id(o.get("id")),
            "description": f"Invoice · Order #{_short_id(o.get('id'))}",
            "debit": inv,
            "credit": 0.0,
            "order_id": o.get("id"),
            "meta": {
                "status": o.get("status"),
                "items": len(o.get("items") or []),
                "shipments": len(o.get("shipments") or []),
                "shipped_qty": o.get("shipped_qty_total") or 0,
                "ordered_qty": o.get("ordered_qty_total") or 0,
                "payment_status": o.get("payment_status"),
            },
        })

    for pay in cust_pays:
        amt = float(pay.get("amount") or 0)
        adv = float(pay.get("unallocated") or 0)
        alloc_list = pay.get("allocations") or []
        alloc_desc = []
        for a in alloc_list:
            oid = a.get("order_id")
            amt_a = float(a.get("amount") or 0)
            alloc_desc.append({
                "order_id": oid, "amount": amt_a,
                "short": _short_id(oid), "invoice_total": float((order_by_id.get(oid) or {}).get("invoice_total") or 0),
            })
        descr = f"Payment · {pay.get('mode') or 'Cash'}"
        if pay.get("account_name"):
            descr += f" → {pay.get('account_name')}"
        if pay.get("reference"):
            descr += f" · Ref {pay.get('reference')}"
        if adv > 0.5:
            descr += f" · Advance {adv:.0f}"
        events.append({
            "type": "payment",
            "date": pay.get("date"),
            "ref": pay.get("reference") or _short_id(pay.get("id")),
            "description": descr,
            "debit": 0.0,
            "credit": amt,
            "payment_id": pay.get("id"),
            "meta": {
                "mode": pay.get("mode"),
                "account_name": pay.get("account_name"),
                "account_id": pay.get("account_id"),
                "reference": pay.get("reference"),
                "remarks": pay.get("remarks"),
                "advance": adv,
                "allocations": alloc_desc,
            },
        })

    # Legacy cash-book entries (kept for parity so nothing is lost)
    for d in legacy:
        received = float((d.get("received_by_me") or 0) + (d.get("received_by_fac") or 0))
        paid = float((d.get("payment_by_me") or 0) + (d.get("payment_by_fac") or 0))
        if received == 0 and paid == 0:
            continue
        events.append({
            "type": "cashbook",
            "date": d.get("date"),
            "ref": _short_id(d.get("id")),
            "description": f"Cash Book · {d.get('mode') or 'Cash'}"
                           + (f" · {d.get('note')}" if d.get("note") else ""),
            "debit": paid,
            "credit": received,
            "cashbook_id": d.get("id"),
            "meta": {"mode": d.get("mode"), "note": d.get("note")},
        })

    # Sort chronologically; invoice before payment on the same date.
    def _k(e):
        return (e.get("date") or "", 0 if e["type"] == "invoice" else 1)
    events.sort(key=_k)

    balance = 0.0
    total_billed = 0.0
    total_received = 0.0
    for e in events:
        balance += float(e.get("debit") or 0) - float(e.get("credit") or 0)
        e["running_balance"] = round(balance, 2)
        total_billed += float(e.get("debit") or 0)
        total_received += float(e.get("credit") or 0)

    advance = sum(float(p.get("unallocated") or 0) for p in cust_pays)
    allocated = sum(float(p.get("amount") or 0) - float(p.get("unallocated") or 0) for p in cust_pays)
    outstanding = round(sum(float(o.get("invoice_total") or 0) for o in orders) - allocated, 2)

    return {
        "party": party,
        "count": len(events),
        "total_billed": round(total_billed, 2),
        "total_received": round(total_received, 2),
        "advance": round(advance, 2),
        "allocated": round(allocated, 2),
        "outstanding": outstanding,
        "net_balance": round(total_billed - total_received, 2),
        "entries": events,
        "orders": [{
            "id": o.get("id"),
            "date": o.get("last_shipped_date") or o.get("shipped_date") or o.get("order_date"),
            "invoice_total": float(o.get("invoice_total") or 0),
            "total_received": float(o.get("total_received") or 0),
            "outstanding_balance": float(o.get("outstanding_balance") or 0),
            "payment_status": o.get("payment_status"),
            "status": o.get("status"),
        } for o in sorted(orders,
                          key=lambda x: (x.get("last_shipped_date") or x.get("order_date") or ""))],
    }


# ================================================================
# MIGRATION: old transactions collection → orders collection
# ================================================================
async def _migrate_transactions_to_orders() -> int:
    """Group old flat transactions rows into orders by client+shipped_date, and
    materialise one Shipment covering all items so historical numbers stay intact."""
    tx = await db.transactions.find({}, {"_id": 0}).to_list(20000)
    if not tx:
        return 0

    groups = defaultdict(list)
    for t in tx:
        day = (t.get("shipped_date") or "")[:10] or "undated"
        key = (t.get("client_name") or "Unknown").strip() + "||" + day
        groups[key].append(t)

    orders_to_insert = []
    for key, rows in groups.items():
        client_name, day = key.split("||")
        shipped_date = rows[0].get("shipped_date")

        packing_cost = sum(float(r.get("packing") or 0) for r in rows)
        freight_paid = sum(float(r.get("freight") or 0) for r in rows)

        items = []
        ship_items = []
        for r in rows:
            it = OrderItem(
                main_category=r.get("category") or "Uncategorised",
                sub_category="",
                product_name=r.get("particulars") or "",
                qty=float(r.get("qty") or 0),
                rate=float(r.get("rate") or 0),
                product_sales=float(r.get("sales") or 0),
                factory_complete=float(r.get("factory_complete") or 0),
                factory_glass=float(r.get("factory_glass") or 0),
                factory_fitting=float(r.get("factory_fitting") or 0),
                outside_complete=float(r.get("outside_complete") or 0),
                outside_glass=float(r.get("outside_glass") or 0),
                outside_fitting=float(r.get("outside_fitting") or 0),
            ).model_dump()
            items.append(it)
            ship_items.append({"order_item_id": it["id"], "qty": it["qty"]})

        # Single shipment covering all items — freight/packing rolled up
        auto_shipment = Shipment(
            date=shipped_date,
            items=[ShipmentItem(**s).model_dump() for s in ship_items],
            freight_paid=freight_paid,
            boxes_shipped=0,
            remarks="Auto-created from legacy data during migration",
        ).model_dump()

        order = Order(
            client_name=client_name,
            order_date=shipped_date,
            shipped_date=shipped_date,
            status="Fully Shipped",
            payment_status="Paid",  # historical rows treated as paid
            items=items,
            shipments=[auto_shipment],
            packing_cost=packing_cost,
        ).model_dump()
        compute_order_aggregates(order)
        orders_to_insert.append(order)

    if orders_to_insert:
        await db.orders.insert_many(orders_to_insert)

    for name in {o["client_name"] for o in orders_to_insert if o.get("client_name")}:
        await db.customers.update_one(
            {"name": name},
            {"$setOnInsert": Customer(name=name).model_dump()},
            upsert=True,
        )
    return len(orders_to_insert)


async def _migrate_order_payments_to_customer_payments() -> int:
    """Move each embedded order_payment out into a CustomerPayment doc with a single allocation."""
    count = 0
    async for o in db.orders.find({"order_payments": {"$exists": True, "$ne": []}}):
        oid = o["id"]
        client = o.get("client_name") or "Unknown"
        for p in (o.get("order_payments") or []):
            amt = float(p.get("amount") or 0)
            cp = CustomerPayment(
                customer_name=client,
                date=p.get("date"),
                amount=amt,
                mode=p.get("mode") or "Cash",
                account_id=p.get("account_id") or "",
                account_name=p.get("account_name") or "",
                reference=p.get("reference") or "",
                remarks=p.get("remarks") or "",
                allocations=[PaymentAllocation(order_id=oid, amount=amt).model_dump()],
                allocated_total=amt,
                unallocated=0,
            ).model_dump()
            await db.customer_payments.insert_one(cp)
            count += 1
        # Remove the embedded field to complete the move
        await db.orders.update_one({"id": oid}, {"$unset": {"order_payments": ""}})
    return count


@api_router.post("/migrate")
async def migrate_endpoint(force: bool = False, confirm_wipe: Optional[str] = None):
    """Migrate legacy transactions → orders. `force=true` wipes ONLY orders
    (never touches payments/accounts/customers). Requires confirm_wipe="YES" for safety."""
    order_count = await db.orders.count_documents({})
    if order_count > 0 and not force:
        return {"status": "skipped", "orders": order_count}
    if force:
        if confirm_wipe != "YES":
            raise HTTPException(
                status_code=400,
                detail="Refusing to wipe orders. Pass confirm_wipe=YES to proceed.",
            )
        await db.orders.delete_many({})
    n = await _migrate_transactions_to_orders()
    return {"status": "migrated", "orders_created": n}


# ================================================================
# SEED (kept for fresh installs — highly guarded to prevent accidental wipes)
# ================================================================
@api_router.post("/seed")
async def seed(force: bool = False, confirm_wipe: Optional[str] = None):
    """One-shot seed of legacy transactions + payments + orders migration.
    Contract:
      - No args: skips silently if any data exists (idempotent for fresh installs).
      - force=true: refuses unless confirm_wipe='YES' is also passed.
        When force=true+confirm_wipe='YES', wipes transactions/orders/payments and reseeds.
    NEVER touches accounts or customers collections."""
    tx_count = await db.transactions.count_documents({})
    order_count = await db.orders.count_documents({})
    pay_count = await db.payments.count_documents({})
    if not force and (tx_count > 0 or order_count > 0):
        return {"status": "skipped", "orders": order_count,
                "raw_transactions": tx_count, "payments": pay_count}

    if force:
        if confirm_wipe != "YES":
            raise HTTPException(
                status_code=400,
                detail=("Refusing to wipe data. Pass confirm_wipe=YES with force=true. "
                        "This will delete ALL transactions, orders and payments."),
            )
        logger.warning(
            f"SEED force=true confirmed — wiping {tx_count} transactions, "
            f"{order_count} orders, {pay_count} payments before reseed."
        )
        await db.transactions.delete_many({})
        await db.orders.delete_many({})
        await db.payments.delete_many({})

    seed_path = ROOT_DIR / "seed" / "pl_seed.json"
    if not seed_path.exists():
        return {"status": "no_seed_file"}
    data = json.loads(seed_path.read_text())

    # Import raw rows into "transactions" (legacy) so migration groups them
    tx_docs = []
    for r in data.get("pl", []):
        cat = r.get("category")
        if not cat or cat in ("-",):
            continue
        tx_docs.append({
            "id": str(uuid.uuid4()),
            "category": cat,
            "particulars": r.get("particulars") or "",
            "client_name": r.get("client_name") or "",
            "qty": float(r.get("qty") or 0),
            "rate": float(r.get("rate") or 0),
            "sales": float(r.get("sales") or 0),
            "factory_complete": float(r.get("factory_complete") or 0),
            "factory_glass": float(r.get("factory_glass") or 0),
            "factory_fitting": float(r.get("factory_fitting") or 0),
            "outside_complete": float(r.get("outside_complete") or 0),
            "outside_glass": float(r.get("outside_glass") or 0),
            "outside_fitting": float(r.get("outside_fitting") or 0),
            "packing": float(r.get("packing") or 0),
            "freight": float(r.get("freight") or 0),
            "net_profit": float(r.get("net_profit") or 0),
            "shipped_date": r.get("shipped_date"),
        })
    if tx_docs:
        await db.transactions.insert_many(tx_docs)

    pay_docs = []
    for r in data.get("cash_flow", []):
        if not r.get("party") and not r.get("date"):
            continue
        pay_docs.append(Payment(
            date=r.get("date"),
            received_by_me=float(r.get("received_by_me") or 0),
            received_by_fac=float(r.get("received_by_fac") or 0),
            payment_by_me=float(r.get("payment_by_me") or 0),
            payment_by_fac=float(r.get("payment_by_fac") or 0),
            party=r.get("party") or "Unknown",
            mode=r.get("mode") or "Cash",
        ).model_dump())
    if pay_docs:
        await db.payments.insert_many(pay_docs)

    # Now migrate raw → orders
    n = await _migrate_transactions_to_orders()
    return {"status": "seeded", "raw_transactions": len(tx_docs), "orders": n, "payments": len(pay_docs)}


@api_router.get("/")
async def root():
    return {"message": "Artisan Ledger API — order-based"}


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _refresh_stored_aggregates() -> int:
    """Recompute and $set aggregate fields on every order using current formula.
    Idempotent — safe to run on startup. Fixes drift when the formula changed."""
    n = 0
    async for doc in db.orders.find({}):
        doc.pop("_id", None)
        before = {k: doc.get(k) for k in ("operating_revenue", "total_cost", "net_profit", "invoice_total")}
        compute_order_aggregates(doc)
        after = {k: doc.get(k) for k in ("operating_revenue", "total_cost", "net_profit", "invoice_total")}
        if before != after or "total_received" not in doc:
            await db.orders.update_one({"id": doc["id"]}, {"$set": {
                "product_sales_total": doc["product_sales_total"],
                "factory_cost_total": doc["factory_cost_total"],
                "outside_cost_total": doc["outside_cost_total"],
                "other_revenue_total": doc.get("other_revenue_total", 0),
                "other_expense_total": doc.get("other_expense_total", 0),
                "operating_revenue": doc["operating_revenue"],
                "total_cost": doc["total_cost"],
                "tax_amount": doc["tax_amount"],
                "invoice_total": doc["invoice_total"],
                "net_profit": doc["net_profit"],
                "margin_percent": doc["margin_percent"],
                "total_received": doc.get("total_received", 0),
                "outstanding_balance": doc.get("outstanding_balance", 0),
            }})
            n += 1
    return n


# ================================================================
# SHIPMENTS (per-order)
# ================================================================
@api_router.post("/orders/{oid}/shipments", response_model=Order)
async def add_shipment(oid: str, payload: Shipment):
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    order["shipments"] = (order.get("shipments") or []) + [payload.model_dump()]
    compute_order_aggregates(order)
    order["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": oid}, {"$set": order})
    await _recompute_payment_aggregates_for_orders([oid])
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    return Order(**updated)


@api_router.put("/orders/{oid}/shipments/{sid}", response_model=Order)
async def update_shipment(oid: str, sid: str, payload: Shipment):
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    shipments = order.get("shipments") or []
    idx = next((i for i, s in enumerate(shipments) if s.get("id") == sid), -1)
    if idx == -1:
        raise HTTPException(404, "Shipment not found")
    new_ship = payload.model_dump()
    new_ship["id"] = sid  # preserve
    shipments[idx] = new_ship
    order["shipments"] = shipments
    compute_order_aggregates(order)
    order["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": oid}, {"$set": order})
    await _recompute_payment_aggregates_for_orders([oid])
    updated = await db.orders.find_one({"id": oid}, {"_id": 0})
    return Order(**updated)


@api_router.delete("/orders/{oid}/shipments/{sid}")
async def delete_shipment(oid: str, sid: str):
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")
    before = len(order.get("shipments") or [])
    order["shipments"] = [s for s in (order.get("shipments") or []) if s.get("id") != sid]
    if len(order["shipments"]) == before:
        raise HTTPException(404, "Shipment not found")
    compute_order_aggregates(order)
    await db.orders.update_one({"id": oid}, {"$set": order})
    await _recompute_payment_aggregates_for_orders([oid])
    return {"deleted": True}


# ================================================================
# CUSTOMER PAYMENTS  (payments + multi-order allocation + advances)
# ================================================================
def _finalise_customer_payment(cp: dict) -> dict:
    amt = float(cp.get("amount") or 0)
    alloc = sum(float((a or {}).get("amount") or 0) for a in (cp.get("allocations") or []))
    if alloc > amt + 0.01:
        raise HTTPException(400, "Allocated amount exceeds payment amount")
    cp["allocated_total"] = alloc
    cp["unallocated"] = max(0.0, amt - alloc)
    return cp


@api_router.post("/customer-payments", response_model=CustomerPayment)
async def create_customer_payment(payload: CustomerPaymentBase):
    cp = CustomerPayment(**payload.model_dump()).model_dump()
    _finalise_customer_payment(cp)
    await db.customer_payments.insert_one(cp)
    order_ids = [a.get("order_id") for a in (cp.get("allocations") or []) if a.get("order_id")]
    await _recompute_payment_aggregates_for_orders(order_ids)
    return CustomerPayment(**cp)


@api_router.get("/customer-payments", response_model=List[CustomerPayment])
async def list_customer_payments(
    customer_name: Optional[str] = None,
    account_id: Optional[str] = None,
    mode: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    only_with_advance: bool = False,
):
    q: dict = {}
    if customer_name:
        q["customer_name"] = {"$regex": customer_name, "$options": "i"}
    if account_id:
        q["account_id"] = account_id
    if mode and mode != "all":
        q["mode"] = mode
    if start_date or end_date:
        d: dict = {}
        if start_date: d["$gte"] = start_date
        if end_date: d["$lte"] = end_date
        q["date"] = d
    if only_with_advance:
        q["unallocated"] = {"$gt": 0}
    docs = await db.customer_payments.find(q, {"_id": 0}).sort("date", -1).to_list(5000)
    return [CustomerPayment(**d) for d in docs]


@api_router.get("/customer-payments/{pid}", response_model=CustomerPayment)
async def get_customer_payment(pid: str):
    doc = await db.customer_payments.find_one({"id": pid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Payment not found")
    return CustomerPayment(**doc)


@api_router.put("/customer-payments/{pid}", response_model=CustomerPayment)
async def update_customer_payment(pid: str, payload: CustomerPaymentBase):
    existing = await db.customer_payments.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Payment not found")
    old_order_ids = [a.get("order_id") for a in (existing.get("allocations") or []) if a.get("order_id")]
    cp = {**existing, **payload.model_dump()}
    _finalise_customer_payment(cp)
    await db.customer_payments.update_one({"id": pid}, {"$set": cp})
    new_order_ids = [a.get("order_id") for a in (cp.get("allocations") or []) if a.get("order_id")]
    await _recompute_payment_aggregates_for_orders(list(set(old_order_ids + new_order_ids)))
    return CustomerPayment(**cp)


@api_router.delete("/customer-payments/{pid}")
async def delete_customer_payment(pid: str):
    existing = await db.customer_payments.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Payment not found")
    order_ids = [a.get("order_id") for a in (existing.get("allocations") or []) if a.get("order_id")]
    await db.customer_payments.delete_one({"id": pid})
    await _recompute_payment_aggregates_for_orders(order_ids)
    return {"deleted": True}


# ================================================================
# ACCOUNTS MASTER
# ================================================================
@api_router.get("/accounts", response_model=List[Account])
async def list_accounts(include_archived: bool = False):
    q = {} if include_archived else {"archived": {"$ne": True}}
    docs = await db.accounts.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    return [Account(**d) for d in docs]


@api_router.post("/accounts", response_model=Account)
async def create_account(payload: Account):
    data = payload.model_dump()
    data["id"] = str(uuid.uuid4())
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.accounts.insert_one(data)
    return Account(**data)


@api_router.put("/accounts/{aid}", response_model=Account)
async def update_account(aid: str, payload: Account):
    existing = await db.accounts.find_one({"id": aid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Account not found")
    upd = payload.model_dump()
    upd.pop("id", None)
    upd.pop("created_at", None)
    await db.accounts.update_one({"id": aid}, {"$set": upd})
    doc = await db.accounts.find_one({"id": aid}, {"_id": 0})
    # Update denormalised account_name inside orders where this account is referenced
    if upd.get("name") and upd["name"] != existing.get("name"):
        await db.orders.update_many(
            {"order_payments.account_id": aid},
            {"$set": {"order_payments.$[p].account_name": upd["name"]}},
            array_filters=[{"p.account_id": aid}],
        )
    return Account(**doc)


@api_router.post("/accounts/{aid}/archive")
async def archive_account(aid: str, archived: bool = True):
    res = await db.accounts.update_one({"id": aid}, {"$set": {"archived": archived}})
    if res.matched_count == 0:
        raise HTTPException(404, "Account not found")
    return {"archived": archived}


async def _seed_default_accounts_if_empty():
    n = await db.accounts.count_documents({})
    if n > 0:
        return 0
    defaults = [
        ("ICICI Current", "Bank"),
        ("HDFC Current", "Bank"),
        ("Cash", "Cash"),
        ("Petty Cash", "PettyCash"),
        ("PhonePe", "UPI"),
        ("Google Pay", "UPI"),
        ("Paytm", "UPI"),
    ]
    for name, typ in defaults:
        await db.accounts.insert_one(Account(name=name, type=typ).model_dump())
    return len(defaults)


# ================================================================
# SALES PAYMENTS REPORT — sourced from customer_payments collection
# ================================================================
@api_router.get("/sales-payments")
async def sales_payments_report(
    account_id: Optional[str] = None,
    mode: Optional[str] = None,
    client_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    q: dict = {}
    if account_id:
        q["account_id"] = account_id
    if mode and mode != "all":
        q["mode"] = mode
    if client_name:
        q["customer_name"] = {"$regex": client_name, "$options": "i"}
    if start_date or end_date:
        d: dict = {}
        if start_date: d["$gte"] = start_date
        if end_date: d["$lte"] = end_date
        q["date"] = d

    docs = await db.customer_payments.find(q, {"_id": 0}).sort("date", -1).to_list(20000)
    rows = []
    total = 0
    total_advance = 0
    by_account = defaultdict(lambda: {"amount": 0, "count": 0})
    by_mode = defaultdict(lambda: {"amount": 0, "count": 0})
    for p in docs:
        amt = float(p.get("amount") or 0)
        adv = float(p.get("unallocated") or 0)
        total += amt
        total_advance += adv
        row = {
            "id": p.get("id"),
            "customer_name": p.get("customer_name"),
            "date": p.get("date"),
            "amount": amt,
            "mode": p.get("mode"),
            "account_id": p.get("account_id"),
            "account_name": p.get("account_name"),
            "reference": p.get("reference"),
            "remarks": p.get("remarks"),
            "allocated": float(p.get("allocated_total") or 0),
            "advance": adv,
            "allocations": p.get("allocations") or [],
        }
        rows.append(row)
        ak = row["account_name"] or "Unassigned"
        by_account[ak]["amount"] += amt
        by_account[ak]["count"] += 1
        mk = row["mode"] or "—"
        by_mode[mk]["amount"] += amt
        by_mode[mk]["count"] += 1

    return {
        "count": len(rows),
        "total": total,
        "total_advance": total_advance,
        "payments": rows,
        "by_account": sorted([{"account": k, **v} for k, v in by_account.items()],
                             key=lambda x: -x["amount"]),
        "by_mode": sorted([{"mode": k, **v} for k, v in by_mode.items()],
                          key=lambda x: -x["amount"]),
    }


@api_router.post("/orders/refresh-aggregates")
async def refresh_aggregates_endpoint():
    n = await _refresh_stored_aggregates()
    return {"refreshed": n}


# ================================================================
# VENDORS + PURCHASES + PURCHASE PAYMENTS (Accounts Payable module)
# ================================================================
class Vendor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    contact: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    gstin: Optional[str] = ""
    address: Optional[str] = ""
    notes: Optional[str] = ""
    archived: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PurchaseItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: Optional[str] = ""   # optional grouping (Raw Material / Glass / Fittings / Services…)
    description: str = ""
    qty: float = 0
    rate: float = 0
    amount: float = 0  # server-computed = qty * rate (if amount not provided)


class PurchaseBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_name: str
    purchase_date: Optional[str] = None
    invoice_no: Optional[str] = ""
    items: List[PurchaseItem] = []
    freight: float = 0
    other_charges: float = 0
    tax_applicable: bool = False
    tax_type: TaxType = "None"
    tax_percent: float = 0
    tax_amount: float = 0
    tax_amount_manual: bool = False
    notes: Optional[str] = ""
    payment_status: PaymentStatus = "Unpaid"


class Purchase(PurchaseBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    subtotal: float = 0
    invoice_total: float = 0
    total_paid: float = 0
    outstanding_balance: float = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Auto-linked-from-order metadata (present only when source_type =
    # 'order_product_purchase'). Manual purchases leave these blank / null.
    source_type: Optional[str] = None
    linked_to_order_id: Optional[str] = None
    linked_source_key: Optional[str] = None
    linked_supplier_id: Optional[str] = None
    linked_source_row_id: Optional[str] = None
    linked_order_item_id: Optional[str] = None
    linked_cost_category: Optional[str] = None
    stale: bool = False


class PurchasePaymentAllocation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    purchase_id: str
    amount: float = 0


class PurchasePaymentBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_name: str
    date: Optional[str] = None
    amount: float
    mode: str = "Cash"
    account_id: Optional[str] = None
    account_name: Optional[str] = ""
    reference: Optional[str] = ""
    remarks: Optional[str] = ""
    allocations: List[PurchasePaymentAllocation] = []
    # Party-ledger linkage. If paid_by_party_id is set (non-self), a linked
    # effect is posted on that party (e.g. Father's Firm paid on Rakshit's
    # behalf). split_paid_by_amount lets the payment be shared between
    # Rakshit and paid_by_party — the primary vendor reduction is the full
    # amount, while paid_by_party gets a linked entry for only its share.
    paid_by_party_id: Optional[str] = None
    paid_by_party_name: Optional[str] = None
    split_paid_by_amount: Optional[float] = None


class PurchasePayment(PurchasePaymentBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    allocated_total: float = 0
    unallocated: float = 0  # vendor advance
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def compute_purchase(purchase: dict) -> dict:
    items = purchase.get("items") or []
    subtotal = 0
    for it in items:
        amt = float(it.get("amount") or 0)
        if amt == 0:
            amt = float(it.get("qty") or 0) * float(it.get("rate") or 0)
            it["amount"] = amt
        subtotal += amt
    freight = float(purchase.get("freight") or 0)
    other = float(purchase.get("other_charges") or 0)
    base = subtotal + freight + other

    if purchase.get("tax_applicable"):
        if purchase.get("tax_amount_manual"):
            tax = float(purchase.get("tax_amount") or 0)
        else:
            tax = round(base * float(purchase.get("tax_percent") or 0) / 100.0, 2)
    else:
        tax = 0
    purchase["subtotal"] = subtotal
    purchase["tax_amount"] = tax
    purchase["invoice_total"] = base + tax
    purchase["items"] = items
    return purchase


async def _recompute_purchase_payment_aggregates(purchase_ids: List[str] = None):
    """Recompute total_paid, outstanding_balance and payment_status for given purchases."""
    q = {"id": {"$in": purchase_ids}} if purchase_ids else {}
    purchases = await db.purchases.find(q, {"_id": 0}).to_list(20000)
    for p in purchases:
        pid = p["id"]
        pays = await db.purchase_payments.find(
            {"allocations.purchase_id": pid}, {"_id": 0}
        ).to_list(10000)
        total_paid = 0
        for pay in pays:
            for alloc in pay.get("allocations") or []:
                if alloc.get("purchase_id") == pid:
                    total_paid += float(alloc.get("amount") or 0)
        invoice = float(p.get("invoice_total") or 0)
        outstanding = max(0.0, invoice - total_paid)
        if total_paid <= 0.5:
            status = "Unpaid"
        elif total_paid + 0.5 >= invoice:
            status = "Paid"
        else:
            status = "Partial"
        await db.purchases.update_one(
            {"id": pid},
            {"$set": {
                "total_paid": round(total_paid, 2),
                "outstanding_balance": round(outstanding, 2),
                "payment_status": status,
            }},
        )


# ---- Vendors CRUD ----
@api_router.get("/vendors", response_model=List[Vendor])
async def list_vendors(archived: bool = False):
    q = {} if archived else {"archived": {"$ne": True}}
    docs = await db.vendors.find(q, {"_id": 0}).sort("name", 1).to_list(2000)
    return [Vendor(**d) for d in docs]


@api_router.get("/purchase-sources")
async def list_purchase_sources():
    """Return the full set of pickable purchase sources for the Order dialog —
    Factory (Father's Firm — protected) as the first entry, followed by all
    active outside vendors. Kept small on purpose so the dropdown can be built
    from a single fetch."""
    docs = await db.vendors.find({"archived": {"$ne": True}}, {"_id": 0}).sort("name", 1).to_list(5000)
    rows = [{
        "id": FACTORY_SUPPLIER_ID,
        "name": "Factory",
        "type": "factory",
        "protected": True,
        "hint": "Father's Firm — settled via the Father's Firm ledger",
    }]
    for v in docs:
        rows.append({
            "id": v.get("id"),
            "name": v.get("name"),
            "type": "vendor",
            "protected": False,
            "hint": v.get("phone") or "",
        })
    return {"count": len(rows), "sources": rows}


@api_router.post("/vendors", response_model=Vendor)
async def create_vendor(payload: Vendor):
    exists = await db.vendors.find_one({"name": payload.name})
    if exists:
        raise HTTPException(400, "Vendor with this name already exists")
    v = payload.model_dump()
    await db.vendors.insert_one(v)
    return Vendor(**v)


@api_router.put("/vendors/{vid}", response_model=Vendor)
async def update_vendor(vid: str, payload: Vendor):
    data = payload.model_dump()
    data["id"] = vid
    res = await db.vendors.update_one({"id": vid}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(404, "Vendor not found")
    return Vendor(**data)


@api_router.delete("/vendors/{vid}")
async def delete_vendor(vid: str):
    res = await db.vendors.delete_one({"id": vid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Vendor not found")
    return {"deleted": True}


# ---- Purchases CRUD ----
@api_router.get("/purchases", response_model=List[Purchase])
async def list_purchases(
    vendor_name: Optional[str] = None,
    payment_status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    q: dict = {}
    if vendor_name:
        q["vendor_name"] = {"$regex": vendor_name, "$options": "i"}
    if payment_status and payment_status != "all":
        q["payment_status"] = payment_status
    if start_date or end_date:
        d: dict = {}
        if start_date: d["$gte"] = start_date
        if end_date: d["$lte"] = end_date
        q["purchase_date"] = d
    docs = await db.purchases.find(q, {"_id": 0}).sort("purchase_date", -1).to_list(5000)
    return [Purchase(**d) for d in docs]


@api_router.post("/purchases", response_model=Purchase)
async def create_purchase(payload: PurchaseBase):
    data = payload.model_dump()
    purchase = Purchase(**data).model_dump()
    compute_purchase(purchase)
    purchase["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.purchases.insert_one(purchase)
    # Ensure vendor exists in vendors master
    if data.get("vendor_name"):
        await db.vendors.update_one(
            {"name": data["vendor_name"]},
            {"$setOnInsert": Vendor(name=data["vendor_name"]).model_dump()},
            upsert=True,
        )
    await _recompute_purchase_payment_aggregates([purchase["id"]])
    fresh = await db.purchases.find_one({"id": purchase["id"]}, {"_id": 0})
    return Purchase(**fresh)


@api_router.get("/purchases/{pid}", response_model=Purchase)
async def get_purchase(pid: str):
    d = await db.purchases.find_one({"id": pid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Purchase not found")
    return Purchase(**d)


@api_router.put("/purchases/{pid}", response_model=Purchase)
async def update_purchase(pid: str, payload: PurchaseBase):
    existing = await db.purchases.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Purchase not found")
    data = payload.model_dump()
    data["id"] = pid
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    compute_purchase(data)
    await db.purchases.update_one({"id": pid}, {"$set": data})
    await _recompute_purchase_payment_aggregates([pid])
    fresh = await db.purchases.find_one({"id": pid}, {"_id": 0})
    return Purchase(**fresh)


@api_router.delete("/purchases/{pid}")
async def delete_purchase(pid: str):
    res = await db.purchases.delete_one({"id": pid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Purchase not found")
    # Remove allocations referring to this purchase from purchase_payments
    async for pay in db.purchase_payments.find({"allocations.purchase_id": pid}, {"_id": 0}):
        new_alloc = [a for a in (pay.get("allocations") or []) if a.get("purchase_id") != pid]
        alloc_total = sum(float(a.get("amount") or 0) for a in new_alloc)
        await db.purchase_payments.update_one(
            {"id": pay["id"]},
            {"$set": {
                "allocations": new_alloc,
                "allocated_total": alloc_total,
                "unallocated": max(0.0, float(pay.get("amount") or 0) - alloc_total),
            }},
        )
    return {"deleted": True}


@api_router.get("/vendors/{name}/outstanding-purchases")
async def vendor_outstanding_purchases(name: str):
    """Return purchases for vendor that are Unpaid/Partial (for allocation UI)."""
    docs = await db.purchases.find(
        {"vendor_name": name, "payment_status": {"$in": ["Unpaid", "Partial"]}},
        {"_id": 0},
    ).sort("purchase_date", 1).to_list(500)
    return [{
        "id": d["id"],
        "invoice_no": d.get("invoice_no") or "—",
        "purchase_date": d.get("purchase_date"),
        "invoice_total": float(d.get("invoice_total") or 0),
        "total_paid": float(d.get("total_paid") or 0),
        "outstanding_balance": float(d.get("outstanding_balance") or 0),
    } for d in docs]


# ---- Purchase Payments CRUD ----
@api_router.get("/purchase-payments", response_model=List[PurchasePayment])
async def list_purchase_payments(
    vendor_name: Optional[str] = None,
    mode: Optional[str] = None,
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    only_with_advance: bool = False,
):
    q: dict = {}
    if vendor_name:
        q["vendor_name"] = {"$regex": vendor_name, "$options": "i"}
    if mode and mode != "all":
        q["mode"] = mode
    if account_id:
        q["account_id"] = account_id
    if only_with_advance:
        q["unallocated"] = {"$gt": 0}
    if start_date or end_date:
        d: dict = {}
        if start_date: d["$gte"] = start_date
        if end_date: d["$lte"] = end_date
        q["date"] = d
    docs = await db.purchase_payments.find(q, {"_id": 0}).sort("date", -1).to_list(20000)
    return [PurchasePayment(**d) for d in docs]


@api_router.post("/purchase-payments", response_model=PurchasePayment)
async def create_purchase_payment(payload: PurchasePaymentBase):
    p = PurchasePayment(**payload.model_dump()).model_dump()
    amt = float(p.get("amount") or 0)
    alloc = sum(float(a.get("amount") or 0) for a in (p.get("allocations") or []))
    p["allocated_total"] = round(alloc, 2)
    p["unallocated"] = round(max(0.0, amt - alloc), 2)
    await db.purchase_payments.insert_one(p)
    # Ensure vendor exists
    if p.get("vendor_name"):
        await db.vendors.update_one(
            {"name": p["vendor_name"]},
            {"$setOnInsert": Vendor(name=p["vendor_name"]).model_dump()},
            upsert=True,
        )
    pids = [a["purchase_id"] for a in (p.get("allocations") or []) if a.get("purchase_id")]
    if pids:
        await _recompute_purchase_payment_aggregates(pids)
    return PurchasePayment(**p)


@api_router.get("/purchase-payments/{pid}", response_model=PurchasePayment)
async def get_purchase_payment(pid: str):
    d = await db.purchase_payments.find_one({"id": pid}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Purchase payment not found")
    return PurchasePayment(**d)


@api_router.put("/purchase-payments/{pid}", response_model=PurchasePayment)
async def update_purchase_payment(pid: str, payload: PurchasePaymentBase):
    existing = await db.purchase_payments.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Purchase payment not found")
    old_pids = [a.get("purchase_id") for a in (existing.get("allocations") or []) if a.get("purchase_id")]
    p = PurchasePayment(**{**payload.model_dump(), "id": pid, "created_at": existing.get("created_at")}).model_dump()
    amt = float(p.get("amount") or 0)
    alloc = sum(float(a.get("amount") or 0) for a in (p.get("allocations") or []))
    p["allocated_total"] = round(alloc, 2)
    p["unallocated"] = round(max(0.0, amt - alloc), 2)
    await db.purchase_payments.update_one({"id": pid}, {"$set": p})
    new_pids = [a.get("purchase_id") for a in (p.get("allocations") or []) if a.get("purchase_id")]
    all_pids = list({*(old_pids or []), *(new_pids or [])})
    if all_pids:
        await _recompute_purchase_payment_aggregates(all_pids)
    return PurchasePayment(**p)


@api_router.delete("/purchase-payments/{pid}")
async def delete_purchase_payment(pid: str):
    existing = await db.purchase_payments.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Purchase payment not found")
    pids = [a.get("purchase_id") for a in (existing.get("allocations") or []) if a.get("purchase_id")]
    await db.purchase_payments.delete_one({"id": pid})
    if pids:
        await _recompute_purchase_payment_aggregates(pids)
    return {"deleted": True}


# Register router AFTER all endpoints are defined


# ================================================================
# QUOTATIONS — native module (replaces embedded Samrat Glass ERP)
# ================================================================
class QuotationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    product_name: str = ""
    description: Optional[str] = ""
    qty: float = 1
    rate: float = 0
    amount: float = 0


class Quotation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    quote_number: Optional[str] = ""  # auto-assigned on create if blank
    quote_date: Optional[str] = None
    valid_until: Optional[str] = None
    client_name: str = ""
    client_phone: Optional[str] = ""
    client_email: Optional[str] = ""
    billing_address: Optional[str] = ""
    billing_city: Optional[str] = ""
    billing_pincode: Optional[str] = ""
    shipping_same_as_billing: bool = True
    shipping_address: Optional[str] = ""
    shipping_city: Optional[str] = ""
    shipping_pincode: Optional[str] = ""
    items: List[QuotationItem] = []
    gst_rate: float = 18
    freight_type: Literal["extra", "included", "none"] = "extra"
    freight_amount: float = 0
    subtotal: float = 0
    tax_amount: float = 0
    total: float = 0
    notes: Optional[str] = ""
    terms: Optional[str] = ""
    status: Literal["Draft", "Sent", "Accepted", "Rejected", "Converted"] = "Draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _compute_quotation_totals(q: dict) -> dict:
    """Recompute per-line amounts + subtotal + tax + total. Freight rules:
       - extra:    added on top of subtotal, taxed together with goods.
       - included: freight is already in the line rates — no separate row.
       - none:     no freight applied.
    """
    items = q.get("items") or []
    subtotal = 0.0
    for it in items:
        qty = float(it.get("qty") or 0)
        rate = float(it.get("rate") or 0)
        amt = round(qty * rate, 2)
        it["amount"] = amt
        subtotal += amt
    freight_type = q.get("freight_type") or "extra"
    freight = float(q.get("freight_amount") or 0) if freight_type == "extra" else 0.0
    taxable = subtotal + freight
    gst = float(q.get("gst_rate") or 0)
    tax = round(taxable * gst / 100.0, 2)
    total = round(taxable + tax, 2)
    q["subtotal"] = round(subtotal, 2)
    q["freight_amount"] = round(freight if freight_type == "extra" else float(q.get("freight_amount") or 0), 2)
    q["tax_amount"] = tax
    q["total"] = total
    return q


async def _next_quotation_number() -> str:
    """Generate the next SGE-YYYY-NNNN sequence based on quotations already stored."""
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"SGE-{year}-"
    # Find the highest existing sequence for this year
    latest = await db.quotations.find(
        {"quote_number": {"$regex": f"^{prefix}"}},
        {"quote_number": 1, "_id": 0},
    ).sort("quote_number", -1).limit(1).to_list(1)
    seq = 1
    if latest:
        try:
            seq = int(latest[0]["quote_number"].split("-")[-1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}{seq:04d}"


@api_router.get("/quotations", response_model=List[Quotation])
async def list_quotations(
    search: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
):
    query = {}
    if status and status != "all":
        query["status"] = status
    if search:
        query["$or"] = [
            {"client_name": {"$regex": search, "$options": "i"}},
            {"quote_number": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.quotations.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return docs


@api_router.get("/quotations/next-number")
async def next_quotation_number():
    return {"quote_number": await _next_quotation_number()}


@api_router.get("/quotations/{qid}", response_model=Quotation)
async def get_quotation(qid: str):
    doc = await db.quotations.find_one({"id": qid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quotation not found")
    return doc


@api_router.post("/quotations", response_model=Quotation)
async def create_quotation(payload: Quotation):
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = payload.model_dump()
    if not doc.get("quote_number"):
        doc["quote_number"] = await _next_quotation_number()
    if not doc.get("quote_date"):
        doc["quote_date"] = now_iso
    doc["created_at"] = now_iso
    doc["updated_at"] = now_iso
    doc = _compute_quotation_totals(doc)
    await db.quotations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/quotations/{qid}", response_model=Quotation)
async def update_quotation(qid: str, payload: Quotation):
    existing = await db.quotations.find_one({"id": qid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Quotation not found")
    doc = payload.model_dump()
    doc["id"] = qid
    doc["quote_number"] = doc.get("quote_number") or existing.get("quote_number")
    doc["created_at"] = existing.get("created_at")
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    doc = _compute_quotation_totals(doc)
    await db.quotations.replace_one({"id": qid}, doc)
    return doc


@api_router.delete("/quotations/{qid}")
async def delete_quotation(qid: str):
    r = await db.quotations.delete_one({"id": qid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Quotation not found")
    return {"deleted": True}


@api_router.post("/quotations/{qid}/duplicate", response_model=Quotation)
async def duplicate_quotation(qid: str):
    src = await db.quotations.find_one({"id": qid}, {"_id": 0})
    if not src:
        raise HTTPException(404, "Quotation not found")
    now_iso = datetime.now(timezone.utc).isoformat()
    new_doc = {**src}
    new_doc["id"] = str(uuid.uuid4())
    new_doc["quote_number"] = await _next_quotation_number()
    new_doc["quote_date"] = now_iso
    new_doc["created_at"] = now_iso
    new_doc["updated_at"] = now_iso
    new_doc["status"] = "Draft"
    # Reset item ids so front-end doesn't collide
    for it in (new_doc.get("items") or []):
        it["id"] = str(uuid.uuid4())
    await db.quotations.insert_one(new_doc)
    new_doc.pop("_id", None)
    return new_doc


# --- Party Ledger v2 (unified) ---
from party_ledger_v2 import make_router as make_party_ledger_v2_router, ensure_bootstrap as ensure_party_ledger_bootstrap
app.include_router(make_party_ledger_v2_router(db), prefix="/api")


app.include_router(api_router)


async def _seed_payments_if_empty() -> int:
    """DISABLED — kept as a stub for reference.
    User policy: existing data must never be automatically recreated after deletion.
    Auto-restore removed. Use POST /api/seed?force=true&confirm_wipe=YES to explicitly
    reseed everything, or restore payments manually from backend/seed/pl_seed.json."""
    return 0


@app.on_event("startup")
async def _startup():
    order_count = await db.orders.count_documents({})
    tx_count = await db.transactions.count_documents({})

    if order_count == 0 and tx_count > 0:
        try:
            n = await _migrate_transactions_to_orders()
            logger.info(f"Auto-migrated {n} orders from legacy transactions.")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
    elif order_count == 0 and tx_count == 0:
        try:
            r = await seed(force=False)
            logger.info(f"Auto-seed result: {r}")
        except Exception as e:
            logger.error(f"Auto-seed failed: {e}")

    # Migrate legacy order_payments → customer_payments (one-time, idempotent)
    try:
        n = await _migrate_order_payments_to_customer_payments()
        if n:
            logger.info(f"Migrated {n} legacy order payments to customer_payments collection.")
    except Exception as e:
        logger.error(f"Order-payment migration failed: {e}")

    # Backfill: existing orders without shipments should get one auto-shipment so
    # historical revenue reports don't drop to zero after this refactor.
    try:
        n = 0
        async for doc in db.orders.find({"$or": [
            {"shipments": {"$exists": False}},
            {"shipments": {"$size": 0}},
        ]}):
            doc.pop("_id", None)
            if not doc.get("items"):
                continue
            ship_items = [{"order_item_id": it["id"], "qty": float(it.get("qty") or 0)}
                          for it in doc["items"] if it.get("id")]
            auto = Shipment(
                date=doc.get("shipped_date") or doc.get("order_date"),
                items=[ShipmentItem(**s).model_dump() for s in ship_items],
                freight_paid=float(doc.get("freight_paid") or 0),
                freight_charged=float(doc.get("freight_charged") or 0),
                boxes_shipped=float(doc.get("boxes_shipped") or 0),
                transporter=doc.get("transporter") or "",
                lr_number=doc.get("lr_number") or "",
                remarks="Auto-created shipment (backfill during ERP refactor)",
            ).model_dump()
            doc["shipments"] = [auto]
            doc["status"] = "Fully Shipped"
            compute_order_aggregates(doc)
            await db.orders.update_one({"id": doc["id"]}, {"$set": doc})
            n += 1
        if n:
            logger.info(f"Backfilled auto-shipments on {n} legacy orders.")
    except Exception as e:
        logger.error(f"Shipment backfill failed: {e}")

    # Refresh aggregates & payment tallies
    try:
        n = await _refresh_stored_aggregates()
        if n:
            logger.info(f"Refreshed stored aggregates on {n} orders.")
        # Recompute payment aggregates for all orders (invoice may have changed)
        all_ids = await db.orders.distinct("id")
        await _recompute_payment_aggregates_for_orders(all_ids)
    except Exception as e:
        logger.error(f"Aggregate refresh failed: {e}")

    # Seed default accounts on fresh install
    try:
        n = await _seed_default_accounts_if_empty()
        if n:
            logger.info(f"Seeded {n} default accounts.")
    except Exception as e:
        logger.error(f"Account seed failed: {e}")

    # Party Ledger v2: seed system parties + derived parties from vendors/customers
    try:
        await ensure_party_ledger_bootstrap(db)
        n_parties = await db.parties.count_documents({})
        logger.info(f"Party Ledger v2 bootstrap OK — {n_parties} parties active.")
    except Exception as e:
        logger.error(f"Party Ledger v2 bootstrap failed: {e}")


@app.on_event("shutdown")
async def _shutdown():
    client.close()
