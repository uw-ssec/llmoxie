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


# ── Actions ─────────────────────────────────────────────────────────────────

def test_posts_without_the_csrf_header_are_refused():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": "N", "slug": "n-x", "budget_ceiling": 1}, csrf=None)
    assert r.status_code == 403 and "expired" in r.json()["error"]["message"]
    r = alice.api_post("/admin/orgs", {"name": "N", "slug": "n-x", "budget_ceiling": 1}, csrf="not-the-token")
    assert r.status_code == 403 and r.json()["error"]["status"] == 403


def test_cross_site_posts_are_refused_before_anything_else():
    alice = sign_in("alice", "alice123")
    r = alice.request("POST", CONSOLE + "/web-api/admin/orgs", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_posts_need_a_session():
    r = Browser().api_post("/admin/orgs", {"name": "N", "slug": "n-x", "budget_ceiling": 1})
    assert r.status_code == 401 and r.json()["error"]["message"] == "You are signed out."


def test_a_bad_value_comes_back_as_a_message_not_a_stack_trace():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": "N", "slug": "Not A Slug", "budget_ceiling": 1})
    assert r.status_code == 422 and isinstance(r.json()["error"]["message"], str)
    r = alice.api_post("/admin/orgs", {"name": "N"})  # fields missing altogether
    assert r.status_code == 422 and r.json() == {"error": {"status": 422, "message": "Some of those values are not valid."}}


def test_creating_an_org_answers_with_a_message_and_where_to_go():
    alice = sign_in("alice", "alice123")
    r = alice.api_post("/admin/orgs", {"name": f"Web API {RUN}", "slug": f"wa-{RUN}", "budget_ceiling": 5})
    body = r.json()
    assert r.status_code == 200 and body["message"] == f"Created Web API {RUN}."
    assert body["goto"].startswith("/orgs/") and set(body) == {"message", "goto"}
    org_id = body["goto"].removeprefix("/orgs/")
    assert alice.api_get(f"/orgs/{org_id}").json()["org"]["slug"] == f"wa-{RUN}"
    taken = alice.api_post("/admin/orgs", {"name": "Again", "slug": f"wa-{RUN}", "budget_ceiling": 5})
    assert taken.status_code == 409 and isinstance(taken.json()["error"]["message"], str)
    removed = alice.api_post(f"/admin/orgs/{org_id}/remove", {"confirm_slug": f"wa-{RUN}"})
    assert removed.status_code == 200 and removed.json()["goto"] == "/admin"
    assert removed.json()["message"].startswith("Organization removed:")
