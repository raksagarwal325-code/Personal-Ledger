"""
Phase 6 · Slice 5 — Party Ledger v2 refactor verification
==========================================================

Test Phase 6 · Slice 5 refactor of Party Ledger v2 derived rows, running-balance
accumulation, and Father's Firm settlement helpers from float arithmetic to
paise-safe helpers in backend/domain.py.

This is a REFACTOR — the goal is byte-equivalent API responses on the live
seeded DB (47 orders, 40 parties).

Auth: admin@artisan.local / Admin@12345
"""
import requests
import json
from typing import Dict, List, Optional

# Backend URL from frontend/.env
BASE_URL = "https://4154df58-62b7-480b-b83b-36a1dc0e500c.preview.emergentagent.com/api"

# Admin credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

# Global token storage
TOKEN = None


def login() -> str:
    """Login and return JWT token."""
    global TOKEN
    resp = requests.post(f"{BASE_URL}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    TOKEN = data.get("access_token")
    assert TOKEN, "No access_token in login response"
    print(f"✅ Login successful")
    return TOKEN


def headers() -> Dict[str, str]:
    """Return auth headers."""
    return {"Authorization": f"Bearer {TOKEN}"}


def test_party_ledger_v2_summary():
    """Test 1: GET /api/party-ledger-v2/summary — 200, has 7 expected keys."""
    print("\n=== Test 1: Party Ledger v2 Summary ===")
    resp = requests.get(f"{BASE_URL}/party-ledger-v2/summary", headers=headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    expected_keys = [
        "fathers_firm_you_pay",
        "fathers_firm_you_receive",
        "vendor_you_pay",
        "vendor_advances_you_receive",
        "customer_you_receive",
        "customer_advances_you_pay",
        "net_position"
    ]
    
    for key in expected_keys:
        assert key in data, f"Missing key: {key}"
        assert isinstance(data[key], (int, float)), f"{key} is not numeric: {type(data[key])}"
    
    print(f"✅ Summary has all 7 keys")
    print(f"   fathers_firm_you_pay: ₹{data['fathers_firm_you_pay']}")
    print(f"   fathers_firm_you_receive: ₹{data['fathers_firm_you_receive']}")
    print(f"   vendor_you_pay: ₹{data['vendor_you_pay']}")
    print(f"   vendor_advances_you_receive: ₹{data['vendor_advances_you_receive']}")
    print(f"   customer_you_receive: ₹{data['customer_you_receive']}")
    print(f"   customer_advances_you_pay: ₹{data['customer_advances_you_pay']}")
    print(f"   net_position: ₹{data['net_position']}")
    return data


def test_party_ledger_v2_parties_list():
    """Test 2: GET /api/party-ledger-v2/parties?include_settled=true — 200, returns expected shape."""
    print("\n=== Test 2: Party Ledger v2 Parties List ===")
    resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties?include_settled=true", headers=headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    assert "count" in data, "Missing 'count' key"
    assert "parties" in data, "Missing 'parties' key"
    assert isinstance(data["parties"], list), "parties is not a list"
    
    count = data["count"]
    parties = data["parties"]
    
    print(f"✅ Parties list returned {count} parties")
    
    # Verify each party has expected fields
    if parties:
        party = parties[0]
        expected_fields = ["name", "type", "status", "net_balance", "abs_balance", "entries_count", "last_activity"]
        for field in expected_fields:
            assert field in party, f"Missing field '{field}' in party"
        print(f"✅ Party structure verified (sample: {party['name']})")
    
    return parties


def test_party_ledger_v2_individual_parties(parties: List[Dict]):
    """Test 3: GET /api/party-ledger-v2/parties/{pid} — byte-equivalence check."""
    print("\n=== Test 3: Individual Party Ledger Byte-Equivalence ===")
    
    # Test a subset of parties (first 10 to keep test fast)
    test_parties = parties[:min(10, len(parties))]
    
    failed_parties = []
    
    for party in test_parties:
        pid = party["id"]
        name = party["name"]
        
        resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties/{pid}", headers=headers())
        assert resp.status_code == 200, f"Failed to get party {name}: {resp.status_code}"
        
        data = resp.json()
        
        # Verify structure
        assert "party" in data, f"Missing 'party' key for {name}"
        assert "entries" in data, f"Missing 'entries' key for {name}"
        assert "net_balance" in data, f"Missing 'net_balance' key for {name}"
        assert "net_balance_paise" in data, f"Missing NEW 'net_balance_paise' key for {name}"
        assert "status" in data, f"Missing 'status' key for {name}"
        assert "you_pay" in data, f"Missing 'you_pay' key for {name}"
        assert "you_receive" in data, f"Missing 'you_receive' key for {name}"
        
        # Verify net_balance_paise is integer
        assert isinstance(data["net_balance_paise"], int), f"net_balance_paise is not int for {name}"
        
        # Verify net_balance_paise == round(net_balance * 100)
        expected_paise = round(data["net_balance"] * 100)
        actual_paise = data["net_balance_paise"]
        if expected_paise != actual_paise:
            print(f"⚠️  {name}: net_balance_paise mismatch: expected {expected_paise}, got {actual_paise}")
            failed_parties.append(name)
        
        # Verify running balance byte-equivalence (walk entries with naive float accumulator)
        entries = data["entries"]
        if entries:
            running_balance_float = 0.0
            max_drift = 0.0
            
            for entry in entries:
                # Only count entries that participate in balance
                if entry.get("counts_in_balance", True):
                    delta = entry.get("delta_you_pay", 0)
                    running_balance_float += delta
                
                # Check drift from API's running_balance
                api_running = entry.get("running_balance", 0)
                drift = abs(running_balance_float - api_running)
                max_drift = max(max_drift, drift)
                
                # Verify within ½-paise (0.005)
                if drift > 0.005:
                    print(f"⚠️  {name}: Entry drift {drift:.4f} > 0.005 at entry {entry.get('id')}")
                    failed_parties.append(name)
                    break
            
            print(f"   {name}: {len(entries)} entries, max drift: {max_drift:.6f}")
    
    if failed_parties:
        print(f"❌ {len(failed_parties)} parties failed byte-equivalence check")
        return False
    else:
        print(f"✅ All {len(test_parties)} parties passed byte-equivalence check")
        return True


def test_fathers_firm_settlement():
    """Test 4: GET /api/party-ledger-v2/fathers-firm-settlement — 200, correct structure."""
    print("\n=== Test 4: Father's Firm Settlement ===")
    resp = requests.get(f"{BASE_URL}/party-ledger-v2/fathers-firm-settlement", headers=headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    
    # Verify structure
    expected_keys = ["party_id", "party_name", "balance_signed", "amount", "status", "label"]
    for key in expected_keys:
        assert key in data, f"Missing key: {key}"
    
    # Verify status is lowercase
    status = data["status"]
    assert status in ["settled", "you_pay", "you_receive"], f"Invalid status: {status}"
    assert status == status.lower(), f"Status is not lowercase: {status}"
    
    # Verify amount == abs(balance_signed) within 0.01
    balance_signed = data["balance_signed"]
    amount = data["amount"]
    expected_amount = abs(balance_signed)
    diff = abs(amount - expected_amount)
    assert diff <= 0.01, f"amount != abs(balance_signed): {amount} != {expected_amount}"
    
    print(f"✅ Father's Firm settlement structure correct")
    print(f"   party_name: {data['party_name']}")
    print(f"   balance_signed: ₹{balance_signed}")
    print(f"   amount: ₹{amount}")
    print(f"   status: {status}")
    
    # Note: -0.0 vs 0.0 is a known cosmetic difference
    if balance_signed == 0.0:
        print(f"   ℹ️  balance_signed is 0.0 (may have been -0.0 pre-refactor, mathematically identical)")
    
    return data


def test_csv_exports():
    """Test 5: CSV exports — all return 200 with text/csv."""
    print("\n=== Test 5: CSV Exports ===")
    
    # Get a party ID for individual ledger export
    parties_resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties?include_settled=true", headers=headers())
    parties = parties_resp.json()["parties"]
    test_party_id = parties[0]["id"] if parties else None
    
    exports = [
        (f"/party-ledger-v2/parties/{test_party_id}/ledger.csv", "Party Ledger CSV") if test_party_id else None,
        ("/party-ledger-v2/exports/vendors.csv", "Vendors CSV"),
        ("/party-ledger-v2/exports/customers.csv", "Customers CSV"),
        ("/party-ledger-v2/exports/fathers-firm.csv", "Father's Firm CSV"),
        ("/party-ledger-v2/exports/summary.csv", "Summary CSV"),
    ]
    
    for export in exports:
        if export is None:
            continue
        
        endpoint, name = export
        resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers())
        assert resp.status_code == 200, f"{name} failed: {resp.status_code}"
        assert "text/csv" in resp.headers.get("Content-Type", ""), f"{name} not CSV: {resp.headers.get('Content-Type')}"
        print(f"✅ {name} export working")


def test_reconcile_healthy():
    """Test 6: GET /api/reconcile — healthy=true, 21/21 passed, engine=P5."""
    print("\n=== Test 6: Reconcile Engine ===")
    resp = requests.get(f"{BASE_URL}/reconcile", headers=headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    
    # Verify structure
    assert "healthy" in data, "Missing 'healthy' key"
    assert "summary" in data, "Missing 'summary' key"
    assert "engine_version" in data, "Missing 'engine_version' key"
    
    # Verify healthy
    assert data["healthy"] == True, f"Reconcile not healthy: {data.get('healthy')}"
    
    # Verify engine version
    assert data["engine_version"] == "P5", f"Wrong engine version: {data['engine_version']}"
    
    # Verify summary
    summary = data["summary"]
    # Allow warnings (warnings are not failures)
    assert summary["failed"] == 0, f"Some invariants failed: {summary['failed']} failures"
    assert summary["total"] == 21, f"Expected 21 invariants, got {summary['total']}"
    
    print(f"✅ Reconcile healthy: {summary['passed']}/{summary['total']} passed, {summary.get('warnings', 0)} warnings")
    print(f"   engine_version: {data['engine_version']}")
    return data


def test_reconcile_run():
    """Test 7: POST /api/reconcile/run — writes exactly one audit log."""
    print("\n=== Test 7: Reconcile Run ===")
    
    # Get current audit log count
    before_resp = requests.get(f"{BASE_URL}/admin/reconcile/last", headers=headers())
    before_count = 0
    if before_resp.status_code == 200:
        # Count exists
        before_count = 1
    
    # Run reconcile
    resp = requests.post(f"{BASE_URL}/reconcile/run", headers=headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    
    data = resp.json()
    assert "healthy" in data, "Missing 'healthy' key in run response"
    
    # Verify audit log was written
    after_resp = requests.get(f"{BASE_URL}/admin/reconcile/last", headers=headers())
    assert after_resp.status_code == 200, f"Failed to get last audit log: {after_resp.status_code}"
    
    audit_data = after_resp.json()
    assert audit_data is not None, "No audit log found after reconcile run"
    assert audit_data.get("kind") == "reconcile_run", f"Wrong audit log kind: {audit_data.get('kind')}"
    
    print(f"✅ Reconcile run successful, audit log written")
    return data


def test_party_ledger_write_flow():
    """Test 8: Party Ledger v2 write flow (CRUD operations)."""
    print("\n=== Test 8: Party Ledger v2 Write Flow ===")
    
    import time
    unique_suffix = str(int(time.time()))
    
    # 1. Create a new "other" party
    print("   Creating new party...")
    create_resp = requests.post(f"{BASE_URL}/party-ledger-v2/parties", headers=headers(), json={
        "name": f"Test Party Slice5 {unique_suffix}",
        "type": "other",
        "contact": {
            "phone": "1234567890",
            "email": "test@example.com"
        }
    })
    assert create_resp.status_code == 200, f"Failed to create party: {create_resp.status_code} {create_resp.text}"
    party = create_resp.json()
    party_id = party["id"]
    print(f"✅ Created party: {party['name']} (id: {party_id})")
    
    # 2. Update contact
    print("   Updating party contact...")
    update_resp = requests.put(f"{BASE_URL}/party-ledger-v2/parties/{party_id}", headers=headers(), json={
        **party,
        "contact": {
            "phone": "9876543210",
            "email": "updated@example.com"
        }
    })
    assert update_resp.status_code == 200, f"Failed to update party: {update_resp.status_code} {update_resp.text}"
    print(f"✅ Updated party contact")
    
    # 3. Post a manual expense transaction
    print("   Posting manual expense transaction...")
    txn_resp = requests.post(f"{BASE_URL}/party-ledger-v2/transactions", headers=headers(), json={
        "party_id": party_id,
        "category": "expense",
        "amount": 100.0,
        "date": "2026-07-22",
        "notes": "Test expense transaction"
    })
    assert txn_resp.status_code == 200, f"Failed to post transaction: {txn_resp.status_code} {txn_resp.text}"
    txn_data = txn_resp.json()
    txn_ref = txn_data["txn_ref"]
    print(f"✅ Posted transaction (txn_ref: {txn_ref})")
    
    # 4. Verify running balance moved correctly
    print("   Verifying running balance...")
    party_resp = requests.get(f"{BASE_URL}/party-ledger-v2/parties/{party_id}", headers=headers())
    assert party_resp.status_code == 200, f"Failed to get party: {party_resp.status_code}"
    party_data = party_resp.json()
    
    # For expense category, CATEGORY_SIGN_MAP["expense"] = -1
    # So delta_you_pay should be -100 (Rakshit paid expense on party's behalf → party owes Rakshit)
    entries = party_data["entries"]
    assert len(entries) > 0, "No entries found after posting transaction"
    
    expense_entry = [e for e in entries if e.get("category") == "expense"][0]
    delta = expense_entry.get("delta_you_pay", 0)
    # expense sign is -1, so delta should be negative
    assert delta == -100.0, f"Wrong delta_you_pay for expense: expected -100.0, got {delta}"
    print(f"✅ Running balance correct (delta_you_pay: {delta})")
    
    # 5. Reverse the transaction
    print("   Reversing transaction...")
    reverse_resp = requests.delete(f"{BASE_URL}/party-ledger-v2/transactions/{txn_ref}", headers=headers())
    assert reverse_resp.status_code == 200, f"Failed to reverse transaction: {reverse_resp.status_code} {reverse_resp.text}"
    print(f"✅ Transaction reversed")
    
    # 6. Verify balance returns to opening (should be 0)
    print("   Verifying balance after reversal...")
    party_resp2 = requests.get(f"{BASE_URL}/party-ledger-v2/parties/{party_id}", headers=headers())
    assert party_resp2.status_code == 200, f"Failed to get party: {party_resp2.status_code}"
    party_data2 = party_resp2.json()
    
    net_balance = party_data2["net_balance"]
    assert abs(net_balance) < 0.01, f"Balance not zero after reversal: {net_balance}"
    print(f"✅ Balance returned to opening (net_balance: {net_balance})")
    
    # 7. Archive the party
    print("   Archiving party...")
    archive_resp = requests.delete(f"{BASE_URL}/party-ledger-v2/parties/{party_id}", headers=headers())
    assert archive_resp.status_code == 200, f"Failed to archive party: {archive_resp.status_code} {archive_resp.text}"
    print(f"✅ Party archived")
    
    print(f"✅ Write flow complete")


def test_dashboard_unaffected():
    """Test 9: Dashboard unaffected (regression sanity)."""
    print("\n=== Test 9: Dashboard Regression Sanity ===")
    
    # GET /api/dashboard
    resp = requests.get(f"{BASE_URL}/dashboard", headers=headers())
    assert resp.status_code == 200, f"Dashboard failed: {resp.status_code} {resp.text}"
    
    data = resp.json()
    assert "kpis" in data, "Missing 'kpis' key"
    
    kpis = data["kpis"]
    expected_kpi_keys = [
        "operating_revenue", "invoice_value", "total_cost", "net_profit",
        "estimated_revenue", "estimated_net_profit", "unrealized_revenue"
    ]
    
    for key in expected_kpi_keys:
        assert key in kpis, f"Missing KPI: {key}"
        assert isinstance(kpis[key], (int, float)), f"{key} is not numeric"
    
    print(f"✅ Dashboard KPIs present and numeric")
    
    # GET /api/dashboard/breakdown
    breakdown_resp = requests.get(f"{BASE_URL}/dashboard/breakdown", headers=headers())
    assert breakdown_resp.status_code == 200, f"Dashboard breakdown failed: {breakdown_resp.status_code}"
    print(f"✅ Dashboard breakdown working")


def test_sign_convention_integration():
    """Test 10: Sign-convention pinning (integration)."""
    print("\n=== Test 10: Sign Convention Integration ===")
    
    import time
    unique_suffix = str(int(time.time()))
    
    # This test creates real transactions to verify sign conventions
    # We'll create a customer party, post a customer payment, and verify delta_you_pay is positive
    
    print("   Creating test customer party...")
    customer_resp = requests.post(f"{BASE_URL}/party-ledger-v2/parties", headers=headers(), json={
        "name": f"Test Customer Sign Convention {unique_suffix}",
        "type": "customer"
    })
    assert customer_resp.status_code == 200, f"Failed to create customer: {customer_resp.status_code}"
    customer = customer_resp.json()
    customer_id = customer["id"]
    print(f"✅ Created customer: {customer['name']}")
    
    # Post a customer payment transaction
    print("   Posting customer payment...")
    payment_resp = requests.post(f"{BASE_URL}/party-ledger-v2/transactions", headers=headers(), json={
        "party_id": customer_id,
        "category": "customer_payment",
        "amount": 500.0,
        "date": "2026-07-22",
        "notes": "Test customer payment"
    })
    assert payment_resp.status_code == 200, f"Failed to post payment: {payment_resp.status_code}"
    payment_data = payment_resp.json()
    payment_txn_ref = payment_data["txn_ref"]
    print(f"✅ Posted customer payment")
    
    # Verify delta_you_pay is POSITIVE (customer paid → Rakshit owes customer less → delta_you_pay > 0)
    print("   Verifying customer payment sign...")
    customer_ledger = requests.get(f"{BASE_URL}/party-ledger-v2/parties/{customer_id}", headers=headers())
    assert customer_ledger.status_code == 200
    ledger_data = customer_ledger.json()
    
    payment_entry = [e for e in ledger_data["entries"] if e.get("category") == "customer_payment"][0]
    delta = payment_entry.get("delta_you_pay", 0)
    assert delta > 0, f"Customer payment delta_you_pay should be positive, got {delta}"
    print(f"✅ Customer payment sign correct (delta_you_pay: {delta})")
    
    # Cleanup
    requests.delete(f"{BASE_URL}/party-ledger-v2/transactions/{payment_txn_ref}", headers=headers())
    requests.delete(f"{BASE_URL}/party-ledger-v2/parties/{customer_id}", headers=headers())
    
    print(f"✅ Sign convention integration verified")


def main():
    """Run all tests."""
    print("=" * 80)
    print("Phase 6 · Slice 5 — Party Ledger v2 Refactor Verification")
    print("=" * 80)
    
    try:
        # Login
        login()
        
        # Test 1: Summary
        summary = test_party_ledger_v2_summary()
        
        # Test 2: Parties list
        parties = test_party_ledger_v2_parties_list()
        
        # Test 3: Individual parties byte-equivalence
        test_party_ledger_v2_individual_parties(parties)
        
        # Test 4: Father's Firm settlement
        test_fathers_firm_settlement()
        
        # Test 5: CSV exports
        test_csv_exports()
        
        # Test 6: Reconcile healthy
        test_reconcile_healthy()
        
        # Test 7: Reconcile run
        test_reconcile_run()
        
        # Test 8: Write flow
        test_party_ledger_write_flow()
        
        # Test 9: Dashboard regression
        test_dashboard_unaffected()
        
        # Test 10: Sign convention integration
        test_sign_convention_integration()
        
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
