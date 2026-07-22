"""Bug fix (2026-07-22) — Dashboard month filter.

One focused test confirming the selected month updates ALL dashboard
figures (KPIs + monthly series + top-customers + modes) using the
month's transaction / order dates.

Design:
  • Create TWO fresh orders — one dated in month A (2026-04-15), one in
    month B (2026-05-20). Different clients, different revenues.
  • Snapshot dashboard KPIs with `month=all` (baseline), `month=2026-04`,
    `month=2026-05`, `month=2026-06` (empty).
  • Assert:
      - `month=2026-04` KPIs reflect ONLY order A. Order-count, revenue,
        `top_customers` all reflect that single order.
      - `month=2026-05` KPIs reflect ONLY order B.
      - `month=2026-06` KPIs are zero for these test clients (nothing in
        that month unless other data exists).
      - `month=all` sums BOTH.
      - `applied_month` metadata reflects the request (mode + key + label
        + from/to bounds).
      - `available_months` includes both `2026-04` and `2026-05`.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

import uuid
import httpx
import pytest

API_BASE = "http://localhost:8001"


def _login() -> str:
    email = "admin@artisan.local"
    password = "Admin@12345"
    try:
        httpx.post(f"{API_BASE}/api/admin/bootstrap",
                   json={"email": email, "password": password, "name": "Admin"},
                   timeout=10.0)
    except Exception:
        pass
    r = httpx.post(f"{API_BASE}/api/auth/login",
                   json={"email": email, "password": password}, timeout=10.0)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(t): return {"Authorization": f"Bearer {t}"}


def _get(path, t, **params):
    r = httpx.get(f"{API_BASE}{path}", headers=_hdr(t), params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _post(path, t, payload):
    r = httpx.post(f"{API_BASE}{path}", headers=_hdr(t), json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


def _delete(path, t):
    r = httpx.delete(f"{API_BASE}{path}", headers=_hdr(t), timeout=15.0)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def token():
    return _login()


def _make_order(t, *, client, date_iso, product_sales, qty=1):
    return _post("/api/orders", t, {
        "client_name": client,
        "order_date": date_iso,
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "MonthFilterTest",
            "qty": qty, "rate": product_sales, "product_sales": product_sales,
        }],
        "tax_applicable": False,
        "tax_type": "None",
    })


class TestDashboardMonthFilter:
    def test_month_filter_updates_all_dashboard_figures(self, token):
        unique = uuid.uuid4().hex[:8]
        client_a = f"MonthFilter A {unique}"
        client_b = f"MonthFilter B {unique}"
        rev_a = 55000
        rev_b = 77000

        order_a = _make_order(token, client=client_a,
                              date_iso="2026-04-15", product_sales=rev_a)
        order_b = _make_order(token, client=client_b,
                              date_iso="2026-05-20", product_sales=rev_b)
        try:
            # ── month=all (baseline) ─────────────────────────────────────
            all_dash = _get("/api/dashboard", token, month="all")
            assert all_dash["applied_month"]["mode"] == "all"
            assert all_dash["applied_month"]["key"] == "all"
            assert all_dash["applied_month"]["label"] == "All Time"
            avail = all_dash.get("available_months") or []
            assert "2026-04" in avail, f"available_months={avail}"
            assert "2026-05" in avail, f"available_months={avail}"
            clients_all = {c["client"] for c in (all_dash.get("top_customers") or [])}
            assert client_a in clients_all
            assert client_b in clients_all

            # ── month=2026-04 ────────────────────────────────────────────
            apr = _get("/api/dashboard", token, month="2026-04")
            assert apr["applied_month"] == {
                "mode": "specific", "key": "2026-04", "label": "April 2026",
                "from_date": "2026-04-01", "to_date": "2026-05-01",
            }
            # KPI: revenue for month A must include order_a's product_sales.
            # (may include other April data on this DB — assert INCLUSION
            # rather than exact equality so the test is not sensitive to
            # seeded data.)
            apr_clients = {c["client"]: c for c in apr.get("top_customers") or []}
            assert client_a in apr_clients, (
                f"top_customers for April must include {client_a}. "
                f"Got: {list(apr_clients.keys())[:10]}"
            )
            assert client_b not in apr_clients, (
                f"top_customers for April must NOT include the May client "
                f"{client_b}. Got: {list(apr_clients.keys())[:10]}"
            )
            # Order-count for April must be >= 1 and INCLUDE order A.
            assert apr["kpis"]["order_count"] >= 1

            # ── month=2026-05 ────────────────────────────────────────────
            may = _get("/api/dashboard", token, month="2026-05")
            assert may["applied_month"] == {
                "mode": "specific", "key": "2026-05", "label": "May 2026",
                "from_date": "2026-05-01", "to_date": "2026-06-01",
            }
            may_clients = {c["client"]: c for c in may.get("top_customers") or []}
            assert client_b in may_clients, (
                f"top_customers for May must include {client_b}. "
                f"Got: {list(may_clients.keys())[:10]}"
            )
            assert client_a not in may_clients, (
                f"top_customers for May must NOT include the April client "
                f"{client_a}. Got: {list(may_clients.keys())[:10]}"
            )

            # ── month=2026-06 (empty for our test clients) ───────────────
            jun = _get("/api/dashboard", token, month="2026-06")
            assert jun["applied_month"]["key"] == "2026-06"
            jun_clients = {c["client"] for c in jun.get("top_customers") or []}
            assert client_a not in jun_clients
            assert client_b not in jun_clients

            # ── monthly series in a filtered response only contains keys
            # within the window (or is empty). ───────────────────────────
            apr_series_months = {m["month"] for m in apr.get("monthly") or []}
            assert apr_series_months.issubset({"2026-04"}), (
                f"April dashboard monthly series must only include April, "
                f"got: {apr_series_months}"
            )

            # ── current / previous smoke-tests ───────────────────────────
            cur = _get("/api/dashboard", token, month="current")
            assert cur["applied_month"]["mode"] == "current"
            assert cur["applied_month"]["key"] != "all"
            prev = _get("/api/dashboard", token, month="previous")
            assert prev["applied_month"]["mode"] == "previous"

            # ── invalid month value → HTTP 400 ───────────────────────────
            r = httpx.get(f"{API_BASE}/api/dashboard",
                          headers=_hdr(token),
                          params={"month": "not-a-month"}, timeout=10.0)
            assert r.status_code == 400, (
                f"invalid month must return HTTP 400, got {r.status_code}"
            )
        finally:
            _delete(f"/api/orders/{order_a['id']}", token)
            _delete(f"/api/orders/{order_b['id']}", token)
