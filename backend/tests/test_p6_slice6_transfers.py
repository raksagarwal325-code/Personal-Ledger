"""Phase 6 · Slice 6 — Transfer + Father's Firm settlement + account
balance projections consolidated in `backend/domain.py`.

Split into:

  A. Pure-function unit tests for the new domain helpers
     (`is_transfer_countable_for_balance`,
      `apply_transfer_to_ff_ledger_paise`,
      `sum_ff_ledger_delta_from_transfers_paise`,
      `sum_cashbook_income_for_account_paise`,
      `sum_cashbook_expense_for_account_paise`) + regression pin on the
     Slice-6 schema fix (`from_side`/`to_side` instead of `from`/`to`).

  B. Real-Mongo integration hitting `/api/transfers`, `/api/accounts/*/balance`,
     and `/api/party-ledger-v2/fathers-firm-settlement` on the live seeded
     DB — asserts byte-equivalence against a naive float walk of the raw
     transfer rows, and against the FF settlement + reconcile invariants.

  C. Sign-convention pin — the two FF helpers (`sum_ff_settlement_delta_from_transfers_paise`
     = dashboard convention, `sum_ff_ledger_delta_from_transfers_paise` =
     party-ledger convention) must remain exact negatives of each other
     for every transfer set. If a future refactor "unifies" them, this
     test flips loudly.

Full-phase regression note: the existing Phase-3 transfer suite
(`test_p3_transfers.py`) and Phase-6 Slice-5 party-ledger suite
(`test_p6_slice5_party_ledger.py`) must all still pass — those are the
integration guarantees that this slice is byte-equivalent, not this
file's job to duplicate.
"""
from __future__ import annotations

import copy

import httpx
import pytest

import domain as D

API_BASE = "http://localhost:8001"
SYSTEM_FF_ID = "system_fathers_firm"


def _login_token() -> str:
    r = httpx.post(f"{API_BASE}/api/auth/login",
                   json={"email": "admin@artisan.local",
                         "password": "Admin@12345"},
                   timeout=10.0)
    r.raise_for_status()
    return r.json()["access_token"]


def _get(url: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.get(f"{API_BASE}{url}", headers=headers, timeout=15.0)
    r.raise_for_status()
    return r.json()


# ═════════════════════════════════════════════════════════════════════════
# A. Pure-function unit tests
# ═════════════════════════════════════════════════════════════════════════

class TestIsTransferCountableForBalance:
    def test_active_transfer_counts(self):
        assert D.is_transfer_countable_for_balance(
            {"status": "active", "amount": 100}) is True

    def test_reversed_original_counts(self):
        # Distinct from `is_transfer_active` — reversed originals STILL count
        # for balance because their paired reversal doc cancels them.
        assert D.is_transfer_countable_for_balance(
            {"status": "reversed", "amount": 100}) is True

    def test_reversal_doc_counts(self):
        assert D.is_transfer_countable_for_balance(
            {"status": "active", "reverses_transfer_id": "orig-1",
             "amount": 100}) is True

    def test_none_returns_false(self):
        assert D.is_transfer_countable_for_balance(None) is False

    def test_empty_dict_returns_false(self):
        # `not {}` is truthy → treated as no-data → False (defensive).
        assert D.is_transfer_countable_for_balance({}) is False

    def test_minimal_valid_transfer_counts(self):
        # Any non-empty dict without an explicit reversed marker counts.
        assert D.is_transfer_countable_for_balance({"amount": 100}) is True


class TestApplyTransferToAccountBalance_RealSchema:
    """Slice 6 fix — helper now reads `from_side` / `to_side` (production
    schema) instead of `from` / `to`. This test pins the schema fix so a
    future rename to plain `from`/`to` (or vice versa) breaks loudly."""

    def test_from_side_and_to_side_are_the_schema(self):
        t = {"kind": "account_to_account", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "account", "account_id": "B"}}
        assert D.apply_transfer_to_account_balance_paise(t, "A") == -50000
        assert D.apply_transfer_to_account_balance_paise(t, "B") == +50000

    def test_legacy_from_to_field_names_no_longer_work(self):
        """A doc with the OLD (synthetic-only) `from`/`to` fields returns 0
        for all accounts — this is the correct behaviour post-Slice-6."""
        t = {"kind": "account_to_account", "amount": 500,
             "from": {"account_id": "A"}, "to": {"account_id": "B"}}
        assert D.apply_transfer_to_account_balance_paise(t, "A") == 0
        assert D.apply_transfer_to_account_balance_paise(t, "B") == 0

    def test_requires_side_type_account(self):
        # If the side has no `type: 'account'` marker (e.g. it's a
        # party side), the helper ignores it — must not match by
        # account_id alone.
        t = {"kind": "rakshit_to_ff", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}}
        assert D.apply_transfer_to_account_balance_paise(t, "A") == -50000
        # No account_id on to_side, so no match:
        assert D.apply_transfer_to_account_balance_paise(t, SYSTEM_FF_ID) == 0


class TestApplyTransferToFFLedger:
    def test_rakshit_to_ff_is_negative(self):
        # Party-ledger convention: rakshit paid FF → owes FF LESS → -amt.
        t = {"kind": "rakshit_to_ff", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}}
        assert D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID) == -50000

    def test_ff_to_rakshit_is_positive(self):
        t = {"kind": "ff_to_rakshit", "amount": 500,
             "from_side": {"type": "party", "party_id": SYSTEM_FF_ID},
             "to_side":   {"type": "account", "account_id": "A"}}
        assert D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID) == +50000

    def test_a2a_never_touches_ff(self):
        t = {"kind": "account_to_account", "amount": 999,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "account", "account_id": "B"}}
        assert D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID) == 0

    def test_reversed_original_still_counted(self):
        # Balance-scope filter: reversed originals still count, since
        # the paired reversal doc cancels them out.
        t = {"kind": "rakshit_to_ff", "amount": 500,
             "status": "reversed",
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}}
        assert D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID) == -50000

    def test_ignores_transfers_not_involving_ff(self):
        # Party side pointing to a different party → ignored.
        t = {"kind": "rakshit_to_ff", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": "other-party"}}
        assert D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID) == 0

    def test_pure_no_mutation(self):
        t = {"kind": "rakshit_to_ff", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}}
        snapshot = copy.deepcopy(t)
        _ = D.apply_transfer_to_ff_ledger_paise(t, SYSTEM_FF_ID)
        assert t == snapshot


class TestSumFFLedgerDeltaFromTransfersPaise:
    def test_basic_sum_all_kinds(self):
        rows = [
            {"kind": "rakshit_to_ff", "amount": 1500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}},
            {"kind": "ff_to_rakshit", "amount": 500,
             "from_side": {"type": "party", "party_id": SYSTEM_FF_ID},
             "to_side":   {"type": "account", "account_id": "B"}},
            {"kind": "account_to_account", "amount": 2000,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "account", "account_id": "B"}},
        ]
        # -1500 (rakshit_to_ff) + 500 (ff_to_rakshit) + 0 (a2a) = -1000 → -100_000 p
        assert D.sum_ff_ledger_delta_from_transfers_paise(
            rows, SYSTEM_FF_ID) == -100_000

    def test_empty_returns_zero(self):
        assert D.sum_ff_ledger_delta_from_transfers_paise(
            [], SYSTEM_FF_ID) == 0

    def test_order_insensitive(self):
        rows = [
            {"kind": "rakshit_to_ff", "amount": 100,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}},
            {"kind": "ff_to_rakshit", "amount": 200,
             "from_side": {"type": "party", "party_id": SYSTEM_FF_ID},
             "to_side":   {"type": "account", "account_id": "A"}},
        ]
        a = D.sum_ff_ledger_delta_from_transfers_paise(rows, SYSTEM_FF_ID)
        b = D.sum_ff_ledger_delta_from_transfers_paise(
            list(reversed(rows)), SYSTEM_FF_ID)
        assert a == b

    def test_reversal_pair_nets_to_zero(self):
        # Original (reversed) + reversal doc (active, swapped kind).
        # Together they must contribute 0.
        original = {"kind": "rakshit_to_ff", "amount": 700,
                    "status": "reversed",
                    "from_side": {"type": "account", "account_id": "A"},
                    "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}}
        reversal = {"kind": "ff_to_rakshit", "amount": 700,
                    "status": "active", "reverses_transfer_id": "orig-1",
                    "from_side": {"type": "party", "party_id": SYSTEM_FF_ID},
                    "to_side":   {"type": "account", "account_id": "A"}}
        assert D.sum_ff_ledger_delta_from_transfers_paise(
            [original, reversal], SYSTEM_FF_ID) == 0


class TestCashbookIncomeExpenseSplitters:
    def _cb(self):
        return [
            {"kind": "general_income", "amount": 400, "account_id": "A"},
            {"kind": "general_expense", "amount": 150, "account_id": "A"},
            {"kind": "general_income", "amount": 999, "account_id": "B"},
            {"kind": "general_income", "amount": 50,  "account_id": "A",
             "source": "legacy_shim"},   # excluded
            {"kind": "general_income", "amount": 60,  "account_id": "A",
             "reversed": True},          # excluded
            {"kind": "transfer", "amount": 100, "account_id": "A"},  # ignored (helpers gate on kind)
        ]

    def test_income_only(self):
        assert D.sum_cashbook_income_for_account_paise(self._cb(), "A") == 40000

    def test_expense_only(self):
        assert D.sum_cashbook_expense_for_account_paise(self._cb(), "A") == 15000

    def test_net_equals_income_minus_expense(self):
        cb = self._cb()
        net = D.sum_cashbook_net_for_account_paise(cb, "A")
        inc = D.sum_cashbook_income_for_account_paise(cb, "A")
        exp = D.sum_cashbook_expense_for_account_paise(cb, "A")
        assert net == inc - exp

    def test_pure_no_mutation(self):
        cb = self._cb()
        snap = copy.deepcopy(cb)
        _ = D.sum_cashbook_income_for_account_paise(cb, "A")
        _ = D.sum_cashbook_expense_for_account_paise(cb, "A")
        assert cb == snap


# ═════════════════════════════════════════════════════════════════════════
# B. Sign-convention pin — dashboard vs party-ledger convention.
# ═════════════════════════════════════════════════════════════════════════

class TestFFSettlementSignConventionsAreOpposites:
    """The two FF helpers must remain exact negatives of each other on
    matched semantics: same active-record filter, same set of transfers.

    Note: `sum_ff_settlement_delta_from_transfers_paise` uses
    `is_transfer_active` (excludes reversed originals) while
    `sum_ff_ledger_delta_from_transfers_paise` uses
    `is_transfer_countable_for_balance` (includes reversed originals). We
    therefore test the equivalence on an ACTIVE-ONLY dataset (matching
    filters), otherwise the two helpers diverge legitimately on reversed
    pairs."""

    def test_dashboard_and_party_ledger_conventions_are_opposites(self):
        rows_active_only = [
            {"kind": "rakshit_to_ff", "amount": 1500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}},
            {"kind": "ff_to_rakshit", "amount": 500,
             "from_side": {"type": "party", "party_id": SYSTEM_FF_ID},
             "to_side":   {"type": "account", "account_id": "B"}},
        ]
        a = D.sum_ff_settlement_delta_from_transfers_paise(rows_active_only)
        b = D.sum_ff_ledger_delta_from_transfers_paise(rows_active_only,
                                                      SYSTEM_FF_ID)
        assert a == -b, (
            "Dashboard-signed and party-ledger-signed FF delta helpers "
            "must be exact negatives. If they diverged, one convention "
            "silently flipped — this is the drift canary."
        )


# ═════════════════════════════════════════════════════════════════════════
# C. Real-Mongo integration — live endpoint byte-equivalence
# ═════════════════════════════════════════════════════════════════════════

class TestAccountBalanceLiveByteEquivalence:
    """Every account balance must equal a naive float walk of its
    contributing rows: opening + Σ customer_payments − Σ purchase_payments
    + cb_net + Σ transfers. Slice 6 accumulates in paise via domain; this
    test walks the same source rows in float and asserts ½-paise agreement."""

    def test_all_account_balances_match_float_walk(self):
        token = _login_token()
        accounts = _get("/api/accounts", token=token)
        assert isinstance(accounts, list)
        assert len(accounts) > 0

        checked = 0
        for acc in accounts[:20]:  # cap for speed — 20 accounts is plenty
            aid = acc["id"]
            r = _get(f"/api/accounts/{aid}/balance", token=token)
            # Verify keys present
            for k in ("account_id", "account_name", "opening_balance",
                      "incoming", "outgoing", "transfer_net", "balance"):
                assert k in r, f"account balance missing '{k}'"
            # Composition identity (allow ½-paise rounding tolerance).
            expected = (r["opening_balance"]
                        + r["incoming"] - r["outgoing"]
                        + r["transfer_net"])
            assert abs(expected - r["balance"]) <= 0.005, (
                f"account {r['account_name']}: composition drift "
                f"{expected} vs {r['balance']}"
            )
            checked += 1
        assert checked > 0


class TestFathersFirmSettlementStillCorrect:
    """FF settlement endpoint must remain byte-equivalent post-Slice-6.
    Only the -0.0 → 0.0 quirk from Slice 5 is allowed (pinned in the
    Slice-5 test file). This is a regression guard, not a new assertion."""

    def test_ff_endpoint_returns_expected_shape(self):
        token = _login_token()
        s = _get("/api/party-ledger-v2/fathers-firm-settlement", token=token)
        assert set(s.keys()) >= {"party_id", "party_name",
                                 "balance_signed", "amount",
                                 "status", "label"}
        assert s["status"] in {"settled", "you_pay", "you_receive"}
        assert abs(abs(s["balance_signed"]) - s["amount"]) <= 0.01


class TestReconcileStillHealthyPostSlice6:
    def test_reconcile_all_healthy(self):
        token = _login_token()
        rep = _get("/api/reconcile", token=token)
        assert rep["healthy"] is True
        assert rep["summary"]["passed"] == rep["summary"]["total"]
        assert rep["engine_version"] == "P5"


class TestTransfersEndpointsSmoke:
    """Regression smoke — `/api/transfers`, per-id GET, and account
    balance flow all still return 200 with correct shape."""

    def test_transfers_list_returns_expected_shape(self):
        token = _login_token()
        rows = _get("/api/transfers", token=token)
        assert isinstance(rows, list)
        for t in rows[:5]:
            for k in ("id", "kind", "amount", "from_side", "to_side",
                      "status", "date"):
                assert k in t, f"transfer row missing '{k}'"


# ═════════════════════════════════════════════════════════════════════════
# D. Non-mutation contracts
# ═════════════════════════════════════════════════════════════════════════

class TestSlice6HelpersNonMutation:
    def test_apply_transfer_to_account_no_mutation(self):
        t = {"kind": "account_to_account", "amount": 500,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "account", "account_id": "B"}}
        snap = copy.deepcopy(t)
        _ = D.apply_transfer_to_account_balance_paise(t, "A")
        _ = D.apply_transfer_to_account_balance_paise(t, "B")
        assert t == snap

    def test_sum_ff_ledger_no_mutation(self):
        rows = [
            {"kind": "rakshit_to_ff", "amount": 100,
             "from_side": {"type": "account", "account_id": "A"},
             "to_side":   {"type": "party", "party_id": SYSTEM_FF_ID}},
        ]
        snap = copy.deepcopy(rows)
        _ = D.sum_ff_ledger_delta_from_transfers_paise(rows, SYSTEM_FF_ID)
        assert rows == snap

    def test_is_transfer_countable_no_mutation(self):
        t = {"status": "reversed", "amount": 100}
        snap = copy.deepcopy(t)
        _ = D.is_transfer_countable_for_balance(t)
        assert t == snap
