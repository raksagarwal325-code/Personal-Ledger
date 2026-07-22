"""
Backend API test for GST settlement with Father's Firm bug fix (2026-07-22).

Tests all 10 verification scenarios (a-j) from the review request.
"""
import requests
import json
from typing import Optional

# Backend URL - use internal localhost for testing
BASE_URL = "http://localhost:8001/api"

# Admin credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Global auth token
auth_token: Optional[str] = None


def login() -> str:
    """Login as admin and return access token."""
    global auth_token
    resp = requests.post(f"{BASE_URL}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    auth_token = data.get("access_token")
    assert auth_token, "No access_token in login response"
    print(f"✓ Logged in as {ADMIN_EMAIL}")
    return auth_token


def headers() -> dict:
    """Return auth headers."""
    return {"Authorization": f"Bearer {auth_token}"}


def get_ff_party_id() -> str:
    """Get Father's Firm party ID."""
    resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties?type=fathers_firm", headers=headers())
    assert resp.status_code == 200, f"Failed to get FF party: {resp.status_code}"
    data = resp.json()
    parties = data.get("parties", [])
    assert len(parties) > 0, "No Father's Firm party found"
    ff_party = parties[0]
    return ff_party["id"]


def get_ff_ledger(ff_party_id: str) -> dict:
    """Get Father's Firm ledger entries."""
    resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties/{ff_party_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to get FF ledger: {resp.status_code}"
    return resp.json()


def count_gst_settlement_entries(ff_party_id: str, order_id: str) -> int:
    """Count gst_settlement entries for a specific order on FF's ledger."""
    ledger = get_ff_ledger(ff_party_id)
    entries = ledger.get("entries", [])
    count = sum(1 for e in entries 
                if e.get("category") == "gst_settlement" 
                and e.get("related_order_id") == order_id)
    return count


def get_gst_settlement_entry(ff_party_id: str, order_id: str) -> Optional[dict]:
    """Get the gst_settlement entry for a specific order."""
    ledger = get_ff_ledger(ff_party_id)
    entries = ledger.get("entries", [])
    for e in entries:
        if e.get("category") == "gst_settlement" and e.get("related_order_id") == order_id:
            return e
    return None


def test_scenario_a():
    """Scenario a: Happy path - taxable order with shipment → FF has exactly ONE gst_settlement entry."""
    print("\n=== Scenario a: Happy path ===")
    
    ff_party_id = get_ff_party_id()
    
    # Create taxable order
    order_payload = {
        "client_name": "BTA_GST_A",
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "GST test",
            "qty": 1,
            "rate": 1000,
            "product_sales": 1000
        }],
        "tax_applicable": True,
        "tax_type": "CGST_SGST",
        "tax_percent": 18
    }
    
    resp = requests.post(f"{BASE_URL}/orders", json=order_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create order: {resp.status_code} {resp.text}"
    order = resp.json()
    order_id = order["id"]
    item_id = order["items"][0]["id"]
    
    # Verify gst_ff_settle is True
    assert order.get("gst_ff_settle") == True, f"gst_ff_settle should be True, got {order.get('gst_ff_settle')}"
    print(f"✓ Order created with gst_ff_settle=True: {order_id[:8]}")
    
    # Add shipment
    shipment_payload = {
        "date": "2026-07-22",
        "items": [{"order_item_id": item_id, "qty": 1}],
        "boxes_shipped": 1,
        "freight_paid": 0,
        "freight_charged": 0,
        "transporter": ""
    }
    
    resp = requests.post(f"{BASE_URL}/orders/{order_id}/shipments", json=shipment_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to add shipment: {resp.status_code} {resp.text}"
    print(f"✓ Shipment added")
    
    # Get updated order
    resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to get order: {resp.status_code}"
    order = resp.json()
    tax_amount = order.get("tax_amount", 0)
    print(f"✓ Order tax_amount: ₹{tax_amount} (expected ~180)")
    assert abs(tax_amount - 180) < 1, f"Expected tax_amount ~180, got {tax_amount}"
    
    # Check FF ledger for gst_settlement entry
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 1, f"Expected exactly 1 gst_settlement entry, found {count}"
    print(f"✓ Found exactly 1 gst_settlement entry on FF ledger")
    
    entry = get_gst_settlement_entry(ff_party_id, order_id)
    assert entry is not None, "gst_settlement entry not found"
    
    delta_you_pay = entry.get("delta_you_pay", 0)
    print(f"✓ delta_you_pay: ₹{delta_you_pay} (expected ~180)")
    assert abs(delta_you_pay - 180) < 1, f"Expected delta_you_pay ~180, got {delta_you_pay}"
    assert delta_you_pay > 0, f"delta_you_pay should be positive, got {delta_you_pay}"
    
    print(f"✅ Scenario a PASSED")
    return order_id


def test_scenario_b():
    """Scenario b: Order with tax but NO shipment → no GST entry on FF."""
    print("\n=== Scenario b: No shipment ===")
    
    ff_party_id = get_ff_party_id()
    
    # Create taxable order WITHOUT shipment
    order_payload = {
        "client_name": "BTA_GST_B",
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "GST test no ship",
            "qty": 1,
            "rate": 1000,
            "product_sales": 1000
        }],
        "tax_applicable": True,
        "tax_type": "CGST_SGST",
        "tax_percent": 18
    }
    
    resp = requests.post(f"{BASE_URL}/orders", json=order_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create order: {resp.status_code} {resp.text}"
    order = resp.json()
    order_id = order["id"]
    print(f"✓ Order created without shipment: {order_id[:8]}")
    
    # Check FF ledger - should have NO gst_settlement entry
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 0, f"Expected 0 gst_settlement entries (no shipment), found {count}"
    print(f"✓ No gst_settlement entry on FF ledger (invoice not raised)")
    
    print(f"✅ Scenario b PASSED")
    return order_id


def test_scenario_c(order_id: str):
    """Scenario c: Change tax_percent → FF entry updates (idempotent, still 1 row)."""
    print("\n=== Scenario c: Tax change idempotency ===")
    
    ff_party_id = get_ff_party_id()
    
    # Get current order
    resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to get order: {resp.status_code}"
    order = resp.json()
    
    # Update tax_percent to 12%
    order["tax_percent"] = 12
    resp = requests.put(f"{BASE_URL}/orders/{order_id}", json=order, headers=headers())
    assert resp.status_code == 200, f"Failed to update order: {resp.status_code} {resp.text}"
    print(f"✓ Updated tax_percent to 12%")
    
    # Get updated order
    resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to get order: {resp.status_code}"
    order = resp.json()
    new_tax_amount = order.get("tax_amount", 0)
    print(f"✓ New tax_amount: ₹{new_tax_amount} (expected ~120)")
    assert abs(new_tax_amount - 120) < 1, f"Expected tax_amount ~120, got {new_tax_amount}"
    
    # Check FF ledger - should still have exactly 1 entry with new amount
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 1, f"Expected exactly 1 gst_settlement entry (idempotent), found {count}"
    print(f"✓ Still exactly 1 gst_settlement entry (idempotent)")
    
    entry = get_gst_settlement_entry(ff_party_id, order_id)
    assert entry is not None, "gst_settlement entry not found"
    
    delta_you_pay = entry.get("delta_you_pay", 0)
    print(f"✓ Updated delta_you_pay: ₹{delta_you_pay} (expected ~120)")
    assert abs(delta_you_pay - 120) < 1, f"Expected delta_you_pay ~120, got {delta_you_pay}"
    
    print(f"✅ Scenario c PASSED")


def test_scenario_d(order_id: str):
    """Scenario d: Cancel order → GST entry disappears."""
    print("\n=== Scenario d: Cancellation ===")
    
    ff_party_id = get_ff_party_id()
    
    # Get current order
    resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to get order: {resp.status_code}"
    order = resp.json()
    
    # Cancel order
    order["status"] = "Cancelled"
    resp = requests.put(f"{BASE_URL}/orders/{order_id}", json=order, headers=headers())
    assert resp.status_code == 200, f"Failed to cancel order: {resp.status_code} {resp.text}"
    print(f"✓ Order cancelled")
    
    # Check FF ledger - gst_settlement entry should be gone
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 0, f"Expected 0 gst_settlement entries (cancelled), found {count}"
    print(f"✓ gst_settlement entry removed from FF ledger")
    
    print(f"✅ Scenario d PASSED")


def test_scenario_e():
    """Scenario e: Delete order → GST entry disappears."""
    print("\n=== Scenario e: Deletion ===")
    
    ff_party_id = get_ff_party_id()
    
    # Create a fresh order with shipment
    order_payload = {
        "client_name": "BTA_GST_E",
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "GST test delete",
            "qty": 1,
            "rate": 1000,
            "product_sales": 1000
        }],
        "tax_applicable": True,
        "tax_type": "CGST_SGST",
        "tax_percent": 18
    }
    
    resp = requests.post(f"{BASE_URL}/orders", json=order_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create order: {resp.status_code} {resp.text}"
    order = resp.json()
    order_id = order["id"]
    item_id = order["items"][0]["id"]
    
    # Add shipment
    shipment_payload = {
        "date": "2026-07-22",
        "items": [{"order_item_id": item_id, "qty": 1}],
        "boxes_shipped": 1,
        "freight_paid": 0,
        "freight_charged": 0,
        "transporter": ""
    }
    
    resp = requests.post(f"{BASE_URL}/orders/{order_id}/shipments", json=shipment_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to add shipment: {resp.status_code} {resp.text}"
    print(f"✓ Order created with shipment: {order_id[:8]}")
    
    # Verify gst_settlement entry exists
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 1, f"Expected 1 gst_settlement entry before delete, found {count}"
    
    # Delete order
    resp = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=headers())
    assert resp.status_code == 200, f"Failed to delete order: {resp.status_code} {resp.text}"
    print(f"✓ Order deleted")
    
    # Check FF ledger - gst_settlement entry should be gone
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 0, f"Expected 0 gst_settlement entries (deleted), found {count}"
    print(f"✓ gst_settlement entry removed from FF ledger")
    
    print(f"✅ Scenario e PASSED")


def test_scenario_f():
    """Scenario f: Non-taxable order → no GST entry."""
    print("\n=== Scenario f: Non-taxable ===")
    
    ff_party_id = get_ff_party_id()
    
    # Create non-taxable order with shipment
    order_payload = {
        "client_name": "BTA_GST_F",
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "Non-taxable test",
            "qty": 1,
            "rate": 1000,
            "product_sales": 1000
        }],
        "tax_applicable": False
    }
    
    resp = requests.post(f"{BASE_URL}/orders", json=order_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create order: {resp.status_code} {resp.text}"
    order = resp.json()
    order_id = order["id"]
    item_id = order["items"][0]["id"]
    
    # Add shipment
    shipment_payload = {
        "date": "2026-07-22",
        "items": [{"order_item_id": item_id, "qty": 1}],
        "boxes_shipped": 1,
        "freight_paid": 0,
        "freight_charged": 0,
        "transporter": ""
    }
    
    resp = requests.post(f"{BASE_URL}/orders/{order_id}/shipments", json=shipment_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to add shipment: {resp.status_code} {resp.text}"
    print(f"✓ Non-taxable order created with shipment: {order_id[:8]}")
    
    # Check FF ledger - should have NO gst_settlement entry
    count = count_gst_settlement_entries(ff_party_id, order_id)
    assert count == 0, f"Expected 0 gst_settlement entries (non-taxable), found {count}"
    print(f"✓ No gst_settlement entry on FF ledger (non-taxable)")
    
    print(f"✅ Scenario f PASSED")


def test_scenario_g():
    """Scenario g: Historical orders (gst_ff_settle=False) never appear as gst_settlement."""
    print("\n=== Scenario g: Historical opt-out ===")
    
    ff_party_id = get_ff_party_id()
    ledger = get_ff_ledger(ff_party_id)
    entries = ledger.get("entries", [])
    
    # Find all gst_settlement entries
    gst_entries = [e for e in entries if e.get("category") == "gst_settlement"]
    print(f"✓ Found {len(gst_entries)} gst_settlement entries on FF ledger")
    
    # For each gst_settlement entry, verify the underlying order has gst_ff_settle=True
    for entry in gst_entries:
        order_id = entry.get("related_order_id")
        if not order_id:
            continue
        
        resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers())
        if resp.status_code != 200:
            print(f"⚠ Warning: Could not fetch order {order_id[:8]}")
            continue
        
        order = resp.json()
        gst_ff_settle = order.get("gst_ff_settle", False)
        assert gst_ff_settle == True, f"Order {order_id[:8]} has gst_settlement entry but gst_ff_settle={gst_ff_settle}"
    
    print(f"✓ All gst_settlement entries are tied to orders with gst_ff_settle=True")
    print(f"✅ Scenario g PASSED")


def test_scenario_h():
    """Scenario h: Customer payment to FF doesn't duplicate GST (only 1 gst_settlement row remains)."""
    print("\n=== Scenario h: Payment doesn't double-count ===")
    
    ff_party_id = get_ff_party_id()
    
    # Create order with shipment (reuse scenario a logic)
    order_payload = {
        "client_name": "BTA_GST_H",
        "order_date": "2026-07-22",
        "status": "Confirmed",
        "items": [{
            "main_category": "Glass",
            "product_name": "GST test payment",
            "qty": 1,
            "rate": 1000,
            "product_sales": 1000
        }],
        "tax_applicable": True,
        "tax_type": "CGST_SGST",
        "tax_percent": 18
    }
    
    resp = requests.post(f"{BASE_URL}/orders", json=order_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create order: {resp.status_code} {resp.text}"
    order = resp.json()
    order_id = order["id"]
    item_id = order["items"][0]["id"]
    
    # Add shipment
    shipment_payload = {
        "date": "2026-07-22",
        "items": [{"order_item_id": item_id, "qty": 1}],
        "boxes_shipped": 1,
        "freight_paid": 0,
        "freight_charged": 0,
        "transporter": ""
    }
    
    resp = requests.post(f"{BASE_URL}/orders/{order_id}/shipments", json=shipment_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to add shipment: {resp.status_code} {resp.text}"
    print(f"✓ Order created with shipment: {order_id[:8]}")
    
    # Verify gst_settlement entry exists
    count_before = count_gst_settlement_entries(ff_party_id, order_id)
    assert count_before == 1, f"Expected 1 gst_settlement entry before payment, found {count_before}"
    
    # Create customer payment received by FF
    payment_payload = {
        "customer_name": "BTA_GST_H",
        "date": "2026-07-22",
        "amount": 500,
        "mode": "Cash",
        "received_by_party_id": ff_party_id,
        "allocations": []
    }
    
    resp = requests.post(f"{BASE_URL}/customer-payments", json=payment_payload, headers=headers())
    assert resp.status_code == 200, f"Failed to create payment: {resp.status_code} {resp.text}"
    print(f"✓ Customer payment created (received by FF)")
    
    # Check FF ledger - should still have exactly 1 gst_settlement entry
    count_after = count_gst_settlement_entries(ff_party_id, order_id)
    assert count_after == 1, f"Expected 1 gst_settlement entry after payment (no duplication), found {count_after}"
    print(f"✓ Still exactly 1 gst_settlement entry (no duplication)")
    
    # Verify there IS a customer_payment linked entry on FF
    ledger = get_ff_ledger(ff_party_id)
    entries = ledger.get("entries", [])
    cp_entries = [e for e in entries if e.get("category") == "customer_payment"]
    assert len(cp_entries) > 0, "Expected at least 1 customer_payment entry on FF ledger"
    print(f"✓ Found {len(cp_entries)} customer_payment entries on FF ledger (existing flow intact)")
    
    print(f"✅ Scenario h PASSED")


def test_scenario_i():
    """Scenario i: Reconcile → healthy:true, 21/21."""
    print("\n=== Scenario i: Reconcile ===")
    
    resp = requests.get(f"{BASE_URL}/reconcile", headers=headers())
    assert resp.status_code == 200, f"Failed to get reconcile: {resp.status_code} {resp.text}"
    data = resp.json()
    
    healthy = data.get("healthy")
    summary = data.get("summary", {})
    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    
    print(f"✓ Reconcile: healthy={healthy}, passed={passed}/{total}")
    assert healthy == True, f"Expected healthy=True, got {healthy}"
    assert passed == total, f"Expected all invariants to pass, got {passed}/{total}"
    assert total == 21, f"Expected 21 invariants, got {total}"
    
    print(f"✅ Scenario i PASSED")


def test_scenario_j():
    """Scenario j: Run pytest tests."""
    print("\n=== Scenario j: Pytest ===")
    
    import subprocess
    
    # Run pytest
    cmd = [
        "python3", "-m", "pytest",
        "tests/test_bug_gst_ff_settlement.py",
        "tests/test_bug_vendor_party_linkage.py",
        "-v", "-o", "addopts="
    ]
    
    result = subprocess.run(cmd, cwd="/app/backend", capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    # Check for pass count in output
    if "passed" in result.stdout:
        # Extract pass count from pytest output
        import re
        match = re.search(r'(\d+) passed', result.stdout)
        if match:
            passed_count = int(match.group(1))
            print(f"✓ Pytest: {passed_count} tests passed")
            assert passed_count == 25, f"Expected 25 tests to pass, got {passed_count}"
        else:
            print("⚠ Could not parse pytest output")
    
    assert result.returncode == 0, f"Pytest failed with return code {result.returncode}"
    
    print(f"✅ Scenario j PASSED")


def main():
    """Run all test scenarios."""
    print("=" * 80)
    print("GST SETTLEMENT WITH FATHER'S FIRM - BACKEND API TESTS")
    print("=" * 80)
    
    # Login
    login()
    
    # Run scenarios
    try:
        # Scenario a: Happy path
        order_a_id = test_scenario_a()
        
        # Scenario b: No shipment
        test_scenario_b()
        
        # Scenario c: Tax change (uses order from scenario a)
        test_scenario_c(order_a_id)
        
        # Scenario d: Cancellation (uses order from scenario a)
        test_scenario_d(order_a_id)
        
        # Scenario e: Deletion
        test_scenario_e()
        
        # Scenario f: Non-taxable
        test_scenario_f()
        
        # Scenario g: Historical opt-out
        test_scenario_g()
        
        # Scenario h: Payment doesn't double-count
        test_scenario_h()
        
        # Scenario i: Reconcile
        test_scenario_i()
        
        # Scenario j: Pytest
        test_scenario_j()
        
        print("\n" + "=" * 80)
        print("✅ ALL SCENARIOS PASSED")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        raise


if __name__ == "__main__":
    main()
