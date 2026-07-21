# Artisan Personal Ledger — PRD

## Origin
Repository `raksagarwal325-code/Personal-Ledger` cloned and continued as a full-stack ERP (FastAPI + MongoDB + React).

## Current mission
Multi-phase refactor to make Cash Book a unified timeline sourced from canonical modules and remove dual sources-of-truth for money movement. Phases:
1. **P0 — Retire legacy `db.payments`** *(shipped Feb 2026)*
2. **P1 — Auto-create parties + resolve `vendors` / `parties` duplication** *(shipped Feb 2026)*
3. **P1 — Transfer UI (Rakshit ↔ Father's Firm, bank ↔ cash, account ↔ account)** *(shipped Feb 2026)*
4. **P1 — Partial-shipment revenue + Estimated vs Realized profit** *(shipped Jul 2025)*
5. **P2 — `/api/reconcile` + invariant tests** *(shipped Jul 2025 · APPROVED and CLOSED Jul 2025)*
6. **P2 — Shared Domain Calculation Consolidation** — *in progress (Jul 2026)*.
   - **Slice 1** *(2026-07-21)*: additive helpers in `backend/domain.py` + 65-test unit/property/mutation-protection suite + CI-guard baseline (float=70, round=67, reversed_ne=3, source_ne=5). Zero callers switched.
   - **Slice 2** *(2026-07-21)*: `dashboard()` + `dashboard_breakdown()` in `server.py` now derive `received`, `paid`, `customer_advances`, `purchase_paid`, `modes`, and `payable` through `sum_received_kpi`/`sum_paid_kpi`/`sum_mode_totals`/`compute_party_metrics`. Active-record filtering delegated to `is_customer_payment_active`/`is_purchase_payment_active`/`is_cash_book_entry_canonical`. Byte-equivalent (paise) response preserved; frontend unaffected. CI baselines decremented: float 70→56, reversed_ne 3→1, source_ne 5→3. 13 new Slice-2 tests (synthetic golden-master + property + live-seed snapshot + endpoint-thinness). Reconcile still healthy 21/21, engine_version=P5.
   - **Slice 3** *(2026-07-21)*: `compute_order_aggregates` in `server.py` refactored into a thin adapter over `order_realized_amounts` + `order_estimated_amounts` + `order_unrealized`. Domain's `order_shipped_ratio_per_item` un-clamped to preserve pre-refactor linear scaling on over-shipment. 33 new Slice-3 tests covering 9 edge-case fixtures (zero/partial/full/over-shipment, zero-qty, missing values, cancelled, tax auto+manual), 14 property + idempotency tests, 3 input-mutation-contract tests, 1 live-seed golden-master. CI baselines decremented: float 56→53 (−3), **round 67→66 (first decrement)**. Live 47-order seed byte-equivalent in paise (0 diffs), reconcile still healthy 21/21.
   - **Awaiting sign-off** before Slice 4 (payment-aggregate recompute + purchase twin).

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

## What's been implemented (Jul 2025 · Phase 5 · P2 /api/reconcile invariant engine)
### Backend
- `backend/domain.py` (new) — shared domain calculation helpers. Every monetary
  value flows through `to_paise(x)` / `from_paise(n)` (Decimal, HALF_UP) so
  comparisons are exact. `money_eq(a, b, tol_paise=1)` is the paise-safe
  equality primitive. Active-record filters are single-sourced here:
  `is_order_active` (excludes Cancelled), `is_customer_payment_active` and
  `is_purchase_payment_active` (exclude voided/reversed),
  `is_cash_book_entry_canonical` (excludes legacy_shim, reversed, migrated
  transfers), `is_transfer_active` (excludes reversed), `is_account_active`
  (excludes archived). Canonical KPI sums: `sum_received_kpi`,
  `sum_paid_kpi`, `sum_mode_totals` (blank/None mode goes into the ""
  sentinel bucket for warning reporting), `sum_allocations_to_order`,
  `sum_allocations_to_purchase`.
- `backend/reconcile.py` (new) — 21 invariants across P0/P1/P3/P4/X:
    P0.payments.legacy_stamped, P0.modes.no_unknown_mode,
    P0.cashbook.ids_unique, P0.cashbook.transfer_appears_once,
    P1.parties.unique_active, P1.parties.normalized_names_current,
    P1.parties.system_ff_intact, P1.parties.ff_aliases_only_system,
    P1.parties.foreign_keys_resolve, P1.vendors.party_id_resolves,
    P3.transfers.sides_valid, P3.transfers.reversals_valid,
    P3.transfers.replacement_no_cycle, P3.transfers.idempotency_keys_unique,
    P3.transfers.migration_no_dupes, P3.transfers.a2a_net_zero,
    P4.orders.identities,
    X.cust_alloc.order_resolves, X.cust_alloc.nonneg_capped_and_cached,
    X.orders.total_received_matches, X.purchase_alloc.and_totals.
  Report contract: `report_version="1.0"`, `engine_version="P5"`, top-level
  `healthy`, `run_status`, `generated_at/started_at/completed_at/duration_ms`,
  `consistency` ∈ {stable, best_effort}, `warnings` list including
  `concurrent_modification` when collection sizes change during a run.
  Per-invariant fields: `id, phase, severity, status, description, expected,
  actual, difference, tolerance, checked_count, offender_count, offenders
  (capped 50), truncated, duration_ms`. Every invariant runs in a
  try/except so a broken check emits `status="error"` with traceback
  captured — never poisons the whole report.
- `backend/server.py`:
  - `GET /api/reconcile` — admin-gated, read-only, zero writes.
  - `POST /api/reconcile/run` — runs reconcile then writes exactly one
    `admin_audit_logs` row (`kind="reconcile_run"`). If the audit write
    fails the report is still returned with an `audit_warning` field.
  - `GET /api/admin/reconcile/last` — most recent reconcile_run row.
  - `POST /api/admin/data-reset/execute` now snapshots reconciliation
    BEFORE and AFTER the destructive operation, attaching
    `pre_reset_reconcile` and `post_reset_reconcile` summaries to the
    response + audit trail.

### Frontend
- `AdminDataManagement.jsx` — new `ReconciliationCard` component:
  HEALTHY / ISSUES FOUND badge, last-run timestamp + duration, per-status
  counters (Total / Passed / Failed / Warnings / Errors), warnings row
  (concurrent_modification etc.), and one collapsible row per non-passed
  invariant with expected/actual/difference/tolerance/checked/duration
  + offender JSON + "Copy ids" clipboard button.

### Tests
- `backend/tests/test_p5_reconcile.py` (new) — **20/20 pass**:
  domain helpers (paise + 1-paise tolerance); report contract
  (stable ids, versions, schema, HTTP 200 on unhealthy); active-record
  filters (cancelled order + reversed transfer excluded); cash-book
  (unstamped legacy transfer, duplicate ids, blank mode warning);
  transfers (reversal-amount mismatch, replacement-chain cycle,
  idempotency uniqueness at DB-index level); allocations (overflow,
  cached-total drift, orders.total_received drift); truncation at 50
  offenders + `truncated=true`; GET writes zero audit rows, POST writes
  exactly one, unauth returns 401/403.
- testing_agent independent verification (Jul 2025): **81/81 checks
  passed** — 8 groups: endpoint contract & schema, healthy path,
  POST/audit, GET/read-only, reset integration (pre + post reconcile
  attached), failure detection via planted broken row, non-admin auth,
  idempotency across consecutive runs. No regressions.

## What's been implemented (Jul 2025 · Phase 4 · P1 Partial-shipment revenue + Estimated vs Realized)
### Backend
- `backend/server.py::compute_order_aggregates` extended: on every order it now
  computes BOTH the realized (shipped-qty-proportioned) and the estimated
  (full-order) revenue / cost / profit. `ratio = shipped_qty / ordered_qty` is
  applied to `product_sales` + each item's `factory_*` and `outside_*` costs.
  Freight, packing, and other adjustments are event-recorded and included
  as-is in both realized and estimated (they are not proportioned).
- New fields on the `Order` model (defaults 0, backfilled idempotently on
  startup by `_refresh_stored_aggregates`):
  `estimated_factory_cost_total`, `estimated_outside_cost_total`,
  `estimated_operating_revenue`, `estimated_total_cost`,
  `estimated_net_profit`, `estimated_margin_percent`,
  `realized_revenue` (alias of `operating_revenue`),
  `realized_net_profit` (alias of `net_profit`),
  `revenue_recognized` (PRD-mandated name = `operating_revenue`),
  `unrealized_revenue`, `unrealized_net_profit`.
- `product_sales_total` is now declared on the `Order` model too (previously it
  was written to Mongo but stripped from `response_model=Order` responses).
- `/api/dashboard` KPIs additionally expose `estimated_revenue`,
  `estimated_total_cost`, `estimated_net_profit`, `estimated_margin_percent`,
  `realized_revenue`, `realized_net_profit`, `revenue_recognized`,
  `unrealized_revenue`, `unrealized_net_profit`. `operating_revenue` and
  `net_profit` remain unchanged (they are realized values).

### Frontend
- `frontend/src/pages/Dashboard.jsx` — renamed "Net Profit" card to
  "Realized Profit" and added a new second KPI row: Estimated Revenue,
  Estimated Profit (with margin + unrealized delta), and Unrealized (in transit).
- `frontend/src/pages/Orders.jsx` — table now has `Realized Rev`, `Est. Rev`,
  `Realized Profit`, `Est. Profit` columns. Est. Profit cell also shows the
  `+X unrealized` delta in terracotta. Summary tiles show both realized and
  estimated totals. Each expanded row has a "Revenue recognition" card with
  realized/estimated revenue + profit + margin + shipment progress, and an
  unrealized-profit warning line.

### Tests
- New `backend/tests/test_p4_partial_shipment_revenue.py` — **6/6 pass**:
  - no shipment → realized=0, estimated>0, unrealized == estimated.
  - full shipment → realized == estimated, unrealized == 0.
  - 60% shipment → product sales + factory + outside costs proportioned by
    ratio; freight and packing NOT proportioned.
  - Adding a shipment reduces unrealized_net_profit.
  - Dashboard exposes all Phase 4 KPI fields and honours the alias identities
    (`realized_revenue == operating_revenue`, `revenue_recognized ==
    operating_revenue`, `unrealized_net_profit == estimated_net_profit -
    net_profit`).
- testing_agent_v3 independent verification (Jul 2025): 17/17 assertions
  passed across three synthetic orders (no shipment, 40% partial, full) with
  exact expected numbers; every existing endpoint (dashboard, orders,
  customer-payments, purchase-payments, dashboard/breakdown, auth/status)
  still returns 200; no regression.

## What's been implemented (Feb 2026 · Phase 3 · P1 First-Class Transfers)
### Backend
- New `db.transfers` collection with `Transfer` / `TransferIn` / `TransferSide` models in `/app/backend/transfers.py`. `db.transfers` is the **sole source of truth** for every transfer event. Account balances and Father's Firm settlement are DERIVED projections — never stored.
- Endpoints:
  - `POST /api/transfers` — create (with optional `Idempotency-Key`).
  - `GET /api/transfers` — filter by kind, account_id, party_id, date range; `include_reversed=true|false`.
  - `GET /api/transfers/{id}` — read one.
  - `PUT /api/transfers/{id}` — edit via **reverse + replace** (original stays immutable, `status='reversed'`).
  - `POST /api/transfers/{id}/reverse` — immutable reversal (creates paired transfer with swapped sides).
  - `DELETE /api/transfers/{id}` — alias for `/reverse`; never a hard delete.
  - `GET /api/accounts/{id}/balance` — derived balance (opening + cust/purchase payments + non-transfer cash-book entries ± transfers).
  - `POST /api/transfer-migration/run` — idempotent legacy → canonical migration.
- Kinds:
  - `account_to_account` — Rakshit-account ↔ Rakshit-account (bank↔cash, bank↔bank, etc.). Net tracked-cash = 0.
  - `rakshit_to_ff` — from Rakshit account to `system_fathers_firm`. Tracked cash −X; FF settlement +X (signed).
  - `ff_to_rakshit` — from `system_fathers_firm` to Rakshit account. Tracked cash +X; FF settlement −X.
- Idempotency: sparse unique index on `idempotency_key` + `legacy_cbe_id`. Duplicate submissions return the original document.
- Validations enforced server-side: positive amount, distinct sides, non-archived accounts, only `system_fathers_firm` party allowed.
- Reversal is IMMUTABLE — reversal docs cannot themselves be reversed or edited. Reversal is blocked only by DIRECT document dependencies (`depends_on_transfer_ids`), never by unrelated later transfers on the same account.
- Cash Book projection: `db.transfers` emits ONE canonical row per transfer; any legacy `cash_book_entries[kind='transfer']` stamped with `migrated_to_transfer_id` is suppressed to prevent duplicates.
- Dashboard KPIs (`received`, `paid`, `modes`, `net_profit`) explicitly exclude transfers (`kind != transfer` filter added on `cash_book_entries`).
- FF settlement projection (`GET /api/party-ledger-v2/fathers-firm-settlement`) folds in `ff_settlement_delta_from_transfers(db)`.
- Legacy `POST /api/cash-book-entries` with `kind='transfer'` auto-forwards to `POST /api/transfers` and returns a synthetic `CashBookEntry`-shaped envelope for UI back-compat.
- Startup: `ensure_transfer_indexes` + `run_transfer_migration` (idempotent, deterministic on `legacy_cbe_id`).
- MongoDB standalone verified — **no multi-doc transactions**. Design commits one atomic `db.transfers` insert and derives all views idempotently on read.

### Tests
- New `tests/test_p3_transfers.py` — **17/17 pass** (validations, account-to-account, Rakshit↔FF sign convention with numeric examples, idempotency, reversal restores balances, reversal is immutable, edit = reverse + replace, delete = alias, no-block on unrelated later transfer, Cash Book emits one row per transfer, `/cash-book-entries kind=transfer` auto-forward).
- testing_agent_v3 verified: `retest_needed=false`, `backend_issues={critical:[], minor:[]}`, `action_items=[]`.
- Full suite: **187 pass** (baseline 137/36 → **+50 pass** across Phases 1-3).

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

## Test status (Feb 2026 · post-Phase 2)
| File | Before P0 | After P0 | After P1 | Notes |
|---|---|---|---|---|
| `test_p0_canonical_cashbook.py` | — | **9/9** | **9/9** | KPI derivation, transfer neutrality, shim non-counting, business events, export column |
| `test_p1_party_auto_create.py` (**new**) | — | — | **14/14** | Stamps, normalization, Factory→FF, rename, migration idempotency, conflict reporting, concurrency |
| Testing-agent supplementary `test_p1_party_review_extras.py` | — | — | **6/6** | System-party rename block + GET system party |
| `test_party_ledger_v2.py` | 7 fail | 0 fail | 0 fail | ✅ all pass |
| `test_party_ledger_reconciliation.py` (isolation) | 8 fail | 2 fail | 0 fail | ✅ all pass in isolation; xdist ordering can still flake 2 |
| `test_review_workflow.py` (isolation) | 1 fail | 0 fail | 0 fail | ✅ dashboard consistency stable in isolation |
| `test_purchase_sources.py` | 0 fail | 0 fail | 0 fail | unchanged |
| `backend_test.py` (legacy tech debt per audit §6 P2) | 20 fail | 19 fail | 19 fail | asserts on pre-refactor db.payments Cash Book KPIs — out of scope |
| `test_erp_refactor.py::TestLegacyMigration` | 2 fail | 2 fail | 2 fail | asserts on old legacy-based dashboard KPIs (design change) |
| `test_purchases_and_bugs.py::test_dashboard_legacy_kpis_intact` | fail | fail | fail | same |
| **Full suite (xdist parallel)** | 137 pass / 36 fail | 158/24 | **170/26** | +33 pass overall; the 26 remaining are all pre-existing tech debt or xdist-order flakes |

## Prioritized backlog
- **P2 — Phase 5** *(next)*: `/api/reconcile` invariant endpoint + pytest suite.
  Read-only integrity endpoint that runs every phase-1..4 invariant and
  returns a structured report. Pre-implementation report was delivered to
  the user in Jul 2025 (see chat log). Design summary:
  * Endpoint: `GET /api/reconcile` (+ `POST /api/reconcile/run` alias for admin UI).
  * Response: `{ok: bool, generated_at, invariants: [{id, description, ok, details, offenders?}], summary: {total, passed, failed}}`.
  * Invariants covered:
      P0/P1: Dashboard KPIs `received`, `paid`, `modes` derive only from
             canonical sources (no `db.payments source='legacy_shim'` rows counted),
             `db.payments` legacy rows all stamped, no orphan `legacy_shim`.
      P1:    `parties` unique index holds (no duplicate normalized names within a
             party type); every `customer_payments.customer_party_id` and
             `purchases.vendor_party_id` (when set) references an existing party;
             `system_fathers_firm` party exists and is type='self'.
      P3:    For every `account_to_account` transfer, sum(from) + sum(to) == 0 on
             tracked cash across all accounts; `db.transfers[status='reversed']` has
             a paired `reverses_transfer_id`; every `cash_book_entries[kind=transfer]`
             that predates the P3 migration has `migrated_to_transfer_id` set;
             FF `balance_signed` equals the composition of derived party ledger v2
             entries + `ff_settlement_delta_from_transfers`.
      P4:    For every order: `operating_revenue + unrealized_revenue ≈
             estimated_operating_revenue` and `net_profit + unrealized_net_profit
             == estimated_net_profit`. Realized costs ≤ estimated costs. Dashboard
             `unrealized_net_profit == estimated_net_profit - net_profit`.
      Cross: Every `customer_payments.allocations[].order_id` resolves to a real
             order; `orders[].total_received` == sum of allocations for that order.
             Every `purchase_payments.allocations[].purchase_id` resolves.
  * Pytest: `backend/tests/test_p5_reconcile.py` — seeded fixtures produce
    a `passed_all=true` report; deliberately corrupted fixture triggers each
    invariant.
- **P2 — Phase 5**: `/api/reconcile` invariant endpoint + pytest suite.
- **P2 — Phase 6 (Admin Data Management + Auth)** — ships **last**, after Phase 5. Approved architecture:
  - **Auth**: JWT-based custom (email + password + bcrypt + role field). First admin created via one-time `POST /api/admin/bootstrap` (rejects once ≥1 admin exists). All admin endpoints re-verify the JWT + `role='admin'` server-side; frontend hiding is not sufficient.
  - **Environment gate**: `ALLOW_ADMIN_DATA_RESET` defaults to `false` everywhere. Server rejects reset endpoints when false. Production additionally requires today's date embedded in the confirmation phrase.
  - **Two scoped actions**:
    - *Clear Transaction Data*: deletes orders/quotations/shipments/purchases/customer-payments/purchase-payments/cash-book-entries/party-ledger transaction rows/customer advances + cached aggregates. Preserves admin users, business/company settings, Father's Firm party, accounts (opt-out), customers, vendors, products, categories, GST/invoice settings, numbering, config.
    - *Full Application Reset*: everything except admin auth + essential system records. After reset, mandatory system records (Father's Firm, default admin, required categories) are recreated. Never deletes the currently-authenticated admin.
  - **Optional module-scoped delete** with orphan-reference validation (deleting customers requires cascading orders/payments; no partial delete leaves orphans).
  - **Safety gate**: admin password re-entry, exact record-count preview, exact confirmation phrase (`CLEAR TRANSACTION DATA` / `FULL RESET SAMRAT GLASS ERP`), "I understand" checkbox, 5-second countdown, plus stronger visuals for Full Reset. Never on mobile quick-actions.
  - **Dry-run**: `POST /api/admin/data-reset/preview` returns collections affected, records to be deleted, records to be preserved, dependency warnings, orphan risks, estimated backup size. UI must call this before enabling confirmation.
  - **Backup (hybrid)**: primary destination = **Emergent Object Storage** (survives container rebuilds); secondary = local `/app/backups/` fallback when object storage is unavailable + always offer a browser download of the same JSON/ZIP artifact. Metadata stored in `db.admin_backups`: `backup_id`, `created_by`, `created_at`, `application_version`, `schema_version`, `erp_version`, `collections`, `record_counts`, `size_bytes`, `sha256`, `storage_location`. Reset aborts if backup verification fails.
  - **Backup History page**: Download / Restore (admin only) / Delete (admin only, with confirmation).
  - **Execution service** (`backend/services/admin_reset_service.py`): acquires an exclusive reset lock (`db.admin_locks`), uses MongoDB transactions where supported, rolls back on any critical failure, clears cached aggregates, rebuilds mandatory system records, resets derived balances, re-runs `/api/reconcile`, and returns a full reset report.
  - **Audit log** (`db.admin_audit_logs`, immune to Clear Transaction Data): admin, timestamp, IP/session, scope, confirmation-phrase validation, backup id, success/failure, deleted counts.
  - **Test-mode helper**: `POST /api/admin/load-test-dataset` seeds records stamped `is_test_data=true` + shared `test_dataset_id` covering Factory purchase, outside vendors, customer advance, partial payment, FF-receives-customer-money, FF-pays-vendor, Rakshit↔FF transfer, partial shipment, estimated/realized profit. `DELETE /api/admin/test-dataset/{id}` removes only that dataset.
  - **Tests**: non-admin rejection, wrong-phrase rejection, env-flag rejection, preview-does-not-delete, transaction-clear preserves setup, full-reset preserves active admin, backup failure blocks deletion, mid-op rollback, concurrent-reset rejection, reconciliation zero-balance post-reset, audit rows survive transaction clear, no orphan references after any scope.
  - MUST call `integration_playbook_expert_v2` before writing any auth code (per platform rules).
- **P2**: Refresh stale `backend_test.py`. GST report / Invoice PDF export. Multi-user (beyond admin).
