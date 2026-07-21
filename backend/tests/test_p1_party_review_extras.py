"""Supplementary Phase 2 (P1) review checks:

    * POST /api/parties/system_fathers_firm/rename => HTTP 400 (protected).
    * GET  /api/party-ledger-v2/parties/system_fathers_firm returns the FF
      party doc (system party is present in the ledger).
    * POST /api/vendors with a fresh vendor name creates a vendor doc that
      carries a party_id linked to a canonical parties row.
    * PUT  /api/vendors/{id} with a new name preserves the same party_id AND
      pushes the old normalized name onto parties[party_id].aliases.
    * POST /api/party-migration/run twice yields identical parties_created
      (idempotent) and last-report exposes all documented keys.
"""
from __future__ import annotations

import uuid

import requests

API = "http://localhost:8001/api"
TIMEOUT = 15


def _post(path, payload):
    return requests.post(f"{API}{path}", json=payload, timeout=TIMEOUT)


def _get(path, params=None):
    return requests.get(f"{API}{path}", params=params, timeout=TIMEOUT)


# ---------- protected system Father's Firm party ----------

class TestSystemFathersFirm:
    def test_ff_party_visible_in_ledger(self):
        r = _get("/party-ledger-v2/parties/system_fathers_firm")
        assert r.status_code == 200, r.text
        body = r.json()
        p = body.get("party") or body
        assert p.get("id") == "system_fathers_firm", p

    def test_rename_system_party_forbidden(self):
        r = _post("/parties/system_fathers_firm/rename",
                  {"display_name": "Should Not Work"})
        assert r.status_code == 400, r.text


# ---------- canonical /vendors write path ----------

class TestVendorPartyStamping:
    def test_new_vendor_gets_party_id(self):
        name = f"P1-Ven-{uuid.uuid4().hex[:8]}"
        r = _post("/vendors", {"name": name})
        assert r.status_code == 200, r.text
        vend = r.json()
        assert vend.get("party_id"), "party_id must be stamped on vendor create"
        # party doc should exist
        pr = _get(f"/party-ledger-v2/parties/{vend['party_id']}")
        assert pr.status_code == 200, pr.text
        p = pr.json().get("party") or pr.json()
        assert p.get("id") == vend["party_id"]

    def test_vendor_rename_preserves_party_and_aliases(self):
        seed = f"P1-VenRen-{uuid.uuid4().hex[:8]}"
        r = _post("/vendors", {"name": seed})
        assert r.status_code == 200, r.text
        vend = r.json()
        vid = vend["id"]
        pid = vend["party_id"]

        new_name = f"{seed} Renamed"
        r2 = requests.put(f"{API}/vendors/{vid}",
                          json={**vend, "name": new_name}, timeout=TIMEOUT)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("party_id") == pid, (r2.json(), pid)

        pr = _get(f"/party-ledger-v2/parties/{pid}")
        assert pr.status_code == 200, pr.text
        p = pr.json().get("party") or pr.json()
        assert p["display_name"] == new_name
        old_norm = seed.strip().casefold()
        aliases = [a.strip().casefold() for a in (p.get("aliases") or [])]
        assert old_norm in aliases, (old_norm, aliases)


# ---------- migration idempotency + report shape ----------

class TestMigrationReport:
    def test_run_twice_is_idempotent(self):
        # warm up first (in case earlier tests appended new parties)
        r0 = _post("/party-migration/run", {})
        assert r0.status_code == 200, r0.text
        r1 = _post("/party-migration/run", {})
        assert r1.status_code == 200, r1.text
        first = r1.json()["parties_created"]
        r2 = _post("/party-migration/run", {})
        assert r2.status_code == 200, r2.text
        second = r2.json()["parties_created"]
        assert first == second, (first, second)

    def test_last_report_has_all_documented_keys(self):
        r = _get("/party-migration/last-report")
        assert r.status_code == 200, r.text
        rep = r.json()
        expected = {
            "parties_created", "vendors_linked", "customers_linked",
            "ff_aliases_resolved", "exact_duplicates_merged",
            "probable_duplicates_flagged", "unmatched_legacy_names",
            "conflicts",
        }
        missing = expected - set(rep.keys())
        assert not missing, f"missing keys in last-report: {missing}"
