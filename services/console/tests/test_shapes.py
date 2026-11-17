"""What console-web lets the browser have. Pure functions, so these run without a stack.

Each test feeds a broker-style reply that holds more than the page shows and checks the exact
fields that come out: a field the broker adds later must not reach the browser by default.
"""

import json

from console_app.web import shapes

ME = {
    "person_id": "p-1", "participant_id": "part-1", "email": "a@uw.edu", "is_admin": True,
    "lead_orgs": [{"id": "o-1", "name": "Astro", "slug": "astro", "status": "active"}],
    "teams": [{"id": "t-1", "name": "Team", "status": "active", "org_id": "o-1", "org_name": "Astro"}],
    "team_orgs": {"t-1": "o-1"},
}

ORG_ROW = {"id": "o-1", "name": "Astro", "slug": "astro", "status": "active", "budget_ceiling": "50.00",
           "mcp_server_id": "mcp-1", "keycloak_client_id": "okf-org-astro", "created_at": "2026-11-01T00:00:00Z"}

ORG_VIEW = {
    "org": ORG_ROW,
    "providers": ["openai", "azure", "mock"],
    "leads": [{"id": "p-2", "email": "lead@uw.edu"}],
    "lead_invites": [{"id": "i-1", "email": "new@uw.edu", "status": "pending", "signin_email": None,
                      "expires_at": "2026-11-20T00:00:00Z"}],
    "models": [{"id": "m-1", "provider": "mock", "model": "gpt", "public_name": "astro/gpt",
                "created_at": "2026-11-01T00:00:00Z"}],
    "teams": [{"id": "t-1", "name": "Team", "status": "active", "team_budget": "5.00", "members": 2}],
}

TEAM_ROW = {"id": "t-1", "name": "Team", "status": "active", "org_id": "o-1", "org_name": "Astro", "org_slug": "astro",
            "org_status": "active", "org_budget_ceiling": "50.00", "team_budget": "5.00", "key_limit": 3,
            "key_budget": "1.00", "key_expiry_days": 30, "consent_text": "Leads see totals.", "litellm_team_id": "lt-1"}

TEAM_VIEW = {
    "team": TEAM_ROW,
    "keys": [{"id": "k-1", "name": "laptop", "email": "p@uw.edu", "created_at": "2026-11-02T00:00:00Z", "waiting": False,
              "hint": "sk-...abcd", "spend": 0.01, "expires": None, "last_used": None, "key_alias": "alias-1"}],
    "models": [{"id": "m-1", "public_name": "astro/gpt", "provider": "mock", "allowed": True}],
    "members": [{"id": "p-3", "email": "p@uw.edu", "participant_id": "part-3", "keys": 1, "terms_accepted": True}],
    "invites": [{"id": "i-2", "email": "q@uw.edu", "status": "needs_approval", "signin_email": "other@x.org",
                 "expires_at": "2026-11-20T00:00:00Z"}],
    "integrations": [{"id": "g-1", "name": "Hub", "client_id": "jupyterhub", "can_enroll": True,
                      "created_at": "2026-11-02T00:00:00Z"}],
}

USAGE = [{"email": "p@uw.edu", "participant_id": "part-3", "requests": 4, "failed": 1, "spend": 0.02, "tokens": 90}]

MY_TEAM_VIEW = {
    "team": {k: TEAM_ROW[k] for k in ("id", "name", "org_name", "status", "org_status", "key_limit", "key_budget",
                                      "key_expiry_days", "consent_text")},
    "consent": {"terms_accepted": True, "research_use": False, "id": 7, "person_id": "p-3", "at": "2026-11-02T00:00:00Z"},
    "keys": [{"id": "k-1", "name": "laptop", "created_at": "2026-11-02T00:00:00Z", "waiting": False}],
    "models": ["astro/gpt"],
    "knowledge_tools": "knowledge_astro",
    "usage": {"requests": 4, "failed": 1, "spend": 0.02, "tokens": 90},
}

CONCEPTS = [{"id": "facts/door", "title": "Door", "type": "fact", "description": "About the door", "tags": ["lab"],
             "written_at": "2026-11-03", "status": "stable", "body": "RAW **markdown** body", "links": 1}]
KNOWLEDGE_VIEW = {"org": {"id": "o-1", "name": "Astro", "slug": "astro", "status": "active"},
                  "tools": "knowledge_astro", "concepts": CONCEPTS,
                  "edges": [{"source": "facts/door", "target": "facts/door", "note": "self"}], "log": "RAW log"}
GRAPH = {"width": 880, "height": 520, "nodes": [], "lines": [], "hidden": 0, "legend": []}

DLP_VIEW = {"enabled": True, "shown": 100, "read": 12,
            "totals": [{"kind": "EMAIL", "action": "mask", "count": 3}],
            "events": [{"at": "2026-11-03T10:00:00Z", "kinds": ["EMAIL"], "blocked": False, "action": "mask",
                        "source": "request", "mode": "enforce", "count": 2, "email": "p@uw.edu", "user_id": "part-3",
                        "request_id": "0123456789abcdef", "value_hash": "deadbeef"}]}


def test_session_drops_identifiers():
    out = shapes.session(ME, "tok", "http://g", "")
    assert set(out) == {"signed_in", "csrf", "me", "config"} and out["signed_in"] is True and out["csrf"] == "tok"
    assert set(out["me"]) == {"email", "is_admin", "lead_orgs", "teams"}
    assert set(out["me"]["lead_orgs"][0]) == {"id", "name", "status"}
    assert set(out["me"]["teams"][0]) == {"id", "name", "org_name", "status"}
    assert out["config"] == {"gateway_url": "http://g", "litellm_admin_url": ""}
    assert "participant_id" not in json.dumps(out) and "team_orgs" not in json.dumps(out)
    assert "person_id" not in json.dumps(out)


def test_admin_orgs_lists_only_the_table_columns():
    out = shapes.admin_orgs([{**ORG_ROW, "leads": 1, "teams": 2}])
    assert set(out) == {"orgs"}
    assert set(out["orgs"][0]) == {"id", "name", "slug", "budget_ceiling", "leads", "teams", "status"}


def test_audit_lists_only_the_table_columns():
    event = {"id": 9, "at": "2026-11-03T10:00:00Z", "actor_person_id": "p-1", "actor_email": "a@uw.edu",
             "actor_role": "admin", "action": "org.create", "result": "ok", "org_id": "o-1", "team_id": None,
             "org_name": "Astro", "team_name": None, "detail": {"slug": "astro"}}
    out = shapes.audit([event])
    assert set(out) == {"events"}
    assert set(out["events"][0]) == {"at", "actor_email", "actor_role", "action", "result", "org_name", "team_name"}


def test_dlp_shortens_the_request_id():
    out = shapes.dlp(DLP_VIEW, {"mask": "hidden from the model"})
    assert set(out) == {"enabled", "read", "shown", "actions", "totals", "events"}
    assert out["events"][0]["request"] == DLP_VIEW["events"][0]["request_id"][:8]
    assert set(out["events"][0]) == {"at", "kinds", "blocked", "action", "source", "mode", "count", "email", "user_id",
                                     "request"}
    assert set(out["totals"][0]) == {"kind", "action", "count"}
    assert "0123456789abcdef" not in json.dumps(out) and "value_hash" not in json.dumps(out)


def test_dlp_says_only_that_it_is_off_when_it_is_off():
    assert shapes.dlp({"enabled": False, "shown": 100, "read": 0, "totals": [], "events": []}, {}) == {"enabled": False}


def test_org_hides_lead_ids_and_invites_from_a_lead():
    out = shapes.org(ORG_VIEW, is_lead=True, is_admin=False)
    assert set(out) == {"org", "is_lead", "is_admin", "leads", "lead_invites", "models", "providers", "teams"}
    assert set(out["org"]) == {"id", "name", "slug", "status", "budget_ceiling"}
    assert set(out["leads"][0]) == {"email"} and out["lead_invites"] == []
    assert set(out["models"][0]) == {"id", "public_name", "provider"}
    assert set(out["teams"][0]) == {"id", "name", "members", "team_budget", "status"}
    assert out["is_lead"] is True and out["is_admin"] is False
    assert "mcp_server_id" not in json.dumps(out)


def test_org_gives_an_admin_what_the_remove_buttons_need():
    out = shapes.org(ORG_VIEW, is_lead=False, is_admin=True)
    assert set(out["leads"][0]) == {"id", "email"} and out["lead_invites"]
    assert set(out["lead_invites"][0]) == {"id", "email", "status", "signin_email"}


def test_team_manage_never_carries_participant_id():
    out = shapes.team_manage(TEAM_VIEW, USAGE, is_lead=True)
    assert set(out) == {"team", "is_lead", "models", "members", "invites", "keys", "usage", "integrations"}
    assert "participant_id" not in json.dumps(out)
    assert set(out["team"]) == {"id", "name", "status", "org_id", "org_name", "org_status", "org_budget_ceiling",
                                "team_budget", "key_limit", "key_budget", "key_expiry_days"}
    assert set(out["members"][0]) == {"id", "email", "terms_accepted", "keys"}
    assert set(out["usage"][0]) == {"email", "requests", "failed", "tokens", "spend"}
    assert set(out["models"][0]) == {"id", "public_name", "allowed"}
    assert set(out["invites"][0]) == {"id", "email", "status", "signin_email"}
    assert set(out["keys"][0]) == {"id", "email", "name", "waiting", "hint", "created_at", "expires", "last_used", "spend"}
    assert set(out["integrations"][0]) == {"id", "name", "client_id", "can_enroll"}


def test_my_team_shows_a_participant_their_own_page_and_no_more():
    out = shapes.my_team(MY_TEAM_VIEW)
    assert set(out) == {"team", "consent", "keys", "models", "knowledge_tools", "usage"}
    assert set(out["team"]) == {"id", "name", "status", "org_name", "org_status", "consent_text", "key_limit",
                                "key_budget", "key_expiry_days"}
    assert out["consent"] == {"terms_accepted": True, "research_use": False}
    assert set(out["keys"][0]) == {"id", "name", "waiting", "created_at"}
    assert out["models"] == ["astro/gpt"] and set(out["usage"]) == {"requests", "tokens", "spend"}


def test_my_team_keeps_no_consent_as_none():
    assert shapes.my_team({**MY_TEAM_VIEW, "consent": None})["consent"] is None


def test_knowledge_carries_no_raw_markdown():
    out = shapes.knowledge(KNOWLEDGE_VIEW, concept=None, body_html="", links_out=[], links_in=[], graph=GRAPH,
                           log_html="")
    assert set(out) == {"org", "tools", "edge_count", "concepts", "concept", "graph", "log_html"}
    assert out["concept"] is None and "body" not in json.dumps(out) and "log" not in out
    assert "RAW" not in json.dumps(out)
    assert set(out["org"]) == {"id", "name"} and out["edge_count"] == 1
    assert set(out["concepts"][0]) == {"id", "title", "type", "description", "tags", "links", "written_at"}


def test_knowledge_carries_the_selected_concept_as_html_only():
    linked = [{**CONCEPTS[0], "note": "see"}]
    out = shapes.knowledge(KNOWLEDGE_VIEW, concept=CONCEPTS[0], body_html="<p>RENDERED</p>", links_out=linked,
                           links_in=[], graph=GRAPH, log_html="<p>LOG</p>")
    assert set(out["concept"]) == {"id", "title", "type", "status", "written_at", "tags", "description", "html",
                                   "links_out", "links_in"}
    assert out["concept"]["html"] == "<p>RENDERED</p>" and out["log_html"] == "<p>LOG</p>"
    assert out["concept"]["links_out"] == [{"id": "facts/door", "title": "Door", "note": "see"}]
    assert "RAW" not in json.dumps(out)


def test_invite_says_what_it_is_for_only_when_valid():
    assert shapes.invite({"valid": False, "outcome": "invalid"}) == {"valid": False}
    assert shapes.invite({"valid": True, "kind": "lead", "org_name": "Astro", "team_name": None, "id": "i-1"}) == {
        "valid": True, "kind": "lead", "org_name": "Astro", "team_name": None}


def test_key_is_a_name_and_the_key():
    assert shapes.key({"id": "k-1", "name": "laptop", "key": "sk-secret"}) == {"name": "laptop", "key": "sk-secret"}
