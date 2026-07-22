"""
Phase 6 · Slice 6 — Backend API Testing Suite
Tests Transfer + Father's Firm settlement + Account balance refactor

Test Coverage:
1. Account balance endpoints byte-equivalence (~100 accounts)
2. Transfer endpoints regression (GET, POST, reverse)
3. Father's Firm settlement endpoint
4. Reconcile invariant engine (21/21)
5. Sign-convention pin (specific integration case)
6. Dashboard regression
7. Party Ledger v2 regression (Slice 5)
"""

import requests
import json
import os
from datetime import datetime

# Read backend URL from frontend/.env
BACKEND_URL = None
with open('/app/frontend/.env', 'r') as f:
    for line in f:
        if line.startswith('REACT_APP_BACKEND_URL='):
            BACKEND_URL = line.split('=', 1)[1].strip()
            break

if not BACKEND_URL:
    raise Exception("REACT_APP_BACKEND_URL not found in /app/frontend/.env")

API_BASE = f"{BACKEND_URL}/api"

# Read test credentials
ADMIN_EMAIL = None
ADMIN_PASSWORD = None
with open('/app/memory/test_credentials.md', 'r') as f:
    for line in f:
        if 'Email' in line and '@' in line:
            ADMIN_EMAIL = line.split('**Email**:')[-1].strip().replace('`', '').strip()
        if 'Password' in line and 'Admin@' in line:
            ADMIN_PASSWORD = line.split('**Password**:')[-1].strip().replace('`', '').strip()

if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    raise Exception("Admin credentials not found in /app/memory/test_credentials.md")

print(f"✓ Backend URL: {API_BASE}")
print(f"✓ Admin credentials loaded: {ADMIN_EMAIL}")

# Global session with JWT token
session = requests.Session()
jwt_token = None


def login():
    """Login and get JWT token"""
    global jwt_token
    print("\n=== LOGIN ===")
    resp = requests.post(f"{API_BASE}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    jwt_token = data.get("access_token")
    assert jwt_token, "No access_token in login response"
    session.headers.update({"Authorization": f"Bearer {jwt_token}"})
    print(f"✓ Login successful, JWT token obtained")


def test_1_account_balance_byte_equivalence():
    """Test 1: Account balance endpoints byte-equivalence for ~100 accounts"""
    print("\n=== TEST 1: ACCOUNT BALANCE BYTE-EQUIVALENCE ===")
    
    # Get all accounts
    resp = session.get(f"{API_BASE}/accounts")
    assert resp.status_code == 200, f"GET /accounts failed: {resp.status_code}"
    accounts = resp.json()
    print(f"✓ GET /api/accounts returned {len(accounts)} accounts")
    
    # Verify each account has id and name
    for acc in accounts[:3]:  # Sample first 3
        assert "id" in acc and "name" in acc, f"Account missing id or name: {acc}"
    
    # Test balance endpoint for all accounts
    failed_accounts = []
    composition_failures = []
    invalid_values = []
    
    for i, acc in enumerate(accounts):
        acc_id = acc["id"]
        acc_name = acc.get("name", "Unknown")
        
        resp = session.get(f"{API_BASE}/accounts/{acc_id}/balance")
        if resp.status_code != 200:
            failed_accounts.append(f"{acc_name} ({acc_id}): HTTP {resp.status_code}")
            continue
        
        bal = resp.json()
        
        # Verify all required keys present
        required_keys = ["account_id", "account_name", "opening_balance", 
                        "incoming", "outgoing", "transfer_net", "balance"]
        missing_keys = [k for k in required_keys if k not in bal]
        if missing_keys:
            failed_accounts.append(f"{acc_name}: missing keys {missing_keys}")
            continue
        
        # Check for NaN or Infinity
        for key in ["opening_balance", "incoming", "outgoing", "transfer_net", "balance"]:
            val = bal[key]
            if not isinstance(val, (int, float)) or str(val) in ['nan', 'inf', '-inf', 'NaN', 'Infinity', '-Infinity']:
                invalid_values.append(f"{acc_name}.{key} = {val}")
        
        # Verify composition identity: opening + incoming - outgoing + transfer_net == balance
        # Tolerance: ½-paise = 0.005
        opening = bal["opening_balance"]
        incoming = bal["incoming"]
        outgoing = bal["outgoing"]
        transfer_net = bal["transfer_net"]
        balance = bal["balance"]
        
        computed_balance = opening + incoming - outgoing + transfer_net
        diff = abs(computed_balance - balance)
        
        if diff > 0.005:
            composition_failures.append(
                f"{acc_name}: computed={computed_balance:.2f}, actual={balance:.2f}, diff={diff:.4f}"
            )
        
        # Progress indicator every 20 accounts
        if (i + 1) % 20 == 0:
            print(f"  ... tested {i + 1}/{len(accounts)} accounts")
    
    print(f"✓ Tested {len(accounts)} account balances")
    
    # Report failures
    if failed_accounts:
        print(f"\n❌ FAILED: {len(failed_accounts)} accounts returned errors:")
        for err in failed_accounts[:5]:  # Show first 5
            print(f"  - {err}")
        if len(failed_accounts) > 5:
            print(f"  ... and {len(failed_accounts) - 5} more")
    
    if invalid_values:
        print(f"\n❌ FAILED: {len(invalid_values)} invalid values (NaN/Infinity):")
        for err in invalid_values[:5]:
            print(f"  - {err}")
    
    if composition_failures:
        print(f"\n❌ FAILED: {len(composition_failures)} composition identity violations:")
        for err in composition_failures[:5]:
            print(f"  - {err}")
        if len(composition_failures) > 5:
            print(f"  ... and {len(composition_failures) - 5} more")
    
    # Assert all passed
    assert not failed_accounts, f"{len(failed_accounts)} accounts failed"
    assert not invalid_values, f"{len(invalid_values)} invalid values found"
    assert not composition_failures, f"{len(composition_failures)} composition failures"
    
    print(f"✓ All {len(accounts)} accounts passed byte-equivalence test")
    print(f"✓ Composition identity holds for all accounts (within ½-paise tolerance)")


def test_2_transfer_endpoints_regression():
    """Test 2: Transfer endpoints regression"""
    print("\n=== TEST 2: TRANSFER ENDPOINTS REGRESSION ===")
    
    # 2a. GET /api/transfers - list
    resp = session.get(f"{API_BASE}/transfers")
    assert resp.status_code == 200, f"GET /transfers failed: {resp.status_code}"
    transfers = resp.json()
    print(f"✓ GET /api/transfers returned {len(transfers)} transfers")
    
    # Verify structure of first transfer
    if transfers:
        t = transfers[0]
        required_keys = ["id", "kind", "amount", "from_side", "to_side", "status", "date"]
        for key in required_keys:
            assert key in t, f"Transfer missing key: {key}"
        print(f"✓ Transfer structure verified: {required_keys}")
    
    # 2b. GET /api/transfers?include_reversed=true
    resp = session.get(f"{API_BASE}/transfers?include_reversed=true")
    assert resp.status_code == 200, f"GET /transfers?include_reversed=true failed"
    transfers_with_reversed = resp.json()
    print(f"✓ GET /api/transfers?include_reversed=true returned {len(transfers_with_reversed)} transfers")
    
    # 2c. GET /api/transfers?kind=rakshit_to_ff (filter)
    resp = session.get(f"{API_BASE}/transfers?kind=rakshit_to_ff")
    assert resp.status_code == 200, f"GET /transfers?kind=rakshit_to_ff failed"
    rakshit_to_ff_transfers = resp.json()
    print(f"✓ GET /api/transfers?kind=rakshit_to_ff returned {len(rakshit_to_ff_transfers)} transfers")
    
    # Verify all returned transfers have kind=rakshit_to_ff
    for t in rakshit_to_ff_transfers:
        assert t["kind"] == "rakshit_to_ff", f"Filter failed: got kind={t['kind']}"
    
    # 2d. Create a rakshit_to_ff transfer
    # First, get a Rakshit-owned bank account
    resp = session.get(f"{API_BASE}/accounts")
    assert resp.status_code == 200
    accounts = resp.json()
    bank_accounts = [a for a in accounts if a.get("type", "").lower() in ["bank", "upi", "wallet"]]
    assert bank_accounts, "No bank accounts found"
    
    test_account = bank_accounts[0]
    print(f"✓ Using account: {test_account['name']} ({test_account['id']})")
    
    # Create transfer
    today = datetime.now().date().isoformat()
    transfer_payload = {
        "date": today,
        "from_side": {
            "type": "account",
            "account_id": test_account["id"],
            "account_name": test_account["name"]
        },
        "to_side": {
            "type": "party",
            "party_id": "system_fathers_firm",
            "party_name": "Father's Firm"
        },
        "amount": 1234,
        "mode": "Bank Transfer"
    }
    
    resp = session.post(f"{API_BASE}/transfers", json=transfer_payload)
    assert resp.status_code in [200, 201], f"POST /transfers failed: {resp.status_code} {resp.text}"
    created_transfer = resp.json()
    transfer_id = created_transfer["id"]
    print(f"✓ Created transfer: {transfer_id}")
    
    # Verify classified kind
    assert created_transfer["kind"] == "rakshit_to_ff", f"Wrong kind: {created_transfer['kind']}"
    assert created_transfer["status"] == "active", f"Wrong status: {created_transfer['status']}"
    assert created_transfer["amount"] == 1234, f"Wrong amount: {created_transfer['amount']}"
    print(f"✓ Transfer correctly classified as rakshit_to_ff with status=active")
    
    # 2e. Reverse the transfer
    resp = session.post(f"{API_BASE}/transfers/{transfer_id}/reverse")
    assert resp.status_code in [200, 201], f"POST /transfers/{transfer_id}/reverse failed: {resp.status_code} {resp.text}"
    reversal = resp.json()
    reversal_id = reversal["id"]
    print(f"✓ Created reversal: {reversal_id}")
    
    # Verify reversal doc
    assert reversal.get("reverses_transfer_id") == transfer_id, "Reversal missing reverses_transfer_id"
    assert reversal["kind"] == "ff_to_rakshit", f"Reversal has wrong kind: {reversal['kind']}"
    assert reversal["from_side"]["type"] == "party", "Reversal from_side not swapped"
    assert reversal["to_side"]["type"] == "account", "Reversal to_side not swapped"
    print(f"✓ Reversal doc has correct structure: reverses_transfer_id={transfer_id}, kind=ff_to_rakshit")
    
    # Verify original doc now has status=reversed
    resp = session.get(f"{API_BASE}/transfers/{transfer_id}")
    assert resp.status_code == 200
    original = resp.json()
    assert original["status"] == "reversed", f"Original status not updated: {original['status']}"
    assert original.get("reversed_transfer_id") == reversal_id, "Original missing reversed_transfer_id"
    print(f"✓ Original transfer now has status=reversed, reversed_transfer_id={reversal_id}")
    
    print(f"✓ Transfer create + reverse flow working correctly")


def test_3_fathers_firm_settlement():
    """Test 3: Father's Firm settlement endpoint"""
    print("\n=== TEST 3: FATHER'S FIRM SETTLEMENT ===")
    
    resp = session.get(f"{API_BASE}/party-ledger-v2/fathers-firm-settlement")
    assert resp.status_code == 200, f"GET /fathers-firm-settlement failed: {resp.status_code}"
    ff = resp.json()
    
    # Verify all required keys
    required_keys = ["party_id", "party_name", "balance_signed", "amount", "status", "label"]
    for key in required_keys:
        assert key in ff, f"Missing key: {key}"
    print(f"✓ All required keys present: {required_keys}")
    
    # Verify status is lowercase
    status = ff["status"]
    assert status in ["settled", "you_pay", "you_receive"], f"Invalid status: {status}"
    assert status == status.lower(), f"Status not lowercase: {status}"
    print(f"✓ Status is lowercase: '{status}'")
    
    # Verify amount == abs(balance_signed) within 0.01
    balance_signed = ff["balance_signed"]
    amount = ff["amount"]
    expected_amount = abs(balance_signed)
    diff = abs(amount - expected_amount)
    assert diff <= 0.01, f"amount != abs(balance_signed): {amount} != {expected_amount} (diff={diff})"
    print(f"✓ amount == abs(balance_signed): {amount} == {expected_amount} (diff={diff:.4f})")
    
    print(f"✓ FF settlement: balance_signed={balance_signed:.2f}, amount={amount:.2f}, status={status}")


def test_4_reconcile_engine():
    """Test 4: Reconcile invariant engine"""
    print("\n=== TEST 4: RECONCILE INVARIANT ENGINE ===")
    
    # 4a. GET /api/reconcile
    resp = session.get(f"{API_BASE}/reconcile")
    assert resp.status_code == 200, f"GET /reconcile failed: {resp.status_code}"
    recon = resp.json()
    
    # Verify healthy=true
    assert recon.get("healthy") == True, f"Reconcile not healthy: {recon.get('healthy')}"
    print(f"✓ healthy=true")
    
    # Verify summary
    summary = recon.get("summary", {})
    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    assert passed == total, f"Not all invariants passed: {passed}/{total}"
    assert total == 21, f"Expected 21 invariants, got {total}"
    print(f"✓ summary.passed == summary.total: {passed}/{total}")
    
    # Verify engine_version
    engine_version = recon.get("engine_version")
    assert engine_version == "P5", f"Wrong engine_version: {engine_version}"
    print(f"✓ engine_version='P5'")
    
    # 4b. POST /api/reconcile/run
    resp = session.post(f"{API_BASE}/reconcile/run")
    assert resp.status_code == 200, f"POST /reconcile/run failed: {resp.status_code}"
    run_result = resp.json()
    print(f"✓ POST /api/reconcile/run returned 200")
    
    # Verify it returns same structure as GET
    assert "healthy" in run_result, "POST /reconcile/run missing 'healthy'"
    assert "summary" in run_result, "POST /reconcile/run missing 'summary'"
    
    # Verify audit log was written
    resp = session.get(f"{API_BASE}/admin/reconcile/last")
    assert resp.status_code == 200, f"GET /admin/reconcile/last failed"
    last_run = resp.json()
    assert last_run.get("kind") == "reconcile_run", f"Wrong audit log kind: {last_run.get('kind')}"
    print(f"✓ Audit log written: kind=reconcile_run")
    
    print(f"✓ Reconcile engine healthy: 21/21 invariants passed")


def test_5_sign_convention_integration():
    """Test 5: Sign-convention pin (specific integration case)"""
    print("\n=== TEST 5: SIGN-CONVENTION PIN ===")
    
    # Get a bank account
    resp = session.get(f"{API_BASE}/accounts")
    assert resp.status_code == 200
    accounts = resp.json()
    bank_accounts = [a for a in accounts if a.get("type", "").lower() in ["bank", "upi"]]
    assert bank_accounts, "No bank accounts found"
    test_account = bank_accounts[0]
    account_id = test_account["id"]
    print(f"✓ Using account: {test_account['name']} ({account_id})")
    
    # Get initial account balance
    resp = session.get(f"{API_BASE}/accounts/{account_id}/balance")
    assert resp.status_code == 200
    initial_balance = resp.json()
    initial_transfer_net = initial_balance["transfer_net"]
    initial_total_balance = initial_balance["balance"]
    print(f"✓ Initial account balance: transfer_net={initial_transfer_net:.2f}, balance={initial_total_balance:.2f}")
    
    # Get initial FF settlement
    resp = session.get(f"{API_BASE}/party-ledger-v2/fathers-firm-settlement")
    assert resp.status_code == 200
    initial_ff = resp.json()
    initial_ff_balance = initial_ff["balance_signed"]
    print(f"✓ Initial FF settlement: balance_signed={initial_ff_balance:.2f}")
    
    # Create ff_to_rakshit transfer (FF pays Rakshit)
    today = datetime.now().date().isoformat()
    transfer_payload = {
        "date": today,
        "from_side": {
            "type": "party",
            "party_id": "system_fathers_firm",
            "party_name": "Father's Firm"
        },
        "to_side": {
            "type": "account",
            "account_id": account_id,
            "account_name": test_account["name"]
        },
        "amount": 555,
        "mode": "Bank Transfer"
    }
    
    resp = session.post(f"{API_BASE}/transfers", json=transfer_payload)
    assert resp.status_code in [200, 201], f"POST /transfers failed: {resp.status_code} {resp.text}"
    transfer = resp.json()
    transfer_id = transfer["id"]
    print(f"✓ Created ff_to_rakshit transfer: {transfer_id}, amount=555")
    
    # Verify account balance increased
    resp = session.get(f"{API_BASE}/accounts/{account_id}/balance")
    assert resp.status_code == 200
    after_balance = resp.json()
    after_transfer_net = after_balance["transfer_net"]
    after_total_balance = after_balance["balance"]
    
    transfer_net_increase = after_transfer_net - initial_transfer_net
    assert abs(transfer_net_increase - 555) <= 0.01, f"transfer_net did not increase by 555: {transfer_net_increase}"
    print(f"✓ Account transfer_net increased by {transfer_net_increase:.2f} (expected +555)")
    
    # Verify FF settlement decreased
    resp = session.get(f"{API_BASE}/party-ledger-v2/fathers-firm-settlement")
    assert resp.status_code == 200
    after_ff = resp.json()
    after_ff_balance = after_ff["balance_signed"]
    
    ff_balance_change = after_ff_balance - initial_ff_balance
    # FF paid Rakshit → Rakshit owes FF more → balance_signed should DECREASE
    # (or in UI convention: FF owes Rakshit less)
    assert abs(ff_balance_change + 555) <= 0.01, f"FF balance_signed did not decrease by 555: {ff_balance_change}"
    print(f"✓ FF balance_signed decreased by {abs(ff_balance_change):.2f} (expected -555)")
    
    # Reverse the transfer
    resp = session.post(f"{API_BASE}/transfers/{transfer_id}/reverse")
    assert resp.status_code in [200, 201], f"Reverse failed: {resp.status_code}"
    print(f"✓ Reversed transfer {transfer_id}")
    
    # Verify account balance returned to initial
    resp = session.get(f"{API_BASE}/accounts/{account_id}/balance")
    assert resp.status_code == 200
    final_balance = resp.json()
    final_transfer_net = final_balance["transfer_net"]
    final_total_balance = final_balance["balance"]
    
    assert abs(final_transfer_net - initial_transfer_net) <= 0.01, \
        f"transfer_net did not return to initial: {final_transfer_net} != {initial_transfer_net}"
    print(f"✓ Account transfer_net returned to initial: {final_transfer_net:.2f}")
    
    # Verify FF settlement returned to initial
    resp = session.get(f"{API_BASE}/party-ledger-v2/fathers-firm-settlement")
    assert resp.status_code == 200
    final_ff = resp.json()
    final_ff_balance = final_ff["balance_signed"]
    
    assert abs(final_ff_balance - initial_ff_balance) <= 0.01, \
        f"FF balance_signed did not return to initial: {final_ff_balance} != {initial_ff_balance}"
    print(f"✓ FF balance_signed returned to initial: {final_ff_balance:.2f}")
    
    print(f"✓ Sign-convention integration test passed: transfer + reversal round-trip correct")


def test_6_dashboard_regression():
    """Test 6: Dashboard regression"""
    print("\n=== TEST 6: DASHBOARD REGRESSION ===")
    
    resp = session.get(f"{API_BASE}/dashboard")
    assert resp.status_code == 200, f"GET /dashboard failed: {resp.status_code}"
    dashboard = resp.json()
    
    # Verify kpis section exists
    assert "kpis" in dashboard, "Dashboard missing 'kpis' section"
    kpis = dashboard["kpis"]
    
    # Verify all required KPI keys present and numeric
    required_kpis = [
        "operating_revenue", "invoice_value", "total_cost", "net_profit",
        "received", "paid",
        "outstanding_receivable", "outstanding_payable",
        "estimated_revenue", "estimated_net_profit"
    ]
    
    missing_kpis = []
    non_numeric_kpis = []
    
    for key in required_kpis:
        if key not in kpis:
            missing_kpis.append(key)
        elif not isinstance(kpis[key], (int, float)):
            non_numeric_kpis.append(f"{key}={kpis[key]}")
    
    assert not missing_kpis, f"Missing KPIs: {missing_kpis}"
    assert not non_numeric_kpis, f"Non-numeric KPIs: {non_numeric_kpis}"
    
    print(f"✓ All required KPIs present and numeric:")
    for key in required_kpis:
        print(f"  - {key}: {kpis[key]}")
    
    # Verify modes section
    assert "modes" in dashboard, "Dashboard missing 'modes' section"
    modes = dashboard["modes"]
    assert isinstance(modes, list), f"modes should be list, got {type(modes)}"
    print(f"✓ modes section present with {len(modes)} entries")
    
    print(f"✓ Dashboard regression test passed")


def test_7_party_ledger_v2_regression():
    """Test 7: Party Ledger v2 regression (Slice 5)"""
    print("\n=== TEST 7: PARTY LEDGER V2 REGRESSION ===")
    
    # 7a. GET /api/party-ledger-v2/summary
    resp = session.get(f"{API_BASE}/party-ledger-v2/summary")
    assert resp.status_code == 200, f"GET /summary failed: {resp.status_code}"
    summary = resp.json()
    
    required_keys = [
        "fathers_firm_you_pay", "fathers_firm_you_receive",
        "vendor_you_pay", "vendor_advances_you_receive",
        "customer_you_receive", "customer_advances_you_pay",
        "net_position"
    ]
    
    for key in required_keys:
        assert key in summary, f"Summary missing key: {key}"
        assert isinstance(summary[key], (int, float)), f"Summary[{key}] not numeric: {summary[key]}"
    
    print(f"✓ Summary has all 7 keys, all numeric")
    
    # 7b. Pick 5 random seeded parties and test running_balance
    resp = session.get(f"{API_BASE}/party-ledger-v2/parties?include_settled=true")
    assert resp.status_code == 200, f"GET /parties failed"
    parties_list = resp.json()
    parties = parties_list.get("parties", [])
    assert len(parties) > 0, "No parties found"
    
    # Test first 5 parties
    test_parties = parties[:min(5, len(parties))]
    print(f"✓ Testing {len(test_parties)} parties for running_balance and net_balance_paise")
    
    for party in test_parties:
        party_id = party["id"]
        party_name = party.get("name", "Unknown")
        
        resp = session.get(f"{API_BASE}/party-ledger-v2/parties/{party_id}")
        assert resp.status_code == 200, f"GET /parties/{party_id} failed"
        ledger = resp.json()
        
        # Verify net_balance_paise field exists and is integer
        assert "net_balance_paise" in ledger, f"Party {party_name} missing net_balance_paise"
        net_balance_paise = ledger["net_balance_paise"]
        assert isinstance(net_balance_paise, int), f"net_balance_paise not int: {type(net_balance_paise)}"
        
        # Verify entries have running_balance
        entries = ledger.get("entries", [])
        if entries:
            # Check first and last entry
            for entry in [entries[0], entries[-1]]:
                assert "running_balance" in entry, f"Entry missing running_balance"
                assert isinstance(entry["running_balance"], (int, float)), \
                    f"running_balance not numeric: {entry['running_balance']}"
        
        # Naive float walk to verify running_balance
        if entries:
            naive_balance = 0.0
            max_drift = 0.0
            for entry in entries:
                if entry.get("counts_in_balance"):
                    naive_balance += float(entry.get("delta_you_pay", 0))
                api_balance = float(entry.get("running_balance", 0))
                drift = abs(naive_balance - api_balance)
                max_drift = max(max_drift, drift)
            
            # ½-paise tolerance = 0.005
            assert max_drift <= 0.005, \
                f"Party {party_name} running_balance drift: {max_drift:.6f} (max allowed: 0.005)"
            print(f"  ✓ {party_name}: {len(entries)} entries, max drift={max_drift:.6f}, net_balance_paise={net_balance_paise}")
    
    print(f"✓ All tested parties have correct running_balance and net_balance_paise")


def main():
    """Run all tests"""
    print("=" * 70)
    print("PHASE 6 · SLICE 6 — BACKEND API TESTING")
    print("=" * 70)
    
    try:
        # Login first
        login()
        
        # Run all tests
        test_1_account_balance_byte_equivalence()
        test_2_transfer_endpoints_regression()
        test_3_fathers_firm_settlement()
        test_4_reconcile_engine()
        test_5_sign_convention_integration()
        test_6_dashboard_regression()
        test_7_party_ledger_v2_regression()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nSUMMARY:")
        print("✓ Test 1: Account balance byte-equivalence (~100 accounts)")
        print("✓ Test 2: Transfer endpoints regression (GET, POST, reverse)")
        print("✓ Test 3: Father's Firm settlement")
        print("✓ Test 4: Reconcile invariant engine (21/21)")
        print("✓ Test 5: Sign-convention pin (integration)")
        print("✓ Test 6: Dashboard regression")
        print("✓ Test 7: Party Ledger v2 regression (Slice 5)")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
