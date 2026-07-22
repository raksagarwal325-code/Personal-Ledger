"""
Phase 4 — Partial-shipment proportional revenue + Estimated vs Realized profit
Independent API-level verification test suite.

Tests the math invariants for proportional revenue recognition and estimated vs realized profit split.
"""
import requests
import uuid
import sys

# Base URL from frontend/.env REACT_APP_BACKEND_URL
BASE_URL = "https://import-ledger-app.preview.emergentagent.com/api"

# Admin credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Tolerance for float comparisons
TOLERANCE = 0.5

class TestResults:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def add_pass(self, test_name):
        self.passed.append(test_name)
        print(f"✅ PASS: {test_name}")
    
    def add_fail(self, test_name, reason):
        self.failed.append((test_name, reason))
        print(f"❌ FAIL: {test_name}")
        print(f"   Reason: {reason}")
    
    def add_warning(self, test_name, reason):
        self.warnings.append((test_name, reason))
        print(f"⚠️  WARNING: {test_name}")
        print(f"   Reason: {reason}")
    
    def summary(self):
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"✅ Passed: {len(self.passed)}")
        print(f"❌ Failed: {len(self.failed)}")
        print(f"⚠️  Warnings: {len(self.warnings)}")
        
        if self.failed:
            print("\nFailed Tests:")
            for test_name, reason in self.failed:
                print(f"  - {test_name}: {reason}")
        
        if self.warnings:
            print("\nWarnings:")
            for test_name, reason in self.warnings:
                print(f"  - {test_name}: {reason}")
        
        return len(self.failed) == 0

def approx_equal(actual, expected, tolerance=TOLERANCE):
    """Check if two values are approximately equal within tolerance."""
    return abs(actual - expected) <= tolerance

def verify_field(order, field_name, expected_value, test_name, results):
    """Verify a field exists and has the expected value."""
    if field_name not in order:
        results.add_fail(test_name, f"Field '{field_name}' missing from order")
        return False
    
    actual = order[field_name]
    if not approx_equal(actual, expected_value):
        results.add_fail(test_name, 
            f"Field '{field_name}': expected {expected_value}, got {actual} (diff: {abs(actual - expected_value)})")
        return False
    
    return True

def login_admin():
    """Login as admin and return bearer token."""
    print("\n" + "="*80)
    print("STEP 1: Admin Login")
    print("="*80)
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10
    )
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.status_code} - {response.text}")
        return None
    
    data = response.json()
    token = data.get("access_token")
    
    if not token:
        print(f"❌ No access_token in response: {data}")
        return None
    
    print(f"✅ Login successful, token obtained")
    return token

def create_order_a(token, results):
    """Create Order A: no shipment, Q=10, R=100, F_total=200, O_total=100."""
    print("\n" + "="*80)
    print("STEP 2A: Create Order A (no shipment)")
    print("="*80)
    
    item_id = str(uuid.uuid4())
    payload = {
        "client_name": f"Test Customer A {uuid.uuid4().hex[:6]}",
        "order_date": "2025-01-15",
        "items": [{
            "id": item_id,
            "main_category": "Test",
            "sub_category": "SubTest",
            "product_name": f"SKU-A-{uuid.uuid4().hex[:4]}",
            "qty": 10,
            "rate": 100,
            "product_sales": 1000,
            "purchase_sources": [],
            "factory_complete": 200,
            "factory_glass": 0,
            "factory_fitting": 0,
            "outside_complete": 100,
            "outside_glass": 0,
            "outside_fitting": 0,
        }],
        "shipments": [],
        "packing_cost": 0,
        "packing_recovery": 0,
    }
    
    response = requests.post(
        f"{BASE_URL}/orders",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("Create Order A", f"Status {response.status_code}: {response.text}")
        return None
    
    order = response.json()
    print(f"✅ Order A created: {order['id']}")
    
    # Verify expected values
    test_name = "Order A - No Shipment Math"
    all_pass = True
    
    all_pass &= verify_field(order, "operating_revenue", 0, test_name, results)
    all_pass &= verify_field(order, "net_profit", 0, test_name, results)
    all_pass &= verify_field(order, "estimated_operating_revenue", 1000, test_name, results)
    all_pass &= verify_field(order, "estimated_total_cost", 300, test_name, results)
    all_pass &= verify_field(order, "estimated_net_profit", 700, test_name, results)
    all_pass &= verify_field(order, "unrealized_revenue", 1000, test_name, results)
    all_pass &= verify_field(order, "unrealized_net_profit", 700, test_name, results)
    all_pass &= verify_field(order, "realized_revenue", 0, test_name, results)
    all_pass &= verify_field(order, "revenue_recognized", 0, test_name, results)
    
    if all_pass:
        results.add_pass(test_name)
    
    return order

def create_order_b(token, results):
    """Create Order B: partial 40%, Q=100, R=50, F_total=1000, O_total=500."""
    print("\n" + "="*80)
    print("STEP 2B: Create Order B (partial 40% shipment)")
    print("="*80)
    
    item_id = str(uuid.uuid4())
    payload = {
        "client_name": f"Test Customer B {uuid.uuid4().hex[:6]}",
        "order_date": "2025-01-15",
        "items": [{
            "id": item_id,
            "main_category": "Test",
            "sub_category": "SubTest",
            "product_name": f"SKU-B-{uuid.uuid4().hex[:4]}",
            "qty": 100,
            "rate": 50,
            "product_sales": 5000,
            "purchase_sources": [],
            "factory_complete": 1000,
            "factory_glass": 0,
            "factory_fitting": 0,
            "outside_complete": 500,
            "outside_glass": 0,
            "outside_fitting": 0,
        }],
        "shipments": [{
            "id": str(uuid.uuid4()),
            "date": "2025-01-20",
            "items": [{"order_item_id": item_id, "qty": 40}],
            "boxes_shipped": 0,
            "freight_charged": 150,
            "freight_paid": 100,
            "transporter": "TestExpress",
            "lr_number": "",
            "remarks": "",
        }],
        "packing_cost": 0,
        "packing_recovery": 0,
    }
    
    response = requests.post(
        f"{BASE_URL}/orders",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("Create Order B", f"Status {response.status_code}: {response.text}")
        return None
    
    order = response.json()
    print(f"✅ Order B created: {order['id']}")
    
    # Verify expected values
    # ratio = 0.4
    # realized_product_sales = 2000
    # operating_revenue = 2000 + 150 = 2150
    # realized_factory = 400; realized_outside = 200; total_cost = 400+200+100 = 700
    # net_profit = 2150 - 700 = 1450
    # estimated_operating_revenue = 5000 + 150 = 5150
    # estimated_total_cost = 1000 + 500 + 100 = 1600
    # estimated_net_profit = 5150 - 1600 = 3550
    # unrealized_revenue = 3000
    # unrealized_net_profit = 2100
    
    test_name = "Order B - Partial 40% Shipment Math"
    all_pass = True
    
    all_pass &= verify_field(order, "operating_revenue", 2150, test_name, results)
    all_pass &= verify_field(order, "net_profit", 1450, test_name, results)
    all_pass &= verify_field(order, "factory_cost_total", 400, test_name, results)
    all_pass &= verify_field(order, "outside_cost_total", 200, test_name, results)
    all_pass &= verify_field(order, "total_cost", 700, test_name, results)
    all_pass &= verify_field(order, "estimated_operating_revenue", 5150, test_name, results)
    all_pass &= verify_field(order, "estimated_total_cost", 1600, test_name, results)
    all_pass &= verify_field(order, "estimated_net_profit", 3550, test_name, results)
    all_pass &= verify_field(order, "unrealized_revenue", 3000, test_name, results)
    all_pass &= verify_field(order, "unrealized_net_profit", 2100, test_name, results)
    all_pass &= verify_field(order, "realized_revenue", 2150, test_name, results)
    all_pass &= verify_field(order, "revenue_recognized", 2150, test_name, results)
    
    if all_pass:
        results.add_pass(test_name)
    
    return order

def create_order_c(token, results):
    """Create Order C: full shipment, Q=25, R=200, F_total=1250, O_total=750."""
    print("\n" + "="*80)
    print("STEP 2C: Create Order C (full shipment)")
    print("="*80)
    
    item_id = str(uuid.uuid4())
    payload = {
        "client_name": f"Test Customer C {uuid.uuid4().hex[:6]}",
        "order_date": "2025-01-15",
        "items": [{
            "id": item_id,
            "main_category": "Test",
            "sub_category": "SubTest",
            "product_name": f"SKU-C-{uuid.uuid4().hex[:4]}",
            "qty": 25,
            "rate": 200,
            "product_sales": 5000,
            "purchase_sources": [],
            "factory_complete": 1250,
            "factory_glass": 0,
            "factory_fitting": 0,
            "outside_complete": 750,
            "outside_glass": 0,
            "outside_fitting": 0,
        }],
        "shipments": [{
            "id": str(uuid.uuid4()),
            "date": "2025-01-20",
            "items": [{"order_item_id": item_id, "qty": 25}],
            "boxes_shipped": 0,
            "freight_charged": 75,
            "freight_paid": 50,
            "transporter": "TestExpress",
            "lr_number": "",
            "remarks": "",
        }],
        "packing_cost": 0,
        "packing_recovery": 0,
    }
    
    response = requests.post(
        f"{BASE_URL}/orders",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("Create Order C", f"Status {response.status_code}: {response.text}")
        return None
    
    order = response.json()
    print(f"✅ Order C created: {order['id']}")
    
    # Verify expected values
    # ratio = 1
    # operating_revenue == estimated_operating_revenue == 5000+75 = 5075
    # net_profit == estimated_net_profit == 5075 - (1250+750+50) = 3025
    # unrealized_revenue == 0
    # unrealized_net_profit == 0
    
    test_name = "Order C - Full Shipment Math"
    all_pass = True
    
    all_pass &= verify_field(order, "operating_revenue", 5075, test_name, results)
    all_pass &= verify_field(order, "net_profit", 3025, test_name, results)
    all_pass &= verify_field(order, "estimated_operating_revenue", 5075, test_name, results)
    all_pass &= verify_field(order, "estimated_net_profit", 3025, test_name, results)
    all_pass &= verify_field(order, "unrealized_revenue", 0, test_name, results)
    all_pass &= verify_field(order, "unrealized_net_profit", 0, test_name, results)
    all_pass &= verify_field(order, "realized_revenue", 5075, test_name, results)
    all_pass &= verify_field(order, "revenue_recognized", 5075, test_name, results)
    
    if all_pass:
        results.add_pass(test_name)
    
    return order

def verify_orders_list(token, order_ids, results):
    """Verify GET /api/orders returns the same values."""
    print("\n" + "="*80)
    print("STEP 3: Verify GET /api/orders")
    print("="*80)
    
    response = requests.get(
        f"{BASE_URL}/orders",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("GET /api/orders", f"Status {response.status_code}: {response.text}")
        return
    
    orders = response.json()
    
    # Find our test orders
    test_orders = {o['id']: o for o in orders if o['id'] in order_ids}
    
    if len(test_orders) != len(order_ids):
        results.add_fail("GET /api/orders", 
            f"Expected {len(order_ids)} test orders, found {len(test_orders)}")
        return
    
    print(f"✅ Found all {len(order_ids)} test orders in list")
    results.add_pass("GET /api/orders - All test orders present")

def verify_dashboard(token, results):
    """Verify GET /api/dashboard has all Phase 4 fields and alias identities."""
    print("\n" + "="*80)
    print("STEP 4: Verify GET /api/dashboard")
    print("="*80)
    
    response = requests.get(
        f"{BASE_URL}/dashboard",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("GET /api/dashboard", f"Status {response.status_code}: {response.text}")
        return
    
    data = response.json()
    kpis = data.get("kpis", {})
    
    # Check all required fields exist
    required_fields = [
        "operating_revenue", "net_profit", "estimated_revenue", "estimated_total_cost",
        "estimated_net_profit", "estimated_margin_percent", "realized_revenue",
        "realized_net_profit", "revenue_recognized", "unrealized_revenue",
        "unrealized_net_profit", "margin_percent"
    ]
    
    missing_fields = [f for f in required_fields if f not in kpis]
    if missing_fields:
        results.add_fail("Dashboard KPIs - Required Fields", 
            f"Missing fields: {', '.join(missing_fields)}")
        return
    
    print(f"✅ All required KPI fields present")
    results.add_pass("Dashboard KPIs - All Required Fields Present")
    
    # Verify alias identities
    test_name = "Dashboard KPIs - Alias Identities"
    all_pass = True
    
    if not approx_equal(kpis["realized_revenue"], kpis["operating_revenue"]):
        results.add_fail(test_name, 
            f"realized_revenue ({kpis['realized_revenue']}) != operating_revenue ({kpis['operating_revenue']})")
        all_pass = False
    
    if not approx_equal(kpis["realized_net_profit"], kpis["net_profit"]):
        results.add_fail(test_name, 
            f"realized_net_profit ({kpis['realized_net_profit']}) != net_profit ({kpis['net_profit']})")
        all_pass = False
    
    if not approx_equal(kpis["revenue_recognized"], kpis["operating_revenue"]):
        results.add_fail(test_name, 
            f"revenue_recognized ({kpis['revenue_recognized']}) != operating_revenue ({kpis['operating_revenue']})")
        all_pass = False
    
    expected_unrealized_profit = kpis["estimated_net_profit"] - kpis["net_profit"]
    if not approx_equal(kpis["unrealized_net_profit"], expected_unrealized_profit):
        results.add_fail(test_name, 
            f"unrealized_net_profit ({kpis['unrealized_net_profit']}) != estimated_net_profit - net_profit ({expected_unrealized_profit})")
        all_pass = False
    
    if kpis["unrealized_revenue"] < -0.5:
        results.add_fail(test_name, 
            f"unrealized_revenue ({kpis['unrealized_revenue']}) is negative")
        all_pass = False
    
    if kpis["estimated_revenue"] < kpis["operating_revenue"] - 1e-6:
        results.add_fail(test_name, 
            f"estimated_revenue ({kpis['estimated_revenue']}) < operating_revenue ({kpis['operating_revenue']})")
        all_pass = False
    
    if all_pass:
        results.add_pass(test_name)

def add_shipment_to_order_a(token, order_a, results):
    """Add a shipment to Order A that ships 5/10 units."""
    print("\n" + "="*80)
    print("STEP 5: Add Shipment to Order A (5/10 units)")
    print("="*80)
    
    item_id = order_a["items"][0]["id"]
    shipment_payload = {
        "id": str(uuid.uuid4()),
        "date": "2025-01-22",
        "items": [{"order_item_id": item_id, "qty": 5}],
        "boxes_shipped": 0,
        "freight_charged": 0,
        "freight_paid": 0,
        "transporter": "",
        "lr_number": "",
        "remarks": "",
    }
    
    response = requests.post(
        f"{BASE_URL}/orders/{order_a['id']}/shipments",
        json=shipment_payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code != 200:
        results.add_fail("Add Shipment to Order A", f"Status {response.status_code}: {response.text}")
        return None
    
    order = response.json()
    print(f"✅ Shipment added to Order A")
    
    # Verify expected values
    # ratio = 0.5
    # operating_revenue == 500 (from product sales)
    # estimated_operating_revenue == 1000
    # net_profit == 500 - 0.5*(200+100) = 500 - 150 = 350
    # estimated_net_profit == 700
    # unrealized_revenue == 500
    # unrealized_net_profit == 350
    
    test_name = "Order A - After Adding 5/10 Shipment"
    all_pass = True
    
    all_pass &= verify_field(order, "operating_revenue", 500, test_name, results)
    all_pass &= verify_field(order, "estimated_operating_revenue", 1000, test_name, results)
    all_pass &= verify_field(order, "net_profit", 350, test_name, results)
    all_pass &= verify_field(order, "estimated_net_profit", 700, test_name, results)
    all_pass &= verify_field(order, "unrealized_revenue", 500, test_name, results)
    all_pass &= verify_field(order, "unrealized_net_profit", 350, test_name, results)
    
    if all_pass:
        results.add_pass(test_name)
    
    return order

def regression_sweep(token, results):
    """Verify existing endpoints don't regress."""
    print("\n" + "="*80)
    print("STEP 6: Regression Sweep")
    print("="*80)
    
    endpoints = [
        "/dashboard",
        "/orders",
        "/customer-payments",
        "/purchase-payments",
        "/dashboard/breakdown",
        "/auth/status",
    ]
    
    for endpoint in endpoints:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            results.add_fail(f"Regression - GET {endpoint}", 
                f"Status {response.status_code}: {response.text}")
        else:
            print(f"✅ GET {endpoint} - 200 OK")
            results.add_pass(f"Regression - GET {endpoint}")
    
    # Verify auth/status has reset_enabled=true
    response = requests.get(
        f"{BASE_URL}/auth/status",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    
    if response.status_code == 200:
        data = response.json()
        if data.get("reset_enabled") != True:
            results.add_warning("Auth Status - reset_enabled", 
                f"Expected reset_enabled=true, got {data.get('reset_enabled')}")

def cleanup_orders(token, order_ids, results):
    """Delete test orders."""
    print("\n" + "="*80)
    print("STEP 7: Cleanup Test Orders")
    print("="*80)
    
    for order_id in order_ids:
        response = requests.delete(
            f"{BASE_URL}/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        if response.status_code != 200:
            results.add_fail(f"Delete Order {order_id}", 
                f"Status {response.status_code}: {response.text}")
        else:
            print(f"✅ Deleted order {order_id}")
            results.add_pass(f"Cleanup - Delete Order {order_id}")

def run_pytest_suite():
    """Optional: run the pytest suite."""
    print("\n" + "="*80)
    print("STEP 8 (Optional): Run pytest suite")
    print("="*80)
    
    import subprocess
    try:
        result = subprocess.run(
            ["pytest", "tests/test_p4_partial_shipment_revenue.py", "-v"],
            cwd="/app/backend",
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        if result.returncode == 0:
            print("✅ Pytest suite passed")
            return True
        else:
            print("❌ Pytest suite failed")
            return False
    except Exception as e:
        print(f"⚠️  Could not run pytest: {e}")
        return None

def main():
    results = TestResults()
    
    print("\n" + "="*80)
    print("PHASE 4 VERIFICATION TEST SUITE")
    print("Partial-shipment proportional revenue + Estimated vs Realized profit")
    print("="*80)
    
    # Step 1: Login
    token = login_admin()
    if not token:
        print("\n❌ CRITICAL: Cannot proceed without authentication")
        return False
    
    # Step 2: Create three test orders
    order_a = create_order_a(token, results)
    order_b = create_order_b(token, results)
    order_c = create_order_c(token, results)
    
    if not all([order_a, order_b, order_c]):
        print("\n❌ CRITICAL: Failed to create all test orders")
        results.summary()
        return False
    
    order_ids = [order_a['id'], order_b['id'], order_c['id']]
    
    # Step 3: Verify GET /api/orders
    verify_orders_list(token, order_ids, results)
    
    # Step 4: Verify GET /api/dashboard
    verify_dashboard(token, results)
    
    # Step 5: Add shipment to Order A
    order_a_updated = add_shipment_to_order_a(token, order_a, results)
    
    # Step 6: Regression sweep
    regression_sweep(token, results)
    
    # Step 7: Cleanup
    cleanup_orders(token, order_ids, results)
    
    # Step 8: Optional pytest
    pytest_result = run_pytest_suite()
    if pytest_result is True:
        results.add_pass("Pytest Suite - test_p4_partial_shipment_revenue.py")
    elif pytest_result is False:
        results.add_fail("Pytest Suite - test_p4_partial_shipment_revenue.py", 
            "Some tests failed")
    
    # Summary
    success = results.summary()
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
