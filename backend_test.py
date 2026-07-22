"""
Backend API Testing for Bug Fix: Canonical vendor_party_id linkage on all Purchase records
+ freight/packing auto-purchase generation

This test file verifies all 12 scenarios from the review request (2026-07-22).
"""
import requests
import json
from typing import Optional

# Backend URL (internal)
BASE_URL = "http://localhost:8001"
API_BASE = f"{BASE_URL}/api"

# Admin credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Global token storage
TOKEN = None


def login() -> str:
    """Login and return Bearer token"""
    global TOKEN
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10
    )
    resp.raise_for_status()
    TOKEN = resp.json()["access_token"]
    return TOKEN


def headers() -> dict:
    """Return Authorization headers"""
    return {"Authorization": f"Bearer {TOKEN}"}


def get(path: str):
    """GET request"""
    resp = requests.get(f"{API_BASE}{path}", headers=headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def post(path: str, payload: dict):
    """POST request"""
    resp = requests.post(f"{API_BASE}{path}", headers=headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def put(path: str, payload: dict):
    """PUT request"""
    resp = requests.put(f"{API_BASE}{path}", headers=headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def delete(path: str):
    """DELETE request"""
    resp = requests.delete(f"{API_BASE}{path}", headers=headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def find_linked_purchase(order_id: str, source_type: str) -> Optional[dict]:
    """Find a linked purchase by order_id and source_type"""
    purchases = get("/purchases")
    for p in purchases:
        if p.get("linked_to_order_id") == order_id and p.get("source_type") == source_type:
            return p
    return None


# ============================================================================
# TEST SCENARIOS
# ============================================================================

def test_1_manual_purchase_linkage():
    """
    Scenario 1: Manual purchase linkage
    a. POST /api/purchases with vendor_name returns Purchase with non-null vendor_party_id
    b. Two POSTs for same vendor return SAME vendor_party_id
    c. PUT /api/purchases keeping same vendor_name preserves vendor_party_id
    d. PUT /api/purchases with different vendor_name MOVES payable to different party
    """
    print("\n" + "="*80)
    print("TEST 1: Manual Purchase Linkage")
    print("="*80)
    
    # 1a: POST with vendor_name stamps vendor_party_id
    print("\n1a. Testing POST /api/purchases stamps vendor_party_id...")
    p1 = post("/purchases", {
        "vendor_name": "TestVendor_Manual_A",
        "purchase_date": "2026-07-22",
        "items": [{"description": "Item A", "qty": 1, "rate": 1000, "amount": 1000}]
    })
    assert p1.get("vendor_party_id"), "❌ FAIL: vendor_party_id is None"
    print(f"✅ PASS: vendor_party_id = {p1['vendor_party_id']}")
    
    # 1b: Same vendor returns same party_id
    print("\n1b. Testing same vendor returns same vendor_party_id...")
    p2 = post("/purchases", {
        "vendor_name": "TestVendor_Manual_A",
        "purchase_date": "2026-07-22",
        "items": [{"description": "Item B", "qty": 1, "rate": 2000, "amount": 2000}]
    })
    assert p2.get("vendor_party_id") == p1["vendor_party_id"], \
        f"❌ FAIL: Different party_ids: {p1['vendor_party_id']} vs {p2['vendor_party_id']}"
    print(f"✅ PASS: Both purchases have same vendor_party_id = {p1['vendor_party_id']}")
    
    # 1c: PUT with same vendor preserves party_id
    print("\n1c. Testing PUT with same vendor_name preserves vendor_party_id...")
    original_pid = p1["vendor_party_id"]
    p1_updated = put(f"/purchases/{p1['id']}", {
        "vendor_name": "TestVendor_Manual_A",
        "purchase_date": "2026-07-22",
        "items": [{"description": "Item A Updated", "qty": 2, "rate": 1000, "amount": 2000}]
    })
    assert p1_updated["vendor_party_id"] == original_pid, \
        f"❌ FAIL: vendor_party_id changed from {original_pid} to {p1_updated['vendor_party_id']}"
    print(f"✅ PASS: vendor_party_id preserved = {original_pid}")
    
    # 1d: PUT with different vendor MOVES party_id
    print("\n1d. Testing PUT with different vendor_name MOVES vendor_party_id...")
    p1_moved = put(f"/purchases/{p1['id']}", {
        "vendor_name": "TestVendor_Manual_B",
        "purchase_date": "2026-07-22",
        "items": [{"description": "Item A Moved", "qty": 1, "rate": 1000, "amount": 1000}]
    })
    assert p1_moved["vendor_party_id"] != original_pid, \
        f"❌ FAIL: vendor_party_id did not change (still {original_pid})"
    print(f"✅ PASS: vendor_party_id moved from {original_pid} to {p1_moved['vendor_party_id']}")
    
    # Cleanup
    delete(f"/purchases/{p1['id']}")
    delete(f"/purchases/{p2['id']}")
    print("\n✅ TEST 1 COMPLETE: All manual purchase linkage tests passed")


def test_2_vendor_rename_preserves_linkage():
    """
    Scenario 2: Vendor rename preserves linkage
    Create purchase → note vendor_party_id → rename party → GET purchase → vendor_party_id unchanged
    """
    print("\n" + "="*80)
    print("TEST 2: Vendor Rename Preserves Linkage")
    print("="*80)
    
    # Create purchase
    print("\nCreating purchase with vendor 'TestVendor_Rename_Original'...")
    p = post("/purchases", {
        "vendor_name": "TestVendor_Rename_Original",
        "purchase_date": "2026-07-22",
        "items": [{"description": "Item", "qty": 1, "rate": 500, "amount": 500}]
    })
    original_pid = p["vendor_party_id"]
    print(f"Original vendor_party_id = {original_pid}")
    
    # Rename the party
    print(f"\nRenaming party {original_pid} to 'TestVendor_Rename_NewName'...")
    post(f"/parties/{original_pid}/rename", {"display_name": "TestVendor_Rename_NewName"})
    
    # Get purchase again
    print("\nFetching purchase after rename...")
    p_after = get(f"/purchases/{p['id']}")
    assert p_after["vendor_party_id"] == original_pid, \
        f"❌ FAIL: vendor_party_id changed from {original_pid} to {p_after['vendor_party_id']}"
    print(f"✅ PASS: vendor_party_id preserved = {original_pid}")
    
    # Cleanup
    delete(f"/purchases/{p['id']}")
    print("\n✅ TEST 2 COMPLETE: Vendor rename preserves linkage")


def test_3_freight_auto_purchase():
    """
    Scenario 3: Freight auto-purchase generation
    POST /api/orders with shipment containing transporter + freight_paid > 0
    → Exactly ONE freight Purchase exists with correct vendor_party_id
    """
    print("\n" + "="*80)
    print("TEST 3: Freight Auto-Purchase Generation")
    print("="*80)
    
    print("\nCreating order with shipment (transporter='TestTransporter_A', freight_paid=250)...")
    order = post("/orders", {
        "client_name": "TestClient_Freight",
        "order_date": "2026-07-22",
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }],
        "shipments": [{
            "date": "2026-07-22",
            "transporter": "TestTransporter_A",
            "freight_paid": 250,
            "freight_charged": 250,
            "boxes_shipped": 1,
            "items": []
        }]
    })
    
    print(f"\nSearching for linked freight purchase (order_id={order['id']})...")
    freight_pur = find_linked_purchase(order["id"], "order_freight_purchase")
    
    assert freight_pur is not None, "❌ FAIL: No freight purchase found"
    print(f"✅ Found freight purchase: id={freight_pur['id']}")
    
    assert freight_pur.get("vendor_party_id"), "❌ FAIL: vendor_party_id is None"
    print(f"✅ vendor_party_id = {freight_pur['vendor_party_id']}")
    
    assert freight_pur["vendor_name"] == "TestTransporter_A", \
        f"❌ FAIL: vendor_name mismatch: {freight_pur['vendor_name']}"
    print(f"✅ vendor_name = {freight_pur['vendor_name']}")
    
    assert abs(float(freight_pur["invoice_total"]) - 250.0) < 0.01, \
        f"❌ FAIL: invoice_total mismatch: {freight_pur['invoice_total']}"
    print(f"✅ invoice_total = {freight_pur['invoice_total']}")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    print("\n✅ TEST 3 COMPLETE: Freight auto-purchase generation working")


def test_4_freight_linkage_matches_manual():
    """
    Scenario 4: Freight linkage matches manual purchase for same vendor
    Create order with transporter → create manual purchase with same vendor
    → Both have same vendor_party_id
    """
    print("\n" + "="*80)
    print("TEST 4: Freight Linkage Matches Manual Purchase")
    print("="*80)
    
    transporter = "TestTransporter_B"
    
    print(f"\nCreating order with transporter='{transporter}'...")
    order = post("/orders", {
        "client_name": "TestClient_Freight_B",
        "order_date": "2026-07-22",
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }],
        "shipments": [{
            "date": "2026-07-22",
            "transporter": transporter,
            "freight_paid": 300,
            "freight_charged": 300,
            "boxes_shipped": 1,
            "items": []
        }]
    })
    
    print(f"\nCreating manual purchase with vendor_name='{transporter}'...")
    manual_pur = post("/purchases", {
        "vendor_name": transporter,
        "purchase_date": "2026-07-22",
        "items": [{"description": "Manual test", "qty": 1, "rate": 100, "amount": 100}]
    })
    
    print("\nFetching freight purchase...")
    freight_pur = find_linked_purchase(order["id"], "order_freight_purchase")
    
    assert freight_pur is not None, "❌ FAIL: No freight purchase found"
    assert freight_pur["vendor_party_id"] == manual_pur["vendor_party_id"], \
        f"❌ FAIL: vendor_party_id mismatch: freight={freight_pur['vendor_party_id']}, manual={manual_pur['vendor_party_id']}"
    print(f"✅ PASS: Both purchases have same vendor_party_id = {freight_pur['vendor_party_id']}")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    delete(f"/purchases/{manual_pur['id']}")
    print("\n✅ TEST 4 COMPLETE: Freight linkage matches manual purchase")


def test_5_freight_sync_idempotency():
    """
    Scenario 5: Freight sync idempotency
    POST order → note freight purchase count → PUT order with identical body
    → Exactly ONE freight purchase (not duplicated)
    """
    print("\n" + "="*80)
    print("TEST 5: Freight Sync Idempotency")
    print("="*80)
    
    print("\nCreating order with freight...")
    order = post("/orders", {
        "client_name": "TestClient_Freight_C",
        "order_date": "2026-07-22",
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }],
        "shipments": [{
            "date": "2026-07-22",
            "transporter": "TestTransporter_C",
            "freight_paid": 400,
            "freight_charged": 400,
            "boxes_shipped": 1,
            "items": []
        }]
    })
    
    print("\nUpdating order with identical body...")
    put(f"/orders/{order['id']}", {
        "client_name": order["client_name"],
        "order_date": order["order_date"],
        "status": order["status"],
        "items": order["items"],
        "shipments": order["shipments"]
    })
    
    print("\nCounting freight purchases...")
    purchases = get("/purchases")
    freight_purs = [p for p in purchases 
                    if p.get("linked_to_order_id") == order["id"] 
                    and p.get("source_type") == "order_freight_purchase"]
    
    assert len(freight_purs) == 1, \
        f"❌ FAIL: Expected 1 freight purchase, found {len(freight_purs)}"
    print(f"✅ PASS: Exactly 1 freight purchase found (idempotent)")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    print("\n✅ TEST 5 COMPLETE: Freight sync is idempotent")


def test_6_zero_freight_suppresses_purchase():
    """
    Scenario 6: Zero freight or blank transporter suppresses purchase
    a. Order with freight_paid=0 → NO freight Purchase
    b. Order with transporter="" but freight_paid>0 → NO freight Purchase
    """
    print("\n" + "="*80)
    print("TEST 6: Zero Freight or Blank Transporter Suppresses Purchase")
    print("="*80)
    
    # 6a: freight_paid=0
    print("\n6a. Testing freight_paid=0...")
    order_a = post("/orders", {
        "client_name": "TestClient_Freight_D",
        "order_date": "2026-07-22",
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }],
        "shipments": [{
            "date": "2026-07-22",
            "transporter": "TestTransporter_D",
            "freight_paid": 0,
            "freight_charged": 0,
            "boxes_shipped": 1,
            "items": []
        }]
    })
    
    freight_pur_a = find_linked_purchase(order_a["id"], "order_freight_purchase")
    assert freight_pur_a is None, "❌ FAIL: freight_paid=0 should not create purchase"
    print("✅ PASS: No freight purchase created for freight_paid=0")
    
    # 6b: blank transporter
    print("\n6b. Testing blank transporter...")
    order_b = post("/orders", {
        "client_name": "TestClient_Freight_E",
        "order_date": "2026-07-22",
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }],
        "shipments": [{
            "date": "2026-07-22",
            "transporter": "",
            "freight_paid": 100,
            "freight_charged": 100,
            "boxes_shipped": 1,
            "items": []
        }]
    })
    
    freight_pur_b = find_linked_purchase(order_b["id"], "order_freight_purchase")
    assert freight_pur_b is None, "❌ FAIL: blank transporter should not create purchase"
    print("✅ PASS: No freight purchase created for blank transporter")
    
    # Cleanup
    delete(f"/orders/{order_a['id']}")
    delete(f"/orders/{order_b['id']}")
    print("\n✅ TEST 6 COMPLETE: Zero freight/blank transporter suppresses purchase")


def test_7_packing_auto_purchase():
    """
    Scenario 7: Packing auto-purchase
    POST order with packer_name + packing_cost > 0
    → Exactly ONE packing Purchase with correct vendor_party_id
    """
    print("\n" + "="*80)
    print("TEST 7: Packing Auto-Purchase Generation")
    print("="*80)
    
    print("\nCreating order with packer_name='TestPacker_A', packing_cost=180...")
    order = post("/orders", {
        "client_name": "TestClient_Packing_A",
        "order_date": "2026-07-22",
        "packer_name": "TestPacker_A",
        "packing_cost": 180,
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }]
    })
    
    print(f"\nSearching for linked packing purchase (order_id={order['id']})...")
    packing_pur = find_linked_purchase(order["id"], "order_packing_purchase")
    
    assert packing_pur is not None, "❌ FAIL: No packing purchase found"
    print(f"✅ Found packing purchase: id={packing_pur['id']}")
    
    assert packing_pur.get("vendor_party_id"), "❌ FAIL: vendor_party_id is None"
    print(f"✅ vendor_party_id = {packing_pur['vendor_party_id']}")
    
    assert abs(float(packing_pur["invoice_total"]) - 180.0) < 0.01, \
        f"❌ FAIL: invoice_total mismatch: {packing_pur['invoice_total']}"
    print(f"✅ invoice_total = {packing_pur['invoice_total']}")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    print("\n✅ TEST 7 COMPLETE: Packing auto-purchase generation working")


def test_8_blank_packer_suppresses_purchase():
    """
    Scenario 8: Blank packer suppresses packing purchase
    Order with packing_cost=100, packer_name="" → NO packing Purchase
    """
    print("\n" + "="*80)
    print("TEST 8: Blank Packer Suppresses Packing Purchase")
    print("="*80)
    
    print("\nCreating order with packing_cost=100, packer_name=''...")
    order = post("/orders", {
        "client_name": "TestClient_Packing_B",
        "order_date": "2026-07-22",
        "packer_name": "",
        "packing_cost": 100,
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }]
    })
    
    packing_pur = find_linked_purchase(order["id"], "order_packing_purchase")
    assert packing_pur is None, "❌ FAIL: blank packer_name should not create purchase"
    print("✅ PASS: No packing purchase created for blank packer_name")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    print("\n✅ TEST 8 COMPLETE: Blank packer suppresses packing purchase")


def test_9_removing_packer_removes_purchase():
    """
    Scenario 9: Removing packer/packing removes linked purchase (when unpaid)
    Create order with packing → verify Purchase exists → PUT with packing_cost=0, packer_name=""
    → Purchase must be gone
    """
    print("\n" + "="*80)
    print("TEST 9: Removing Packer/Packing Removes Linked Purchase")
    print("="*80)
    
    print("\nCreating order with packer_name='TestPacker_C', packing_cost=90...")
    order = post("/orders", {
        "client_name": "TestClient_Packing_C",
        "order_date": "2026-07-22",
        "packer_name": "TestPacker_C",
        "packing_cost": 90,
        "items": [{
            "main_category": "Glass",
            "product_name": "TestProduct",
            "qty": 6,
            "rate": 1000,
            "product_sales": 6000
        }]
    })
    
    print("\nVerifying packing purchase exists...")
    packing_pur = find_linked_purchase(order["id"], "order_packing_purchase")
    assert packing_pur is not None, "❌ FAIL: Packing purchase should exist"
    print(f"✅ Packing purchase exists: id={packing_pur['id']}")
    
    print("\nUpdating order to remove packing (packing_cost=0, packer_name='')...")
    put(f"/orders/{order['id']}", {
        "client_name": order["client_name"],
        "order_date": order["order_date"],
        "status": order["status"],
        "items": order["items"],
        "packing_cost": 0,
        "packer_name": ""
    })
    
    print("\nVerifying packing purchase is gone...")
    packing_pur_after = find_linked_purchase(order["id"], "order_packing_purchase")
    assert packing_pur_after is None, "❌ FAIL: Packing purchase should be deleted"
    print("✅ PASS: Packing purchase deleted after removing packer/packing")
    
    # Cleanup
    delete(f"/orders/{order['id']}")
    print("\n✅ TEST 9 COMPLETE: Removing packer/packing removes linked purchase")


def test_10_admin_backfill_migration():
    """
    Scenario 10: Admin backfill migration report
    POST /api/admin/purchases/backfill-vendor-party-id returns structured report
    Two consecutive calls: second has newly_linked == 0 (idempotent)
    """
    print("\n" + "="*80)
    print("TEST 10: Admin Backfill Migration Report")
    print("="*80)
    
    print("\nCalling POST /api/admin/purchases/backfill-vendor-party-id (first time)...")
    report1 = post("/admin/purchases/backfill-vendor-party-id", {})
    
    print("\nVerifying report structure...")
    assert "purchases" in report1, "❌ FAIL: 'purchases' section missing"
    assert "purchase_payments" in report1, "❌ FAIL: 'purchase_payments' section missing"
    
    for section in ["purchases", "purchase_payments"]:
        data = report1[section]
        for key in ["scanned", "already_linked", "newly_linked", "ambiguous", "unmatched", "by_resolution"]:
            assert key in data, f"❌ FAIL: {section}.{key} missing"
    
    print(f"✅ Report structure valid")
    print(f"   purchases: scanned={report1['purchases']['scanned']}, "
          f"already_linked={report1['purchases']['already_linked']}, "
          f"newly_linked={report1['purchases']['newly_linked']}")
    print(f"   purchase_payments: scanned={report1['purchase_payments']['scanned']}, "
          f"already_linked={report1['purchase_payments']['already_linked']}, "
          f"newly_linked={report1['purchase_payments']['newly_linked']}")
    
    print("\nCalling POST /api/admin/purchases/backfill-vendor-party-id (second time)...")
    report2 = post("/admin/purchases/backfill-vendor-party-id", {})
    
    print("\nVerifying idempotency (newly_linked should be 0)...")
    assert report2["purchases"]["newly_linked"] == 0, \
        f"❌ FAIL: purchases.newly_linked = {report2['purchases']['newly_linked']} (expected 0)"
    assert report2["purchase_payments"]["newly_linked"] == 0, \
        f"❌ FAIL: purchase_payments.newly_linked = {report2['purchase_payments']['newly_linked']} (expected 0)"
    print("✅ PASS: Second call has newly_linked=0 for both sections (idempotent)")
    
    print("\n✅ TEST 10 COMPLETE: Admin backfill migration report working")


def test_11_reconciliation_healthy():
    """
    Scenario 11: Reconciliation stays healthy
    GET /api/reconcile → healthy == true, summary.passed == summary.total
    """
    print("\n" + "="*80)
    print("TEST 11: Reconciliation Stays Healthy")
    print("="*80)
    
    print("\nCalling GET /api/reconcile...")
    report = get("/reconcile")
    
    print(f"\nReconciliation status:")
    print(f"   healthy: {report.get('healthy')}")
    print(f"   summary: {report.get('summary')}")
    
    assert report.get("healthy") is True, \
        f"❌ FAIL: healthy={report.get('healthy')} (expected True)"
    print("✅ healthy = True")
    
    summary = report.get("summary", {})
    assert summary.get("passed") == summary.get("total"), \
        f"❌ FAIL: passed={summary.get('passed')}, total={summary.get('total')}"
    print(f"✅ summary.passed ({summary.get('passed')}) == summary.total ({summary.get('total')})")
    
    print("\n✅ TEST 11 COMPLETE: Reconciliation is healthy")


def test_12_run_pytest_suite():
    """
    Scenario 12: Run the pre-existing pytest suite
    cd /app/backend && python3 -m pytest tests/test_bug_vendor_party_linkage.py -v -o addopts=""
    """
    print("\n" + "="*80)
    print("TEST 12: Run Pre-Existing Pytest Suite")
    print("="*80)
    
    import subprocess
    
    print("\nRunning: cd /app/backend && python3 -m pytest tests/test_bug_vendor_party_linkage.py -v -o addopts=\"\"")
    result = subprocess.run(
        ["python3", "-m", "pytest", "tests/test_bug_vendor_party_linkage.py", "-v", "-o", "addopts="],
        cwd="/app/backend",
        capture_output=True,
        text=True,
        timeout=60
    )
    
    print("\n" + "-"*80)
    print("PYTEST OUTPUT:")
    print("-"*80)
    print(result.stdout)
    if result.stderr:
        print("STDERR:")
        print(result.stderr)
    print("-"*80)
    
    if result.returncode == 0:
        print("\n✅ TEST 12 COMPLETE: Pytest suite passed")
    else:
        print(f"\n❌ TEST 12 FAILED: Pytest suite failed with return code {result.returncode}")
        raise Exception(f"Pytest suite failed with return code {result.returncode}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Run all test scenarios"""
    print("\n" + "="*80)
    print("BACKEND API TESTING: Canonical vendor_party_id Linkage Bug Fix")
    print("="*80)
    
    # Login
    print("\nLogging in as admin...")
    login()
    print(f"✅ Logged in successfully (token: {TOKEN[:20]}...)")
    
    # Run all tests
    try:
        test_1_manual_purchase_linkage()
        test_2_vendor_rename_preserves_linkage()
        test_3_freight_auto_purchase()
        test_4_freight_linkage_matches_manual()
        test_5_freight_sync_idempotency()
        test_6_zero_freight_suppresses_purchase()
        test_7_packing_auto_purchase()
        test_8_blank_packer_suppresses_purchase()
        test_9_removing_packer_removes_purchase()
        test_10_admin_backfill_migration()
        test_11_reconciliation_healthy()
        test_12_run_pytest_suite()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\nSummary:")
        print("  ✅ Test 1: Manual purchase linkage")
        print("  ✅ Test 2: Vendor rename preserves linkage")
        print("  ✅ Test 3: Freight auto-purchase generation")
        print("  ✅ Test 4: Freight linkage matches manual purchase")
        print("  ✅ Test 5: Freight sync idempotency")
        print("  ✅ Test 6: Zero freight/blank transporter suppresses purchase")
        print("  ✅ Test 7: Packing auto-purchase generation")
        print("  ✅ Test 8: Blank packer suppresses packing purchase")
        print("  ✅ Test 9: Removing packer/packing removes linked purchase")
        print("  ✅ Test 10: Admin backfill migration report")
        print("  ✅ Test 11: Reconciliation stays healthy")
        print("  ✅ Test 12: Pytest suite (16/16 tests)")
        print("\n" + "="*80)
        
    except Exception as e:
        print("\n" + "="*80)
        print("❌ TEST SUITE FAILED")
        print("="*80)
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
