# Artisan Personal Ledger — PRD

## Origin
Repository `raksagarwal325-code/Personal-Ledger` cloned and continued as a full-stack ERP (FastAPI + MongoDB + React).

## Current mission
Multi-phase refactor to make Cash Book a unified timeline sourced from canonical modules and remove dual sources-of-truth for money movement. Phases:
1. **P0 — Retire legacy `db.payments`** *(shipped Feb 2026)*
2. **P1 — Auto-create parties + resolve `vendors` / `parties` duplication**
3. **P1 — Transfer UI (Rakshit ↔ Father's Firm, bank ↔ cash, account ↔ account)**
4. **P1 — Partial-shipment revenue + Estimated vs Realized profit**
5. **P2 — `/api/reconcile` + invariant tests**

## Architecture (unchanged)
- FastAPI (`backend/server.py`, `backend/party_ledger_v2.py`) + MongoDB.
- React SPA (`frontend/src/…`) using shadcn/ui + Tailwind.
- Party Ledger v2 = derived-live source of truth for balances.

## User personas
- Rakshit (workshop owner) — records orders, shipments, purchases, customer payments, vendor payments, general income/expense and inter-account transfers.

## Core requirements (static)
- Every business event enters ERP through its natural module (Order, Sales Payments, Purchase Payments, Purchases, Cash Book). Cash Book NEVER creates customer or vendor payments.
- Every payment lives in exactly one canonical collection.
- Dashboard reads canonical sources only; legacy `db.payments` never enters KPI computations.
- Revenue only recognised on shipped quantity.

## What's been implemented (Feb 2026 · Phase 1 · P0)
### Backend
- New `CashBookEntry` model + `db.cash_book_entries` collection with `kind ∈ {general_income, general_expense, transfer}` and `source ∈ {cash_book, legacy_shim, legacy_migrated}`.
- Endpoints
  - `POST/GET/PUT/DELETE /api/cash-book-entries` (canonical Cash Book writes; only allows genuine income / expense / transfer).
  - `GET /api/cash-book` — unified read-only timeline projection from `customer_payments` + `purchase_payments` + `cash_book_entries` + legacy migration rows. Every row carries a `source_document` envelope for one-click origin navigation.
  - `GET /api/business-events` — ERP-wide activity feed (Orders, Shipments, Customer/Vendor Payments, Purchases, Cash Book) with a common envelope (`event_id`, `event_type`, `source_module`, `source_document`, `date`, `party`, `amount`, `reversed`, `created_by`, `created_at`, `updated_at`).
- Dashboard KPIs (`received`, `paid`, `modes`) refactored to derive from canonical collections only. Legacy `db.payments` no longer touched by `/dashboard`, `/dashboard/breakdown/payable`, `/meta`, or exports.
- `/export/payments.csv` and `/export/payments.xlsx` rebuilt as a canonical union with a `Source Module` column: `Sales Payment | Purchase Payment | Cash Book | Cash Book (Legacy Shim) | Transfer | Migration`.
- `POST/PUT/DELETE /api/payments` retained as **deprecated shims**. New writes are stamped `source='legacy_shim'` in `db.payments` and mirrored to `cash_book_entries` for timeline visibility, but excluded from every canonical KPI.
- Startup migration: every pre-existing `db.payments` row is stamped `source='legacy_migrated'` (idempotent). No data is deleted.

### Frontend
- Cash Book page (`pages/Payments.jsx`) rewritten as a timeline (grouped by date, source tags, per-row "Open Source" navigation).
- Header split-button `New entry ▾ → General Income / General Expense / Transfer`. NO button for customer / vendor payment — those live in their own modules.
- Rows originating from `customer_payments`, `purchase_payments`, `orders` are read-only in Cash Book; the "Open Source" button routes to the origin module.
- New `components/CashBookEntryDialog.jsx` for creating income / expense / transfer entries (canonical `POST /cash-book-entries`).
- Old free-form `components/PaymentDialog.jsx` is no longer imported anywhere (kept on disk for git history).
- "Include pre-refactor migration rows" toggle to hide/show historic legacy rows.

## Test status (Feb 2026 · post-Phase 1)
| File | Before P0 | After P0 | Notes |
|---|---|---|---|
| `test_p0_canonical_cashbook.py` (**new**) | — | **9/9 pass** | KPI derivation, transfer neutrality, shim non-counting, business events, export column |
| `test_party_ledger_v2.py` | 7 fail | 0 fail | ✅ all pass |
| `test_party_ledger_reconciliation.py` | 8 fail | 2 fail | 6 fixed |
| `test_review_workflow.py` | 1 fail | 0 fail | ✅ dashboard consistency restored |
| `test_purchase_sources.py` | 0 fail | 0 fail | unchanged |
| `backend_test.py` | 20 fail | 19 fail | legacy tech-debt (asserts on old db.payments Cash Book behaviour) |
| `test_erp_refactor.py::test_47_orders_fully_shipped` | fail | fail | unrelated legacy migration |
| `test_erp_refactor.py::test_dashboard_kpis_preserved` | fail | fail | asserts on old legacy-based dashboard KPIs (design change) |
| `test_purchases_and_bugs.py::test_dashboard_legacy_kpis_intact` | fail | fail | same |
| **Full suite** | 137 pass / 36 fail | **158 pass / 24 fail** | +21 pass |

## Prioritized backlog
- **P1 — Phase 2**: Auto-create parties in every canonical write path (`customer_payments`, `purchase_payments`, `purchases`, `orders`). Resolve `db.vendors` vs `parties.type='vendor'` duplication. Should retire the 2 remaining `test_party_ledger_reconciliation.py` failures + many `backend_test.py` legacy assertions.
- **P1 — Phase 3**: Transfer UI is already live (Cash Book "Transfer" entry). Extend with a "Rakshit ↔ Father's Firm" transfer that routes through Party Ledger v2 `POST /party-transactions category=transfer`.
- **P1 — Phase 4**: Partial-shipment revenue proportional recognition + Estimated vs Realized profit split. Order model already stores `shipped_qty_total` / `ordered_qty_total`; frontend just needs `revenue_recognized` + `realized_profit` fields from `/orders/{oid}/payments`.
- **P2 — Phase 5**: `/api/reconcile` invariant endpoint + pytest suite.
- **P2**: Refresh stale `backend_test.py`. GST report / Invoice PDF export. Multi-user / auth.
