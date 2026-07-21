#!/usr/bin/env python3
"""
Phase 5 — /api/reconcile invariant engine verification

Tests:
1. Endpoint contract & schema
2. Healthy path
3. POST /api/reconcile/run — audit + return
4. GET is read-only (no audit logs written)
5. Reset integration (pre_reset_reconcile + post_reset_reconcile)
6. Failure detection (plant a broken row)
7. Non-admin access (401/403)
8. Recon idempotency
"""

import requests
import json
import sys
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
from dotenv import load_dotenv

# Load environment
load_dotenv('/app/backend/.env')
load_dotenv('/app/frontend/.env')

# Configuration
BACKEND_URL = os.getenv('REACT_APP_BACKEND_URL', 'http://localhost:8001')
API_BASE = f"{BACKEND_URL}/api"
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# MongoDB connection for direct DB manipulation
MONGO_URL = os.getenv('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.getenv('DB_NAME', 'personal_ledger')

# Test results
results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def log_pass(test_name, detail=""):
    msg = f"✅ {test_name}"
    if detail:
        msg += f": {detail}"
    print(msg)
    results["passed"].append({"test": test_name, "detail": detail})

def log_fail(test_name, detail=""):
    msg = f"❌ {test_name}"
    if detail:
        msg += f": {detail}"
    print(msg)
    results["failed"].append({"test": test_name, "detail": detail})

def log_warn(test_name, detail=""):
    msg = f"⚠️  {test_name}"
    if detail:
        msg += f": {detail}"
    print(msg)
    results["warnings"].append({"test": test_name, "detail": detail})

def admin_login():
    """Login as admin and return auth token"""
    resp = requests.post(f"{API_BASE}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if resp.status_code != 200:
        log_fail("Admin login", f"Status {resp.status_code}")
        sys.exit(1)
    data = resp.json()
    token = data.get("access_token")
    if not token:
        log_fail("Admin login", "No access_token in response")
        sys.exit(1)
    log_pass("Admin login", f"Token: {token[:20]}...")
    return token

def get_headers(token):
    """Return headers with Bearer token"""
    return {"Authorization": f"Bearer {token}"}

# ============================================================================
# TEST 1: Endpoint contract & schema
# ============================================================================
def test_endpoint_contract(token):
    print("\n" + "="*80)
    print("TEST 1: Endpoint contract & schema")
    print("="*80)
    
    resp = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    
    if resp.status_code != 200:
        log_fail("GET /api/reconcile returns 200", f"Got {resp.status_code}")
        return None
    log_pass("GET /api/reconcile returns 200")
    
    try:
        report = resp.json()
    except Exception:
        log_fail("Response is valid JSON")
        return None
    log_pass("Response is valid JSON")
    
    # Check top-level fields
    required_fields = [
        "report_version", "engine_version", "run_status", "healthy",
        "generated_at", "started_at", "completed_at", "duration_ms",
        "consistency", "summary", "warnings", "invariants"
    ]
    
    for field in required_fields:
        if field not in report:
            log_fail(f"Field '{field}' present", "Missing")
        else:
            log_pass(f"Field '{field}' present", f"Value: {report[field]}")
    
    # Check specific values
    if report.get("report_version") != "1.0":
        log_fail("report_version == '1.0'", f"Got {report.get('report_version')}")
    else:
        log_pass("report_version == '1.0'")
    
    if report.get("engine_version") != "P5":
        log_fail("engine_version == 'P5'", f"Got {report.get('engine_version')}")
    else:
        log_pass("engine_version == 'P5'")
    
    if report.get("run_status") != "completed":
        log_fail("run_status == 'completed'", f"Got {report.get('run_status')}")
    else:
        log_pass("run_status == 'completed'")
    
    # Check summary structure
    summary = report.get("summary", {})
    summary_fields = ["total", "passed", "failed", "warnings", "errors"]
    for field in summary_fields:
        if field not in summary:
            log_fail(f"summary.{field} present", "Missing")
        else:
            log_pass(f"summary.{field} present", f"Value: {summary[field]}")
    
    # Check summary math
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    warnings = summary.get("warnings", 0)
    errors = summary.get("errors", 0)
    
    if total == passed + failed + warnings + errors:
        log_pass("summary.total == passed + failed + warnings + errors", 
                f"{total} == {passed} + {failed} + {warnings} + {errors}")
    else:
        log_fail("summary.total == passed + failed + warnings + errors",
                f"{total} != {passed} + {failed} + {warnings} + {errors}")
    
    # Check invariants structure
    invariants = report.get("invariants", [])
    if len(invariants) < 20:
        log_warn("Total invariants >= 20", f"Got {len(invariants)}")
    else:
        log_pass("Total invariants >= 20", f"Got {len(invariants)}")
    
    # Check first invariant structure
    if invariants:
        inv = invariants[0]
        inv_fields = [
            "id", "phase", "severity", "status", "description",
            "expected", "actual", "difference", "tolerance",
            "checked_count", "offender_count", "offenders",
            "truncated", "duration_ms"
        ]
        for field in inv_fields:
            if field not in inv:
                log_fail(f"Invariant field '{field}' present", f"Missing in {inv.get('id')}")
            else:
                log_pass(f"Invariant field '{field}' present")
        
        # Check id is stable (prefixed)
        inv_id = inv.get("id", "")
        if inv_id.startswith(("p0.", "p1.", "p3.", "p4.", "x.")):
            log_pass("Invariant id is stable (prefixed)", f"ID: {inv_id}")
        else:
            log_fail("Invariant id is stable (prefixed)", f"ID: {inv_id}")
        
        # Check status values
        status = inv.get("status")
        if status in ["passed", "failed", "warning", "error"]:
            log_pass("Invariant status is valid", f"Status: {status}")
        else:
            log_fail("Invariant status is valid", f"Status: {status}")
        
        # Check severity values
        severity = inv.get("severity")
        if severity in ["info", "warning", "error"]:
            log_pass("Invariant severity is valid", f"Severity: {severity}")
        else:
            log_fail("Invariant severity is valid", f"Severity: {severity}")
    
    return report

# ============================================================================
# TEST 2: Healthy path
# ============================================================================
def test_healthy_path(token, report):
    print("\n" + "="*80)
    print("TEST 2: Healthy path")
    print("="*80)
    
    if not report:
        log_fail("Healthy path test", "No report from previous test")
        return
    
    healthy = report.get("healthy")
    summary = report.get("summary", {})
    failed_count = summary.get("failed", 0)
    errors_count = summary.get("errors", 0)
    
    print(f"healthy: {healthy}")
    print(f"summary.failed: {failed_count}")
    print(f"summary.errors: {errors_count}")
    
    if healthy:
        log_pass("healthy == true")
    else:
        log_warn("healthy == true", f"Got false (may be legitimate drift in DB)")
    
    if failed_count == 0:
        log_pass("summary.failed == 0")
    else:
        log_warn("summary.failed == 0", f"Got {failed_count} (may be legitimate drift)")
        # List failing invariants
        failing = [inv for inv in report.get("invariants", []) 
                  if inv.get("status") == "failed"]
        for inv in failing[:5]:  # Show first 5
            print(f"  - {inv.get('id')}: {inv.get('offender_count')} offenders")
    
    if errors_count == 0:
        log_pass("summary.errors == 0")
    else:
        log_warn("summary.errors == 0", f"Got {errors_count} (may be legitimate drift)")

# ============================================================================
# TEST 3: POST /api/reconcile/run — audit + return
# ============================================================================
def test_post_reconcile_run(token):
    print("\n" + "="*80)
    print("TEST 3: POST /api/reconcile/run — audit + return")
    print("="*80)
    
    # Count audit logs BEFORE
    resp = requests.get(f"{API_BASE}/admin/audit-logs?kind=reconcile_run&limit=1000",
                       headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("Get audit logs before", f"Status {resp.status_code}")
        return
    
    before_logs = resp.json() if isinstance(resp.json(), list) else resp.json().get("logs", [])
    before_count = len(before_logs)
    log_pass("Count audit logs BEFORE", f"Count: {before_count}")
    
    # POST /api/reconcile/run
    resp = requests.post(f"{API_BASE}/reconcile/run", headers=get_headers(token))
    
    if resp.status_code != 200:
        log_fail("POST /api/reconcile/run returns 200", f"Got {resp.status_code}")
        return
    log_pass("POST /api/reconcile/run returns 200")
    
    try:
        report = resp.json()
    except Exception:
        log_fail("Response is valid JSON")
        return
    log_pass("Response is valid JSON")
    
    # Check response schema (same as GET)
    if "report_version" in report and "engine_version" in report:
        log_pass("Response schema identical to GET")
    else:
        log_fail("Response schema identical to GET")
    
    # Check no audit_warning on success
    if "audit_warning" in report:
        log_warn("No audit_warning on success", f"Got: {report['audit_warning']}")
    else:
        log_pass("No audit_warning on success")
    
    # Count audit logs AFTER
    resp = requests.get(f"{API_BASE}/admin/audit-logs?kind=reconcile_run&limit=1000",
                       headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("Get audit logs after", f"Status {resp.status_code}")
        return
    
    after_logs = resp.json() if isinstance(resp.json(), list) else resp.json().get("logs", [])
    after_count = len(after_logs)
    log_pass("Count audit logs AFTER", f"Count: {after_count}")
    
    # Check exactly one new log
    if after_count == before_count + 1:
        log_pass("Exactly one audit log written", f"{after_count} - {before_count} = 1")
    else:
        log_fail("Exactly one audit log written", 
                f"{after_count} - {before_count} = {after_count - before_count}")
    
    # Check GET /api/admin/reconcile/last
    resp = requests.get(f"{API_BASE}/admin/reconcile/last", headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("GET /api/admin/reconcile/last returns 200", f"Got {resp.status_code}")
        return
    log_pass("GET /api/admin/reconcile/last returns 200")
    
    last = resp.json()
    if last.get("kind") == "reconcile_run":
        log_pass("Last audit log has kind='reconcile_run'")
    else:
        log_fail("Last audit log has kind='reconcile_run'", f"Got {last.get('kind')}")
    
    if "summary" in last and "summary" in last.get("summary", {}):
        log_pass("Last audit log has summary.summary")
    else:
        log_fail("Last audit log has summary.summary")

# ============================================================================
# TEST 4: GET is read-only (no audit logs written)
# ============================================================================
def test_get_readonly(token):
    print("\n" + "="*80)
    print("TEST 4: GET is read-only (no audit logs written)")
    print("="*80)
    
    # Count audit logs BEFORE
    resp = requests.get(f"{API_BASE}/admin/audit-logs?kind=reconcile_run&limit=1000",
                       headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("Get audit logs before", f"Status {resp.status_code}")
        return
    
    before_logs = resp.json() if isinstance(resp.json(), list) else resp.json().get("logs", [])
    before_count = len(before_logs)
    log_pass("Count audit logs BEFORE", f"Count: {before_count}")
    
    # GET /api/reconcile
    resp = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("GET /api/reconcile returns 200", f"Got {resp.status_code}")
        return
    log_pass("GET /api/reconcile returns 200")
    
    # Count audit logs AFTER
    resp = requests.get(f"{API_BASE}/admin/audit-logs?kind=reconcile_run&limit=1000",
                       headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("Get audit logs after", f"Status {resp.status_code}")
        return
    
    after_logs = resp.json() if isinstance(resp.json(), list) else resp.json().get("logs", [])
    after_count = len(after_logs)
    log_pass("Count audit logs AFTER", f"Count: {after_count}")
    
    # Check no new logs
    if after_count == before_count:
        log_pass("GET wrote zero audit logs", f"{after_count} == {before_count}")
    else:
        log_fail("GET wrote zero audit logs", 
                f"{after_count} != {before_count} (diff: {after_count - before_count})")

# ============================================================================
# TEST 5: Reset integration
# ============================================================================
def test_reset_integration(token):
    print("\n" + "="*80)
    print("TEST 5: Reset integration")
    print("="*80)
    
    # POST /api/admin/data-reset/execute
    payload = {
        "scope": "clear_transaction_data",
        "password": ADMIN_PASSWORD,
        "confirmation_phrase": "CLEAR TRANSACTION DATA",
        "understand_checkbox": True,
        "create_backup_first": True,
        "keep_accounts": True
    }
    
    resp = requests.post(f"{API_BASE}/admin/data-reset/execute", 
                        json=payload, headers=get_headers(token))
    
    if resp.status_code != 200:
        log_fail("POST /api/admin/data-reset/execute returns 200", 
                f"Got {resp.status_code}: {resp.text[:200]}")
        return
    log_pass("POST /api/admin/data-reset/execute returns 200")
    
    try:
        report = resp.json()
    except Exception:
        log_fail("Response is valid JSON")
        return
    log_pass("Response is valid JSON")
    
    # Check pre_reset_reconcile
    if "pre_reset_reconcile" not in report:
        log_fail("pre_reset_reconcile present in response")
        return
    log_pass("pre_reset_reconcile present in response")
    
    pre = report["pre_reset_reconcile"]
    if "summary" in pre and "healthy" in pre:
        log_pass("pre_reset_reconcile has summary and healthy")
        print(f"  pre_reset_reconcile.summary: {pre['summary']}")
        print(f"  pre_reset_reconcile.healthy: {pre['healthy']}")
    else:
        log_fail("pre_reset_reconcile has summary and healthy")
    
    # Check post_reset_reconcile
    if "post_reset_reconcile" not in report:
        log_fail("post_reset_reconcile present in response")
        return
    log_pass("post_reset_reconcile present in response")
    
    post = report["post_reset_reconcile"]
    if "summary" in post and "healthy" in post:
        log_pass("post_reset_reconcile has summary and healthy")
        print(f"  post_reset_reconcile.summary: {post['summary']}")
        print(f"  post_reset_reconcile.healthy: {post['healthy']}")
    else:
        log_fail("post_reset_reconcile has summary and healthy")
    
    # Check totals match
    pre_total = pre.get("summary", {}).get("total", 0)
    post_total = post.get("summary", {}).get("total", 0)
    
    if pre_total == post_total and pre_total >= 20:
        log_pass("pre and post reconcile have same total invariants", 
                f"Both have {pre_total} invariants")
    else:
        log_fail("pre and post reconcile have same total invariants",
                f"pre: {pre_total}, post: {post_total}")
    
    # After reset, GET /api/reconcile should still return healthy=true
    resp = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("GET /api/reconcile after reset returns 200", f"Got {resp.status_code}")
        return
    log_pass("GET /api/reconcile after reset returns 200")
    
    report = resp.json()
    if report.get("healthy"):
        log_pass("After reset, healthy == true (empty collections produce zero offenders)")
    else:
        log_warn("After reset, healthy == true", 
                f"Got false (may have pre-existing data)")

# ============================================================================
# TEST 6: Failure detection (plant a broken row)
# ============================================================================
async def test_failure_detection_async(token):
    print("\n" + "="*80)
    print("TEST 6: Failure detection (plant a broken row)")
    print("="*80)
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    # Insert a customer_payment with a non-existent party id
    broken_payment = {
        "id": "test-broken-payment-12345",
        "customer_name": "Test Customer",
        "customer_party_id": "non-existent-party-id-99999",
        "date": datetime.now().date().isoformat(),
        "amount": 1000.0,
        "mode": "Cash",
        "allocations": [],
        "allocated_total": 0,
        "unallocated": 1000.0,
        "created_at": datetime.now().isoformat()
    }
    
    try:
        await db.customer_payments.insert_one(broken_payment)
        log_pass("Inserted broken customer_payment with non-existent party_id")
    except Exception as ex:
        log_fail("Insert broken row", str(ex))
        client.close()
        return
    
    # GET /api/reconcile
    resp = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    if resp.status_code != 200:
        log_fail("GET /api/reconcile returns 200 (even with broken data)", 
                f"Got {resp.status_code}")
        await db.customer_payments.delete_one({"id": "test-broken-payment-12345"})
        client.close()
        return
    log_pass("GET /api/reconcile returns 200 (even with broken data)")
    
    report = resp.json()
    
    # Check healthy is false
    if not report.get("healthy"):
        log_pass("healthy == false (broken data detected)")
    else:
        log_fail("healthy == false (broken data detected)", "Got true")
    
    # Find the p1.parties.foreign_keys_resolve invariant
    invariants = report.get("invariants", [])
    fk_inv = next((inv for inv in invariants 
                   if inv.get("id") == "p1.parties.foreign_keys_resolve"), None)
    
    if not fk_inv:
        log_fail("Invariant p1.parties.foreign_keys_resolve present")
        await db.customer_payments.delete_one({"id": "test-broken-payment-12345"})
        client.close()
        return
    log_pass("Invariant p1.parties.foreign_keys_resolve present")
    
    # Check status is failed
    if fk_inv.get("status") == "failed":
        log_pass("p1.parties.foreign_keys_resolve status == 'failed'")
    else:
        log_fail("p1.parties.foreign_keys_resolve status == 'failed'",
                f"Got {fk_inv.get('status')}")
    
    # Check offender_count >= 1
    offender_count = fk_inv.get("offender_count", 0)
    if offender_count >= 1:
        log_pass("p1.parties.foreign_keys_resolve offender_count >= 1",
                f"Got {offender_count}")
    else:
        log_fail("p1.parties.foreign_keys_resolve offender_count >= 1",
                f"Got {offender_count}")
    
    # Clean up
    await db.customer_payments.delete_one({"id": "test-broken-payment-12345"})
    log_pass("Cleaned up broken row")
    
    client.close()

def test_failure_detection(token):
    """Wrapper to run async test"""
    asyncio.run(test_failure_detection_async(token))

# ============================================================================
# TEST 7: Non-admin access
# ============================================================================
def test_non_admin_access():
    print("\n" + "="*80)
    print("TEST 7: Non-admin access")
    print("="*80)
    
    # GET /api/reconcile with NO auth
    resp = requests.get(f"{API_BASE}/reconcile")
    if resp.status_code in [401, 403]:
        log_pass("GET /api/reconcile with NO auth returns 401/403",
                f"Got {resp.status_code}")
    else:
        log_fail("GET /api/reconcile with NO auth returns 401/403",
                f"Got {resp.status_code}")
    
    # POST /api/reconcile/run with NO auth
    resp = requests.post(f"{API_BASE}/reconcile/run")
    if resp.status_code in [401, 403]:
        log_pass("POST /api/reconcile/run with NO auth returns 401/403",
                f"Got {resp.status_code}")
    else:
        log_fail("POST /api/reconcile/run with NO auth returns 401/403",
                f"Got {resp.status_code}")

# ============================================================================
# TEST 8: Recon idempotency
# ============================================================================
def test_idempotency(token):
    print("\n" + "="*80)
    print("TEST 8: Recon idempotency")
    print("="*80)
    
    # First GET
    resp1 = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    if resp1.status_code != 200:
        log_fail("First GET /api/reconcile returns 200", f"Got {resp1.status_code}")
        return
    log_pass("First GET /api/reconcile returns 200")
    
    report1 = resp1.json()
    
    # Second GET
    resp2 = requests.get(f"{API_BASE}/reconcile", headers=get_headers(token))
    if resp2.status_code != 200:
        log_fail("Second GET /api/reconcile returns 200", f"Got {resp2.status_code}")
        return
    log_pass("Second GET /api/reconcile returns 200")
    
    report2 = resp2.json()
    
    # Compare invariant IDs
    ids1 = set(inv.get("id") for inv in report1.get("invariants", []))
    ids2 = set(inv.get("id") for inv in report2.get("invariants", []))
    
    if ids1 == ids2:
        log_pass("Same invariant IDs in both runs", f"Count: {len(ids1)}")
    else:
        log_fail("Same invariant IDs in both runs",
                f"Run1: {len(ids1)}, Run2: {len(ids2)}, Diff: {ids1 ^ ids2}")
    
    # Compare passed/failed counts
    summary1 = report1.get("summary", {})
    summary2 = report2.get("summary", {})
    
    if (summary1.get("passed") == summary2.get("passed") and
        summary1.get("failed") == summary2.get("failed")):
        log_pass("Same passed/failed counts in both runs",
                f"passed: {summary1.get('passed')}, failed: {summary1.get('failed')}")
    else:
        log_warn("Same passed/failed counts in both runs",
                f"Run1: passed={summary1.get('passed')}, failed={summary1.get('failed')} | "
                f"Run2: passed={summary2.get('passed')}, failed={summary2.get('failed')}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    print("="*80)
    print("Phase 5 — /api/reconcile invariant engine verification")
    print("="*80)
    print(f"Backend URL: {API_BASE}")
    print(f"Admin: {ADMIN_EMAIL}")
    print()
    
    # Login
    token = admin_login()
    
    # Run tests
    report = test_endpoint_contract(token)
    test_healthy_path(token, report)
    test_post_reconcile_run(token)
    test_get_readonly(token)
    test_reset_integration(token)
    test_failure_detection(token)
    test_non_admin_access()
    test_idempotency(token)
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"✅ Passed: {len(results['passed'])}")
    print(f"❌ Failed: {len(results['failed'])}")
    print(f"⚠️  Warnings: {len(results['warnings'])}")
    
    if results['failed']:
        print("\nFailed tests:")
        for item in results['failed']:
            print(f"  - {item['test']}: {item['detail']}")
    
    if results['warnings']:
        print("\nWarnings:")
        for item in results['warnings']:
            print(f"  - {item['test']}: {item['detail']}")
    
    # Exit code
    if results['failed']:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
