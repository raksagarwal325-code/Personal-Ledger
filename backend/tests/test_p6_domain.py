"""Phase 6 — Slice 1 unit + property + mutation-protection tests for
`backend/domain.py`. Pure-function tests — no Mongo, no HTTP, no fixtures
that touch the app. Runs in isolation, deterministically, in any order.

Rules being pinned (per Phase 6 pre-implementation report + user
adjustments):
  * All new helpers are pure — same inputs → same outputs.
  * All new helpers are non-mutating — deepcopy(input) equals input after.
  * `SETTLED_THRESHOLD_PAISE == 50` (party ledger UX threshold).
  * Property: for every order,
        estimated_operating_revenue = realized_operating_revenue + unrealized_revenue
        estimated_net_profit        = realized_net_profit + unrealized_net_profit
    (checked in paise, exact equality — not tolerance-based.)
  * Property: for every purchase,
        outstanding = max(0, invoice_total - allocated)
  * CI guard: production files (excluding domain.py + tests/) must not
    exceed a hard baseline of banned inline patterns
    (float(x.get("amount")…), round(…), `"reversed":{"$ne":True}`,
    `"source":{"$ne":"legacy_shim"}`). Baseline shrinks per slice.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

import domain as D


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def synth_order_full():
    """Synthetic deterministic order — fully shipped (ratio = 1.0)."""
    return {
        "id": "ord-synth-1",
        "status": "Fully Shipped",
        "client_name": "Test Customer",
        "invoice_total": 12500,
        "packing_cost": 200,
        "packing_recovery": 300,
        "tax_applicable": True,
        "tax_percent": 12,
        "tax_amount_manual": False,
        "items": [
            {"id": "i1", "qty": 10, "rate": 1000,
             "factory_complete": 400, "factory_glass": 100, "factory_fitting": 50,
             "outside_complete": 0, "outside_glass": 0, "outside_fitting": 0},
        ],
        "shipments": [
            {"id": "s1", "boxes_shipped": 2, "freight_charged": 500, "freight_paid": 300,
             "items": [{"order_item_id": "i1", "qty": 10}]},
        ],
        "other_revenue": [{"amount": 100}],
        "other_expense": [{"amount": 50}],
    }


@pytest.fixture
def synth_order_partial():
    """40% shipped."""
    return {
        "id": "ord-synth-2",
        "status": "Partially Shipped",
        "invoice_total": 0,
        "packing_cost": 200,
        "packing_recovery": 100,
        "tax_applicable": False,
        "items": [
            {"id": "i1", "qty": 10, "rate": 1000,
             "factory_complete": 300, "factory_glass": 0, "factory_fitting": 0,
             "outside_complete": 200, "outside_glass": 0, "outside_fitting": 0},
        ],
        "shipments": [
            {"id": "s1", "boxes_shipped": 1, "freight_charged": 200, "freight_paid": 150,
             "items": [{"order_item_id": "i1", "qty": 4}]},
        ],
    }


@pytest.fixture
def synth_order_no_ship():
    """Confirmed but zero shipments."""
    return {
        "id": "ord-synth-3",
        "status": "Confirmed",
        "invoice_total": 0,
        "items": [
            {"id": "i1", "qty": 5, "rate": 500,
             "factory_complete": 100, "outside_complete": 100},
        ],
        "shipments": [],
    }


@pytest.fixture
def synth_order_cancelled():
    return {"id": "ord-x", "status": "Cancelled", "items": [], "shipments": []}


@pytest.fixture
def prod_style_orders(synth_order_full, synth_order_partial, synth_order_no_ship):
    """Small production-style fixture — mimics the seed shape."""
    return [synth_order_full, synth_order_partial, synth_order_no_ship]


@pytest.fixture
def synth_cust_pays():
    return [
        {"id": "cp1", "amount": 5000, "mode": "UPI", "unallocated": 0,
         "allocations": [{"order_id": "ord-synth-1", "amount": 5000}]},
        {"id": "cp2", "amount": 2000, "mode": "Cash", "unallocated": 500,
         "allocations": [{"order_id": "ord-synth-2", "amount": 1500}]},
        # voided → must be excluded everywhere
        {"id": "cp3", "amount": 999, "voided": True, "mode": "UPI",
         "unallocated": 0, "allocations": []},
    ]


@pytest.fixture
def synth_purchase_pays():
    return [
        {"id": "pp1", "amount": 3000, "mode": "ICICI",
         "allocations": [{"purchase_id": "pu1", "amount": 3000}]},
        {"id": "pp2", "amount": 1200, "mode": "Cash",
         "allocations": [{"purchase_id": "pu1", "amount": 200}]},
        {"id": "pp3", "amount": 1, "reversed": True, "mode": "UPI",
         "allocations": []},
    ]


@pytest.fixture
def synth_cb_entries():
    return [
        {"id": "cb1", "kind": "general_income", "amount": 400, "mode": "Cash",
         "account_id": "acc-1"},
        {"id": "cb2", "kind": "general_expense", "amount": 150, "mode": "UPI",
         "account_id": "acc-1"},
        # legacy_shim → excluded
        {"id": "cb3", "kind": "general_income", "amount": 999,
         "source": "legacy_shim"},
        # reversed → excluded
        {"id": "cb4", "kind": "general_expense", "amount": 111, "reversed": True},
        # transfer → excluded
        {"id": "cb5", "kind": "transfer", "amount": 5000},
        # migrated → excluded
        {"id": "cb6", "kind": "transfer", "amount": 6000,
         "migrated_to_transfer_id": "t-x"},
    ]


@pytest.fixture
def synth_purchases():
    return [
        {"id": "pu1", "invoice_total": 4000,
         "items": [{"qty": 4, "rate": 900}], "packing_total": 200, "freight_total": 200},
    ]


@pytest.fixture
def synth_transfers():
    return [
        {"id": "t1", "kind": "account_to_account", "amount": 2000,
         "from": {"account_id": "acc-1"}, "to": {"account_id": "acc-2"}},
        {"id": "t2", "kind": "rakshit_to_ff", "amount": 1500,
         "from": {"account_id": "acc-1"}, "to": {"party_id": "system_fathers_firm"}},
        {"id": "t3", "kind": "ff_to_rakshit", "amount": 500,
         "from": {"party_id": "system_fathers_firm"}, "to": {"account_id": "acc-2"}},
        {"id": "t4", "kind": "account_to_account", "amount": 999,
         "from": {"account_id": "acc-1"}, "to": {"account_id": "acc-2"},
         "status": "reversed"},
    ]


# ─── 1. Money primitives (already exist — pin behaviour) ───────────────────

class TestMoneyPrimitives:
    def test_to_paise_int_and_float(self):
        assert D.to_paise(1) == 100
        assert D.to_paise(1.23) == 123
        assert D.to_paise("1.235") == 124   # HALF_UP
        assert D.to_paise("1.234") == 123

    def test_to_paise_none_empty_junk_returns_zero(self):
        assert D.to_paise(None) == 0
        assert D.to_paise("") == 0
        assert D.to_paise("abc") == 0

    def test_from_paise_roundtrip(self):
        for v in [0, 1, 100, 12345, 9999999]:
            assert D.to_paise(D.from_paise(v)) == v

    def test_money_eq_uses_tolerance(self):
        assert D.money_eq(1000, 1000)
        assert D.money_eq(1000, 1001)  # within 1 paise
        assert not D.money_eq(1000, 1002)

    def test_settled_threshold_constant(self):
        # Adjustment §5 — must remain 50 paise (₹0.50). Do not unify with
        # TOLERANCE_PAISE.
        assert D.SETTLED_THRESHOLD_PAISE == 50
        assert D.TOLERANCE_PAISE == 1


# ─── 2. Active-record filters ──────────────────────────────────────────────

class TestActiveFilters:
    def test_order_active(self):
        assert D.is_order_active({"status": "Confirmed"})
        assert D.is_order_active({"status": "Fully Shipped"})
        assert not D.is_order_active({"status": "Cancelled"})
        assert not D.is_order_active({"status": "cancelled"})

    def test_customer_payment_active(self):
        assert D.is_customer_payment_active({})
        assert not D.is_customer_payment_active({"voided": True})
        assert not D.is_customer_payment_active({"reversed": True})

    def test_purchase_payment_active(self):
        assert D.is_purchase_payment_active({})
        assert not D.is_purchase_payment_active({"voided": True})
        assert not D.is_purchase_payment_active({"reversed": True})

    def test_cash_book_entry_canonical(self):
        assert D.is_cash_book_entry_canonical({"kind": "general_income"})
        assert not D.is_cash_book_entry_canonical({"source": "legacy_shim"})
        assert not D.is_cash_book_entry_canonical({"reversed": True})
        assert not D.is_cash_book_entry_canonical({"migrated_to_transfer_id": "x"})

    def test_transfer_active(self):
        assert D.is_transfer_active({})
        assert D.is_transfer_active({"status": "active"})
        assert not D.is_transfer_active({"status": "reversed"})

    def test_account_active(self):
        assert D.is_account_active({})
        assert not D.is_account_active({"archived": True})


# ─── 3. KPI sums ───────────────────────────────────────────────────────────

class TestKpiSums:
    def test_sum_received_kpi(self, synth_cust_pays, synth_cb_entries):
        # cp1 (5000) + cp2 (2000) + cb1 (400 general_income) = 7400 rupees
        # cp3 excluded (voided), cb2/cb4/cb5/cb6 excluded, cb3 excluded (shim)
        assert D.sum_received_kpi(synth_cust_pays, synth_cb_entries) == 7400 * 100

    def test_sum_paid_kpi(self, synth_purchase_pays, synth_cb_entries):
        # pp1 (3000) + pp2 (1200) + cb2 (150 general_expense) = 4350 rupees
        assert D.sum_paid_kpi(synth_purchase_pays, synth_cb_entries) == 4350 * 100

    def test_sum_mode_totals(self, synth_cust_pays, synth_purchase_pays, synth_cb_entries):
        modes = D.sum_mode_totals(synth_cust_pays, synth_purchase_pays, synth_cb_entries)
        assert modes["UPI"]["received_paise"] == 5000 * 100
        assert modes["Cash"]["received_paise"] == 2000 * 100 + 400 * 100
        assert modes["ICICI"]["paid_paise"] == 3000 * 100
        assert modes["Cash"]["paid_paise"] == 1200 * 100
        assert modes["UPI"]["paid_paise"] == 150 * 100
        # Voided/reversed excluded from every bucket
        assert 999 * 100 not in [v["received_paise"] for v in modes.values()]

    def test_sum_allocations_to_order(self, synth_cust_pays):
        assert D.sum_allocations_to_order(synth_cust_pays, "ord-synth-1") == 5000 * 100
        assert D.sum_allocations_to_order(synth_cust_pays, "ord-synth-2") == 1500 * 100
        assert D.sum_allocations_to_order(synth_cust_pays, "nonexistent") == 0

    def test_sum_allocations_to_purchase(self, synth_purchase_pays):
        assert D.sum_allocations_to_purchase(synth_purchase_pays, "pu1") == 3200 * 100


# ─── 4. Order helpers ──────────────────────────────────────────────────────

class TestOrderHelpers:
    def test_shipped_ratio_full(self, synth_order_full):
        r = D.order_shipped_ratio_per_item(synth_order_full)
        assert r["i1"] == 1  # 10/10

    def test_shipped_ratio_partial(self, synth_order_partial):
        r = D.order_shipped_ratio_per_item(synth_order_partial)
        # 4/10
        assert float(r["i1"]) == pytest.approx(0.4)

    def test_shipped_ratio_zero(self, synth_order_no_ship):
        r = D.order_shipped_ratio_per_item(synth_order_no_ship)
        assert float(r["i1"]) == 0.0

    def test_realized_full_shipment(self, synth_order_full):
        real = D.order_realized_amounts(synth_order_full)
        # product_sales = 10*1000 = 10000 → 1_000_000 paise; ratio = 1
        assert real["shipped_product_sales_paise"] == 10000 * 100
        # freight_charged 500, packing_recovery 300, other_revenue 100
        assert real["operating_revenue_paise"] == (10000 + 500 + 300 + 100) * 100
        # factory 400+100+50 = 550, outside 0, packing_cost 200, freight_paid 300, other_expense 50
        assert real["total_cost_paise"] == (550 + 200 + 300 + 50) * 100
        # tax: base = op_rev - other_expense = 10900 - 50 = 10850; 12% = 1302
        assert real["tax_amount_paise"] == 1302 * 100

    def test_realized_zero_shipment(self, synth_order_no_ship):
        real = D.order_realized_amounts(synth_order_no_ship)
        assert real["shipped_product_sales_paise"] == 0
        assert real["factory_cost_realized_paise"] == 0

    def test_estimated_matches_full_shipment(self, synth_order_full):
        real = D.order_realized_amounts(synth_order_full)
        est = D.order_estimated_amounts(synth_order_full)
        # For a fully-shipped order, product sales should equal.
        assert real["shipped_product_sales_paise"] == est["estimated_product_sales_paise"]

    def test_unrealized_zero_on_full(self, synth_order_full):
        u = D.order_unrealized(synth_order_full)
        # Full shipment ⇒ zero unrealized revenue.
        assert u["unrealized_revenue_paise"] == 0

    def test_unrealized_positive_on_partial(self, synth_order_partial):
        u = D.order_unrealized(synth_order_partial)
        assert u["unrealized_revenue_paise"] > 0

    def test_outstanding_from_alloc(self, synth_order_full):
        # invoice_total 12500 → paise 1_250_000. allocated 500_000. outstanding 750_000.
        assert D.order_outstanding_from_alloc(synth_order_full, 500_000) == 750_000
        # Over-allocation clamps to 0.
        assert D.order_outstanding_from_alloc(synth_order_full, 99_999_999) == 0


# ─── 5. PROPERTY tests (per adjustment §8) ─────────────────────────────────

class TestOrderIdentityProperties:
    """For every order: estimated == realized + unrealized. Exact in paise."""

    @pytest.mark.parametrize("fixture_name",
                             ["synth_order_full", "synth_order_partial",
                              "synth_order_no_ship"])
    def test_estimated_eq_realized_plus_unrealized_revenue(self, request, fixture_name):
        o = request.getfixturevalue(fixture_name)
        real = D.order_realized_amounts(o)
        est = D.order_estimated_amounts(o)
        u = D.order_unrealized(o)
        assert est["estimated_operating_revenue_paise"] == (
            real["operating_revenue_paise"] + u["unrealized_revenue_paise"]
        )

    @pytest.mark.parametrize("fixture_name",
                             ["synth_order_full", "synth_order_partial",
                              "synth_order_no_ship"])
    def test_estimated_eq_realized_plus_unrealized_profit(self, request, fixture_name):
        o = request.getfixturevalue(fixture_name)
        real = D.order_realized_amounts(o)
        est = D.order_estimated_amounts(o)
        u = D.order_unrealized(o)
        assert est["estimated_net_profit_paise"] == (
            real["net_profit_paise"] + u["unrealized_net_profit_paise"]
        )


class TestPurchaseIdentityProperties:
    def test_outstanding_eq_total_minus_allocated(self, synth_purchases,
                                                  synth_purchase_pays):
        for p in synth_purchases:
            alloc = D.sum_allocations_to_purchase(synth_purchase_pays, p["id"])
            outstanding = D.purchase_outstanding_from_alloc(p, alloc)
            assert outstanding == max(0, D.to_paise(p.get("invoice_total")) - alloc)


# ─── 6. Mutation protection (per adjustment §9) ────────────────────────────

class TestMutationProtection:
    """Every domain helper receives dicts/lists — none of them must mutate
    caller-owned objects. Compared with deepcopy."""

    def _assert_pure(self, fn, args=(), kwargs=None):
        kwargs = kwargs or {}
        args_copy = copy.deepcopy(args)
        kwargs_copy = copy.deepcopy(kwargs)
        fn(*args, **kwargs)
        assert args == args_copy, f"{fn.__name__} mutated a positional argument"
        assert kwargs == kwargs_copy, f"{fn.__name__} mutated a kw argument"

    def test_order_realized_amounts_non_mutating(self, synth_order_partial):
        self._assert_pure(D.order_realized_amounts, (synth_order_partial,))

    def test_order_estimated_amounts_non_mutating(self, synth_order_partial):
        self._assert_pure(D.order_estimated_amounts, (synth_order_partial,))

    def test_order_unrealized_non_mutating(self, synth_order_partial):
        self._assert_pure(D.order_unrealized, (synth_order_partial,))

    def test_order_shipped_ratio_non_mutating(self, synth_order_partial):
        self._assert_pure(D.order_shipped_ratio_per_item, (synth_order_partial,))

    def test_purchase_realized_non_mutating(self, synth_purchases):
        self._assert_pure(D.purchase_realized_amounts, (synth_purchases[0],))

    def test_sum_allocations_non_mutating(self, synth_cust_pays):
        self._assert_pure(D.sum_allocations_to_order,
                          (synth_cust_pays, "ord-synth-1"))

    def test_sum_received_non_mutating(self, synth_cust_pays, synth_cb_entries):
        self._assert_pure(D.sum_received_kpi,
                          (synth_cust_pays, synth_cb_entries))

    def test_sum_mode_totals_non_mutating(self, synth_cust_pays,
                                          synth_purchase_pays, synth_cb_entries):
        self._assert_pure(D.sum_mode_totals,
                          (synth_cust_pays, synth_purchase_pays, synth_cb_entries))

    def test_build_dashboard_kpis_non_mutating(self, prod_style_orders,
                                               synth_cust_pays,
                                               synth_purchase_pays,
                                               synth_cb_entries,
                                               synth_purchases,
                                               synth_transfers):
        self._assert_pure(D.build_dashboard_kpis, (),
                          {"orders": prod_style_orders,
                           "cust_pays": synth_cust_pays,
                           "purchase_pays": synth_purchase_pays,
                           "cb_entries": synth_cb_entries,
                           "purchases": synth_purchases,
                           "transfers": synth_transfers})

    def test_account_balance_paise_non_mutating(self, synth_cust_pays,
                                                synth_purchase_pays,
                                                synth_cb_entries,
                                                synth_transfers):
        self._assert_pure(D.account_balance_paise, (),
                          {"opening_paise": 10_000,
                           "cust_pays": synth_cust_pays,
                           "purchase_pays": synth_purchase_pays,
                           "cb_entries": synth_cb_entries,
                           "transfers": synth_transfers,
                           "account_id": "acc-1"})


# ─── 7. Determinism (per adjustment §2) ────────────────────────────────────

class TestDeterminism:
    """Same inputs → identical outputs across independent calls, order-insensitive
    where documented."""

    def test_build_dashboard_kpis_repeatable(self, prod_style_orders,
                                             synth_cust_pays,
                                             synth_purchase_pays,
                                             synth_cb_entries,
                                             synth_purchases,
                                             synth_transfers):
        kw = dict(orders=prod_style_orders,
                  cust_pays=synth_cust_pays,
                  purchase_pays=synth_purchase_pays,
                  cb_entries=synth_cb_entries,
                  purchases=synth_purchases,
                  transfers=synth_transfers)
        first = D.build_dashboard_kpis(**kw)
        second = D.build_dashboard_kpis(**kw)
        assert first == second

    def test_order_realized_amounts_repeatable(self, synth_order_partial):
        a = D.order_realized_amounts(synth_order_partial)
        b = D.order_realized_amounts(synth_order_partial)
        assert a == b


# ─── 8. Party ledger + transfer helpers ────────────────────────────────────

class TestPartyLedgerHelpers:
    def test_party_status_from_paise_settled_boundary(self):
        assert D.party_status_from_paise(0) == "Settled"
        assert D.party_status_from_paise(50) == "Settled"        # exactly on threshold
        assert D.party_status_from_paise(-50) == "Settled"
        assert D.party_status_from_paise(51) == "You Pay"
        assert D.party_status_from_paise(-51) == "You Receive"

    def test_party_delta_for_row_fixed_categories(self):
        # sale_invoice always negative (customer owes you → decreases you-pay).
        assert D.party_delta_for_row("sale_invoice", 10_000) == -10_000
        assert D.party_delta_for_row("customer_payment", 10_000) == 10_000
        assert D.party_delta_for_row("purchase", 10_000) == 10_000
        assert D.party_delta_for_row("vendor_payment", 10_000) == -10_000

    def test_party_delta_for_row_directional(self):
        assert D.party_delta_for_row("transfer", 5000, "you_pay") == 5000
        assert D.party_delta_for_row("transfer", 5000, "you_receive") == -5000
        # Default direction = you_pay
        assert D.party_delta_for_row("transfer", 5000) == 5000

    def test_party_delta_takes_absolute_value(self):
        # Sign is decided by category/direction, magnitude is absolute.
        assert D.party_delta_for_row("customer_payment", -10_000) == 10_000


class TestTransferHelpers:
    def test_apply_transfer_a2a(self, synth_transfers):
        t = synth_transfers[0]  # acc-1 → acc-2 for 2000
        assert D.apply_transfer_to_account_balance_paise(t, "acc-1") == -2000 * 100
        assert D.apply_transfer_to_account_balance_paise(t, "acc-2") == +2000 * 100
        assert D.apply_transfer_to_account_balance_paise(t, "acc-3") == 0

    def test_apply_transfer_ignores_reversed(self, synth_transfers):
        reversed_t = synth_transfers[3]
        assert D.apply_transfer_to_account_balance_paise(reversed_t, "acc-1") == 0

    def test_ff_delta_signs(self, synth_transfers):
        # +1500 (rakshit_to_ff) − 500 (ff_to_rakshit) = +1000 rupees = 100_000 paise
        # The reversed a2a (t4) doesn't affect FF.
        assert D.sum_ff_settlement_delta_from_transfers_paise(synth_transfers) == 100_000

    def test_account_balance_composition(self, synth_cust_pays,
                                         synth_purchase_pays,
                                         synth_cb_entries,
                                         synth_transfers):
        # For acc-1 (nothing tagged in cust_pays/purchase_pays fixtures):
        #   opening 10_000_00
        #   + cb_entries net for acc-1: cb1 (+400) - cb2 (-150) = +250 → +25_000 paise
        #   + transfers: t1 (−2000 = −200_000 p), t2 (from acc-1 for 1500 = −150_000 p)
        # Total = 1_000_000 + 25_000 − 200_000 − 150_000 = 675_000 paise
        bal = D.account_balance_paise(
            opening_paise=1_000_000,
            cust_pays=synth_cust_pays,
            purchase_pays=synth_purchase_pays,
            cb_entries=synth_cb_entries,
            transfers=synth_transfers,
            account_id="acc-1",
        )
        assert bal == 675_000


# ─── 9. Composable dashboard builders ──────────────────────────────────────

class TestComposableBuilders:
    def test_compute_receipts(self, synth_cust_pays, synth_cb_entries):
        r = D.compute_receipts(synth_cust_pays, synth_cb_entries)
        # received: cp1 (5000) + cp2 (2000) + cb1 (400) = 7400 → 740_000
        assert r["received_paise"] == 740_000
        # advances: cp2 has unallocated 500 → 50_000
        assert r["customer_advances_paise"] == 50_000

    def test_compute_payments(self, synth_purchase_pays, synth_cb_entries):
        p = D.compute_payments(synth_purchase_pays, synth_cb_entries)
        assert p["paid_paise"] == 435_000  # 3000+1200+150 rupees

    def test_compute_order_metrics(self, prod_style_orders, synth_cust_pays):
        m = D.compute_order_metrics(prod_style_orders, synth_cust_pays)
        # order_count = 3 (none cancelled here).
        assert m["order_count"] == 3
        # Every field must be a paise int, not a float.
        for k, v in m.items():
            if k.endswith("_paise"):
                assert isinstance(v, int), f"{k} is {type(v).__name__}, not int"

    def test_compute_purchase_metrics(self, synth_purchases, synth_purchase_pays):
        m = D.compute_purchase_metrics(synth_purchases, synth_purchase_pays)
        assert m["purchase_value_paise"] == 400_000
        assert m["purchase_paid_paise"] == 420_000  # 3000 + 1200 (reversed excluded)
        # outstanding for pu1: invoice_total 4000 - allocated 3200 = 800 → 80_000 paise
        assert m["purchase_outstanding_paise"] == 80_000

    def test_compute_transfer_metrics(self, synth_transfers):
        m = D.compute_transfer_metrics(synth_transfers)
        # 3 active transfers (t4 reversed).
        assert m["transfer_count_active"] == 3
        assert m["ff_settlement_delta_paise"] == 100_000

    def test_compute_party_metrics(self, synth_cust_pays, synth_purchase_pays):
        m = D.compute_party_metrics(synth_cust_pays, synth_purchase_pays)
        assert m["customer_advances_paise"] == 50_000  # cp2 unallocated

    def test_build_dashboard_kpis_contains_all_sections(self, prod_style_orders,
                                                       synth_cust_pays,
                                                       synth_purchase_pays,
                                                       synth_cb_entries,
                                                       synth_purchases,
                                                       synth_transfers):
        k = D.build_dashboard_kpis(orders=prod_style_orders,
                                   cust_pays=synth_cust_pays,
                                   purchase_pays=synth_purchase_pays,
                                   cb_entries=synth_cb_entries,
                                   purchases=synth_purchases,
                                   transfers=synth_transfers)
        expected_keys = {
            # order block
            "operating_revenue_paise", "total_cost_paise", "net_profit_paise",
            "invoice_value_paise", "gst_collected_paise",
            "estimated_revenue_paise", "estimated_total_cost_paise",
            "estimated_net_profit_paise",
            "unrealized_revenue_paise", "unrealized_net_profit_paise",
            "outstanding_receivable_paise", "order_count",
            "boxes_used", "boxes_shipped",
            "freight_charged_paise", "freight_paid_paise", "packing_cost_paise",
            # purchase block
            "purchase_value_paise", "purchase_paid_paise",
            "purchase_outstanding_paise", "purchase_count",
            # receipts / payments
            "received_paise", "paid_paise",
            # transfers
            "ff_settlement_delta_paise", "transfer_count_active",
            # party
            "customer_advances_paise",
            # modes
            "modes_paise",
        }
        missing = expected_keys - set(k.keys())
        assert not missing, f"build_dashboard_kpis missing: {missing}"


# ─── 10. Determinism across list ordering ──────────────────────────────────

class TestOrderInsensitive:
    def test_sum_received_order_insensitive(self, synth_cust_pays, synth_cb_entries):
        a = D.sum_received_kpi(synth_cust_pays, synth_cb_entries)
        b = D.sum_received_kpi(list(reversed(synth_cust_pays)),
                               list(reversed(synth_cb_entries)))
        assert a == b


# ═════════════════════════════════════════════════════════════════════════
# CI GUARD (adjustment §10) — grep-baseline that must decrease per slice.
# ═════════════════════════════════════════════════════════════════════════

# Snapshot baseline shrinks per slice. Any PR that INCREASES these counts
# is rejected here. History:
#   Slice 1 (initial):  70 / 67 / 3 / 5
#   Slice 2 (dashboard + dashboard/breakdown consolidation):
#                       56 / 67 / 1 / 3  — removed 14 float(x.get(*amount*)),
#                       2 reversed:$ne, 2 source:$ne_legacy_shim.
CI_GUARD_BASELINE = {
    "float_amount_get":        56,
    "round_calls":             67,
    "reversed_ne_true":         1,
    "source_ne_legacy_shim":    3,
}

_BACKEND_DIR = Path(__file__).resolve().parents[1]

_BANNED_PATTERNS = {
    "float_amount_get":     re.compile(r"float\(.*\.get\(.*amount"),
    "round_calls":          re.compile(r"\bround\("),
    "reversed_ne_true":     re.compile(r'"reversed"\s*:\s*\{\s*"\$ne"\s*:\s*True'),
    "source_ne_legacy_shim": re.compile(
        r'"source"\s*:\s*\{\s*"\$ne"\s*:\s*"legacy_shim"'),
}

# domain.py is where these patterns are ALLOWED to live. tests/ are excluded.
_ALLOWED_FILES = {"domain.py"}


def _count_pattern(pattern: re.Pattern) -> int:
    total = 0
    for f in _BACKEND_DIR.glob("*.py"):
        if f.name in _ALLOWED_FILES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        total += sum(1 for _ in pattern.finditer(text))
    return total


class TestCIGuard:
    """Baseline-shrinking gate. Rejects new occurrences of banned inline
    patterns outside `domain.py`. Baseline shrinks slice-by-slice."""

    @pytest.mark.parametrize("name", list(CI_GUARD_BASELINE.keys()))
    def test_count_does_not_exceed_baseline(self, name):
        actual = _count_pattern(_BANNED_PATTERNS[name])
        baseline = CI_GUARD_BASELINE[name]
        assert actual <= baseline, (
            f"CI guard: pattern '{name}' has {actual} occurrences in "
            f"production files (baseline was {baseline}). Add the new "
            f"logic to `domain.py` instead."
        )

    def test_domain_module_has_no_forbidden_patterns_removed(self):
        # Sanity: domain.py should CONTAIN some of these patterns (it's
        # the sanctioned location). We assert to_paise/from_paise exist.
        assert hasattr(D, "to_paise")
        assert hasattr(D, "from_paise")
        assert hasattr(D, "TOLERANCE_PAISE")
        assert hasattr(D, "SETTLED_THRESHOLD_PAISE")
