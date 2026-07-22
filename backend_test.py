#!/usr/bin/env python3
"""
Backend API Test Suite for Bug Fix Verification
Two ERP bugs fixed 2026-07-22:
  1. Dashboard Outstanding Receivable (was showing invoice_total instead of outstanding_balance)
  2. Order Shipped Date derivation (was blank despite full shipment)
"""

import requests
import json
from datetime import datetime, date
from typing import Dict, List, Any, Optional

# Backend URL from frontend/.env
BASE_URL = "https://github-sync-ledger.preview.emergentagent.com/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Global token storage
AUTH_TOKEN = None


def login() -> str:
    """Login and return JWT token"""
    global AUTH_TOKEN
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, f"Login failed: {response.status_code} {response.text}"
    data = response.json()
    AUTH_TOKEN = data.get("access_token")
    assert AUTH_TOKEN, "No access_token in login response"
    print(f"✅ Login successful")
    return AUTH_TOKEN


def get_headers() -> Dict[str, str]:
    """Get authorization headers"""
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


def test_bug1_dashboard_outstanding_receivable():
    """
    Bug 1 — Dashboard Outstanding Receivable
    Verify the specific regression case: order ₹96,300 with ₹75,000 allocated
    should show outstanding ₹21,300 (not ₹96,300)
    """
    print("\n" + "="*80)
    print("BUG 1 — DASHBOARD OUTSTANDING RECEIVABLE")
    print("="*80)
    
    # 1. GET /api/dashboard → kpis.outstanding_receivable == 21300
    print("\n[1/6] Testing GET /api/dashboard → kpis.outstanding_receivable")
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    assert response.status_code == 200, f"Dashboard failed: {response.status_code}"
    dashboard = response.json()
    
    outstanding_receivable = dashboard.get("kpis", {}).get("outstanding_receivable")
    assert outstanding_receivable is not None, "outstanding_receivable not in dashboard KPIs"
    
    # Allow ±0.01 tolerance for floating point
    expected = 21300.0
    tolerance = 0.01
    assert abs(outstanding_receivable - expected) <= tolerance, \
        f"Dashboard KPI outstanding_receivable = {outstanding_receivable}, expected {expected}"
    
    print(f"   ✅ Dashboard KPI outstanding_receivable = ₹{outstanding_receivable:,.2f} (expected ₹21,300.00)")
    
    # 2. GET /api/dashboard/breakdown → receivable.total == 21300
    print("\n[2/6] Testing GET /api/dashboard/breakdown → receivable.total")
    response = requests.get(f"{BASE_URL}/dashboard/breakdown", headers=get_headers())
    assert response.status_code == 200, f"Breakdown failed: {response.status_code}"
    breakdown = response.json()
    
    receivable_total = breakdown.get("receivable", {}).get("total")
    assert receivable_total is not None, "receivable.total not in breakdown"
    
    assert abs(receivable_total - expected) <= tolerance, \
        f"Breakdown receivable.total = {receivable_total}, expected {expected}"
    
    print(f"   ✅ Breakdown receivable.total = ₹{receivable_total:,.2f} (expected ₹21,300.00)")
    
    # Verify both endpoints match
    assert abs(outstanding_receivable - receivable_total) <= tolerance, \
        f"Dashboard KPI ({outstanding_receivable}) != Breakdown total ({receivable_total})"
    print(f"   ✅ Dashboard KPI matches Breakdown total")
    
    # 3. receivable.orders[] includes outstanding_balance field
    print("\n[3/6] Testing receivable.orders[] includes outstanding_balance field")
    receivable_orders = breakdown.get("receivable", {}).get("orders", [])
    assert len(receivable_orders) > 0, "No orders in receivable.orders[]"
    
    # Find Minakshi Jain order
    minakshi_order = None
    for order in receivable_orders:
        if "Minakshi Jain" in order.get("client_name", ""):
            minakshi_order = order
            break
    
    assert minakshi_order is not None, "Minakshi Jain order not found in receivable.orders[]"
    
    # Verify outstanding_balance field exists
    assert "outstanding_balance" in minakshi_order, \
        "outstanding_balance field missing from receivable.orders[] entry"
    
    outstanding_balance = minakshi_order["outstanding_balance"]
    invoice_total = minakshi_order.get("invoice_total")
    
    # Verify Minakshi Jain order has outstanding_balance ≈ 21300 and invoice_total ≈ 96300
    assert abs(outstanding_balance - 21300) <= tolerance, \
        f"Minakshi Jain outstanding_balance = {outstanding_balance}, expected ≈21300"
    assert abs(invoice_total - 96300) <= tolerance, \
        f"Minakshi Jain invoice_total = {invoice_total}, expected ≈96300"
    
    print(f"   ✅ Minakshi Jain order: outstanding_balance = ₹{outstanding_balance:,.2f}, invoice_total = ₹{invoice_total:,.2f}")
    
    # 4. receivable.by_status — sum of Unpaid.amount + Partial.amount == receivable.total
    print("\n[4/6] Testing receivable.by_status sums correctly")
    by_status = breakdown.get("receivable", {}).get("by_status", [])
    
    unpaid_amount = 0
    partial_amount = 0
    for status_entry in by_status:
        status = status_entry.get("status", "").lower()
        amount = status_entry.get("amount", 0)
        if status == "unpaid":
            unpaid_amount = amount
        elif status == "partial":
            partial_amount = amount
    
    by_status_sum = unpaid_amount + partial_amount
    assert abs(by_status_sum - receivable_total) <= tolerance, \
        f"by_status sum ({by_status_sum}) != receivable.total ({receivable_total})"
    
    print(f"   ✅ by_status: Unpaid={unpaid_amount:,.2f} + Partial={partial_amount:,.2f} = {by_status_sum:,.2f} (matches total)")
    
    # 5. Verify Paid orders are NOT in receivable.orders[]
    print("\n[5/6] Testing Paid orders are NOT in receivable.orders[]")
    paid_orders_in_receivable = [o for o in receivable_orders if o.get("payment_status", "").lower() == "paid"]
    assert len(paid_orders_in_receivable) == 0, \
        f"Found {len(paid_orders_in_receivable)} Paid orders in receivable.orders[] (should be 0)"
    
    print(f"   ✅ No Paid orders in receivable.orders[] (correct)")
    
    print("\n[6/6] Live edge case testing will be done in separate test function")
    print(f"   ⏭️  See test_bug1_live_edge_cases()")


def test_bug1_live_edge_cases():
    """
    Bug 1 — Live edge cases
    Create fresh order, ship it, add payments, verify outstanding_balance updates correctly
    """
    print("\n" + "="*80)
    print("BUG 1 — LIVE EDGE CASES")
    print("="*80)
    
    # Get initial dashboard state
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    initial_dashboard = response.json()
    initial_outstanding = initial_dashboard.get("kpis", {}).get("outstanding_receivable", 0)
    initial_advances = initial_dashboard.get("kpis", {}).get("customer_advances", 0)
    
    print(f"\nInitial state:")
    print(f"  outstanding_receivable = ₹{initial_outstanding:,.2f}")
    print(f"  customer_advances = ₹{initial_advances:,.2f}")
    
    # Get existing customers and use the first one
    print("\n[1/9] Getting existing customer for test")
    customers_response = requests.get(f"{BASE_URL}/customers", headers=get_headers())
    assert customers_response.status_code == 200, f"Customers list failed: {customers_response.status_code}"
    customers = customers_response.json()
    assert len(customers) > 0, "No customers found in database"
    
    # Use first customer
    customer = customers[0]
    customer_id = customer["id"]
    customer_name = customer["name"]
    print(f"   ✅ Using existing customer: {customer_name} ({customer_id})")
    
    # Create test order with single item (qty=1, rate=100000, no tax)
    print("\n[2/9] Creating test order (qty=1, rate=100000)")
    order_response = requests.post(
        f"{BASE_URL}/orders",
        headers=get_headers(),
        json={
            "client_id": customer_id,
            "client_name": customer_name,
            "order_date": date.today().isoformat(),
            "items": [{
                "main_category": "Test Category",
                "sub_category": "Test Sub",
                "product_name": "Test Product",
                "qty": 1,
                "rate": 100000,
                "amount": 100000,
                "factory_cost_total": 0,
                "outside_cost_total": 0
            }],
            "product_sales_total": 100000,
            "invoice_total": 100000
        }
    )
    assert order_response.status_code == 200, f"Order creation failed: {order_response.status_code}"
    order = order_response.json()
    order_id = order["id"]
    order_item_id = order["items"][0]["id"]
    print(f"   ✅ Order created: {order_id}")
    
    # Fully ship it
    print("\n[3/9] Fully shipping order (qty=1)")
    shipment_response = requests.post(
        f"{BASE_URL}/orders/{order_id}/shipments",
        headers=get_headers(),
        json={
            "date": date.today().isoformat(),
            "items": [{
                "order_item_id": order_item_id,
                "qty": 1
            }]
        }
    )
    assert shipment_response.status_code == 200, f"Shipment creation failed: {shipment_response.status_code}"
    print(f"   ✅ Shipment created")
    
    # Get updated order
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    outstanding_balance = order.get("outstanding_balance", 0)
    
    # Verify outstanding_balance = 100000
    assert abs(outstanding_balance - 100000) <= 0.01, \
        f"Order outstanding_balance = {outstanding_balance}, expected 100000"
    print(f"   ✅ Order outstanding_balance = ₹{outstanding_balance:,.2f}")
    
    # Verify dashboard outstanding increased by 100000
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    dashboard = response.json()
    current_outstanding = dashboard.get("kpis", {}).get("outstanding_receivable", 0)
    
    outstanding_increase = current_outstanding - initial_outstanding
    assert abs(outstanding_increase - 100000) <= 0.01, \
        f"Dashboard outstanding increased by {outstanding_increase}, expected 100000"
    print(f"   ✅ Dashboard outstanding_receivable increased by ₹{outstanding_increase:,.2f}")
    
    # Create customer payment allocating 30000 to the order
    print("\n[4/9] Creating customer payment (₹30,000 allocated)")
    payment1_response = requests.post(
        f"{BASE_URL}/customer-payments",
        headers=get_headers(),
        json={
            "party_id": customer_id,
            "customer_name": customer_name,
            "date": date.today().isoformat(),
            "amount": 30000,
            "mode": "cash",
            "allocations": [{
                "order_id": order_id,
                "amount": 30000
            }]
        }
    )
    assert payment1_response.status_code == 200, f"Payment creation failed: {payment1_response.status_code}"
    payment1 = payment1_response.json()
    payment1_id = payment1["id"]
    print(f"   ✅ Payment created: {payment1_id}")
    
    # Verify order outstanding_balance = 70000
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    outstanding_balance = order.get("outstanding_balance", 0)
    
    assert abs(outstanding_balance - 70000) <= 0.01, \
        f"Order outstanding_balance = {outstanding_balance}, expected 70000"
    print(f"   ✅ Order outstanding_balance = ₹{outstanding_balance:,.2f}")
    
    # Verify dashboard outstanding decreased by 30000
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    dashboard = response.json()
    current_outstanding = dashboard.get("kpis", {}).get("outstanding_receivable", 0)
    
    expected_outstanding = initial_outstanding + 70000
    assert abs(current_outstanding - expected_outstanding) <= 0.01, \
        f"Dashboard outstanding = {current_outstanding}, expected {expected_outstanding}"
    print(f"   ✅ Dashboard outstanding_receivable = ₹{current_outstanding:,.2f} (net contribution ₹70,000)")
    
    # Create ANOTHER customer payment with 150000 but only 70000 allocated → 80000 unallocated advance
    print("\n[5/9] Creating customer payment (₹150,000 total, ₹70,000 allocated, ₹80,000 advance)")
    payment2_response = requests.post(
        f"{BASE_URL}/customer-payments",
        headers=get_headers(),
        json={
            "party_id": customer_id,
            "customer_name": customer_name,
            "date": date.today().isoformat(),
            "amount": 150000,
            "mode": "cash",
            "allocations": [{
                "order_id": order_id,
                "amount": 70000
            }]
        }
    )
    assert payment2_response.status_code == 200, f"Payment2 creation failed: {payment2_response.status_code}"
    payment2 = payment2_response.json()
    payment2_id = payment2["id"]
    print(f"   ✅ Payment created: {payment2_id}")
    
    # Verify order outstanding_balance = 0
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    outstanding_balance = order.get("outstanding_balance", 0)
    
    assert abs(outstanding_balance - 0) <= 0.01, \
        f"Order outstanding_balance = {outstanding_balance}, expected 0"
    print(f"   ✅ Order outstanding_balance = ₹{outstanding_balance:,.2f}")
    
    # Verify dashboard outstanding no longer includes this order
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    dashboard = response.json()
    current_outstanding = dashboard.get("kpis", {}).get("outstanding_receivable", 0)
    
    assert abs(current_outstanding - initial_outstanding) <= 0.01, \
        f"Dashboard outstanding = {current_outstanding}, expected {initial_outstanding}"
    print(f"   ✅ Dashboard outstanding_receivable = ₹{current_outstanding:,.2f} (order no longer contributes)")
    
    # Verify customer_advances increased by 80000
    current_advances = dashboard.get("kpis", {}).get("customer_advances", 0)
    advances_increase = current_advances - initial_advances
    
    assert abs(advances_increase - 80000) <= 0.01, \
        f"Customer advances increased by {advances_increase}, expected 80000"
    print(f"   ✅ customer_advances increased by ₹{advances_increase:,.2f}")
    
    # Reverse the LAST payment
    print("\n[6/9] Reversing last payment (₹150,000)")
    reverse_response = requests.delete(
        f"{BASE_URL}/customer-payments/{payment2_id}",
        headers=get_headers()
    )
    assert reverse_response.status_code == 200, f"Payment reversal failed: {reverse_response.status_code}"
    print(f"   ✅ Payment reversed")
    
    # Verify order outstanding_balance restored to 70000
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    outstanding_balance = order.get("outstanding_balance", 0)
    
    assert abs(outstanding_balance - 70000) <= 0.01, \
        f"Order outstanding_balance = {outstanding_balance}, expected 70000"
    print(f"   ✅ Order outstanding_balance restored to ₹{outstanding_balance:,.2f}")
    
    # Verify dashboard outstanding restored
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    dashboard = response.json()
    current_outstanding = dashboard.get("kpis", {}).get("outstanding_receivable", 0)
    
    expected_outstanding = initial_outstanding + 70000
    assert abs(current_outstanding - expected_outstanding) <= 0.01, \
        f"Dashboard outstanding = {current_outstanding}, expected {expected_outstanding}"
    print(f"   ✅ Dashboard outstanding_receivable restored to ₹{current_outstanding:,.2f}")
    
    # Cleanup: delete test order and remaining payment
    print("\n[7/9] Cleaning up: deleting payment")
    requests.delete(f"{BASE_URL}/customer-payments/{payment1_id}", headers=get_headers())
    
    print("[8/9] Cleaning up: deleting order")
    delete_response = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    assert delete_response.status_code == 200, f"Order deletion failed: {delete_response.status_code}"
    
    print("[9/9] Cleanup complete (customer not deleted - was pre-existing)")
    
    print(f"\n   ✅ Cleanup complete")


def test_bug2_order_shipped_date():
    """
    Bug 2 — Order Shipped Date derivation
    Verify Minakshi Jain order has shipped_date and all fully shipped orders have dates
    """
    print("\n" + "="*80)
    print("BUG 2 — ORDER SHIPPED DATE DERIVATION")
    print("="*80)
    
    # 1. GET /api/orders and find Minakshi Jain order
    print("\n[1/3] Testing Minakshi Jain order has shipped_date = 2026-04-06")
    response = requests.get(f"{BASE_URL}/orders", headers=get_headers())
    assert response.status_code == 200, f"Orders list failed: {response.status_code}"
    orders = response.json()
    
    minakshi_order = None
    for order in orders:
        if "Minakshi Jain" in order.get("client_name", ""):
            minakshi_order = order
            break
    
    assert minakshi_order is not None, "Minakshi Jain order not found"
    
    # Verify status, shipped_date, last_shipped_date
    status = minakshi_order.get("status")
    shipped_date = minakshi_order.get("shipped_date")
    last_shipped_date = minakshi_order.get("last_shipped_date")
    
    assert status == "Fully Shipped", f"Minakshi Jain order status = {status}, expected 'Fully Shipped'"
    assert shipped_date is not None, "Minakshi Jain order shipped_date is null"
    assert shipped_date.startswith("2026-04-06"), \
        f"Minakshi Jain shipped_date = {shipped_date}, expected to start with '2026-04-06'"
    assert last_shipped_date is not None, "Minakshi Jain order last_shipped_date is null"
    assert last_shipped_date.startswith("2026-04-06"), \
        f"Minakshi Jain last_shipped_date = {last_shipped_date}, expected to start with '2026-04-06'"
    
    print(f"   ✅ Minakshi Jain order:")
    print(f"      status = {status}")
    print(f"      shipped_date = {shipped_date}")
    print(f"      last_shipped_date = {last_shipped_date}")
    
    # 2. Sweep every order: Fully Shipped must have shipped_date, Partially Shipped must not
    print("\n[2/3] Testing all orders: Fully Shipped → non-null, Partially Shipped → null")
    
    fully_shipped_count = 0
    partially_shipped_count = 0
    fully_shipped_without_date = []
    partially_shipped_with_date = []
    
    for order in orders:
        status = order.get("status")
        shipped_date = order.get("shipped_date")
        order_id = order.get("id")
        client_name = order.get("client_name", "Unknown")
        
        if status == "Fully Shipped":
            fully_shipped_count += 1
            if shipped_date is None:
                fully_shipped_without_date.append(f"{client_name} ({order_id})")
        elif status == "Partially Shipped":
            partially_shipped_count += 1
            if shipped_date is not None:
                partially_shipped_with_date.append(f"{client_name} ({order_id})")
    
    assert len(fully_shipped_without_date) == 0, \
        f"Found {len(fully_shipped_without_date)} Fully Shipped orders without shipped_date: {fully_shipped_without_date}"
    
    assert len(partially_shipped_with_date) == 0, \
        f"Found {len(partially_shipped_with_date)} Partially Shipped orders with shipped_date: {partially_shipped_with_date}"
    
    print(f"   ✅ Fully Shipped orders: {fully_shipped_count} (all have shipped_date)")
    print(f"   ✅ Partially Shipped orders: {partially_shipped_count} (all have null shipped_date)")
    
    print("\n[3/3] Live shipment flow testing will be done in separate test function")
    print(f"   ⏭️  See test_bug2_live_shipment_flow()")


def test_bug2_live_shipment_flow():
    """
    Bug 2 — Live shipment flow
    Create order, add partial shipment, complete shipment, edit, delete, verify shipped_date behavior
    """
    print("\n" + "="*80)
    print("BUG 2 — LIVE SHIPMENT FLOW")
    print("="*80)
    
    # Get existing customers and use the first one
    print("\n[1/11] Getting existing customer for test")
    customers_response = requests.get(f"{BASE_URL}/customers", headers=get_headers())
    assert customers_response.status_code == 200, f"Customers list failed: {customers_response.status_code}"
    customers = customers_response.json()
    assert len(customers) > 0, "No customers found in database"
    
    # Use first customer
    customer = customers[0]
    customer_id = customer["id"]
    customer_name = customer["name"]
    print(f"   ✅ Using existing customer: {customer_name} ({customer_id})")
    
    # Create order with qty=5, rate=100
    print("\n[2/11] Creating test order (qty=5, rate=100)")
    order_response = requests.post(
        f"{BASE_URL}/orders",
        headers=get_headers(),
        json={
            "client_id": customer_id,
            "client_name": customer_name,
            "order_date": date.today().isoformat(),
            "items": [{
                "main_category": "widget",
                "sub_category": "Test Sub",
                "product_name": "Test Widget",
                "qty": 5,
                "rate": 100,
                "amount": 500,
                "factory_cost_total": 0,
                "outside_cost_total": 0
            }],
            "product_sales_total": 500,
            "invoice_total": 500
        }
    )
    assert order_response.status_code == 200, f"Order creation failed: {order_response.status_code}"
    order = order_response.json()
    order_id = order["id"]
    order_item_id = order["items"][0]["id"]
    print(f"   ✅ Order created: {order_id}")
    
    # Verify shipped_date is null immediately after creation
    print("\n[3/11] Verifying shipped_date is null (no shipments yet)")
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipped_date = order.get("shipped_date")
    
    assert shipped_date is None, f"shipped_date should be null, got {shipped_date}"
    print(f"   ✅ shipped_date = null (correct)")
    
    # Add partial shipment (qty=2)
    print("\n[4/11] Adding partial shipment (qty=2 of 5)")
    shipment1_response = requests.post(
        f"{BASE_URL}/orders/{order_id}/shipments",
        headers=get_headers(),
        json={
            "date": "2026-05-01",
            "items": [{
                "order_item_id": order_item_id,
                "qty": 2
            }]
        }
    )
    assert shipment1_response.status_code == 200, f"Shipment creation failed: {shipment1_response.status_code}"
    
    # Get shipment ID from order
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipment1_id = order["shipments"][0]["id"]
    print(f"   ✅ Partial shipment created: {shipment1_id}")
    
    # Verify status = Partially Shipped, shipped_date = null
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    status = order.get("status")
    shipped_date = order.get("shipped_date")
    
    assert status == "Partially Shipped", f"Status = {status}, expected 'Partially Shipped'"
    assert shipped_date is None, f"shipped_date should be null for partial shipment, got {shipped_date}"
    print(f"   ✅ status = {status}, shipped_date = null (correct)")
    
    # Add completing shipment (qty=3)
    print("\n[5/11] Adding completing shipment (qty=3, total=5)")
    shipment2_response = requests.post(
        f"{BASE_URL}/orders/{order_id}/shipments",
        headers=get_headers(),
        json={
            "date": "2026-05-10",
            "items": [{
                "order_item_id": order_item_id,
                "qty": 3
            }]
        }
    )
    assert shipment2_response.status_code == 200, f"Completing shipment failed: {shipment2_response.status_code}"
    
    # Get shipment ID from order
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipment2_id = order["shipments"][1]["id"]
    print(f"   ✅ Completing shipment created: {shipment2_id}")
    
    # Verify status = Fully Shipped, shipped_date starts with 2026-05-10
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    status = order.get("status")
    shipped_date = order.get("shipped_date")
    
    assert status == "Fully Shipped", f"Status = {status}, expected 'Fully Shipped'"
    assert shipped_date is not None, "shipped_date should not be null for fully shipped order"
    assert shipped_date.startswith("2026-05-10"), \
        f"shipped_date = {shipped_date}, expected to start with '2026-05-10'"
    print(f"   ✅ status = {status}, shipped_date = {shipped_date}")
    
    # Edit completing shipment date to 2026-06-15
    print("\n[6/11] Editing completing shipment date to 2026-06-15")
    edit_response = requests.put(
        f"{BASE_URL}/orders/{order_id}/shipments/{shipment2_id}",
        headers=get_headers(),
        json={
            "date": "2026-06-15",
            "items": [{
                "order_item_id": order_item_id,
                "qty": 3
            }]
        }
    )
    assert edit_response.status_code == 200, f"Shipment edit failed: {edit_response.status_code}"
    print(f"   ✅ Shipment date edited")
    
    # Verify shipped_date now starts with 2026-06-15
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipped_date = order.get("shipped_date")
    
    assert shipped_date is not None, "shipped_date should not be null"
    assert shipped_date.startswith("2026-06-15"), \
        f"shipped_date = {shipped_date}, expected to start with '2026-06-15'"
    print(f"   ✅ shipped_date updated to {shipped_date}")
    
    # Delete completing shipment
    print("\n[7/11] Deleting completing shipment")
    delete_response = requests.delete(
        f"{BASE_URL}/orders/{order_id}/shipments/{shipment2_id}",
        headers=get_headers()
    )
    assert delete_response.status_code == 200, f"Shipment deletion failed: {delete_response.status_code}"
    print(f"   ✅ Completing shipment deleted")
    
    # Verify status = Partially Shipped, shipped_date = null (cleared)
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    status = order.get("status")
    shipped_date = order.get("shipped_date")
    
    assert status == "Partially Shipped", f"Status = {status}, expected 'Partially Shipped'"
    assert shipped_date is None, f"shipped_date should be null after deleting completing shipment, got {shipped_date}"
    print(f"   ✅ status = {status}, shipped_date = null (cleared)")
    
    # Add it back with date 2026-07-20
    print("\n[8/11] Adding completing shipment back with date 2026-07-20")
    shipment3_response = requests.post(
        f"{BASE_URL}/orders/{order_id}/shipments",
        headers=get_headers(),
        json={
            "date": "2026-07-20",
            "items": [{
                "order_item_id": order_item_id,
                "qty": 3
            }]
        }
    )
    assert shipment3_response.status_code == 200, f"Shipment re-creation failed: {shipment3_response.status_code}"
    
    # Get shipment ID from order
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipment3_id = order["shipments"][1]["id"]  # Second shipment (index 1)
    print(f"   ✅ Completing shipment re-created: {shipment3_id}")
    
    # Verify status = Fully Shipped, shipped_date starts with 2026-07-20
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    status = order.get("status")
    shipped_date = order.get("shipped_date")
    
    assert status == "Fully Shipped", f"Status = {status}, expected 'Fully Shipped'"
    assert shipped_date is not None, "shipped_date should not be null"
    assert shipped_date.startswith("2026-07-20"), \
        f"shipped_date = {shipped_date}, expected to start with '2026-07-20'"
    print(f"   ✅ status = {status}, shipped_date = {shipped_date}")
    
    # Idempotency: call POST /api/reconcile/run twice
    print("\n[9/11] Testing idempotency: POST /api/reconcile/run twice")
    reconcile1_response = requests.post(f"{BASE_URL}/reconcile/run", headers=get_headers())
    assert reconcile1_response.status_code == 200, f"Reconcile run 1 failed: {reconcile1_response.status_code}"
    reconcile1 = reconcile1_response.json()
    shipped_date_after_recon1 = order_response.json().get("shipped_date")
    
    reconcile2_response = requests.post(f"{BASE_URL}/reconcile/run", headers=get_headers())
    assert reconcile2_response.status_code == 200, f"Reconcile run 2 failed: {reconcile2_response.status_code}"
    
    order_response = requests.get(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    order = order_response.json()
    shipped_date_after_recon2 = order.get("shipped_date")
    
    # Verify shipped_date didn't drift
    assert shipped_date_after_recon2 == shipped_date, \
        f"shipped_date drifted after reconcile: {shipped_date} → {shipped_date_after_recon2}"
    print(f"   ✅ shipped_date unchanged after 2x reconcile runs (idempotent)")
    
    # Cleanup
    print("\n[10/11] Cleaning up: deleting order")
    delete_response = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=get_headers())
    assert delete_response.status_code == 200, f"Order deletion failed: {delete_response.status_code}"
    
    print("[11/11] Cleanup complete (customer not deleted - was pre-existing)")
    
    print(f"\n   ✅ Cleanup complete")


def test_regression_checks():
    """
    Regression checks to ensure no existing functionality broke
    """
    print("\n" + "="*80)
    print("REGRESSION CHECKS")
    print("="*80)
    
    # 1. GET /api/reconcile: healthy=true, 21/21
    print("\n[1/5] Testing GET /api/reconcile")
    response = requests.get(f"{BASE_URL}/reconcile", headers=get_headers())
    assert response.status_code == 200, f"Reconcile failed: {response.status_code}"
    reconcile = response.json()
    
    healthy = reconcile.get("healthy")
    summary = reconcile.get("summary", {})
    passed = summary.get("passed")
    total = summary.get("total")
    engine_version = reconcile.get("engine_version")
    
    assert healthy == True, f"Reconcile healthy = {healthy}, expected True"
    assert passed == 21, f"Reconcile passed = {passed}, expected 21"
    assert total == 21, f"Reconcile total = {total}, expected 21"
    assert engine_version == "P5", f"Reconcile engine_version = {engine_version}, expected 'P5'"
    
    print(f"   ✅ Reconcile: healthy={healthy}, {passed}/{total} passed, engine={engine_version}")
    
    # 2. GET /api/party-ledger-v2/summary
    print("\n[2/5] Testing GET /api/party-ledger-v2/summary")
    response = requests.get(f"{BASE_URL}/party-ledger-v2/summary", headers=get_headers())
    assert response.status_code == 200, f"Party ledger summary failed: {response.status_code}"
    summary = response.json()
    
    expected_keys = [
        "fathers_firm_you_pay", "fathers_firm_you_receive",
        "vendor_you_pay", "vendor_advances_you_receive",
        "customer_you_receive", "customer_advances_you_pay",
        "net_position"
    ]
    
    for key in expected_keys:
        assert key in summary, f"Missing key '{key}' in party-ledger-v2/summary"
        assert isinstance(summary[key], (int, float)), f"Key '{key}' is not numeric"
    
    print(f"   ✅ Party ledger summary: all 7 keys present and numeric")
    
    # 3. GET /api/party-ledger-v2/fathers-firm-settlement
    print("\n[3/5] Testing GET /api/party-ledger-v2/fathers-firm-settlement")
    response = requests.get(f"{BASE_URL}/party-ledger-v2/fathers-firm-settlement", headers=get_headers())
    assert response.status_code == 200, f"FF settlement failed: {response.status_code}"
    settlement = response.json()
    
    expected_keys = ["party_id", "party_name", "balance_signed", "amount", "status", "label"]
    for key in expected_keys:
        assert key in settlement, f"Missing key '{key}' in fathers-firm-settlement"
    
    status = settlement.get("status")
    assert status in ["settled", "you_pay", "you_receive"], \
        f"FF settlement status = {status}, expected one of [settled, you_pay, you_receive]"
    assert status == status.lower(), f"FF settlement status should be lowercase, got {status}"
    
    print(f"   ✅ FF settlement: all keys present, status={status} (lowercase)")
    
    # 4. GET /api/dashboard - check all KPIs
    print("\n[4/5] Testing GET /api/dashboard - all KPIs present")
    response = requests.get(f"{BASE_URL}/dashboard", headers=get_headers())
    assert response.status_code == 200, f"Dashboard failed: {response.status_code}"
    dashboard = response.json()
    kpis = dashboard.get("kpis", {})
    
    expected_kpis = [
        "received", "paid", "net_profit", "estimated_revenue",
        "estimated_net_profit", "customer_advances", "outstanding_receivable"
    ]
    
    for kpi in expected_kpis:
        assert kpi in kpis, f"Missing KPI '{kpi}' in dashboard"
        value = kpis[kpi]
        assert isinstance(value, (int, float)), f"KPI '{kpi}' is not numeric"
        
        # customer_advances and outstanding_receivable should be non-negative
        if kpi in ["customer_advances", "outstanding_receivable"]:
            assert value >= 0, f"KPI '{kpi}' = {value}, should be non-negative"
    
    print(f"   ✅ Dashboard: all expected KPIs present and numeric")
    
    # 5. GET /api/accounts/{id}/balance - composition identity for first 10 accounts
    print("\n[5/5] Testing GET /api/accounts/{id}/balance - composition identity")
    accounts_response = requests.get(f"{BASE_URL}/accounts", headers=get_headers())
    assert accounts_response.status_code == 200, f"Accounts list failed: {accounts_response.status_code}"
    accounts = accounts_response.json()
    
    test_count = min(10, len(accounts))
    print(f"   Testing {test_count} accounts...")
    
    for i, account in enumerate(accounts[:test_count]):
        account_id = account["id"]
        balance_response = requests.get(f"{BASE_URL}/accounts/{account_id}/balance", headers=get_headers())
        assert balance_response.status_code == 200, f"Account balance failed for {account_id}"
        balance_data = balance_response.json()
        
        opening = balance_data.get("opening_balance", 0)
        incoming = balance_data.get("incoming", 0)
        outgoing = balance_data.get("outgoing", 0)
        transfer_net = balance_data.get("transfer_net", 0)
        balance = balance_data.get("balance", 0)
        
        # Composition identity: opening + incoming - outgoing + transfer_net == balance
        computed_balance = opening + incoming - outgoing + transfer_net
        diff = abs(computed_balance - balance)
        
        assert diff <= 0.01, \
            f"Account {account_id}: composition identity failed. " \
            f"opening({opening}) + incoming({incoming}) - outgoing({outgoing}) + transfer_net({transfer_net}) " \
            f"= {computed_balance}, but balance = {balance} (diff = {diff})"
    
    print(f"   ✅ All {test_count} accounts: composition identity satisfied (within ±0.01)")


def main():
    """Main test runner"""
    print("\n" + "="*80)
    print("BACKEND API TEST SUITE")
    print("Bug Fix Verification: Dashboard Outstanding Receivable + Order Shipped Date")
    print("="*80)
    
    try:
        # Login
        login()
        
        # Bug 1 tests
        test_bug1_dashboard_outstanding_receivable()
        test_bug1_live_edge_cases()
        
        # Bug 2 tests
        test_bug2_order_shipped_date()
        test_bug2_live_shipment_flow()
        
        # Regression tests
        test_regression_checks()
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        
    except AssertionError as e:
        print("\n" + "="*80)
        print(f"❌ TEST FAILED: {e}")
        print("="*80)
        raise
    except Exception as e:
        print("\n" + "="*80)
        print(f"❌ ERROR: {e}")
        print("="*80)
        raise


if __name__ == "__main__":
    main()
