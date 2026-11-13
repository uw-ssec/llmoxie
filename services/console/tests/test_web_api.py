"""The browser API (/web-api/) that the console's own pages call: its plumbing, not the flows.

The flows from first sign-in to archiving are in test_console.py. These tests pin what every call
shares: the session report, the one error shape, the CSRF header and what a response may carry.
"""

import json
import uuid

from .helpers import CONSOLE, Browser, sign_in

RUN = uuid.uuid4().hex[:6]


def test_session_reports_signed_out_without_a_cookie():
    r = Browser().api_get("/session")
    assert r.status_code == 200 and r.json() == {"signed_in": False}
    assert r.headers["cache-control"] == "no-store"


def test_page_data_needs_a_session_and_says_so_as_json():
    r = Browser().api_get("/admin/orgs")
    assert r.status_code == 401 and r.json() == {"error": {"status": 401, "message": "You are signed out."}}
    assert r.headers["cache-control"] == "no-store"


def test_admin_session_carries_no_identifiers():
    alice = sign_in("alice", "alice123")
    body = alice.api_get("/session").json()
    assert body["signed_in"] and body["me"]["is_admin"] and len(body["csrf"]) >= 24
    assert set(body) == {"signed_in", "csrf", "me", "config"}
    assert body["config"]["gateway_url"].startswith("http")
    assert "participant_id" not in json.dumps(body) and "team_orgs" not in json.dumps(body)


def test_admin_reads_the_organization_list_as_json():
    alice = sign_in("alice", "alice123")
    r = alice.api_get("/admin/orgs")
    assert r.status_code == 200 and set(r.json()) == {"orgs"}
    for org in r.json()["orgs"]:
        assert set(org) == {"id", "name", "slug", "budget_ceiling", "leads", "teams", "status"}


def test_an_org_that_is_not_there_is_refused_without_saying_so():
    alice = sign_in("alice", "alice123")
    r = alice.api_get(f"/orgs/{uuid.uuid4()}")  # the broker answers as for an org one may not see
    assert r.status_code == 403 and r.json() == {"error": {"status": 403, "message": "You do not have access to that."}}


def test_an_address_that_holds_no_id_is_a_json_404():
    alice = sign_in("alice", "alice123")
    r = alice.api_get("/orgs/not-an-id")
    assert r.status_code == 404 and r.json() == {"error": {"status": 404, "message": "That does not exist."}}


def test_a_page_outside_ones_role_is_a_json_403():
    alice = sign_in("alice", "alice123")  # an SSEC admin leads no organization, so no knowledge base is hers to read
    orgs = alice.api_get("/admin/orgs").json()["orgs"]
    if orgs:
        r = alice.api_get(f"/orgs/{orgs[0]['id']}/knowledge")
        assert r.status_code == 403 and r.json()["error"] == {"status": 403, "message": "You do not have access to that."}


def test_invitation_lookup_needs_no_session():
    r = Browser().api_get("/invites/" + "x" * 30)
    assert r.status_code == 200 and r.json() == {"valid": False}
    assert Browser().api_get("/invites/short").json() == {"valid": False}
