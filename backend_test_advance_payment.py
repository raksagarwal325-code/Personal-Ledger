#!/usr/bin/env python3
"""
Backend API test for Advance-payment customer reuse bug fix.

Verifies:
1. New customer via advance payment becomes reusable
2. Normalized-name reuse (no duplicate parties)
3. Regressions (reconcile health)
"""

import requests
import uuid
import sys
from typing import Dict, Any, List

# Backend URL from frontend/.env
BASE_URL = "https://1781388d-eca6-4416-aced-add139d9246b.preview.emergentagent.com/api"

# Test credentials
ADMIN_EMAIL = "admin@artisan.local"
ADMIN_PASSWORD = "Admin@12345"

class TestRunner:
    def __init__(self):
        self.token = None
        self.created_payment_ids = []
        self.test_results = []
        
    def login(self) -> bool:
        """Login and get access token"""
        print("\n=== LOGIN ===")
        try:
            response = requests.post(
                f"{BASE_URL}/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("access_token")
            if not self.token:
                print("❌ FAIL: No access_token in response")
                return False
            print(f"✅ PASS: Logged in successfully")
            return True
        except Exception as e:
            print(f"❌ FAIL: Login failed - {e}")
            return False
    
    def headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        return {"Authorization": f"Bearer {self.token}"}
    
    def cleanup_payment(self, payment_id: str):
        """Delete a payment"""
        try:
            response = requests.delete(
                f"{BASE_URL}/customer-payments/{payment_id}",
                headers=self.headers()
            )
            if response.status_code in [200, 204]:
                print(f"  🧹 Cleaned up payment {payment_id}")
        except Exception as e:
            print(f"  ⚠️  Cleanup failed for {payment_id}: {e}")
    
    def scenario_1_new_customer_reusable(self) -> bool:
        """
        Scenario 1: New customer via advance payment becomes reusable
        
        Steps:
        (a) GET /api/meta → confirm unique name NOT in clients
        (b) POST /api/customer-payments with new customer name
        (c) Response must include non-empty customer_party_id
        (d) Fresh GET /api/meta → clients MUST include the name
        (e) GET /api/party-ledger-v2/parties?type=customer → must contain the party
        """
        print("\n=== SCENARIO 1: New customer via advance payment becomes reusable ===")
        
        # Generate unique test name
        base_name = f"AdvReuse T1 {uuid.uuid4().hex[:8]}"
        print(f"Test customer name: {base_name}")
        
        try:
            # Step (a): Confirm name NOT in clients yet
            print("\n(a) GET /api/meta - checking clients list...")
            response = requests.get(f"{BASE_URL}/meta", headers=self.headers())
            response.raise_for_status()
            meta_data = response.json()
            clients_before = meta_data.get("clients", [])
            
            if base_name in clients_before:
                print(f"❌ FAIL: Test name '{base_name}' already exists in clients (collision)")
                return False
            print(f"✅ PASS: Test name NOT in clients (count: {len(clients_before)})")
            
            # Step (b): POST customer payment
            print(f"\n(b) POST /api/customer-payments with customer_name='{base_name}'...")
            payment_data = {
                "date": "2026-07-22",
                "customer_name": base_name,
                "amount": 7500,
                "mode": "UPI",
                "allocations": []
            }
            response = requests.post(
                f"{BASE_URL}/customer-payments",
                json=payment_data,
                headers=self.headers()
            )
            response.raise_for_status()
            payment_response = response.json()
            
            # Step (c): Check customer_party_id
            print("\n(c) Checking customer_party_id in response...")
            customer_party_id = payment_response.get("customer_party_id")
            payment_id = payment_response.get("id")
            
            if payment_id:
                self.created_payment_ids.append(payment_id)
            
            if not customer_party_id:
                print(f"❌ FAIL: customer_party_id is empty or missing")
                print(f"   Response: {payment_response}")
                return False
            
            # Validate UUID format
            try:
                uuid.UUID(customer_party_id)
                print(f"✅ PASS: customer_party_id = {customer_party_id} (valid UUID)")
            except ValueError:
                print(f"❌ FAIL: customer_party_id '{customer_party_id}' is not a valid UUID")
                return False
            
            # Step (d): Fresh GET /api/meta → clients must include the name
            print(f"\n(d) Fresh GET /api/meta - checking if '{base_name}' now in clients...")
            response = requests.get(f"{BASE_URL}/meta", headers=self.headers())
            response.raise_for_status()
            meta_data_after = response.json()
            clients_after = meta_data_after.get("clients", [])
            
            # Check for exact match or normalized match
            found_in_clients = False
            matched_name = None
            for client in clients_after:
                if client.strip().lower() == base_name.strip().lower():
                    found_in_clients = True
                    matched_name = client
                    break
            
            if not found_in_clients:
                print(f"❌ FAIL: Test name NOT found in clients after payment creation")
                print(f"   Clients count: {len(clients_after)}")
                print(f"   Looking for: '{base_name}'")
                # Show some clients for debugging
                print(f"   Sample clients: {clients_after[:10]}")
                return False
            
            print(f"✅ PASS: Test name found in clients as '{matched_name}'")
            
            # Step (e): GET parties endpoint
            print(f"\n(e) GET /api/party-ledger-v2/parties?type=customer...")
            response = requests.get(
                f"{BASE_URL}/party-ledger-v2/parties",
                params={"type": "customer"},
                headers=self.headers()
            )
            response.raise_for_status()
            parties_data = response.json()
            
            # Handle both array and object response formats
            if isinstance(parties_data, dict):
                parties = parties_data.get("parties", [])
            else:
                parties = parties_data
            
            # Find the party with matching ID
            party_found = False
            for party in parties:
                if party.get("id") == customer_party_id:
                    party_found = True
                    party_name = party.get("display_name") or party.get("name")
                    print(f"✅ PASS: Party found with id={customer_party_id}, name='{party_name}'")
                    break
            
            if not party_found:
                print(f"❌ FAIL: Party with id={customer_party_id} NOT found in parties endpoint")
                print(f"   Total parties: {len(parties)}")
                return False
            
            print("\n✅ SCENARIO 1: ALL CHECKS PASSED")
            return True
            
        except Exception as e:
            print(f"❌ FAIL: Exception in scenario 1 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def scenario_2_normalized_name_reuse(self) -> bool:
        """
        Scenario 2: Normalized-name reuse (no duplicate parties)
        
        Steps:
        (a) POST four advance payments with SAME normalized name (different case/whitespace)
        (b) Every customer_party_id MUST be the same single UUID
        (c) GET parties → exactly ONE party with matching name
        (d) Payment allocation semantics untouched
        """
        print("\n=== SCENARIO 2: Normalized-name reuse (no duplicate parties) ===")
        
        # Generate unique base name
        base_name = f"AdvReuse T2 {uuid.uuid4().hex[:8]}"
        variants = [
            base_name,
            base_name.upper(),
            f"  {base_name.lower()}  ",
            f"{base_name}\t\t"
        ]
        
        print(f"Base name: '{base_name}'")
        print(f"Variants: {[repr(v) for v in variants]}")
        
        try:
            party_ids = []
            payment_ids = []
            
            # Step (a): POST four payments
            print("\n(a) Creating four payments with name variants...")
            for i, variant in enumerate(variants):
                print(f"\n  Payment {i+1}/4: customer_name='{variant}' (repr: {repr(variant)})")
                payment_data = {
                    "date": "2026-07-22",
                    "customer_name": variant,
                    "amount": 1000 + i,
                    "mode": "UPI",
                    "allocations": []
                }
                
                response = requests.post(
                    f"{BASE_URL}/customer-payments",
                    json=payment_data,
                    headers=self.headers()
                )
                response.raise_for_status()
                payment_response = response.json()
                
                customer_party_id = payment_response.get("customer_party_id")
                payment_id = payment_response.get("id")
                amount = payment_response.get("amount")
                unallocated = payment_response.get("unallocated")
                allocations = payment_response.get("allocations", [])
                
                if payment_id:
                    payment_ids.append(payment_id)
                    self.created_payment_ids.append(payment_id)
                
                if not customer_party_id:
                    print(f"    ❌ FAIL: customer_party_id missing in response")
                    return False
                
                party_ids.append(customer_party_id)
                print(f"    ✅ customer_party_id: {customer_party_id}")
                print(f"       amount: {amount}, unallocated: {unallocated}, allocations: {allocations}")
            
            # Step (b): All party IDs must be the same
            print(f"\n(b) Checking if all customer_party_id values are identical...")
            unique_party_ids = set(party_ids)
            
            if len(unique_party_ids) != 1:
                print(f"❌ FAIL: Expected 1 unique party_id, got {len(unique_party_ids)}")
                print(f"   Party IDs: {party_ids}")
                return False
            
            canonical_party_id = party_ids[0]
            print(f"✅ PASS: All four payments share the same customer_party_id: {canonical_party_id}")
            
            # Step (c): GET parties → exactly ONE party
            print(f"\n(c) GET /api/party-ledger-v2/parties?type=customer...")
            response = requests.get(
                f"{BASE_URL}/party-ledger-v2/parties",
                params={"type": "customer"},
                headers=self.headers()
            )
            response.raise_for_status()
            parties_data = response.json()
            
            # Handle both array and object response formats
            if isinstance(parties_data, dict):
                parties = parties_data.get("parties", [])
            else:
                parties = parties_data
            
            # Filter parties matching base_name (case-insensitive)
            matching_parties = []
            for party in parties:
                party_name = party.get("display_name") or party.get("name") or ""
                if party_name.strip().lower() == base_name.strip().lower():
                    matching_parties.append(party)
            
            if len(matching_parties) != 1:
                print(f"❌ FAIL: Expected exactly 1 party matching '{base_name}', found {len(matching_parties)}")
                if matching_parties:
                    print(f"   Matching parties: {[p.get('id') for p in matching_parties]}")
                return False
            
            party = matching_parties[0]
            party_id = party.get("id")
            party_name = party.get("display_name") or party.get("name")
            
            if party_id != canonical_party_id:
                print(f"❌ FAIL: Party id mismatch")
                print(f"   Expected: {canonical_party_id}")
                print(f"   Found: {party_id}")
                return False
            
            print(f"✅ PASS: Exactly ONE party found: id={party_id}, name='{party_name}'")
            
            # Step (d): Payment allocation semantics untouched
            print(f"\n(d) Verifying payment allocation semantics...")
            all_allocations_empty = True
            for i, pid in enumerate(payment_ids):
                response = requests.get(
                    f"{BASE_URL}/customer-payments/{pid}",
                    headers=self.headers()
                )
                response.raise_for_status()
                payment = response.json()
                
                allocations = payment.get("allocations", [])
                amount = payment.get("amount")
                unallocated = payment.get("unallocated")
                
                if allocations:
                    all_allocations_empty = False
                    print(f"    Payment {i+1}: allocations NOT empty: {allocations}")
                
                expected_amount = 1000 + i
                if amount != expected_amount:
                    print(f"    ❌ FAIL: Payment {i+1} amount mismatch (expected {expected_amount}, got {amount})")
                    return False
            
            if all_allocations_empty:
                print(f"✅ PASS: All four payments have allocations=[] (allocation semantics preserved)")
            else:
                print(f"⚠️  WARNING: Some payments have non-empty allocations")
            
            print("\n✅ SCENARIO 2: ALL CHECKS PASSED")
            return True
            
        except Exception as e:
            print(f"❌ FAIL: Exception in scenario 2 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def scenario_3_regressions(self) -> bool:
        """
        Scenario 3: Regressions
        
        (a) GET /api/reconcile → healthy=true, passed=21, failed=0
        (b) Run pytest on bug fix + related test files
        """
        print("\n=== SCENARIO 3: Regressions ===")
        
        try:
            # Step (a): Check reconcile health
            print("\n(a) GET /api/reconcile...")
            response = requests.get(f"{BASE_URL}/reconcile", headers=self.headers())
            response.raise_for_status()
            reconcile_data = response.json()
            
            healthy = reconcile_data.get("healthy")
            passed = reconcile_data.get("summary", {}).get("passed", 0)
            failed = reconcile_data.get("summary", {}).get("failed", 0)
            
            print(f"   healthy: {healthy}")
            print(f"   passed: {passed}")
            print(f"   failed: {failed}")
            
            if not healthy:
                print(f"❌ FAIL: Reconcile is NOT healthy")
                # Show failed checks
                checks = reconcile_data.get("checks", [])
                for check in checks:
                    if not check.get("passed"):
                        print(f"   Failed check: {check.get('name')}")
                        print(f"   Issue: {check.get('issue')}")
                return False
            
            if passed != 21:
                print(f"❌ FAIL: Expected 21 passed checks, got {passed}")
                return False
            
            if failed != 0:
                print(f"❌ FAIL: Expected 0 failed checks, got {failed}")
                return False
            
            print(f"✅ PASS: Reconcile is healthy (21/21 passed)")
            
            print("\n✅ SCENARIO 3: RECONCILE CHECK PASSED")
            return True
            
        except Exception as e:
            print(f"❌ FAIL: Exception in scenario 3 - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_pytest(self) -> bool:
        """Run pytest on the bug fix test files"""
        print("\n=== PYTEST: Running bug fix + related test files ===")
        
        import subprocess
        
        try:
            result = subprocess.run(
                [
                    "python", "-m", "pytest",
                    "tests/test_bug_advance_payment_customer_reuse.py",
                    "tests/test_p6_slice5_party_ledger.py",
                    "tests/test_p5_reconcile.py",
                    "-v"
                ],
                cwd="/app/backend",
                capture_output=True,
                text=True,
                timeout=60
            )
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            if result.returncode == 0:
                print("\n✅ PASS: All pytest tests passed")
                return True
            else:
                print(f"\n❌ FAIL: pytest exited with code {result.returncode}")
                return False
                
        except Exception as e:
            print(f"❌ FAIL: Exception running pytest - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def cleanup(self):
        """Clean up all created test data"""
        print("\n=== CLEANUP ===")
        for payment_id in self.created_payment_ids:
            self.cleanup_payment(payment_id)
        print("✅ Cleanup complete")
    
    def run_all(self):
        """Run all test scenarios"""
        print("=" * 80)
        print("BACKEND API TEST: Advance-payment customer reuse bug fix")
        print("=" * 80)
        
        # Login
        if not self.login():
            print("\n❌ OVERALL RESULT: FAILED (login failed)")
            return False
        
        # Run scenarios
        results = []
        
        scenario_1_pass = self.scenario_1_new_customer_reusable()
        results.append(("Scenario 1: New customer reusable", scenario_1_pass))
        
        scenario_2_pass = self.scenario_2_normalized_name_reuse()
        results.append(("Scenario 2: Normalized-name reuse", scenario_2_pass))
        
        scenario_3_pass = self.scenario_3_regressions()
        results.append(("Scenario 3: Regressions (reconcile)", scenario_3_pass))
        
        pytest_pass = self.run_pytest()
        results.append(("Pytest: Bug fix + related tests", pytest_pass))
        
        # Cleanup
        self.cleanup()
        
        # Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        
        for name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status}: {name}")
        
        all_passed = all(passed for _, passed in results)
        
        print("\n" + "=" * 80)
        if all_passed:
            print("✅ OVERALL RESULT: ALL TESTS PASSED")
        else:
            print("❌ OVERALL RESULT: SOME TESTS FAILED")
        print("=" * 80)
        
        return all_passed


if __name__ == "__main__":
    runner = TestRunner()
    success = runner.run_all()
    sys.exit(0 if success else 1)
