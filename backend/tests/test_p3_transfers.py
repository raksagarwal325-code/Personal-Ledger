"""Phase 3 (P1) — First-Class Transfers reconciliation invariants.

`db.transfers` is the SOLE source of truth. Account balances and FF
settlement are DERIVED — asserted here.

FF signed-balance convention (numerical guarantee):
    - rakshit_to_ff ₹X → tracked cash −X, FF settlement −X (delta_you_pay)
    - ff_to_rakshit ₹X → tracked cash +X, FF settlement +X (delta_you_pay)
    Both variants are P&L-neutral.
"""
from __future__ import annotations

import uuid

import pytest
import requests

API = "http://localhost:8001/api"
SYSTEM_FF = "system_fathers_firm"


def _post(p, body):    return requests.post(f"{API}{p}", json=body, timeout=10)
def _get(p, params=None): return requests.get(f"{API}{p}", params=params, timeout=10)
def _put(p, body):     return requests.put(f"{API}{p}", json=body, timeout=10)


def _acct(name, kind="Bank"):
    r = _post("/accounts", {"name": name, "type": kind})
    assert r.status_code == 200, r.text
    return r.json()


def _balance(aid):
    r = _get(f"/accounts/{aid}/balance")
    assert r.status_code == 200, r.text
    return r.json()["balance"]


def _ff_signed():
    r = _get("/party-ledger-v2/fathers-firm-settlement")
    assert r.status_code == 200, r.text
    return r.json()["balance_signed"]


def _kpis():
    return _get("/dashboard").json()["kpis"]


def _dashboard():
    return _get("/dashboard").json()


class TestValidations:
    def test_same_source_and_destination_rejected(self):
        a = _acct(f"Bank-{uuid.uuid4().hex[:6]}")
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": a["id"]},
            "amount": 100,
        })
        assert r.status_code == 400, r.text

    def test_zero_or_negative_rejected(self):
        a = _acct(f"Bank-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Cash-{uuid.uuid4().hex[:6]}", "Cash")
        for amt in (0, -100):
            r = _post("/transfers", {
                "date": "2025-01-15",
                "from_side": {"type": "account", "account_id": a["id"]},
                "to_side": {"type": "account", "account_id": b["id"]},
                "amount": amt,
            })
            assert r.status_code == 400, (amt, r.text)

    def test_archived_account_rejected(self):
        a = _acct(f"Old-{uuid.uuid4().hex[:6]}")
        b = _acct(f"New-{uuid.uuid4().hex[:6]}", "Cash")
        requests.post(f"{API}/accounts/{a['id']}/archive", timeout=10)
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 100,
        })
        assert r.status_code == 400, r.text


class TestAccountToAccount:
    def test_totals_leaving_equal_entering(self):
        a = _acct(f"A2A-Bank-{uuid.uuid4().hex[:6]}")
        b = _acct(f"A2A-Cash-{uuid.uuid4().hex[:6]}", "Cash")
        b_a_before = _balance(a["id"])
        b_b_before = _balance(b["id"])
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 1000,
        })
        assert r.status_code == 200, r.text
        assert _balance(a["id"]) == round(b_a_before - 1000, 2)
        assert _balance(b["id"]) == round(b_b_before + 1000, 2)
        # Net across both accounts is zero
        assert (_balance(a["id"]) - b_a_before) + (_balance(b["id"]) - b_b_before) == 0

    def test_does_not_affect_pnl(self):
        a = _acct(f"P&L-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"P&L-B-{uuid.uuid4().hex[:6]}", "Cash")
        before = _dashboard()
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 500,
        })
        assert r.status_code == 200
        after = _dashboard()
        for k in ("received", "paid", "net_profit"):
            assert abs(after["kpis"][k] - before["kpis"][k]) < 0.5, (k, before["kpis"][k], after["kpis"][k])

    def test_cash_book_shows_one_row_per_transfer(self):
        a = _acct(f"CB-Row-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"CB-Row-B-{uuid.uuid4().hex[:6]}", "Cash")
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 250,
        })
        assert r.status_code == 200
        tid = r.json()["id"]
        cb = _get("/cash-book", {"kind": "transfer", "limit": 1000}).json()
        matching = [row for row in cb["rows"] if row["event_id"] == tid]
        assert len(matching) == 1, matching


class TestRakshitFF:
    def test_rakshit_to_ff_moves_cash_down_ff_delta_down(self):
        a = _acct(f"FF-Src-{uuid.uuid4().hex[:6]}")
        cash_before = _balance(a["id"])
        ff_before = _ff_signed()
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "party", "party_id": SYSTEM_FF},
            "amount": 10000,
        })
        assert r.status_code == 200, r.text
        # Tracked-account cash falls by 10000
        assert _balance(a["id"]) == round(cash_before - 10000, 2)
        # FF settlement (signed convention: +ve = FF owes Rakshit) moves UP by 10000
        assert abs(_ff_signed() - (ff_before + 10000)) < 0.5, (ff_before, _ff_signed())

    def test_ff_to_rakshit_moves_cash_up_ff_delta_up(self):
        a = _acct(f"FF-Dst-{uuid.uuid4().hex[:6]}", "Cash")
        cash_before = _balance(a["id"])
        ff_before = _ff_signed()
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "party", "party_id": SYSTEM_FF},
            "to_side": {"type": "account", "account_id": a["id"]},
            "amount": 4000,
        })
        assert r.status_code == 200, r.text
        assert _balance(a["id"]) == round(cash_before + 4000, 2)
        # FF signed (+ve = FF owes Rakshit) FALLS by 4000
        assert abs(_ff_signed() - (ff_before - 4000)) < 0.5, (ff_before, _ff_signed())

    def test_ff_transfer_is_pnl_neutral(self):
        a = _acct(f"FF-PNL-{uuid.uuid4().hex[:6]}")
        before = _dashboard()
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "party", "party_id": SYSTEM_FF},
            "amount": 2500,
        })
        assert r.status_code == 200
        after = _dashboard()
        for k in ("received", "paid", "net_profit"):
            assert abs(after["kpis"][k] - before["kpis"][k]) < 0.5

    def test_ff_settlement_unchanged_by_account_to_account(self):
        a = _acct(f"A2A-FFN-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"A2A-FFN-B-{uuid.uuid4().hex[:6]}", "Cash")
        ff_before = _ff_signed()
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 999,
        })
        assert r.status_code == 200
        assert abs(_ff_signed() - ff_before) < 0.5


class TestIdempotency:
    def test_duplicate_idempotency_key_returns_original(self):
        a = _acct(f"Idem-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Idem-B-{uuid.uuid4().hex[:6]}", "Cash")
        key = f"idem-{uuid.uuid4()}"
        payload = {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 700,
            "idempotency_key": key,
        }
        r1 = _post("/transfers", payload)
        r2 = _post("/transfers", payload)
        r3 = _post("/transfers", payload)
        assert r1.status_code == r2.status_code == r3.status_code == 200
        assert r1.json()["id"] == r2.json()["id"] == r3.json()["id"]
        # And no duplicate reflected in balance
        assert _balance(a["id"]) == -700  # opening 0, one leg only


class TestReversalAndEdit:
    def test_reversal_returns_previous_balances(self):
        a = _acct(f"Rev-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Rev-B-{uuid.uuid4().hex[:6]}", "Cash")
        before_a = _balance(a["id"])
        before_b = _balance(b["id"])
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 300,
        })
        tid = r.json()["id"]
        assert _balance(a["id"]) == round(before_a - 300, 2)
        # Reverse
        r2 = _post(f"/transfers/{tid}/reverse", {})
        assert r2.status_code == 200, r2.text
        # Balances restored
        assert _balance(a["id"]) == round(before_a, 2)
        assert _balance(b["id"]) == round(before_b, 2)
        # Original document is now status=reversed and points at reversal
        orig = _get(f"/transfers/{tid}").json()
        assert orig["status"] == "reversed"
        assert orig["reversed_transfer_id"] == r2.json()["id"]

    def test_reversal_is_immutable(self):
        a = _acct(f"Imm-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Imm-B-{uuid.uuid4().hex[:6]}", "Cash")
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 100,
        })
        tid = r.json()["id"]
        rev = _post(f"/transfers/{tid}/reverse", {}).json()
        # Cannot reverse a reversal
        r2 = _post(f"/transfers/{rev['id']}/reverse", {})
        assert r2.status_code == 400
        # Cannot re-reverse the already reversed original
        r3 = _post(f"/transfers/{tid}/reverse", {})
        assert r3.status_code == 409

    def test_edit_uses_reverse_plus_replace(self):
        a = _acct(f"Edt-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Edt-B-{uuid.uuid4().hex[:6]}", "Cash")
        c = _acct(f"Edt-C-{uuid.uuid4().hex[:6]}")
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 400,
        })
        tid = r.json()["id"]
        # Edit — change destination from b to c
        r2 = _put(f"/transfers/{tid}", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": c["id"]},
            "amount": 400,
        })
        assert r2.status_code == 200, r2.text
        # b returned to zero, c has +400
        assert _balance(b["id"]) == 0
        assert _balance(c["id"]) == 400
        # Original marked reversed
        assert _get(f"/transfers/{tid}").json()["status"] == "reversed"

    def test_delete_alias_for_reverse(self):
        a = _acct(f"Del-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Del-B-{uuid.uuid4().hex[:6]}", "Cash")
        r = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 50,
        })
        tid = r.json()["id"]
        r2 = requests.delete(f"{API}/transfers/{tid}", timeout=10)
        assert r2.status_code == 200
        assert _get(f"/transfers/{tid}").json()["status"] == "reversed"

    def test_no_block_when_unrelated_transfer_uses_same_account(self):
        """User adjustment: only DIRECT document dependencies block reversal.
        Other transfers using the same account must not block."""
        a = _acct(f"NB-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"NB-B-{uuid.uuid4().hex[:6]}", "Cash")
        r1 = _post("/transfers", {
            "date": "2025-01-15",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 100,
        })
        # An unrelated later transfer on the same accounts
        _post("/transfers", {
            "date": "2025-01-16",
            "from_side": {"type": "account", "account_id": a["id"]},
            "to_side": {"type": "account", "account_id": b["id"]},
            "amount": 100,
        })
        r_rev = _post(f"/transfers/{r1.json()['id']}/reverse", {})
        assert r_rev.status_code == 200, r_rev.text


class TestCashBookForwarding:
    def test_cbe_transfer_creates_canonical_transfer(self):
        """Legacy front-door POST /cash-book-entries kind=transfer must
        auto-forward to db.transfers so there is exactly one source of truth."""
        a = _acct(f"Fwd-A-{uuid.uuid4().hex[:6]}")
        b = _acct(f"Fwd-B-{uuid.uuid4().hex[:6]}", "Cash")
        r = _post("/cash-book-entries", {
            "date": "2025-01-15",
            "kind": "transfer",
            "amount": 1500,
            "from_account_id": a["id"], "from_account_name": a["name"],
            "to_account_id": b["id"], "to_account_name": b["name"],
            "mode": "Bank Transfer",
        })
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        # Doc exists in db.transfers, not db.cash_book_entries
        assert _get(f"/transfers/{tid}").status_code == 200
        # Cash Book emits exactly one row for this event
        cb = _get("/cash-book", {"limit": 1000}).json()
        rows = [row for row in cb["rows"] if row["event_id"] == tid]
        assert len(rows) == 1, rows
