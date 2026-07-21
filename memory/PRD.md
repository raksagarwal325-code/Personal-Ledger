# Artisan Personal Ledger — PRD

## Problem statement (current iteration)
Order Workflow & Settlement UX Improvements. Do not redesign the accounting engine. Preserve Party Ledger v2, linked transactions, audit trail, reconciliation, and payment endpoints. Fix the bug where a payment recorded in Sales Payments never appears on the related order.

## Architecture (unchanged)
- FastAPI (`/app/backend/server.py`, `/app/backend/party_ledger_v2.py`) + MongoDB.
- React SPA (`/app/frontend/src/…`) using shadcn/ui + Tailwind.
- Party Ledger v2 = single source of truth for balances (linked transactions).

## User personas
- Rakshit (workshop owner) — records orders, shipments, purchases, customer payments, vendor payments.

## Core requirements (static)
- Every payment lives in `customer_payments` collection ONLY (no duplicates).
- All modules (Orders, Sales Payments, Customer Ledger, Party Ledger, Cash Book, Dashboard) must reflect the same underlying data.
- Revenue only recognised on shipped quantity.

## What's been implemented (Feb 2026)
- Bug fix — `CustomerPaymentDialog` auto-allocates FIFO the moment an amount is typed, so payments recorded from Sales Payments now show up on the related order without the user needing to press "Auto-allocate FIFO". Root cause was UX (empty allocations submitted) not a backend defect.
- `GET /api/orders/{oid}/payments` — extended with `customer_advance_available`, `advance_payment_id`, `received_by_party_name`, per-row `payment_status`.
- `POST /api/orders/{oid}/allocate-advance` — updates existing customer_payments in place; never creates a duplicate.
- `GET /api/orders/{oid}/timeline` — chronological events.
- `GET /api/party-ledger-v2/fathers-firm-settlement` — single signed balance + status.
- Frontend — `OrderDialog` shows advance-available card + Allocate button, payment_status pills, 4-column summary, Shipment Progress panel, Timeline, Party Ledger shortcut chips, Estimated profit label (until Fully Shipped/Delivered).
- Frontend — `CustomerPaymentDialog` allocation table now shows 6 columns: Order · Invoice Total · Already Paid · Balance Due · Outstanding · Allocate. Helper text updated for "Received by".
- Frontend — Dashboard replaces two Father's Firm cards with a single settlement card driven by the backend endpoint.

## Test status
- `/app/backend/tests/test_review_workflow.py` — 18/18 pass (test_reports/iteration_12.json).
- Prior suites (`test_review_changes.py`, `test_party_ledger_v2.py`) untouched.

## Prioritized backlog
- P1: Split `OrderDialog.jsx` (~1600 lines) into subcomponents.
- P1: Extract `/orders`, `/customer-payments`, `/purchases` into modules to keep `server.py` <700 lines.
- P2: Refresh stale `backend_test.py`.
- P2: GST report / Invoice PDF export.
- P2: Multi-user / auth.

## Feb 2026 · Unified Purchase Sources
- Backend: added `PurchaseSource` model + `OrderItem.purchase_sources`. Legacy `factory_*/outside_*` fields are now derived from `purchase_sources` on save.
- Backend: new endpoint `GET /api/purchase-sources` returns Factory + all vendors for the OrderDialog dropdown.
- Backend: `_sync_order_linked_purchases` mirrors every (item, source, category) with amount > 0 into `db.purchases` using a stable `linked_source_key`. Repeated saves don't duplicate. Zero-out or removal of a source cascades: unpaid → deleted; paid → kept with `stale=True` and a note.
- Backend: `DELETE /orders/{oid}` refuses when any linked purchase has payments (`kept_paid > 0`).
- Frontend: new `PurchaseSourcesEditor.jsx` with a searchable Popover combobox (Factory shown as protected system supplier), quick-create vendor form, per-row Complete/Glass/Fitting inputs, totals, and remove button.
- Frontend: OrderDialog replaces the two Factory/Outside grids with the editor; summary math now sums from `purchase_sources` when present (falls back to legacy).
- Frontend: New orders start with an empty Factory row so the shape is familiar; users add outside vendor rows via "+ Add purchase source".

## Feb 2026 · Unified Purchase Sources — v2 (post-audit fixes)
- Bug fix: `_derived_entries_for_party` in `party_ledger_v2.py` now handles `ptype=='fathers_firm'` by scanning `db.purchases` where `vendor_name = FACTORY_PARTY_NAME`. Factory purchases created via `_sync_order_linked_purchases` now correctly move FF settlement balance (verified: -600 for a 300+200+100 factory order).
- Bug fix: `_validate_purchase_sources` runs BEFORE the order is inserted/updated, so a blank-supplier row can no longer leave a half-written order in `db.orders`.
- Testing: `test_purchase_sources.py` (16 new tests) + `test_review_workflow.py` (18 regression) — 34/34 pass sequentially (iteration_14).
- Known non-code note: two balance-snapshot tests aren't parallel-safe under `pytest -n auto` (they'd need `@pytest.mark.serial`). Sequential run is clean.
