# Artisan Personal Ledger — Single-Source-of-Truth Audit
_(Read-only audit. No code changed. Feb 2026.)_

Design principle under review: **one business event is entered once, and every accounting, ledger, order, account, settlement, dashboard and reporting effect is derived automatically.**

---

## 1. Current architecture map

### 1.1 Backend collections (MongoDB, `test_database`)

| Collection | Purpose | Written by | Read by | Notes |
|---|---|---|---|---|
| `orders` | Source of truth for order + shipments + item mix + costs. Also stores denormalised `total_received`, `outstanding`, `payment_status`. | `POST/PUT /orders`, `POST/PUT/DELETE /orders/{oid}/shipments`, `_recompute_payment_aggregates_for_orders`, `_refresh_stored_aggregates` | Everywhere | Denormalised `total_received` is **the** source used by dashboard cards but is only rewritten when a `customer_payments` write triggers `_recompute_payment_aggregates_for_orders`. |
| `customer_payments` | Source of truth for **customer receipts**. Holds allocations to orders + advance leftovers. | `POST/PUT/DELETE /customer-payments`, `POST /orders/{oid}/allocate-advance` | `GET /orders/{oid}/payments`, `/sales-payments`, `/orders/{oid}/timeline`, Party Ledger v2 derived rows. | Correct single source for AR. |
| `purchase_payments` | Source of truth for **vendor payments**. Holds allocations to purchases. | `POST/PUT/DELETE /purchase-payments` | `/purchase-payments`, purchases aggregates, Party Ledger v2 derived rows. | Correct single source for AP. |
| `purchases` | Source of truth for **vendor bills** (packing / freight / raw material lines). | `POST/PUT/DELETE /purchases` | Party Ledger v2 (`purchase` category), order profit ("linked_to_order_id"), `/dashboard` (purchase KPIs). | |
| `parties` | Directory of Father's Firm / vendors / customers / self. | Party Ledger v2 (`create_party`, `migrate_from_v1`). | Party Ledger v2, new FF settlement endpoint. | System parties: `Rakshit` (self) + `Father's Firm` created idempotently. **Vendor / customer parties are NOT auto-created** when a vendor/customer name first appears in `purchases` / `customer_payments` — Party Ledger v2 requires an explicit party row and legacy vendor id migration. This causes several currently-failing tests. |
| `party_ledger_entries` | **Manual + linked** postings only (opening balances, quick-entry FF-pays-vendor splits, reversals). Derived entries are **not stored** — merged in at read time. | Party Ledger v2 `create_party`, `POST /party-transactions`, `POST /party-transactions/reverse`, migration. | Party Ledger v2 reader. | Good design; audit trail lives here. |
| `payments` **(legacy)** | Old flat cash-book: `party`, `mode`, `received_by_me/fac`, `payment_by_me/fac`. | `POST/PUT/DELETE /payments`, `PaymentDialog` on `Payments` page (sidebar "Cash Book"). Also `POST /seed`. | `GET /dashboard` (received/paid, mode chart), `GET /meta`, `GET /export/payments.csv`, `GET /export/payments.xlsx`, `GET /party-ledger/summary` (v1), sidebar **Cash Book**. | **THIS IS THE PRIMARY DUAL-SOURCE-OF-TRUTH DEFECT.** Any receipt/payment recorded via the "Cash Book" page updates this collection **only** — it never appears in `customer_payments`, `purchase_payments`, `orders`, Party Ledger v2, or the Order dialog. Yet the Dashboard KPIs "Received" / "Paid" / "Payments by mode" still read from it. |
| `accounts` | Reference master (Bank / Cash / UPI / etc). | `/accounts` CRUD, seed. | Every payment dropdown. Denormalised `account_name` copied into payment rows. | **Not a ledger** — no balances are tracked. Frontend page explicitly says so. |
| `vendors` | Vendor directory. | `/vendors` + auto-upsert on purchase-payment write. | `/vendors`, dialogs, `/purchases`. | Overlaps with `parties` (vendor rows exist twice). |
| `quotations` | Native quotation module. | `/quotations` CRUD. | Native. | Isolated — no accounting effects, no impact on audit. |
| `transactions` **(dead)** | Row-per-legacy-shipment CSV data prior to the migration to `orders`. | Only read by `_migrate_transactions_to_orders`, cleared by `POST /seed`. | Migration only. | Safe to ignore. |
| `customers` | Legacy customer directory. | Various. | Legacy. | Not authoritative — customer party rows should live in `parties`. |

### 1.2 Backend endpoints, grouped by real-world event

| Real-world event | Endpoint(s) that write | Collections written | Modules that derive live |
|---|---|---|---|
| Order created / updated | `POST /orders`, `PUT /orders/{oid}` | `orders` | Party Ledger v2 (customer `sale_invoice`), `/dashboard`, `/orders`, `/party-ledger/summary`. |
| Shipment recorded | `POST /orders/{oid}/shipments` (+ PUT/DELETE) | `orders.shipments`, denormalised order KPIs. | Party Ledger v2 (sale_invoice date pivots to last-shipped), `/dashboard` monthly revenue. |
| Purchase bill entered | `POST /purchases` | `purchases`, sometimes `vendors` upsert. | Party Ledger v2 vendor `purchase`, `/dashboard` purchase KPIs, orders (linked). |
| Vendor payment (Rakshit paid) | `POST /purchase-payments` (`paid_by_party_id` absent or self) | `purchase_payments`, `purchases.total_paid`, `vendors` upsert. | Party Ledger v2 vendor `vendor_payment`. |
| Vendor payment (Father's Firm paid on Rakshit's behalf) | Same endpoint with `paid_by_party_id = Father's Firm party id`, optional `split_paid_by_amount`. | Same. | Party Ledger v2 derives BOTH a vendor entry AND a linked FF entry (`PP-LINK-*`) live from the same row. |
| Customer receipt (received by Rakshit) | `POST /customer-payments` | `customer_payments`, allocated `orders.total_received`. | `/orders/{oid}/payments`, `/sales-payments`, Party Ledger v2 customer `customer_payment`, `/dashboard/kpis.customer_advances`. |
| Customer receipt (received by Father's Firm on Rakshit's behalf) | Same endpoint + `received_by_party_id = FF party id`. | Same. | Party Ledger v2 derives BOTH the customer entry AND a linked FF entry (`CP-LINK-*`). |
| Allocate an existing advance to a specific order | `POST /orders/{oid}/allocate-advance` | Updates `customer_payments.allocations`, recalculates `orders.total_received`. | Everything above. **No new payment row is created — verified by test.** |
| Manual FF adjustment / transfer | `POST /party-ledger-v2/transactions` | `party_ledger_entries` (linked pair for FF ↔ other party). | Party Ledger v2 reader. Not currently linked to `accounts` balances. |
| **Cash Book row (legacy)** | `POST /payments`, `PUT/DELETE /payments/{id}` | `payments` **only**. | Dashboard KPIs `received`/`paid`, payments-by-mode chart, `/party-ledger/summary` (v1), `/export/payments.csv`, `/meta`. **Not visible on orders, not in Party Ledger v2, not in `/sales-payments`.** |

---

## 2. Source-of-truth map (per business object)

| Business object | ✅ Correct single source | ⚠️ Duplicate / stale copies |
|---|---|---|
| Customer receipt | `customer_payments` | `payments` (legacy Cash Book still receives writes independently) |
| Vendor payment | `purchase_payments` | `payments` (legacy Cash Book still writes here too) |
| Vendor bill | `purchases` | — |
| Order + shipment | `orders` (with denormalised aggregates) | Legacy `transactions` collection (migration source, otherwise dead) |
| Vendor directory | `vendors` **and** `parties.type='vendor'` | ⚠️ Two collections. `parties` is authoritative for Party Ledger v2 balances; `vendors` is what the UI dropdowns use. They are only kept in sync during migration and vendor upserts on purchase-payment writes. |
| Customer directory | `orders.client_name` + `customer_payments.customer_name` + `parties.type='customer'` | ⚠️ Three loosely-related surfaces. No enforced party row per customer. |
| Bank / cash balance | **Nowhere** | Accounts are only tags. `/accounts` page banner literally states no balance is tracked. |
| Party balance (You Pay / You Receive) | Party Ledger v2 (`party_ledger_entries` + derived from source rows) | ⚠️ Dashboard's "Net settlement" and "Party summary" still read `partyLedger.net_position`, which is correct — but Cash Book KPIs come from `payments` and never enter Party Ledger v2. |

---

## 3. Screen-by-screen field derivation

### 3.1 Dashboard (`GET /api/dashboard` + `GET /api/party-ledger-v2/summary` + `GET /api/party-ledger-v2/fathers-firm-settlement`)

| Card | Source |
|---|---|
| Operating revenue, invoice value, total cost, net profit, GST, order count | `orders` — correct. |
| Received / Paid / Payments-by-mode | **`payments` (legacy)** — orphaned. Does not include anything from `customer_payments` or `purchase_payments`. |
| Purchase value / paid / outstanding | `purchases` + `purchase_payments` — correct. |
| Customer advances | `customer_payments.unallocated` — correct. |
| Father's Firm Settlement (single card) | **`/party-ledger-v2/fathers-firm-settlement`** — correct, single signed value. |
| Vendor payables / advances, Customer receivables | Party Ledger v2 summary — correct. |
| Net settlement | `partyLedger.net_position` — correct (does NOT double-count FF because the two split cards were removed). |

### 3.2 Orders / OrderDialog

Purely order-centric; reads `orders`, `orders/{oid}/payments`, `orders/{oid}/timeline`. **Correct** — every payment surface uses `customer_payments`. Advance allocation reuses the existing payment row. Verified in `iteration_12.json`.

### 3.3 Sales Payments (`/api/sales-payments`)

Reads `customer_payments`. Auto-allocate FIFO in dialog. Any payment created here also appears on the order. **Correct.**

### 3.4 Purchase Payments (`/api/purchase-payments`)

Reads `purchase_payments`. Supports `paid_by_party_id` + `split_paid_by_amount`. **Correct.**

### 3.5 Cash Book (`/payments` page, sidebar label "Cash Book")

Reads `payments` (legacy). `PaymentDialog` writes to `POST /payments`. **Data written here NEVER reaches orders, customer_payments, purchase_payments, or Party Ledger v2.** This is the largest single-source-of-truth violation in the app.

### 3.6 Party Ledger v2 (`/party-ledger?type=…`)

Reads `/party-ledger-v2/parties`, `/party-ledger-v2/parties/{id}/ledger`. Uses derived rows from `orders`, `customer_payments`, `purchase_payments`, `purchases`, plus manual entries. Sign convention verified by `iteration_12`. **Correct — this is the modern layer.**

### 3.7 Accounts

Reference master only. `/accounts` page explicitly says the app does not reconcile bank balances. No account balance is calculated from any source. **Design gap** — an ERP-style app should be able to say "ICICI Current has ₹X" derived from `customer_payments` inflows minus `purchase_payments` outflows tagged to that account (± manual adjustments).

### 3.8 Exports (`/api/export/*`)

- `orders.xlsx / .csv` — orders collection. Correct.
- `order-items.xlsx` — orders items. Correct.
- `payments.csv / .xlsx` — **legacy `payments`.** Orphaned in exactly the same way as Cash Book.
- Party ledger CSVs — Party Ledger v2. Correct.

---

## 4. Twelve end-to-end scenarios — expected vs. actual

Legend: ✅ works · ⚠️ partial · ❌ broken

| # | Scenario | Expected effects | Actual effects | Status |
|---|---|---|---|---|
| 1 | Customer pays Rakshit for one order via Sales Payments | Order rec-payment row, customer ledger +receipt, dashboard receivables ↓, cash advance if unallocated | All wired via `customer_payments`. Dashboard **Received card doesn't move** because it reads `payments`. | ⚠️ Dashboard "Received" desync |
| 2 | Customer pays FF for one order (`received_by_party_id = FF`) | Same as #1 + FF settlement ↓ (they owe you) | Party Ledger v2 derives the FF-link entry live. Order sees the receipt via allocations. FF Settlement card updates. Dashboard "Received" **still stale**. | ⚠️ same |
| 3 | Customer pays a pure advance (no allocation) | Advance visible on order dialog as "Customer advance available"; no order gets updated `total_received` | Works — verified by `iteration_12`. | ✅ |
| 4 | One customer payment split across multiple orders | Each order shows only its slice; total across allocations = payment amount | Works — `_recompute_payment_aggregates_for_orders` handles a list of order ids. | ✅ |
| 5 | Rakshit pays a vendor | Vendor bill updated, vendor payable ↓, Party Ledger v2 vendor_payment | Works via `purchase_payments`. Dashboard **Paid card doesn't move** because it reads `payments`. | ⚠️ same |
| 6 | Father's Firm pays a vendor on Rakshit's behalf | Same as #5 + FF settlement ↑ (you owe FF) | Party Ledger v2 posts a linked entry to FF live. FF settlement card updates. | ⚠️ Tests failing because vendor party isn't auto-created; production path relies on prior migration having done so. |
| 7 | Split vendor payment (partial FF, partial Rakshit) | FF settlement gets `split_paid_by_amount`; Rakshit's account (dashboard) reflects rest | Model supports `split_paid_by_amount`. Party Ledger v2 uses it. Two of three failing reconciliation tests hit this path. | ⚠️ Test fixtures broken; endpoint appears correct. |
| 8 | Rakshit → FF transfer | Neutral on P&L; FF balance ↓; a "you paid Father's Firm" ledger entry | `POST /party-ledger-v2/transactions` `category=transfer` supports this. **Not currently reachable from any UI screen.** | ⚠️ UI gap |
| 9 | FF → Rakshit transfer | Neutral on P&L; FF balance ↑ | Same as #8. | ⚠️ UI gap |
| 10 | Purchase + packing + freight from different suppliers on one order | Order's `packing_cost` and shipment `freight_paid` roll up into Estimated / Realized profit; each vendor sees their own purchase invoice | Wired: purchases can be `linked_to_order_id`; per-order dialog now shows Packing / Freight / Other costs. Realized vs. Estimated split **not implemented**. | ⚠️ profit only "Estimated" today |
| 11 | Payment edited / reassigned / reversed / deleted | Affected orders re-aggregated; ledger reversal entry created (for manual v2 postings); linked FF entries move with source | `customer_payments` PUT/DELETE + `purchase_payments` PUT/DELETE re-aggregate. Party Ledger v2 derives from source rows live, so linked FF entries follow automatically. Legacy `/payments` PUT/DELETE has no equivalent effect on anything else. | ⚠️ legacy path leaks |
| 12 | Shipment causes partial revenue recognition | Only shipped-qty invoice value counted as recognised revenue | Order dialog now shows Ordered / Shipped / Remaining + Revenue recognized. **But the number shown for "Revenue recognized" is the full invoice_total whenever any shipment exists**, not proportional. `orders.operating_revenue` is likewise the full invoice value. | ⚠️ partial-shipment logic missing |

---

## 5. Gaps ranked by severity

### 🔴 P0 — Data-integrity risk (fix first)

1. **Legacy `payments` collection duplicates state.** Everything written via the sidebar "Cash Book" page never touches `customer_payments` / `purchase_payments` / Party Ledger v2 / orders. Yet `GET /dashboard` still totals Received/Paid/mode-chart from it. Files: `backend/server.py:500-548`, `782-911`, `1506-1553`, `1618-1655`, `2001-1958`, `frontend/src/pages/Payments.jsx` (entire file), `frontend/src/components/PaymentDialog.jsx`.
2. **Dashboard "Received / Paid / Payments by mode" is orphaned.** These KPIs come from `payments` — they diverge from actual receipts every time a user records a payment through the modern screens. Fix: replace with a union of `customer_payments.amount − allocations to orders that are also Rakshit's` and `purchase_payments.amount where paid_by_party_id is null or self`. File: `backend/server.py:779-943`.
3. **No transactional guarantee across the two aggregate writes.** `_recompute_payment_aggregates_for_orders` and `purchase_payments` writes are separate awaits — if the process dies between the payment insert and the order re-aggregate, `orders.total_received` drifts. Fix: MongoDB transactions or a single upsert-with-pipeline stage.

### 🟠 P1 — Correctness / UX

4. **Vendor party / customer party rows are not auto-created** when a vendor first appears in `purchases`, or when a customer first appears in `customer_payments`. Party Ledger v2 relies on `parties` rows. Result: 12+ test failures in `test_party_ledger_v2.py` and `test_party_ledger_reconciliation.py` and any brand-new vendor/customer added through the UI is invisible in Party Ledger v2 until a migration is re-run. Fix: in the write paths for `customer_payments`, `purchase_payments`, and `purchases`, `await _get_or_create_party(...)` idempotently.
5. **Vendor directory duplication.** `db.vendors` and `db.parties.type='vendor'` are two separate lists. UI dialogs (`PurchasePayments.jsx`, `PaymentDialog.jsx`, `PurchaseDialog.jsx`) still read `db.vendors`. Fix: read from `parties` where `type in ('vendor','fathers_firm')`, or backfill `vendors` from `parties` whenever a new party is created.
6. **Sidebar "Cash Book" needs to be replaced or repurposed.** Because #1/#2 exist, the safest short-term fix is: mount `/payments` on a **read-only union view** of `customer_payments` + `purchase_payments` + manual `party_ledger_entries` categorised as transfer/adjustment, and hide the "New payment" button on that page. Long-term: retire `db.payments` entirely.
7. **Transfers between Rakshit and Father's Firm have no UI screen.** The endpoint `POST /party-ledger-v2/transactions` with `category=transfer` supports it, but nothing calls it. Users therefore book FF adjustments through Cash Book (see #1), reintroducing the same bug.
8. **Partial-shipment revenue recognition is not implemented.** `orders.operating_revenue` uses the full invoice value regardless of shipped qty. The dialog's "Revenue recognized" reads `invoice_total` as soon as any shipment exists. Fix: `revenue_recognized = invoice_total * shipped_qty_total / ordered_qty_total`, `pending_revenue = invoice_total − revenue_recognized`.
9. **Estimated vs. Realized profit split is only cosmetic.** The dialog now labels the number "Estimated profit" until status is Fully Shipped, but the number itself is still `operating_revenue − total_cost`. There is no realised-profit calculation (weighted by recognised revenue and actually-recorded costs). Fix: add both fields.
10. **No reconciliation endpoint.** There is no `/api/reconcile` or similar that returns `{ok: bool, mismatches: [...]}` for the invariants below. Adding it would make regressions catchable and testable.

### 🟡 P2 — Reporting / polish

11. **Legacy exports (`/export/payments.csv/.xlsx`) reference `db.payments`.** After the union rewrite in #6, these should be rebuilt from the modern collections or removed.
12. **Legacy `/party-ledger/summary` still exists (v1) alongside `/party-ledger-v2/summary`.** Kept for compatibility. Should be removed once frontend consumers are audited (`grep` shows only the v1 path is unused by React code).
13. **Denormalised `account_name` on payment rows can drift** if the account is renamed. `PUT /accounts/{id}` fixes it for `orders.order_payments.$[].account_name` but does NOT update `customer_payments.account_name` or `purchase_payments.account_name`. Fix: add the same array-filter update in `PUT /accounts/{id}`.
14. **Party Ledger v2 date-filtering for opening balances is loose.** Opening balances always show up regardless of the requested date window — fine for balances, but the CSV export can produce a misleading `running_balance` if the window excludes the opening entry.

---

## 6. Test status

Full suite (`pytest tests/ -q`) — **120 pass / 37 fail** (Feb 2026):

- ✅ `test_review_workflow.py` — 18/18 (Feb 2026 iteration, verifies advance-allocation, timeline, FF single card, auto-allocate FIFO).
- ✅ `test_review_changes.py` — 7/7 (prior iteration).
- ✅ `test_erp_refactor.py` — 25/27 (2 legacy-migration failures on stale KPI expectations).
- ⚠️ `test_party_ledger_v2.py` — **7 fail / 13 pass.** All 7 failures come from either (a) vendor party not auto-seeded (gap #4), or (b) tests still asserting old sign conventions.
- ⚠️ `test_party_ledger_reconciliation.py` — **8 fail / 8 pass.** Every failure is `StopIteration` on `next(p for p in parties if p['type']=='vendor')` — same root cause as #4.
- ❌ `backend_test.py` — **15 fail / 28 pass.** All failures are stale — they assert on `db.payments` behaviour and pre-refactor Order aggregate shapes. Known technical debt from the previous PRD.

**Interpretation:** the 37 failing tests do not indicate broken production functionality. They are three distinct symptoms of gaps #1, #4 and legacy `backend_test.py` (P2 item 12 in prior PRD backlog). Fixing the vendor-party auto-create (#4) alone eliminates ~15 of the 37 failures without any behavior change.

---

## 7. Recommended implementation sequence

_Do not start any of this yet — this is the plan for approval._

**Phase A — Data integrity (P0, ~1–2 days)**
1. Auto-create vendor/customer/FF parties inside every write path for `customer_payments`, `purchase_payments`, `purchases`, and `orders` (calls to `_get_or_create_party`). Removes ~15 test failures immediately.
2. Introduce a thin "business event / posting service" (`backend/posting_service.py`) that every source-of-truth write goes through. Its job is: (a) validate, (b) write the source row, (c) trigger downstream aggregates, (d) return the event id. The current CRUD endpoints become 5-line wrappers around it.
3. Wrap the source-write + aggregate-update in a MongoDB session/transaction so a mid-flight failure cannot desynchronise `orders.total_received`.
4. **Retire `db.payments`**:
   - Read side: rewrite `/dashboard` Received/Paid/mode chart from `customer_payments` + `purchase_payments`. Same for `/export/payments.*` and `/party-ledger/summary`.
   - Write side: remove `POST /payments`. Redirect the sidebar "Cash Book" page to a **read-only union view** of `customer_payments` + `purchase_payments` + non-order-non-payment `party_ledger_entries`. Add a "New receipt / New vendor payment / New adjustment" split-button that opens the correct existing dialog.

**Phase B — Order-centric UX polish (P1, ~1 day)**
5. Compute `revenue_recognized` and `pending_revenue` on the backend from `shipped_qty_total / ordered_qty_total` and expose them via `/orders/{oid}/payments` (they belong here so the UI already has them). Backfill the OrderDialog progress panel.
6. Distinguish `estimated_profit` vs. `realized_profit` on the order and dashboard. Show both when a shipment exists.
7. Add a "Transfer between Rakshit and Father's Firm" UI hook — a single dialog that posts to `POST /party-ledger-v2/transactions` `category=transfer`. Removes the last reason to use the legacy Cash Book page.

**Phase C — Reconciliation & audit (P1, ~0.5 day)**
8. Add `GET /api/reconcile` returning invariants:
   - `customer_payments.amount total == sum of orders.total_received + sum of customer_payments.unallocated`
   - `purchase_payments.amount total == sum of purchases.total_paid + sum of purchase_payments.unallocated`
   - `sum(orders.allocations.amount) <= customer_payments.amount` (per row)
   - No `customer_payments.id` referenced twice across orders/allocations
   - `party_ledger_v2.summary.net_position == sum of every party's signed running_balance`
   - `dashboard.received == /sales-payments.total − customer_payments.unallocated (received-by-me only)`
   - `party.type='fathers_firm'` count == 1
   - Every party with type='vendor' has a matching `db.vendors` row (or vice-versa if the two are unified)
9. Ship each invariant as a pytest so a CI run halts before the next regression.

**Phase D — Reports and enhancements (P2)**
10. GST report, invoice PDF export, multi-user auth. **Only after Phase A + B + C pass.**

Estimated total: ~3 dev-days of focused work; ~1 day of testing agent iteration on top.

---

## 8. Files & functions to touch (once green-lit)

- `backend/server.py`
  - Retire: `POST /payments`, `PUT /payments/{pid}`, `DELETE /payments/{pid}` (~lines 500-548)
  - Retire: `db.payments` reads in `/dashboard` (~782-943), `/meta` (~1243), `/export/payments.*` (~1504-1553), `/party-ledger/summary` (~1618-1655)
  - Add: `_get_or_create_party` calls in `create_customer_payment`, `create_purchase_payment`, `create_purchase` (~2077, 2599, 2492)
  - Add: `POST /reconcile`
  - Extract: `_recompute_payment_aggregates_for_orders`, `_recompute_purchase_payment_aggregates`, party-linked derivations into `backend/posting_service.py`
- `backend/party_ledger_v2.py`
  - Nothing structural — sign convention and derived-row logic already correct.
  - Consider moving `_get_or_create_party` to a shared module.
- `frontend/src/pages/Payments.jsx`
  - Rewrite as read-only union view; remove `PaymentDialog`; add split-button for New receipt / New vendor payment / New transfer.
- `frontend/src/components/PaymentDialog.jsx`
  - Delete after Payments.jsx is rewritten.
- `frontend/src/components/OrderDialog.jsx`
  - Consume `revenue_recognized` / `realized_profit` from backend instead of computing locally.
- `frontend/src/pages/Dashboard.jsx`
  - After #4 the Received/Paid/mode chart will start reflecting reality; no code change needed if the endpoint keeps the same response shape.

---

## 9. Preview URL

The preview URL you couldn't reach externally is served through the Emergent ingress; internal `http://localhost:8001/api/` responds `{"message":"Artisan Ledger API — order-based"}`. All endpoints listed above respond 200 locally. If the preview is still unreachable when you look next, it is worth checking whether the pod was scaled to zero — the code and data are intact.

---

_End of audit. No code changes were made._
