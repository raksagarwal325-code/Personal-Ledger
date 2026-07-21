#!/usr/bin/env python3
"""
Backend API Testing for Admin Data Management v1 - Test Dataset Fix Verification
Tests the fix for GET /api/orders 500 error after loading test dataset.
"""
import requests
import sys
import json

# Backend URL from frontend/.env
BASE_URL = "https://9fe41c99-64e9-4a3f-a108-354bddd7bc42.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Global token storage
auth_token = None


def log(msg, level="INFO"):
    """Simple logging"""
    print(f"[{level}] {msg}")


def login_admin():
    """Login as admin and capture JWT token"""
    global auth_token
    log("Step 1: Logging in as admin...")
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"Login failed: {response.status_code} - {response.text}", "ERROR")
        return False
    
    data = response.json()
    auth_token = data.get("access_token")
    
    if not auth_token:
        log("No access_token in login response", "ERROR")
        return False
    
    log(f"✅ Admin login successful, token captured: {auth_token[:20]}...")
    return True


def get_headers():
    """Return headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


def reset_transaction_data():
    """Reset DB to clean state using POST /api/admin/data-reset/execute"""
    log("Step 2: Resetting transaction data to clean state...")
    
    payload = {
        "scope": "clear_transaction_data",
        "password": ADMIN_PASSWORD,
        "confirmation_phrase": "CLEAR TRANSACTION DATA",
        "understand_checkbox": True,
        "create_backup_first": False,
        "keep_accounts": True
    }
    
    response = requests.post(
        f"{BASE_URL}/admin/data-reset/execute",
        json=payload,
        headers=get_headers(),
        timeout=60
    )
    
    if response.status_code != 200:
        log(f"Reset failed: {response.status_code} - {response.text}", "ERROR")
        return False
    
    data = response.json()
    log(f"✅ Transaction data reset successful")
    log(f"   Deleted collections: {list(data.get('deleted_counts', {}).keys())}")
    return True


def load_test_dataset():
    """Load test dataset using POST /api/admin/test-dataset/load"""
    log("Step 3: Loading test dataset...")
    
    response = requests.post(
        f"{BASE_URL}/admin/test-dataset/load",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"Load test dataset failed: {response.status_code} - {response.text}", "ERROR")
        return False, None
    
    data = response.json()
    test_dataset_id = data.get("test_dataset_id")
    created = data.get("created", {})
    
    log(f"✅ Test dataset loaded successfully")
    log(f"   test_dataset_id: {test_dataset_id}")
    log(f"   Created: {created}")
    
    # Verify expected counts
    expected = {"accounts": 2, "purchases": 2, "orders": 1, "customer_payments": 1, "transfers": 1}
    if created != expected:
        log(f"⚠️  Created counts mismatch. Expected: {expected}, Got: {created}", "WARN")
    
    return True, test_dataset_id


def verify_orders_endpoint():
    """
    **KEY TEST**: Verify GET /api/orders returns 200 and test order is properly structured.
    This is the main fix being tested - previously returned 500 due to incomplete OrderItem fields.
    """
    log("Step 4: Verifying GET /api/orders (KEY TEST - previously returned 500)...")
    
    response = requests.get(
        f"{BASE_URL}/orders",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ CRITICAL: GET /api/orders returned {response.status_code}", "ERROR")
        log(f"   Response: {response.text}", "ERROR")
        return False
    
    log(f"✅ GET /api/orders returned 200 (no longer 500)")
    
    try:
        orders = response.json()
    except json.JSONDecodeError as e:
        log(f"❌ Failed to parse orders JSON: {e}", "ERROR")
        return False
    
    if not isinstance(orders, list):
        log(f"❌ Orders response is not a list: {type(orders)}", "ERROR")
        return False
    
    log(f"   Total orders: {len(orders)}")
    
    # Find the test order
    test_order = None
    for order in orders:
        if order.get("client_name", "").startswith("Test Customer"):
            test_order = order
            break
    
    if not test_order:
        log(f"❌ Test order not found in orders list", "ERROR")
        log(f"   Available orders: {[o.get('client_name') for o in orders]}", "ERROR")
        return False
    
    log(f"✅ Test order found: client_name={test_order.get('client_name')}")
    
    # Verify order structure
    items = test_order.get("items", [])
    if not items:
        log(f"❌ Test order has no items", "ERROR")
        return False
    
    item = items[0]
    main_category = item.get("main_category")
    product_name = item.get("product_name")
    item_id = item.get("id")
    
    log(f"   Order item[0]: id={item_id}, main_category={main_category}, product_name={product_name}")
    
    if main_category != "Test Category":
        log(f"❌ Expected main_category='Test Category', got '{main_category}'", "ERROR")
        return False
    
    if product_name != "Test SKU":
        log(f"❌ Expected product_name='Test SKU', got '{product_name}'", "ERROR")
        return False
    
    log(f"✅ Order item has correct main_category and product_name")
    
    # Verify shipment structure
    shipments = test_order.get("shipments", [])
    if not shipments:
        log(f"❌ Test order has no shipments", "ERROR")
        return False
    
    shipment = shipments[0]
    shipment_items = shipment.get("items", [])
    if not shipment_items:
        log(f"❌ Shipment has no items", "ERROR")
        return False
    
    shipment_item = shipment_items[0]
    order_item_id = shipment_item.get("order_item_id")
    qty = shipment_item.get("qty")
    
    log(f"   Shipment item[0]: order_item_id={order_item_id}, qty={qty}")
    
    if order_item_id != item_id:
        log(f"❌ Shipment order_item_id mismatch. Expected '{item_id}', got '{order_item_id}'", "ERROR")
        return False
    
    if qty != 60:
        log(f"❌ Expected shipment qty=60, got {qty}", "ERROR")
        return False
    
    log(f"✅ Shipment item correctly references order item with qty=60")
    log(f"✅ **FIX VERIFIED**: Test order is properly structured and serializable")
    
    return True


def sanity_check_customer_payments():
    """Sanity check: GET /api/customer-payments should list the test payment"""
    log("Step 5: Sanity check - GET /api/customer-payments...")
    
    response = requests.get(
        f"{BASE_URL}/customer-payments",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ GET /api/customer-payments returned {response.status_code}", "ERROR")
        return False
    
    payments = response.json()
    log(f"✅ GET /api/customer-payments returned 200, count: {len(payments)}")
    
    if len(payments) < 1:
        log(f"⚠️  Expected at least 1 customer payment, got {len(payments)}", "WARN")
        return False
    
    return True


def sanity_check_purchases():
    """Sanity check: GET /api/purchases should list the two test purchases"""
    log("Step 6: Sanity check - GET /api/purchases...")
    
    response = requests.get(
        f"{BASE_URL}/purchases",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ GET /api/purchases returned {response.status_code}", "ERROR")
        return False
    
    purchases = response.json()
    log(f"✅ GET /api/purchases returned 200, count: {len(purchases)}")
    
    if len(purchases) < 2:
        log(f"⚠️  Expected at least 2 purchases, got {len(purchases)}", "WARN")
        return False
    
    return True


def sanity_check_transfers():
    """Sanity check: GET /api/transfers should list the test transfer"""
    log("Step 7: Sanity check - GET /api/transfers...")
    
    response = requests.get(
        f"{BASE_URL}/transfers",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ GET /api/transfers returned {response.status_code}", "ERROR")
        return False
    
    transfers = response.json()
    log(f"✅ GET /api/transfers returned 200, count: {len(transfers)}")
    
    if len(transfers) < 1:
        log(f"⚠️  Expected at least 1 transfer, got {len(transfers)}", "WARN")
        return False
    
    return True


def sanity_check_dashboard():
    """Sanity check: GET /api/dashboard should return 200 (no crash from test order)"""
    log("Step 8: Sanity check - GET /api/dashboard...")
    
    response = requests.get(
        f"{BASE_URL}/dashboard",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ GET /api/dashboard returned {response.status_code}", "ERROR")
        return False
    
    data = response.json()
    kpis = data.get("kpis", {})
    log(f"✅ GET /api/dashboard returned 200")
    log(f"   KPIs: received={kpis.get('received')}, paid={kpis.get('paid')}, "
        f"operating_revenue={kpis.get('operating_revenue')}, order_count={kpis.get('order_count')}")
    
    return True


def sanity_check_party_ledger():
    """Sanity check: GET /api/party-ledger-v2/parties should include system_fathers_firm"""
    log("Step 9: Sanity check - GET /api/party-ledger-v2/parties...")
    
    response = requests.get(
        f"{BASE_URL}/party-ledger-v2/parties",
        headers=get_headers(),
        timeout=30
    )
    
    if response.status_code != 200:
        log(f"❌ GET /api/party-ledger-v2/parties returned {response.status_code}", "ERROR")
        return False
    
    parties = response.json()
    
    # Handle both list and dict responses
    if isinstance(parties, dict):
        parties = parties.get("parties", [])
    
    log(f"✅ GET /api/party-ledger-v2/parties returned 200, count: {len(parties)}")
    
    # Check for system_fathers_firm
    system_ff = None
    for party in parties:
        if isinstance(party, dict) and party.get("id") == "system_fathers_firm":
            system_ff = party
            break
        elif isinstance(party, str) and party == "system_fathers_firm":
            system_ff = {"id": party}
            break
    
    if not system_ff:
        log(f"⚠️  system_fathers_firm party not found in response", "WARN")
        log(f"   Available parties: {parties[:5]}", "WARN")
        # Don't fail the test for this - it's a sanity check
        return True
    
    log(f"✅ system_fathers_firm party present: {system_ff}")
    
    return True


def main():
    """Main test execution"""
    log("=" * 80)
    log("BACKEND TEST: Admin Data Management v1 - Test Dataset Fix Verification")
    log("=" * 80)
    
    results = {
        "login": False,
        "reset": False,
        "load_dataset": False,
        "orders_endpoint": False,
        "customer_payments": False,
        "purchases": False,
        "transfers": False,
        "dashboard": False,
        "party_ledger": False
    }
    
    # Step 1: Login
    if not login_admin():
        log("❌ Test suite failed at login step", "ERROR")
        sys.exit(1)
    results["login"] = True
    
    # Step 2: Reset transaction data
    if not reset_transaction_data():
        log("❌ Test suite failed at reset step", "ERROR")
        sys.exit(1)
    results["reset"] = True
    
    # Step 3: Load test dataset
    success, dataset_id = load_test_dataset()
    if not success:
        log("❌ Test suite failed at load dataset step", "ERROR")
        sys.exit(1)
    results["load_dataset"] = True
    
    # Step 4: **KEY TEST** - Verify GET /api/orders
    if not verify_orders_endpoint():
        log("❌ **CRITICAL FAILURE**: GET /api/orders test failed", "ERROR")
        log("   The fix for test dataset order structure did not work", "ERROR")
        results["orders_endpoint"] = False
        # Continue with other tests to gather more info
    else:
        results["orders_endpoint"] = True
    
    # Step 5-9: Sanity checks
    results["customer_payments"] = sanity_check_customer_payments()
    results["purchases"] = sanity_check_purchases()
    results["transfers"] = sanity_check_transfers()
    results["dashboard"] = sanity_check_dashboard()
    results["party_ledger"] = sanity_check_party_ledger()
    
    # Summary
    log("=" * 80)
    log("TEST SUMMARY")
    log("=" * 80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        log(f"{status}: {test_name}")
    
    log("=" * 80)
    log(f"OVERALL: {passed}/{total} tests passed")
    
    if results["orders_endpoint"]:
        log("✅ **FIX VERIFIED**: GET /api/orders no longer returns 500 after loading test dataset")
        log("✅ Test order has correct OrderItem structure (main_category, product_name)")
        log("✅ Test order shipment correctly references order_item_id")
    else:
        log("❌ **FIX FAILED**: GET /api/orders still has issues")
    
    log("=" * 80)
    
    # Exit with appropriate code
    if not results["orders_endpoint"]:
        sys.exit(1)
    
    if passed == total:
        log("✅ ALL TESTS PASSED", "SUCCESS")
        sys.exit(0)
    else:
        log(f"⚠️  {total - passed} test(s) failed", "WARN")
        sys.exit(1)


if __name__ == "__main__":
    main()
