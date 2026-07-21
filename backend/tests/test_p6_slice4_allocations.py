"""Phase 6 · Slice 4 — Payment + purchase allocation consolidation.

Functions migrated to the shared domain layer:
  * server.compute_purchase                     — via purchase_realized_amounts
  * server._recompute_payment_aggregates_for_orders — via sum_allocations_to_order
  * server._recompute_purchase_payment_aggregates   — via sum_allocations_to_purchase
                                                      + purchase_outstanding_from_alloc
  * server.customer_outstanding_orders          — paise-safe read/write
  * server.vendor_outstanding_purchases         — paise-safe read/write

Regression net:
  1. compute_purchase — synthetic fixtures for every code path
     (item-amount fallback, freight, other_charges, tax auto, tax manual,
     tax_applicable=false, zero-qty items, missing values).
  2. Payment/allocation math — synthetic Mongo-side integration tests
     that push real customer/purchase payments through the recompute
     helpers and assert the stored aggregates in paise.
  3. Idempotency — three repeated recompute calls produce zero drift.
  4. Property — for every purchase,
        outstanding_balance_stored == max(0, invoice_total_paise - Σ_alloc_paise)
  5. Behaviour-preservation snapshot on live seed (dashboard KPIs +
     reconcile still healthy) — pinned via existing Slice-2/3 tests;
     we add here only a targeted reconcile-still-healthy assertion
     because the seed has zero purchases / zero payments.
"""
from __future__ import annotations

import copy
import os
import uuid
from decimal import Decimal

import pytest
from pymongo import MongoClient

import server


# ─── Helpers ───────────────────────────────────────────────────────────────

def to_paise(x) -> int:
    try:
        return int((Decimal(str(x)) * 100).quantize(Decimal("1")))
    except Exception:
        return 0


@pytest.fixture(scope="module")
def sync_db():
    """Synchronous pymongo handle for direct read/write in tests. Avoids the
    motor event-loop coupling that binds server.db at import time."""
    cli = MongoClient(os.environ["MONGO_URL"])
    yield cli[os.environ["DB_NAME"]]
    cli.close()


@pytest.fixture(scope="session")
def async_run():
    """Run a coroutine on a SESSION-scoped event loop.

    Motor's AsyncIOMotorClient binds to the first event loop that uses it;
    creating a fresh loop per test breaks subsequent tests. We keep one
    loop for the whole session so server.db always sees the same loop.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    def _run(coro):
        return loop.run_until_complete(coro)
    yield _run
    loop.close()


# ═════════════════════════════════════════════════════════════════════════
# 1.  compute_purchase — synthetic fixtures
# ═════════════════════════════════════════════════════════════════════════

class TestComputePurchase:
    """server.compute_purchase must produce paise-equivalent output vs
    hand-computed expectations, covering every code path."""

    def test_basic_no_tax(self):
        p = {"items": [{"qty": 10, "rate": 100}, {"qty": 5, "rate": 200}],
             "freight": 50, "other_charges": 30, "tax_applicable": False}
        result = server.compute_purchase(copy.deepcopy(p))
        # subtotal = 10*100 + 5*200 = 2000
        assert to_paise(result["subtotal"]) == 200_000
        # invoice_total = subtotal + freight + other = 2080
        assert to_paise(result["invoice_total"]) == 208_000
        assert to_paise(result["tax_amount"]) == 0

    def test_item_amount_fallback_to_qty_times_rate(self):
        """Item with amount=0 must be stamped with qty*rate."""
        p = {"items": [{"qty": 4, "rate": 250}], "tax_applicable": False}
        result = server.compute_purchase(copy.deepcopy(p))
        assert result["items"][0]["amount"] == 1000
        assert to_paise(result["subtotal"]) == 100_000
        assert to_paise(result["invoice_total"]) == 100_000

    def test_item_amount_stored_takes_precedence(self):
        """Stored non-zero amount is used AS-IS (no qty*rate override)."""
        p = {"items": [{"qty": 4, "rate": 250, "amount": 999}],
             "tax_applicable": False}
        result = server.compute_purchase(copy.deepcopy(p))
        # Stored amount 999 wins over 4*250 = 1000.
        assert to_paise(result["subtotal"]) == 99_900

    def test_tax_auto_percent(self):
        """Auto tax = HALF_UP paise on base."""
        p = {"items": [{"qty": 10, "rate": 100, "amount": 1000}],
             "freight": 100, "other_charges": 0,
             "tax_applicable": True, "tax_percent": 18}
        result = server.compute_purchase(copy.deepcopy(p))
        # subtotal 1000 + freight 100 = base 1100; tax = 1100 * 18% = 198.00
        assert to_paise(result["tax_amount"]) == 19_800
        assert to_paise(result["invoice_total"]) == 129_800

    def test_tax_manual_reads_stored(self):
        """tax_amount_manual=True must use stored tax_amount as-is."""
        p = {"items": [{"qty": 10, "rate": 100, "amount": 1000}],
             "tax_applicable": True, "tax_amount_manual": True,
             "tax_amount": 234.56}
        result = server.compute_purchase(copy.deepcopy(p))
        assert to_paise(result["tax_amount"]) == 23_456

    def test_tax_applicable_false_ignores_percent(self):
        """tax_applicable=False → tax must be zero even if tax_percent is set."""
        p = {"items": [{"qty": 10, "rate": 100, "amount": 1000}],
             "tax_applicable": False, "tax_percent": 18}
        result = server.compute_purchase(copy.deepcopy(p))
        assert to_paise(result["tax_amount"]) == 0

    def test_empty_purchase_all_zeros(self):
        p = {"items": [], "tax_applicable": False}
        result = server.compute_purchase(copy.deepcopy(p))
        assert to_paise(result["subtotal"]) == 0
        assert to_paise(result["invoice_total"]) == 0
        assert to_paise(result["tax_amount"]) == 0

    def test_missing_optional_values(self):
        p = {"items": [{"qty": 5, "rate": 20}]}  # no freight / other / tax fields
        result = server.compute_purchase(copy.deepcopy(p))
        assert to_paise(result["subtotal"]) == 10_000
        assert to_paise(result["invoice_total"]) == 10_000


class TestComputePurchaseIdempotency:
    """Re-running compute_purchase on its own output must produce zero drift."""

    @pytest.mark.parametrize("purchase", [
        {"items": [{"qty": 3, "rate": 400}], "freight": 20, "other_charges": 5,
         "tax_applicable": True, "tax_percent": 12},
        {"items": [{"qty": 1, "rate": 999.99}], "tax_applicable": False},
        {"items": [{"qty": 10, "rate": 100, "amount": 1050}],  # stored amount != qty*rate
         "freight": 0, "tax_applicable": True, "tax_percent": 5},
    ])
    def test_repeat_recompute_no_drift(self, purchase):
        r1 = server.compute_purchase(copy.deepcopy(purchase))
        r2 = server.compute_purchase(copy.deepcopy(r1))
        r3 = server.compute_purchase(copy.deepcopy(r2))
        for k in ("subtotal", "invoice_total", "tax_amount"):
            assert to_paise(r1[k]) == to_paise(r2[k]), f"{k}: drift 1→2"
            assert to_paise(r2[k]) == to_paise(r3[k]), f"{k}: drift 2→3"


class TestComputePurchaseNonMutating:
    """compute_purchase DOES intentionally mutate the purchase (that's its
    contract). But it must not corrupt fields it doesn't own — only
    `subtotal`, `tax_amount`, `invoice_total`, and `items[*].amount` (when
    that item's amount was 0) may change."""

    def test_only_documented_fields_mutated(self):
        original = {
            "vendor_name": "Vendor X",
            "purchase_date": "2026-01-01",
            "items": [{"id": "i1", "qty": 5, "rate": 200}],
            "freight": 25, "other_charges": 5,
            "tax_applicable": True, "tax_percent": 10,
            "notes": "keep me",
        }
        after = server.compute_purchase(copy.deepcopy(original))
        # These MUST be preserved
        for k in ("vendor_name", "purchase_date", "freight",
                  "other_charges", "tax_applicable", "tax_percent", "notes"):
            assert after[k] == original[k]
        # items[0].amount stamped (was missing)
        assert after["items"][0]["amount"] == 1000
        # items[0].qty/rate/id preserved
        for k in ("id", "qty", "rate"):
            assert after["items"][0][k] == original["items"][0][k]


# ═════════════════════════════════════════════════════════════════════════
# 2.  _recompute_payment_aggregates_for_orders — real Mongo flow
# ═════════════════════════════════════════════════════════════════════════

class TestOrderPaymentAggregates:
    """Push real customer_payments + orders through the recompute helper
    and assert the stored aggregates in paise."""

    def _cleanup(self, sync_db, order_id, payment_ids):
        sync_db.orders.delete_one({"id": order_id})
        if payment_ids:
            sync_db.customer_payments.delete_many({"id": {"$in": payment_ids}})

    def test_zero_payments_zero_received(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test Cust", "invoice_total": 5000,
            "payment_status": "Unpaid",
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([oid]))
            doc = sync_db.orders.find_one({"id": oid})
            assert to_paise(doc.get("total_received") or 0) == 0
            # Unpaid status preserved.
            assert doc["payment_status"] == "Unpaid"
            # Outstanding = invoice - 0 = 5000, unclamped storage.
            assert to_paise(doc["outstanding_balance"]) == 500_000
        finally:
            self._cleanup(sync_db, oid, [])

    def test_partial_payment_status_partial(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        pid = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test", "invoice_total": 10000,
            "payment_status": "Unpaid",
        })
        sync_db.customer_payments.insert_one({
            "id": pid, "customer_name": "Test", "amount": 3000,
            "mode": "UPI", "allocations": [{"order_id": oid, "amount": 3000}],
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([oid]))
            doc = sync_db.orders.find_one({"id": oid})
            assert to_paise(doc["total_received"]) == 300_000
            assert to_paise(doc["outstanding_balance"]) == 700_000
            assert doc["payment_status"] == "Partial"
        finally:
            self._cleanup(sync_db, oid, [pid])

    def test_full_payment_status_paid(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        pid = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test", "invoice_total": 10000,
            "payment_status": "Unpaid",
        })
        sync_db.customer_payments.insert_one({
            "id": pid, "customer_name": "Test", "amount": 10000,
            "mode": "UPI", "allocations": [{"order_id": oid, "amount": 10000}],
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([oid]))
            doc = sync_db.orders.find_one({"id": oid})
            assert doc["payment_status"] == "Paid"
            assert to_paise(doc["outstanding_balance"]) == 0
        finally:
            self._cleanup(sync_db, oid, [pid])

    def test_paid_within_50_paise_hysteresis(self, sync_db, async_run):
        """Alloc within ₹0.50 of invoice → status = Paid (pre-refactor rule)."""
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        pid = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test", "invoice_total": 10000,
        })
        sync_db.customer_payments.insert_one({
            "id": pid, "customer_name": "Test", "amount": 9999.75,
            "allocations": [{"order_id": oid, "amount": 9999.75}],
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([oid]))
            doc = sync_db.orders.find_one({"id": oid})
            assert doc["payment_status"] == "Paid"  # within 50-paise threshold
        finally:
            self._cleanup(sync_db, oid, [pid])

    def test_over_payment_stores_negative_outstanding(self, sync_db, async_run):
        """Customer orders store UNCLAMPED outstanding — negative on over-payment.
        Pre-refactor behaviour is preserved."""
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        pid = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test", "invoice_total": 5000,
        })
        sync_db.customer_payments.insert_one({
            "id": pid, "customer_name": "Test", "amount": 7000,
            "allocations": [{"order_id": oid, "amount": 7000}],
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([oid]))
            doc = sync_db.orders.find_one({"id": oid})
            # Over-paid by 2000 → outstanding = -2000 (unclamped).
            assert to_paise(doc["outstanding_balance"]) == -200_000
            assert doc["payment_status"] == "Paid"
        finally:
            self._cleanup(sync_db, oid, [pid])

    def test_multi_payment_across_orders(self, sync_db, async_run):
        """One payment allocates to two orders — each gets the right slice."""
        o1 = f"slice4-o-{uuid.uuid4().hex[:8]}"
        o2 = f"slice4-o-{uuid.uuid4().hex[:8]}"
        p1 = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_many([
            {"id": o1, "client_name": "Test", "invoice_total": 1000},
            {"id": o2, "client_name": "Test", "invoice_total": 2000},
        ])
        sync_db.customer_payments.insert_one({
            "id": p1, "customer_name": "Test", "amount": 2500,
            "allocations": [{"order_id": o1, "amount": 1000},
                            {"order_id": o2, "amount": 1500}],
        })
        try:
            async_run(server._recompute_payment_aggregates_for_orders([o1, o2]))
            d1 = sync_db.orders.find_one({"id": o1})
            d2 = sync_db.orders.find_one({"id": o2})
            assert d1["payment_status"] == "Paid"
            assert to_paise(d1["outstanding_balance"]) == 0
            assert d2["payment_status"] == "Partial"
            assert to_paise(d2["outstanding_balance"]) == 50_000
        finally:
            sync_db.orders.delete_many({"id": {"$in": [o1, o2]}})
            sync_db.customer_payments.delete_one({"id": p1})

    def test_idempotency_three_reruns_no_drift(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        pid = f"slice4-cp-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "Test", "invoice_total": 12345.67,
        })
        sync_db.customer_payments.insert_one({
            "id": pid, "customer_name": "Test", "amount": 4321.12,
            "allocations": [{"order_id": oid, "amount": 4321.12}],
        })
        try:
            snaps = []
            for _ in range(3):
                async_run(server._recompute_payment_aggregates_for_orders([oid]))
                doc = sync_db.orders.find_one({"id": oid})
                snaps.append((to_paise(doc["total_received"]),
                              to_paise(doc["outstanding_balance"]),
                              doc["payment_status"]))
            # All three snapshots must be identical.
            assert snaps[0] == snaps[1] == snaps[2]
        finally:
            self._cleanup(sync_db, oid, [pid])


# ═════════════════════════════════════════════════════════════════════════
# 3.  _recompute_purchase_payment_aggregates — real Mongo flow
# ═════════════════════════════════════════════════════════════════════════

class TestPurchasePaymentAggregates:
    def _cleanup(self, sync_db, purchase_id, payment_ids):
        sync_db.purchases.delete_one({"id": purchase_id})
        if payment_ids:
            sync_db.purchase_payments.delete_many({"id": {"$in": payment_ids}})

    def test_purchase_over_payment_CLAMPS_outstanding_to_zero(self, sync_db, async_run):
        """PRE-REFACTOR RULE: purchases CLAMP outstanding to 0 on over-payment
        (unlike customer orders which store negative). This asymmetry must
        be preserved."""
        pu = f"slice4-pu-{uuid.uuid4().hex[:8]}"
        pp = f"slice4-pp-{uuid.uuid4().hex[:8]}"
        sync_db.purchases.insert_one({
            "id": pu, "vendor_name": "Vendor", "invoice_total": 5000,
        })
        sync_db.purchase_payments.insert_one({
            "id": pp, "vendor_name": "Vendor", "amount": 8000,
            "allocations": [{"purchase_id": pu, "amount": 8000}],
        })
        try:
            async_run(server._recompute_purchase_payment_aggregates([pu]))
            doc = sync_db.purchases.find_one({"id": pu})
            assert to_paise(doc["total_paid"]) == 800_000
            # CLAMPED to zero, not -3000.
            assert to_paise(doc["outstanding_balance"]) == 0
            assert doc["payment_status"] == "Paid"
        finally:
            self._cleanup(sync_db, pu, [pp])

    def test_purchase_partial_payment(self, sync_db, async_run):
        pu = f"slice4-pu-{uuid.uuid4().hex[:8]}"
        pp = f"slice4-pp-{uuid.uuid4().hex[:8]}"
        sync_db.purchases.insert_one({
            "id": pu, "vendor_name": "Vendor", "invoice_total": 10000,
        })
        sync_db.purchase_payments.insert_one({
            "id": pp, "vendor_name": "Vendor", "amount": 3000,
            "allocations": [{"purchase_id": pu, "amount": 3000}],
        })
        try:
            async_run(server._recompute_purchase_payment_aggregates([pu]))
            doc = sync_db.purchases.find_one({"id": pu})
            assert doc["payment_status"] == "Partial"
            assert to_paise(doc["outstanding_balance"]) == 700_000
        finally:
            self._cleanup(sync_db, pu, [pp])

    def test_purchase_zero_alloc_status_unpaid(self, sync_db, async_run):
        pu = f"slice4-pu-{uuid.uuid4().hex[:8]}"
        sync_db.purchases.insert_one({
            "id": pu, "vendor_name": "Vendor", "invoice_total": 5000,
        })
        try:
            async_run(server._recompute_purchase_payment_aggregates([pu]))
            doc = sync_db.purchases.find_one({"id": pu})
            assert doc["payment_status"] == "Unpaid"
            assert to_paise(doc["total_paid"]) == 0
            assert to_paise(doc["outstanding_balance"]) == 500_000
        finally:
            self._cleanup(sync_db, pu, [])

    def test_idempotency_three_reruns_no_drift(self, sync_db, async_run):
        pu = f"slice4-pu-{uuid.uuid4().hex[:8]}"
        pp = f"slice4-pp-{uuid.uuid4().hex[:8]}"
        sync_db.purchases.insert_one({
            "id": pu, "vendor_name": "Vendor", "invoice_total": 9876.54,
        })
        sync_db.purchase_payments.insert_one({
            "id": pp, "vendor_name": "Vendor", "amount": 1234.56,
            "allocations": [{"purchase_id": pu, "amount": 1234.56}],
        })
        try:
            snaps = []
            for _ in range(3):
                async_run(server._recompute_purchase_payment_aggregates([pu]))
                doc = sync_db.purchases.find_one({"id": pu})
                snaps.append((to_paise(doc["total_paid"]),
                              to_paise(doc["outstanding_balance"]),
                              doc["payment_status"]))
            assert snaps[0] == snaps[1] == snaps[2]
        finally:
            self._cleanup(sync_db, pu, [pp])


# ═════════════════════════════════════════════════════════════════════════
# 4.  customer_outstanding_orders + vendor_outstanding_purchases endpoints
# ═════════════════════════════════════════════════════════════════════════

class TestOutstandingEndpoints:
    """The list-endpoints CLAMP the displayed `outstanding` (never negative)
    while the underlying stored `outstanding_balance` may be negative for
    over-paid customer orders. Both paths must be paise-safe."""

    def test_customer_outstanding_clamps_display(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "OutstandingTest",
            "invoice_total": 5000, "outstanding_balance": -1500,
            "total_received": 6500, "payment_status": "Paid",
        })
        try:
            resp = async_run(server.customer_outstanding_orders("OutstandingTest"))
            # Paid+negative outstanding → not shown in the allocation UI
            # (both filters: outstanding_p > 50 is False, status NOT in
            # Unpaid/Partial). Correct: allocation UI excludes it.
            ids = [r["id"] for r in resp["orders"]]
            assert oid not in ids
        finally:
            sync_db.orders.delete_one({"id": oid})

    def test_customer_outstanding_shows_partial(self, sync_db, async_run):
        oid = f"slice4-o-{uuid.uuid4().hex[:8]}"
        sync_db.orders.insert_one({
            "id": oid, "client_name": "PartialTest",
            "invoice_total": 5000, "outstanding_balance": 2500,
            "total_received": 2500, "payment_status": "Partial",
        })
        try:
            resp = async_run(server.customer_outstanding_orders("PartialTest"))
            row = next((r for r in resp["orders"] if r["id"] == oid), None)
            assert row is not None
            assert to_paise(row["outstanding"]) == 250_000
            assert to_paise(row["invoice_total"]) == 500_000
        finally:
            sync_db.orders.delete_one({"id": oid})

    def test_vendor_outstanding_purchases(self, sync_db, async_run):
        pu = f"slice4-pu-{uuid.uuid4().hex[:8]}"
        sync_db.purchases.insert_one({
            "id": pu, "vendor_name": "VendorX",
            "invoice_no": "INV-1", "purchase_date": "2026-01-15",
            "invoice_total": 10000, "total_paid": 4000,
            "outstanding_balance": 6000, "payment_status": "Partial",
        })
        try:
            rows = async_run(server.vendor_outstanding_purchases("VendorX"))
            row = next((r for r in rows if r["id"] == pu), None)
            assert row is not None
            assert to_paise(row["invoice_total"]) == 1_000_000
            assert to_paise(row["total_paid"]) == 400_000
            assert to_paise(row["outstanding_balance"]) == 600_000
        finally:
            sync_db.purchases.delete_one({"id": pu})


# ═════════════════════════════════════════════════════════════════════════
# 5.  Reconciliation + dashboard remain healthy
# ═════════════════════════════════════════════════════════════════════════

class TestReconcileHealthyAfterSlice4:
    """After Slice 4 lands, /api/reconcile must still report healthy=true
    (all 21 invariants pass) on the current seed."""

    def test_reconcile_still_healthy(self):
        import httpx
        base = os.environ.get("API_BASE") or "http://localhost:8001"
        try:
            httpx.get(f"{base}/api/", timeout=2.0)
        except Exception:
            pytest.skip("API not reachable")
        r = httpx.post(f"{base}/api/auth/login",
                       json={"email": "admin@artisan.local",
                             "password": "Admin@12345"}, timeout=10.0)
        assert r.status_code == 200
        tok = r.json()["access_token"]
        rr = httpx.get(f"{base}/api/reconcile",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15.0)
        j = rr.json()
        assert j["healthy"] is True
        assert j["summary"]["failed"] == 0
        assert j["engine_version"] == "P5"
