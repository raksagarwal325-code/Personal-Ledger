"""Phase 1 (P0) — canonical Cash Book invariants.

Verifies:
    * dashboard KPIs (`received`, `paid`, `modes`) come from canonical sources
      only — customer_payments, purchase_payments, cash_book_entries.
    * legacy `POST /api/payments` (deprecated shim) never double-counts.
    * `POST /api/cash-book-entries` (kind ∈ general_income / general_expense
      / transfer) is the ONLY create-path for genuine Cash Book rows.
    * Transfers are profit-neutral.
    * `/api/cash-book` returns a unified timeline with source-linked docs.
    * `/api/business-events` emits envelopes for every ERP event.
    * `/api/export/payments.csv` includes a `source_module` column.
"""
from datetime import date

import pytest
import requests

API = "http://localhost:8001/api"


def _dashboard():
    r = requests.get(f"{API}/dashboard", timeout=10)
    r.raise_for_status()
    return r.json()


def _cash_book(**params):
    r = requests.get(f"{API}/cash-book", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _events(**params):
    r = requests.get(f"{API}/business-events", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _post_cbe(kind, amount, **kw):
    payload = {
        "date": date.today().isoformat(),
        "kind": kind,
        "amount": amount,
        "mode": "Cash",
        **kw,
    }
    r = requests.post(f"{API}/cash-book-entries", json=payload, timeout=10)
    return r


def _delete_cbe(eid):
    return requests.delete(f"{API}/cash-book-entries/{eid}", timeout=10)


class TestP0Canonical:
    def test_general_income_moves_received_kpi(self):
        before = _dashboard()["kpis"]["received"]
        r = _post_cbe("general_income", 1234.0, party_name="Scrap Buyer",
                      notes="p0 test general income")
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        try:
            after = _dashboard()["kpis"]["received"]
            assert abs((after - before) - 1234.0) < 0.5, (before, after)
        finally:
            _delete_cbe(eid)

    def test_general_expense_moves_paid_kpi(self):
        before = _dashboard()["kpis"]["paid"]
        r = _post_cbe("general_expense", 777.0, party_name="Office Tea",
                      notes="p0 test general expense")
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        try:
            after = _dashboard()["kpis"]["paid"]
            assert abs((after - before) - 777.0) < 0.5, (before, after)
        finally:
            _delete_cbe(eid)

    def test_transfer_is_profit_neutral(self):
        # Pick two accounts
        r = requests.get(f"{API}/meta", timeout=10)
        accts = r.json().get("accounts") or []
        assert len(accts) >= 2, "need at least 2 accounts to test transfers"
        a, b = accts[0], accts[1]

        d = _dashboard()["kpis"]
        r = _post_cbe("transfer", 500.0,
                      from_account_id=a["id"], from_account_name=a["name"],
                      to_account_id=b["id"], to_account_name=b["name"],
                      notes="p0 transfer test")
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        try:
            d2 = _dashboard()["kpis"]
            assert abs(d2["received"] - d["received"]) < 0.5
            assert abs(d2["paid"] - d["paid"]) < 0.5
            assert abs(d2["net_profit"] - d["net_profit"]) < 0.5
            # Should still show up on the Cash Book timeline
            cb = _cash_book(kind="transfer")
            assert any(row["event_id"] == eid for row in cb["rows"])
        finally:
            _delete_cbe(eid)

    def test_legacy_post_payments_does_not_double_count(self):
        """Legacy shim writes must not enter canonical KPIs."""
        before = _dashboard()["kpis"]
        payload = {
            "date": date.today().isoformat(),
            "party": "P0 Legacy Shim",
            "mode": "Cash",
            "received_by_me": 999.0,
            "payment_by_me": 0.0,
        }
        r = requests.post(f"{API}/payments", json=payload, timeout=10)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            after = _dashboard()["kpis"]
            # Legacy shim must NOT move canonical KPIs
            assert abs(after["received"] - before["received"]) < 0.5, \
                (before["received"], after["received"])
            assert abs(after["paid"] - before["paid"]) < 0.5
            # Row should show up in Cash Book as a Migration-family / Legacy Shim source
            cb = _cash_book(include_shim=True, include_migration=True)
            hits = [r for r in cb["rows"]
                    if r["source_module"] in ("Cash Book (Legacy Shim)", "Migration")]
            assert len(hits) > 0
        finally:
            requests.delete(f"{API}/payments/{pid}", timeout=10)

    def test_cashbook_timeline_shows_canonical_sources(self):
        cb = _cash_book(include_migration=False, include_shim=False)
        sources = {r["source_module"] for r in cb["rows"]}
        # If any customer_payments / purchase_payments exist in the DB, their
        # source labels must appear on the timeline.
        n_cust = requests.get(f"{API}/customer-payments", timeout=10).json()
        n_purch = requests.get(f"{API}/purchase-payments", timeout=10).json()
        if len(n_cust) > 0:
            assert "Sales Payments" in sources
        if len(n_purch) > 0:
            assert "Purchase Payments" in sources

    def test_business_events_endpoint(self):
        ev = _events(limit=1000)
        types = {e["event_type"] for e in ev["events"]}
        # Baseline seed data guarantees at least orders and shipments.
        assert "order_created" in types
        for e in ev["events"][:5]:
            assert set(e.keys()) >= {
                "event_id", "event_type", "source_module", "source_document",
                "date", "amount", "reversed", "created_by",
            }, f"missing keys in business event: {e}"

    def test_cash_book_entry_is_editable_only_via_own_route(self):
        # Create a Cash Book entry via POST /cash-book-entries — must be editable.
        r = _post_cbe("general_expense", 10.0, notes="p0 editable")
        eid = r.json()["id"]
        try:
            row = next(x for x in _cash_book()["rows"] if x["event_id"] == eid)
            assert row["editable"] is True
            # PUT works
            r2 = requests.put(
                f"{API}/cash-book-entries/{eid}",
                json={"date": date.today().isoformat(), "kind": "general_expense",
                      "amount": 11.0, "mode": "Cash", "notes": "p0 edited"},
                timeout=10,
            )
            assert r2.status_code == 200, r2.text
            assert r2.json()["amount"] == 11.0
        finally:
            _delete_cbe(eid)

    def test_legacy_shim_row_not_editable_via_cashbook(self):
        # Create a legacy shim, then attempt to PUT its id as a Cash Book entry.
        r = requests.post(
            f"{API}/payments",
            json={"date": date.today().isoformat(), "party": "Shim Test",
                  "mode": "Cash", "received_by_me": 10.0},
            timeout=10,
        )
        pid = r.json()["id"]
        try:
            # The shim row exists in cash_book_entries with source='legacy_shim';
            # PUT must be refused.
            cb = _cash_book(include_shim=True)
            shim = next((x for x in cb["rows"]
                         if x["source_module"] == "Cash Book (Legacy Shim)"), None)
            if shim:
                r2 = requests.put(
                    f"{API}/cash-book-entries/{shim['event_id']}",
                    json={"date": date.today().isoformat(),
                          "kind": "general_expense", "amount": 5.0, "mode": "Cash"},
                    timeout=10,
                )
                assert r2.status_code == 400
        finally:
            requests.delete(f"{API}/payments/{pid}", timeout=10)

    def test_export_csv_has_source_module_column(self):
        r = requests.get(f"{API}/export/payments.csv", timeout=10)
        assert r.status_code == 200
        header = r.text.split("\n")[0]
        assert "source_module" in header, header
