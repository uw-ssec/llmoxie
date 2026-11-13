"""The console from first sign-in to archiving, then every way of stepping outside one's own org.

The tests run in order and share what earlier ones created (W). Run with `-x`.
"""

import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from azure.storage.blob import ContainerClient

from .helpers import (CONSOLE, Browser, access_token, broker, chat, create_user, invite_token,
                      sign_in, sql)

RUN = uuid.uuid4().hex[:6]  # keeps names unique when the suite runs twice against one stack
PASSWORD = "Correct-horse-9"
PROVIDER_KEY_A = f"sk-PROVIDER-SECRET-A-{RUN}"
PROVIDER_KEY_B = f"sk-PROVIDER-SECRET-B-{RUN}"
PROMPT_MARKER = f"PROMPT-MARKER-{RUN}"
CONSENT = "By joining you agree that your organization's leads can see how many requests you make and what they cost."
W: dict = {}


def email(name: str) -> str:
    return f"{name}-{RUN}@example.com"


def one(query: str, params=()):
    return sql("SUPERUSER_DATABASE_URL", query, params)[0]


def data(browser, path: str) -> dict:
    """A page's data, as the application fetches it."""
    response = browser.api_get(path)
    assert response.status_code == 200, (path, response.status_code, response.text[:300])
    return response.json()


def said(response) -> str:
    """What the application would show after an action: its message, or the reason it was refused."""
    body = response.json()
    return body.get("message") or body.get("error", {}).get("message", "")


def new_key(response) -> str:
    """The key in the one response that carries it."""
    assert response.status_code == 200, response.text[:300]
    return response.json()["key"]["key"]


def not_invited(browser) -> bool:
    """Signed in, but with no role anywhere: the application shows "You are not invited yet"."""
    me = data(browser, "/session")["me"]
    return not (me["is_admin"] or me["lead_orgs"] or me["teams"])


def invite_is_dead(token: str) -> bool:
    return Browser().api_get(f"/invites/{token}").json() == {"valid": False}


# ── Sign-in and roles ───────────────────────────────────────────────────────

def test_login_page_has_one_button():
    response = Browser().get("/")
    assert response.status_code == 200
    assert Browser().api_get("/session").json() == {"signed_in": False}  # so the application shows only "Sign in"
    assert response.headers["cache-control"] == "no-store" and response.headers["referrer-policy"] == "same-origin"


def test_admin_signs_in_and_session_cookie_is_locked_down():
    W["alice"] = sign_in("alice", "alice123")
    assert data(W["alice"], "/session")["me"]["is_admin"] is True
    cookie = next(h for h in W["alice"].set_cookie_headers if h.startswith("__Host-Http-console="))
    lowered = cookie.lower()
    assert "secure" in lowered and "httponly" in lowered and "samesite=strict" in lowered and "path=/" in lowered
    assert "domain=" not in lowered


def test_signed_in_without_membership_is_not_invited():
    create_user(email("stranger"), PASSWORD)
    browser = sign_in(email("stranger"), PASSWORD)
    assert browser.landed_path == "/" and not_invited(browser)
    assert browser.api_get("/admin/orgs").status_code == 403


def test_admin_creates_two_orgs_and_invites_their_leads():
    alice = W["alice"]
    for letter in ("a", "b"):
        created = alice.api_post("/admin/orgs", {"name": f"Org {letter.upper()} {RUN}", "slug": f"org{letter}-{RUN}",
                                                 "budget_ceiling": 100})
        assert created.status_code == 200, created.text[:300]
        W[f"org_{letter}"] = str(one("SELECT id FROM org WHERE slug = %s", (f"org{letter}-{RUN}",))["id"])
        assert created.json()["goto"] == f"/orgs/{W[f'org_{letter}']}"
        create_user(email(f"lead-{letter}"), PASSWORD)
        invited = alice.api_post(f"/admin/orgs/{W[f'org_{letter}']}/leads", {"email": email(f"lead-{letter}")})
        assert "Invitation sent" in said(invited)


def test_opening_an_invite_link_does_not_use_it():
    token = invite_token(email("lead-a"))
    for _ in range(3):  # an email scanner fetching the link
        page = Browser().get(f"/invite/{token}")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store" and page.headers["referrer-policy"] == "same-origin"
        looked = Browser().api_get(f"/invites/{token}")  # what the invitation screen asks for
        assert looked.json() == {"valid": True, "kind": "lead", "org_name": f"Org A {RUN}", "team_name": None}
        assert looked.headers["cache-control"] == "no-store"
    assert one("SELECT status FROM invite WHERE org_id = %s", (W["org_a"],))["status"] == "pending"


def test_leads_accept_their_invites():
    for letter in ("a", "b"):
        token = invite_token(email(f"lead-{letter}"))
        browser = sign_in(email(f"lead-{letter}"), PASSWORD, start=(f"/invite/{token}", {}))
        assert browser.landed_path == f"/orgs/{W[f'org_{letter}']}"
        assert data(browser, f"/orgs/{W[f'org_{letter}']}")["is_lead"] is True  # so "New team" is theirs to use
        W[f"lead_{letter}"] = browser
        W[f"lead_{letter}_token"] = access_token(email(f"lead-{letter}"), PASSWORD)
    assert invite_is_dead(invite_token(email("lead-a")))  # used up


# ── The lead's workshop ─────────────────────────────────────────────────────

def test_lead_adds_models_and_the_key_is_write_only():
    for letter, key in (("a", PROVIDER_KEY_A), ("b", PROVIDER_KEY_B)):
        lead, org = W[f"lead_{letter}"], W[f"org_{letter}"]
        added = lead.api_post(f"/orgs/{org}/models", {"provider": "mock", "model": "m1", "api_key": key})
        assert f"Added org{letter}-{RUN}/m1" in said(added), added.text[:400]
        assert key not in added.text and key not in lead.api_get(f"/orgs/{org}").text
        W[f"model_{letter}"] = str(one("SELECT id FROM org_model WHERE org_id = %s", (org,))["id"])
    everything = str(sql("SUPERUSER_DATABASE_URL", "SELECT to_jsonb(m) AS j FROM org_model m")) + \
        str(sql("SUPERUSER_DATABASE_URL", "SELECT to_jsonb(a) AS j FROM audit_event a"))
    assert PROVIDER_KEY_A not in everything and PROVIDER_KEY_B not in everything


def test_custom_endpoints_cannot_send_a_key_elsewhere():
    token, org = W["lead_a_token"], W["org_a"]
    for body in ({"provider": "openai", "model": "x", "api_key": "k", "api_base": "https://evil.example"},
                 {"provider": "azure", "model": "x", "api_key": "k", "api_base": "https://evil.example",
                  "api_version": "2024-12-01-preview"},
                 {"provider": "azure", "model": "x", "api_key": "k", "api_version": "2024-12-01-preview",
                  "api_base": "https://x.openai.azure.com.evil.example"},
                 {"provider": "custom", "model": "x", "api_key": "k"}):
        assert broker("POST", f"/orgs/{org}/models", token, body).status_code == 422, body


def test_lead_creates_a_team_within_the_ceiling():
    for letter in ("a", "b"):
        lead, org = W[f"lead_{letter}"], W[f"org_{letter}"]
        form = {"name": f"Workshop {letter.upper()}", "team_budget": 500, "key_budget": 5, "key_limit": 2,
                "key_expiry_days": 30, "consent_text": CONSENT}
        assert "ceiling" in said(lead.api_post(f"/orgs/{org}/teams", form))  # 500 is over the org's 100
        created = lead.api_post(f"/orgs/{org}/teams", {**form, "team_budget": 50})
        assert "Created Workshop" in said(created), created.text[:400]
        W[f"team_{letter}"] = str(one("SELECT id FROM team WHERE org_id = %s", (org,))["id"])
        assert created.json()["goto"] == f"/teams/{W[f'team_{letter}']}/manage"


def test_lead_allows_a_model_and_sets_the_budget():
    lead, team = W["lead_a"], W["team_a"]
    assert "Models updated" in said(lead.api_post(f"/teams/{team}/models", {"model_ids": [W["model_a"]]}))
    assert "Team budget updated" in said(lead.api_post(f"/teams/{team}/budget", {"team_budget": 60}))
    assert "ceiling" in said(lead.api_post(f"/teams/{team}/budget", {"team_budget": 101}))
    view = data(lead, f"/teams/{team}/manage")
    assert [m["allowed"] for m in view["models"]] == [True] and float(view["team"]["team_budget"]) == 60
    # Another org's model cannot be attached, whatever id is sent.
    assert broker("POST", f"/teams/{team}/models", W["lead_a_token"],
                  {"model_ids": [W["model_a"], W["model_b"]]}).status_code == 422
    assert broker("POST", f"/teams/{W['team_b']}/models", W["lead_b_token"],
                  {"model_ids": [W["model_b"]]}).status_code == 200


def test_lead_invites_people_by_text_and_csv():
    lead, team = W["lead_a"], W["team_a"]
    for name in ("p1", "p2", "p3"):
        create_user(email(name), PASSWORD)
    sent = lead.api_post(f"/teams/{team}/invites", data={"emails": email("p1")},
                         files={"csv_file": ("people.csv", f"name,email\nTwo,{email('p2')}\nThree,{email('p3')}\n")})
    assert "Sent 3 invitation(s)" in said(sent), sent.text[:400]
    assert "No email addresses found" in said(lead.api_post(f"/teams/{team}/invites", data={"emails": "nobody"}))


def test_lead_cancels_an_invitation_before_it_is_accepted():
    lead, team = W["lead_a"], W["team_a"]
    create_user(email("uninvited"), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": email("uninvited")})
    token = invite_token(email("uninvited"))
    invite = one("SELECT id FROM invite WHERE team_id = %s AND email = %s", (team, email("uninvited")))["id"]
    listed = {i["email"]: i for i in data(lead, f"/teams/{team}/manage")["invites"]}
    assert listed[email("uninvited")] == {"id": str(invite), "email": email("uninvited"), "status": "pending",
                                          "signin_email": None}  # what "Cancel invitation" needs

    assert broker("POST", f"/teams/{team}/invites/{invite}/revoke", W["lead_b_token"]).status_code == 403
    assert "Invitation cancelled" in said(lead.api_post(f"/teams/{team}/invites/{invite}/revoke"))
    assert email("uninvited") not in lead.api_get(f"/teams/{team}/manage").text
    assert invite_is_dead(token)
    late = sign_in(email("uninvited"), PASSWORD, start=(f"/invite/{token}", {}))
    assert late.landed_path == "/invite-result/invalid" and late.api_get(f"/teams/{team}").status_code == 403
    assert lead.api_post(f"/teams/{team}/invites/{invite}/revoke").status_code == 404   # already cancelled
    # The other invitations sent earlier are untouched.
    assert one("SELECT count(*) AS n FROM invite WHERE team_id = %s AND status = 'pending'", (team,))["n"] == 3


# ── Participants ────────────────────────────────────────────────────────────

def test_participant_registers_consents_and_gets_a_key_shown_once():
    team = W["team_a"]
    p1 = sign_in(email("p1"), PASSWORD, start=(f"/invite/{invite_token(email('p1'))}", {}))
    before = data(p1, f"/teams/{team}")
    assert p1.landed_path == f"/teams/{team}" and before["team"]["consent_text"] == CONSENT
    assert before["consent"] is None and before["keys"] == []  # nothing about keys before consent

    W["p1_token"] = access_token(email("p1"), PASSWORD)
    assert broker("POST", f"/my/teams/{team}/keys", W["p1_token"], {"name": "early"}).status_code == 409

    agreed = p1.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})  # research use left unticked
    assert "Your choices are saved" in said(agreed)
    assert data(p1, f"/teams/{team}")["consent"] == {"terms_accepted": True, "research_use": False}
    consent = one("SELECT terms_accepted, research_use FROM consent WHERE team_id = %s ORDER BY id DESC LIMIT 1", (team,))
    assert consent == {"terms_accepted": True, "research_use": False}

    created = p1.api_post(f"/teams/{team}/my/keys", {"name": "laptop"})
    key = new_key(created)
    assert created.json() == {"key": {"name": "laptop", "key": key}, "rotated": False} and key.startswith("sk-")
    assert created.headers["cache-control"] == "no-store"
    assert key not in p1.api_get(f"/teams/{team}").text  # never shown again
    assert key not in str(sql("SUPERUSER_DATABASE_URL", "SELECT to_jsonb(k) AS j FROM api_key k"))  # nor stored
    W["p1"], W["p1_key"] = p1, key


def test_key_reaches_only_the_teams_models():
    key = W["p1_key"]
    answer = chat(key, f"orga-{RUN}/m1", PROMPT_MARKER)
    assert answer.status_code == 200, answer.text
    W["request_id"] = answer.json()["id"]
    assert chat(key, f"orgb-{RUN}/m1").status_code in (401, 403)   # another org's model
    assert chat(key, "fake-gpt").status_code in (401, 403)         # a model no team was given
    assert httpx.get(f"{os.environ['GATEWAY_URL']}/key/info", headers={"Authorization": f"Bearer {key}"}).status_code == 404


def test_key_limit_holds_under_concurrent_requests():
    team, token = W["team_a"], W["p1_token"]  # limit is 2 and one key exists
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda i: broker("POST", f"/my/teams/{team}/keys", token, {"name": f"k{i}"}).status_code,
                              range(12)))
    assert sorted(codes) == [200] + [409] * 11, codes
    active = one("SELECT count(*) AS n FROM api_key WHERE team_id = %s AND status = 'active'", (team,))["n"]
    assert active == 2
    assert "you already have 2 keys" in said(W["p1"].api_post(f"/teams/{team}/my/keys", {"name": "third"}))


def test_participant_can_delete_and_replace_a_key():
    p1, team = W["p1"], W["team_a"]
    extra = one("SELECT id FROM api_key WHERE team_id = %s AND status = 'active' AND name <> 'laptop'", (team,))["id"]
    assert "Key deleted" in said(p1.api_post(f"/teams/{team}/my/keys/{extra}/delete"))
    view = data(p1, f"/teams/{team}")
    assert len(view["keys"]) < view["team"]["key_limit"]  # so "Name for a new key" is offered again


def test_mismatched_email_waits_for_the_lead():
    lead, team = W["lead_a"], W["team_a"]
    create_user(email("other"), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": email("invited-elsewhere")})
    token = invite_token(email("invited-elsewhere"))

    other = sign_in(email("other"), PASSWORD, start=(f"/invite/{token}", {}))
    assert other.landed_path == "/invite-result/waiting"
    assert not_invited(other) and other.api_get(f"/teams/{team}").status_code == 403
    assert invite_is_dead(token)  # the link is spent either way

    waiting = [i for i in data(lead, f"/teams/{team}/manage")["invites"] if i["status"] == "needs_approval"]
    assert [(i["email"], i["signin_email"]) for i in waiting] == [(email("invited-elsewhere"), email("other"))]
    request_id = one("SELECT id FROM invite WHERE team_id = %s AND status = 'needs_approval'", (team,))["id"]
    assert "Request approved" in said(lead.api_post(f"/teams/{team}/requests/{request_id}", {"approve": True}))
    assert other.api_get(f"/teams/{team}").status_code == 200


def test_rejected_request_grants_nothing():
    lead, team = W["lead_a"], W["team_a"]
    lead.api_post(f"/teams/{team}/invites", data={"emails": email("invited-again")})
    stranger = sign_in(email("stranger"), PASSWORD, start=(f"/invite/{invite_token(email('invited-again'))}", {}))
    request_id = one("SELECT id FROM invite WHERE team_id = %s AND status = 'needs_approval'", (team,))["id"]
    assert "Request rejected" in said(lead.api_post(f"/teams/{team}/requests/{request_id}", {"approve": False}))
    assert stranger.api_get(f"/teams/{team}").status_code == 403


def test_expired_and_reused_invites_fail_safely():
    team = W["team_a"]
    token = invite_token(email("p3"))
    sql("SUPERUSER_DATABASE_URL", "UPDATE invite SET expires_at = now() - interval '1 minute' WHERE team_id = %s AND email = %s",
        (team, email("p3")))
    expired = sign_in(email("p3"), PASSWORD, start=(f"/invite/{token}", {}))
    assert expired.landed_path == "/invite-result/invalid" and expired.api_get(f"/teams/{team}").status_code == 403

    p1_again = sign_in(email("p2"), PASSWORD, start=(f"/invite/{invite_token(email('p1'))}", {}))  # p1's used link
    assert p1_again.landed_path == "/invite-result/invalid" and p1_again.api_get(f"/teams/{team}").status_code == 403
    assert broker("POST", "/invites/accept", W["p1_token"], {"token": "x" * 43}).json()["outcome"] == "invalid"


def test_second_participant_joins():
    team = W["team_a"]
    p2 = sign_in(email("p2"), PASSWORD, start=(f"/invite/{invite_token(email('p2'))}", {}))
    assert p2.landed_path == f"/teams/{team}"
    p2.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True, "research_use": True})
    W["p2_key"] = new_key(p2.api_post(f"/teams/{team}/my/keys", {"name": "desk"}))
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 200
    W["p2"], W["p2_token"] = p2, access_token(email("p2"), PASSWORD)
    W["p2_person"] = str(one("SELECT id FROM person WHERE email = %s", (email("p2"),))["id"])
    W["p1_person"] = str(one("SELECT id FROM person WHERE email = %s", (email("p1"),))["id"])


def test_lead_sees_who_holds_which_keys_but_never_a_key():
    team = W["team_a"]
    view = broker("GET", f"/teams/{team}/manage", W["lead_a_token"])
    keys = {(k["email"], k["name"]): k for k in view.json()["keys"]}
    assert set(keys) == {(email("p1"), "laptop"), (email("p2"), "desk")}
    mine = keys[(email("p1"), "laptop")]
    assert set(mine) == {"id", "name", "email", "created_at", "waiting", "hint", "spend", "expires", "last_used"}
    assert mine["expires"] and mine["hint"] and mine["hint"] != W["p1_key"] and len(mine["hint"]) < len(W["p1_key"])
    page = W["lead_a"].api_get(f"/teams/{team}/manage")
    assert {(k["email"], k["name"]) for k in page.json()["keys"]} == set(keys)
    for text in (view.text, page.text):
        assert W["p1_key"] not in text and W["p2_key"] not in text
        assert W["p1_key"][3:] not in text  # nor the key without its sk- prefix
    assert "participant_id" not in page.text  # a lead sees people by email, never by the id the logs carry
    assert broker("GET", f"/teams/{team}/manage", W["lead_b_token"]).status_code == 403


def test_participant_rotates_a_key():
    p1, team = W["p1"], W["team_a"]
    old_key = W["p1_key"]
    old_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))["id"]
    rotated = p1.api_post(f"/teams/{team}/my/keys/{old_id}/rotate")
    fresh = new_key(rotated)
    assert rotated.json() == {"key": {"name": "laptop", "key": fresh}, "rotated": True}  # "Your replacement key: laptop"
    assert fresh != old_key and fresh not in p1.api_get(f"/teams/{team}").text   # shown once
    assert chat(old_key, f"orga-{RUN}/m1").status_code == 401
    assert chat(fresh, f"orga-{RUN}/m1").status_code == 200
    mine = sql("SUPERUSER_DATABASE_URL", "SELECT name, status FROM api_key WHERE person_id = %s ORDER BY created_at",
               (W["p1_person"],))
    assert [k["name"] for k in mine if k["status"] == "active"] == ["laptop"]   # same name, still one slot used
    assert broker("POST", f"/my/teams/{team}/keys/{old_id}/rotate", W["p1_token"]).status_code == 404  # already replaced
    W["p1_key"] = fresh


def test_rotating_does_not_refill_a_keys_budget():
    team = W["team_a"]
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    litellm = os.environ["LITELLM_URL"]
    row = one("SELECT id, key_alias FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))
    # Mocked models cost nothing, so give the key some spend directly in LiteLLM, as real usage would.
    httpx.post(f"{litellm}/key/update", headers=headers, json={"key": W["p1_key"], "spend": 3.25}).raise_for_status()
    rotated = broker("POST", f"/my/teams/{team}/keys/{row['id']}/rotate", W["p1_token"])
    assert rotated.status_code == 200
    info = httpx.get(f"{litellm}/key/info", params={"key": rotated.json()["key"]}, headers=headers).json()["info"]
    assert info["spend"] == 3.25 and info["max_budget"] == 5.0
    W["p1_key"] = rotated.json()["key"]


def test_lead_revokes_one_key_and_the_person_can_make_another():
    lead, team, p2 = W["lead_a"], W["team_a"], W["p2"]
    key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p2_person"],))["id"]
    assert broker("POST", f"/teams/{team}/keys/{key_id}/revoke", W["p1_token"]).status_code == 403  # not a lead
    revoked = lead.api_post(f"/teams/{team}/keys/{key_id}/revoke")
    assert "Key revoked" in said(revoked)
    assert "desk" not in [k["name"] for k in data(lead, f"/teams/{team}/manage")["keys"]]
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 401
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200          # nobody else's key is affected
    assert lead.api_post(f"/teams/{team}/keys/{key_id}/revoke").status_code == 404
    assert p2.api_get(f"/teams/{team}").status_code == 200                  # still a member
    W["p2_key"] = new_key(p2.api_post(f"/teams/{team}/my/keys", {"name": "desk"}))
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 200


def test_lead_rotates_a_key_without_ever_seeing_it():
    lead, team, p2 = W["lead_a"], W["team_a"], W["p2"]
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    old_key = W["p2_key"]
    key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p2_person"],))["id"]
    httpx.post(f"{litellm}/key/update", headers=headers, json={"key": old_key, "spend": 1.75}).raise_for_status()
    assert broker("POST", f"/teams/{team}/keys/{key_id}/rotate", W["p1_token"]).status_code == 403  # not a lead

    rotated = lead.api_post(f"/teams/{team}/keys/{key_id}/rotate")
    assert "Key rotated" in said(rotated) and set(rotated.json()) == {"message"}
    after = lead.api_get(f"/teams/{team}/manage")
    assert [k["waiting"] for k in after.json()["keys"] if k["id"] == str(key_id)] == [True]  # "rotated, not collected yet"
    assert "sk-" not in re.sub(r"sk-\.\.\.\w+", "", after.text)    # no key in the lead's data, only masked hints
    assert chat(old_key, f"orga-{RUN}/m1").status_code == 401            # stopped at once
    assert lead.api_post(f"/teams/{team}/keys/{key_id}/rotate").status_code == 404   # nothing left to rotate
    notice = httpx.get(f"{os.environ['MAILPIT_URL']}/api/v1/search", params={"query": f'to:{email("p2")} subject:rotated'})
    assert notice.json()["messages"], "the owner was not told"

    # The slot is held for the owner: they cannot make an extra key meanwhile, and they collect the replacement.
    mine = data(p2, f"/teams/{team}")["keys"]
    assert [(k["name"], k["waiting"]) for k in mine] == [("desk", True)]  # "Get replacement key", "rotated by your lead"
    collected = p2.api_post(f"/teams/{team}/my/keys/{key_id}/rotate")
    fresh = new_key(collected)
    assert collected.json() == {"key": {"name": "desk", "key": fresh}, "rotated": True} and fresh != old_key
    assert chat(fresh, f"orga-{RUN}/m1").status_code == 200
    info = httpx.get(f"{litellm}/key/info", params={"key": fresh}, headers=headers).json()["info"]
    assert info["spend"] == 1.75                                         # the budget was not refilled
    live = sql("SUPERUSER_DATABASE_URL", "SELECT name FROM api_key WHERE person_id = %s AND status <> 'deleted'",
               (W["p2_person"],))
    assert [k["name"] for k in live] == ["desk"]
    W["p2_key"] = fresh


def test_participants_cannot_touch_each_others_keys():
    team = W["team_a"]
    p2_key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p2_person"],))["id"]
    assert broker("POST", f"/my/teams/{team}/keys/{p2_key_id}/delete", W["p1_token"]).status_code == 404
    assert broker("POST", f"/my/teams/{team}/keys/{p2_key_id}/rotate", W["p1_token"]).status_code == 404
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 200


# ── Usage and logs ──────────────────────────────────────────────────────────

def test_lead_sees_totals_but_never_content():
    team = W["team_a"]
    deadline = time.time() + 60  # LiteLLM writes spend logs in batches
    while time.time() < deadline:
        usage = broker("GET", f"/teams/{team}/usage", W["lead_a_token"])
        mine = next(row for row in usage.json() if row["email"] == email("p1"))
        if mine["requests"] >= 1:
            break
        time.sleep(3)
    assert mine["requests"] >= 1
    assert set(mine) == {"email", "participant_id", "requests", "failed", "spend", "tokens"}
    assert PROMPT_MARKER not in usage.text
    page = W["lead_a"].api_get(f"/teams/{team}/manage")
    shown = next(row for row in page.json()["usage"] if row["email"] == email("p1"))
    assert set(shown) == {"email", "requests", "failed", "tokens", "spend"} and shown["requests"] >= 1
    assert PROMPT_MARKER not in page.text and "participant_id" not in page.text
    assert PROMPT_MARKER not in W["p1"].api_get(f"/teams/{team}").text


def test_request_logs_carry_no_provider_key_and_no_email():
    participant_id = one("SELECT participant_id FROM person WHERE id = %s", (W["p1_person"],))["participant_id"]
    container = ContainerClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"], "litellm-logs")
    deadline, record = time.time() + 40, None
    while time.time() < deadline and record is None:
        blob = next((b.name for b in container.list_blobs() if W["request_id"] in b.name), None)
        record = container.download_blob(blob).readall().decode() if blob else None
        time.sleep(0 if record else 2)
    assert record, "no request log in Azurite"
    assert PROMPT_MARKER in record and participant_id in record     # it is the real record for that call
    assert PROVIDER_KEY_A not in record and email("p1") not in record

    mlflow = os.environ["MLFLOW_URL"]
    traces = httpx.get(f"{mlflow}/api/2.0/mlflow/traces", params={"experiment_ids": "0", "max_results": 50}).json()
    assert traces.get("traces"), "no MLflow traces"
    texts = [httpx.get(f"{mlflow}/api/2.0/mlflow/traces", params={"experiment_ids": "0", "max_results": 50}).text]
    for trace in traces["traces"]:
        texts.append(httpx.get(f"{mlflow}/ajax-api/2.0/mlflow/get-trace-artifact",
                               params={"request_id": trace["request_id"]}).text)
    joined = "\n".join(texts)
    assert PROMPT_MARKER in joined, "the MLflow trace for the call was not found"
    assert PROVIDER_KEY_A not in joined and email("p1") not in joined


# ── Staying inside one's own org ────────────────────────────────────────────

def lead_operations(org, team, model, person, key_id, invite_id):
    """Every org-lead and participant operation the broker offers, aimed at one org's objects."""
    return [
        ("GET", f"/orgs/{org}", None),
        ("POST", f"/orgs/{org}/models", {"provider": "mock", "model": "sneaky", "api_key": "k"}),
        ("POST", f"/orgs/{org}/models/{model}/remove", None),
        ("POST", f"/orgs/{org}/teams", {"name": "Sneaky", "key_limit": 1, "key_budget": 1, "key_expiry_days": 1,
                                        "team_budget": 1, "consent_text": "x" * 30}),
        ("GET", f"/teams/{team}/manage", None),
        ("POST", f"/teams/{team}/budget", {"team_budget": 1}),
        ("POST", f"/teams/{team}/models", {"model_ids": []}),
        ("POST", f"/teams/{team}/invites", {"emails": ["sneaky@example.com"]}),
        ("POST", f"/teams/{team}/requests/{invite_id}", {"approve": True}),
        ("POST", f"/teams/{team}/invites/{invite_id}/revoke", None),
        ("POST", f"/teams/{team}/members/{person}/remove", None),
        ("POST", f"/teams/{team}/keys/{key_id}/revoke", None),
        ("POST", f"/teams/{team}/keys/{key_id}/rotate", None),
        ("GET", f"/teams/{team}/usage", None),
        ("POST", f"/teams/{team}/archive", None),
    ]


def participant_operations(team, key_id):
    return [
        ("GET", f"/my/teams/{team}", None),
        ("POST", f"/my/teams/{team}/consent", {"terms_accepted": True, "research_use": True}),
        ("POST", f"/my/teams/{team}/keys", {"name": "sneaky"}),
        ("POST", f"/my/teams/{team}/keys/{key_id}/delete", None),
        ("POST", f"/my/teams/{team}/keys/{key_id}/rotate", None),
    ]


def admin_operations(org, invite_id, lead_person, team):
    return [
        ("POST", f"/admin/teams/{team}/remove", {"confirm_name": "Workshop A"}),
        ("GET", "/admin/orgs", None),
        ("POST", "/admin/orgs", {"name": "Sneaky", "slug": f"sneaky-{RUN}", "budget_ceiling": 1}),
        ("POST", f"/admin/orgs/{org}/suspend", None),
        ("POST", f"/admin/orgs/{org}/resume", None),
        ("POST", f"/admin/orgs/{org}/remove", {"confirm_slug": f"orga-{RUN}"}),
        ("POST", f"/admin/orgs/{org}/ceiling", {"budget_ceiling": 999999}),
        ("POST", f"/admin/orgs/{org}/leads", {"email": "sneaky@example.com"}),
        ("POST", f"/admin/orgs/{org}/lead-requests/{invite_id}", {"approve": True}),
        ("POST", f"/admin/orgs/{org}/leads/{lead_person}/remove", None),
        ("POST", f"/admin/orgs/{org}/lead-invites/{invite_id}/revoke", None),
        ("GET", "/admin/audit", None),
    ]


def snapshot() -> str:
    """Everything the denied calls below must leave untouched, in the console and in LiteLLM."""
    tables = ["org", "org_lead", "org_model", "team", "team_model", "team_member", "invite", "consent", "api_key"]
    console = [sql("SUPERUSER_DATABASE_URL", f"SELECT to_jsonb(t) AS j FROM {table} t ORDER BY 1") for table in tables]
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    litellm = []
    for team in (W["team_a"], W["team_b"]):
        info = httpx.get(f"{os.environ['LITELLM_URL']}/team/info", params={"team_id": team}, headers=headers).json()
        litellm.append((info["team_info"]["models"], info["team_info"]["max_budget"], info["team_info"]["blocked"],
                        sorted(k["key_alias"] for k in info["keys"])))
    models = httpx.get(f"{os.environ['LITELLM_URL']}/v1/model/info", headers=headers).json()["data"]
    return str(console) + str(litellm) + str(sorted(m["model_name"] for m in models))


def test_every_out_of_scope_call_is_denied_and_changes_nothing():
    a = dict(org=W["org_a"], team=W["team_a"], model=W["model_a"], person=W["p1_person"],
             key_id=str(one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))["id"]),
             invite_id=str(one("SELECT id FROM invite WHERE team_id = %s LIMIT 1", (W["team_a"],))["id"]))
    b_team = W["team_b"]
    nowhere = dict(org=str(uuid.uuid4()), team=str(uuid.uuid4()), model=a["model"], person=a["person"],
                   key_id=a["key_id"], invite_id=a["invite_id"])
    alice_token = access_token("alice", "alice123")
    stranger_token = access_token(email("stranger"), PASSWORD)

    cases = []
    # A lead of another org, a participant, and someone with no membership try org A's lead operations.
    for who in ("lead_b_token", "p1_token"):
        cases += [(who, *op) for op in lead_operations(**a)]
    cases += [("stranger", *op) for op in lead_operations(**a)]
    # An admin may look at an org but not run it.
    # (and its teams, and remove someone from a team: those three are left out here and tested on their own)
    cases += [("alice", *op) for op in lead_operations(**a)[1:]
              if not op[1].endswith(("/manage", "/usage")) and "/members/" not in op[1]]
    # Lead A is not a participant of their own team, and nobody from org A may touch org B's team.
    cases += [("lead_a_token", *op) for op in participant_operations(a["team"], a["key_id"])]
    cases += [(who, *op) for who in ("lead_a_token", "p1_token", "p2_token")
              for op in participant_operations(b_team, a["key_id"]) + lead_operations(
                  W["org_b"], b_team, W["model_b"], a["person"], a["key_id"], a["invite_id"])]
    # Only SSEC admins run admin operations.
    cases += [(who, *op) for who in ("lead_a_token", "p1_token", "stranger") for op in admin_operations(
        a["org"], a["invite_id"], one("SELECT person_id FROM org_lead WHERE org_id = %s", (a["org"],))["person_id"],
        a["team"])]
    # Ids that do not exist are refused the same way, so they cannot be probed.
    cases += [("lead_a_token", *op) for op in lead_operations(**nowhere) + participant_operations(nowhere["team"], a["key_id"])]

    tokens = {**W, "alice": alice_token, "stranger": stranger_token}
    before = snapshot()
    denied_before = one("SELECT count(*) AS n FROM audit_event WHERE result = 'denied'")["n"]
    wrong = [(who, method, path, status) for who, method, path, body in cases
             if (status := broker(method, path, tokens[who], body).status_code) != 403]
    assert not wrong, wrong
    assert snapshot() == before
    assert one("SELECT count(*) AS n FROM audit_event WHERE result = 'denied'")["n"] - denied_before == len(cases)
    assert len(cases) > 100


def test_broker_rejects_callers_without_a_valid_user_assertion():
    path = f"/orgs/{W['org_a']}"
    assert broker("GET", path, W["lead_a_token"]).status_code == 200
    assert broker("GET", path, W["lead_a_token"], caller=None).status_code == 401          # not console-web
    assert broker("GET", path, W["lead_a_token"], caller="guess").status_code == 401
    assert broker("GET", path, None).status_code == 401                                    # console-web, no user
    header, payload, signature = W["lead_a_token"].split(".")
    assert broker("GET", path, f"{header}.{payload}.{signature[:-4]}AAAA").status_code == 401  # tampered
    unsigned = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0." + payload + "."
    assert broker("GET", path, unsigned).status_code == 401
    assert broker("POST", "/invites/inspect", None, {"token": "x" * 43}, caller=None).status_code == 401


def test_console_web_enforces_the_same_rules():
    a_org, a_team, b_team = W["org_a"], W["team_a"], W["team_b"]
    for browser in (W["p1"], W["lead_b"]):
        for path in ("/admin/orgs", "/admin/audit", "/admin/dlp", f"/orgs/{a_org}", f"/orgs/{a_org}/knowledge",
                     f"/teams/{a_team}/manage"):
            refused = browser.api_get(path)
            assert refused.status_code == 403 and refused.json()["error"]["status"] == 403, path
    assert W["lead_b"].api_get(f"/teams/{a_team}").status_code == 403
    assert W["p1"].api_get(f"/teams/{b_team}").status_code == 403
    assert W["p1"].api_post(f"/teams/{a_team}/archive").status_code == 403
    assert W["p1"].api_post(f"/admin/orgs/{a_org}/suspend").status_code == 403
    assert W["alice"].api_get(f"/orgs/{a_org}").status_code == 200  # admins may look
    assert W["alice"].api_post(f"/orgs/{a_org}/teams", {"name": "x"}).status_code in (403, 422)
    team_form = {"name": "x", "team_budget": 1, "key_budget": 1, "key_limit": 1, "key_expiry_days": 1,
                 "consent_text": "x" * 30}
    assert W["alice"].api_post(f"/orgs/{a_org}/teams", team_form).status_code == 403  # but not run it


def test_forms_refuse_cross_site_and_tokenless_posts():
    lead, team = W["lead_a"], W["team_a"]
    archive = f"{CONSOLE}/web-api/teams/{team}/archive"
    for origin in ("http://evil.example", "null"):
        refused = lead.request("POST", archive, headers={"Origin": origin, "X-CSRF-Token": lead.csrf})
        assert refused.status_code == 403, origin
    assert lead.api_post(f"/teams/{team}/archive", csrf="wrong").status_code == 403
    assert lead.api_post(f"/teams/{team}/archive", csrf=None).status_code == 403
    assert one("SELECT status FROM team WHERE id = %s", (team,))["status"] == "active"
    assert Browser().api_post(f"/teams/{team}/archive", csrf="x").status_code == 401  # not signed in
    # Signing out is a plain form, and is held to the same two checks.
    assert lead.post("/logout", {"csrf": "wrong"}, follow=False).status_code == 403
    assert lead.post("/logout", headers={"Origin": "http://evil.example"}, follow=False).status_code == 403
    assert data(lead, "/session")["signed_in"] is True


def test_database_roles_are_separated_and_logs_are_append_only():
    def refused(role: str, query: str) -> bool:
        try:
            sql(role, query)
        except psycopg.errors.InsufficientPrivilege:
            return True
        return False

    assert refused("WEB_DATABASE_URL", "SELECT * FROM org")
    assert refused("WEB_DATABASE_URL", "SELECT * FROM api_key")
    assert refused("BROKER_DATABASE_URL", "SELECT * FROM web_session")
    assert refused("BROKER_DATABASE_URL", "UPDATE audit_event SET result = 'ok'")
    assert refused("BROKER_DATABASE_URL", "DELETE FROM audit_event")
    assert refused("BROKER_DATABASE_URL", "UPDATE consent SET research_use = true")
    assert refused("BROKER_DATABASE_URL", "DELETE FROM consent")
    for role in ("console_web:console-web-dev", "console_broker:console-broker-dev"):
        for database in ("litellm", "mlflow_db"):
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(f"postgresql://{role}@postgres:5432/{database}").close()

    # Row-level security: with no scope the broker's role sees nothing; scoped to org A it sees only org A.
    with psycopg.connect(os.environ["BROKER_DATABASE_URL"]) as conn:
        assert conn.execute("SELECT count(*) FROM team").fetchone()[0] == 0
        conn.execute("SELECT set_config('app.scope', 'org', true), set_config('app.org_id', %s, true)", (W["org_a"],))
        assert {str(r[0]) for r in conn.execute("SELECT org_id FROM team")} == {W["org_a"]}
        assert {str(r[0]) for r in conn.execute("SELECT id FROM org")} == {W["org_a"]}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE team SET org_id = %s", (W["org_b"],))


# ── Removing people, archiving, suspending ──────────────────────────────────

def test_admin_can_remove_someone_from_any_team_but_not_run_it():
    alice, lead, team = W["alice"], W["lead_a"], W["team_a"]
    create_user(email("p-admin"), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": email("p-admin")})
    member = sign_in(email("p-admin"), PASSWORD, start=(f"/invite/{invite_token(email('p-admin'))}", {}))
    member.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})
    key = new_key(member.api_post(f"/teams/{team}/my/keys", {"name": "k"}))
    person = str(one("SELECT id FROM person WHERE email = %s", (email("p-admin"),))["id"])
    assert chat(key, f"orga-{RUN}/m1").status_code == 200

    # The admin leads no org, yet can open the team from the organization's page.
    assert team in [t["id"] for t in data(alice, f"/orgs/{W['org_a']}")["teams"]]
    view = data(alice, f"/teams/{team}/manage")
    # `is_lead` false is what puts "viewing this team as an SSEC admin" on the page and takes the lead's buttons off;
    # the refusals further down are what actually hold.
    assert view["is_lead"] is False and data(alice, "/session")["me"]["is_admin"] is True
    assert data(lead, f"/teams/{team}/manage")["is_lead"] is True   # the lead still has them
    assert person in [m["id"] for m in view["members"] if m["email"] == email("p-admin")]

    removed = alice.api_post(f"/teams/{team}/members/{person}/remove")
    assert "Removed. 1 key(s) deleted" in said(removed)
    after = data(alice, f"/teams/{team}/manage")
    assert person not in [m["id"] for m in after["members"]]   # gone from People (past usage stays listed)
    assert one("SELECT status FROM team_member WHERE person_id = %s", (person,))["status"] == "removed"
    assert chat(key, f"orga-{RUN}/m1").status_code == 401
    assert member.api_get(f"/teams/{team}").status_code == 403
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200       # nobody else is affected
    event = one("SELECT actor_role, result FROM audit_event WHERE action = 'team.remove_member' ORDER BY id DESC LIMIT 1")
    assert event == {"actor_role": "admin", "result": "ok"}

    # Everything else about the team is still the lead's alone.
    key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))["id"]
    for path, body in ((f"/teams/{team}/archive", None), (f"/teams/{team}/budget", {"team_budget": 1}),
                       (f"/teams/{team}/keys/{key_id}/revoke", None), (f"/teams/{team}/keys/{key_id}/rotate", None),
                       (f"/teams/{team}/models", {"model_ids": []}),
                       (f"/teams/{team}/invites/{uuid.uuid4()}/revoke", None)):
        assert alice.api_post(path, body).status_code == 403, path
    assert alice.api_post(f"/teams/{team}/invites", data={"emails": "x@example.com"}).status_code == 403
    assert one("SELECT status FROM team WHERE id = %s", (team,))["status"] == "active"


def test_removing_someone_deletes_their_keys():
    lead, team = W["lead_a"], W["team_a"]
    assert "Removed. 1 key(s) deleted" in said(lead.api_post(f"/teams/{team}/members/{W['p2_person']}/remove"))
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 401
    assert W["p2"].api_get(f"/teams/{team}").status_code == 403
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200


def test_archiving_stops_every_key_and_freezes_the_team():
    lead, team = W["lead_a"], W["team_a"]
    archived = lead.api_post(f"/teams/{team}/archive")
    assert "Team archived" in said(archived)
    frozen = data(lead, f"/teams/{team}/manage")
    assert frozen["team"]["status"] == "archived" and frozen["keys"] == []   # "This team is archived"
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 401
    assert broker("POST", f"/my/teams/{team}/keys", W["p1_token"], {"name": "after"}).status_code == 409
    for method, path, body in lead_operations(W["org_a"], team, W["model_a"], W["p1_person"], str(uuid.uuid4()), str(uuid.uuid4())):
        if "/teams/" in path and method == "POST":
            assert broker(method, path, W["lead_a_token"], body).status_code in (404, 409), path
    assert data(W["p1"], f"/teams/{team}")["team"]["status"] == "archived"   # "This team is closed"
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    info = httpx.get(f"{os.environ['LITELLM_URL']}/team/info", params={"team_id": team}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True
    assert info["team_info"]["models"] == ["no-default-models"]
    # The org's model and provider key stay: other teams may use them.
    assert one("SELECT removed_at FROM org_model WHERE id = %s", (W["model_a"],))["removed_at"] is None


def test_suspended_org_cannot_be_run_until_resumed():
    alice, org, team = W["alice"], W["org_b"], W["team_b"]
    assert "Organization suspended" in said(alice.api_post(f"/admin/orgs/{org}/suspend"))
    assert data(alice, f"/orgs/{org}")["org"]["status"] == "suspended"
    assert broker("POST", f"/teams/{team}/budget", W["lead_b_token"], {"team_budget": 10}).status_code == 409
    assert broker("GET", f"/orgs/{org}", W["lead_b_token"]).status_code == 200  # still readable
    assert "Organization resumed" in said(alice.api_post(f"/admin/orgs/{org}/resume"))
    assert broker("POST", f"/teams/{team}/budget", W["lead_b_token"], {"team_budget": 10}).status_code == 200
    assert "lower that first" in said(alice.api_post(f"/admin/orgs/{org}/ceiling", {"budget_ceiling": 5}))


def test_admin_removes_a_lead_and_cancels_an_invitation():
    alice, org = W["alice"], W["org_b"]
    create_user(email("lead-temp"), PASSWORD)
    alice.api_post(f"/admin/orgs/{org}/leads", {"email": email("lead-temp")})
    temp = sign_in(email("lead-temp"), PASSWORD, start=(f"/invite/{invite_token(email('lead-temp'))}", {}))
    temp_token = access_token(email("lead-temp"), PASSWORD)
    assert temp.api_get(f"/orgs/{org}").status_code == 200 and broker("GET", f"/orgs/{org}", temp_token).status_code == 200

    person = str(one("SELECT id FROM person WHERE email = %s", (email("lead-temp"),))["id"])
    leads = {lead["email"]: lead for lead in data(alice, f"/orgs/{org}")["leads"]}
    assert set(leads) == {email("lead-temp"), email("lead-b")} and leads[email("lead-temp")]["id"] == person
    # A lead sees who else leads, but is not handed their ids or the pending invitations.
    as_lead = data(W["lead_b"], f"/orgs/{org}")
    assert all(set(lead) == {"email"} for lead in as_lead["leads"]) and as_lead["lead_invites"] == []
    assert "Lead removed" in said(alice.api_post(f"/admin/orgs/{org}/leads/{person}/remove"))
    # Access ends at once, in the browser session and for the token they already hold.
    assert temp.api_get(f"/orgs/{org}").status_code == 403 and not_invited(temp)
    assert broker("GET", f"/orgs/{org}", temp_token).status_code == 403
    assert broker("POST", f"/teams/{W['team_b']}/budget", temp_token, {"team_budget": 1}).status_code == 403
    assert broker("GET", f"/orgs/{org}", W["lead_b_token"]).status_code == 200      # the other lead is untouched
    assert one("SELECT status FROM team WHERE id = %s", (W["team_b"],))["status"] == "active"  # so is their work
    assert alice.api_post(f"/admin/orgs/{org}/leads/{person}/remove").status_code == 404  # no longer a lead

    # An invitation that was never accepted can be cancelled, and its link stops working.
    alice.api_post(f"/admin/orgs/{org}/leads", {"email": email("lead-never")})
    token = invite_token(email("lead-never"))
    invite = one("SELECT id FROM invite WHERE org_id = %s AND email = %s AND status = 'pending'", (org, email("lead-never")))["id"]
    pending = [i for i in data(alice, f"/orgs/{org}")["lead_invites"] if i["email"] == email("lead-never")]
    assert pending == [{"id": str(invite), "email": email("lead-never"), "status": "pending", "signin_email": None}]
    assert "Invitation cancelled" in said(alice.api_post(f"/admin/orgs/{org}/lead-invites/{invite}/revoke"))
    assert invite_is_dead(token)
    assert email("lead-never") not in alice.api_get(f"/orgs/{org}").text


def test_admin_removes_a_team_and_only_that_team():
    alice, lead, org = W["alice"], W["lead_b"], W["org_b"]
    slug = f"orgb-{RUN}"
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    # A second team in org B, with a member who holds a working key.
    scratch_form = {"name": "Scratch", "team_budget": 5, "key_budget": 1, "key_limit": 1, "key_expiry_days": 7,
                    "consent_text": CONSENT}
    lead.api_post(f"/orgs/{org}/teams", scratch_form)
    scratch = str(one("SELECT id FROM team WHERE org_id = %s AND name = 'Scratch'", (org,))["id"])
    lead.api_post(f"/teams/{scratch}/models", {"model_ids": [W["model_b"]]})
    create_user(email("ps"), PASSWORD)
    lead.api_post(f"/teams/{scratch}/invites", data={"emails": f"{email('ps')}\n{email('ps-pending')}"})
    pending_token = invite_token(email("ps-pending"))
    member = sign_in(email("ps"), PASSWORD, start=(f"/invite/{invite_token(email('ps'))}", {}))
    member.api_post(f"/teams/{scratch}/my/consent", {"terms_accepted": True})
    key = new_key(member.api_post(f"/teams/{scratch}/my/keys", {"name": "k"}))
    assert chat(key, f"{slug}/m1").status_code == 200

    # A lead has no such button or right; the admin must type the team's name.
    assert data(lead, "/session")["me"]["is_admin"] is False     # what keeps "Remove team" off the lead's page
    assert lead.api_post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"}).status_code == 403
    assert data(alice, "/session")["me"]["is_admin"] is True
    assert "name exactly" in said(alice.api_post(f"/admin/teams/{scratch}/remove", {"confirm_name": "scratch"}))
    assert chat(key, f"{slug}/m1").status_code == 200

    removed = alice.api_post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"})
    assert "Team removed: 1 member(s) removed, 1 key(s) deleted" in said(removed)
    assert removed.json()["goto"] == f"/orgs/{org}"
    assert [t["name"] for t in data(alice, f"/orgs/{org}")["teams"]] == ["Workshop B"]  # the org page it leads to

    assert chat(key, f"{slug}/m1").status_code == 401
    info = httpx.get(f"{litellm}/team/info", params={"team_id": scratch}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True
    for browser in (member, lead, alice):
        assert browser.api_get(f"/teams/{scratch}/manage").status_code == 403
    assert member.api_get(f"/teams/{scratch}").status_code == 403 and not_invited(member)
    assert broker("GET", f"/teams/{scratch}/manage", W["lead_b_token"]).status_code == 403
    assert invite_is_dead(pending_token)
    assert alice.api_post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"}).status_code == 404

    # The rest of the org carries on: its other team, its model, and the freed name.
    assert broker("GET", f"/teams/{W['team_b']}/manage", W["lead_b_token"]).status_code == 200
    assert one("SELECT removed_at FROM org_model WHERE id = %s", (W["model_b"],))["removed_at"] is None
    assert one("SELECT count(*) AS n FROM consent WHERE team_id = %s", (scratch,))["n"] == 1     # records kept
    again = lead.api_post(f"/orgs/{org}/teams", scratch_form)
    assert "Created Scratch" in said(again)
    # An archived team can be removed too.
    second = str(one("SELECT id FROM team WHERE org_id = %s AND name = 'Scratch' AND status = 'active'", (org,))["id"])
    lead.api_post(f"/teams/{second}/archive")
    assert "Team removed: 0 member(s) removed, 0 key(s) deleted" in said(
        alice.api_post(f"/admin/teams/{second}/remove", {"confirm_name": "Scratch"}))


def test_admin_removes_an_org_and_everything_in_it_stops():
    alice, org, team, lead = W["alice"], W["org_b"], W["team_b"], W["lead_b"]
    slug = f"orgb-{RUN}"
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    # Give org B a member with a working key, and a pending invitation.
    create_user(email("pb"), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": f"{email('pb')}\n{email('pb-pending')}"})
    pending_token = invite_token(email("pb-pending"))
    member = sign_in(email("pb"), PASSWORD, start=(f"/invite/{invite_token(email('pb'))}", {}))
    member.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})
    key = new_key(member.api_post(f"/teams/{team}/my/keys", {"name": "k"}))
    assert chat(key, f"{slug}/m1").status_code == 200

    # The short name must be typed exactly; otherwise nothing happens.
    assert "short name exactly" in said(alice.api_post(f"/admin/orgs/{org}/remove", {"confirm_slug": "wrong"}))
    assert chat(key, f"{slug}/m1").status_code == 200 and one("SELECT status FROM org WHERE id = %s", (org,))["status"] == "active"

    removed = alice.api_post(f"/admin/orgs/{org}/remove", {"confirm_slug": slug})
    assert "Organization removed: 1 team(s) archived, 1 key(s) deleted, 1 model(s) removed" in said(removed)
    assert removed.json()["goto"] == "/admin"
    assert f"Org B {RUN}" not in [o["name"] for o in data(alice, "/admin/orgs")["orgs"]]   # gone from the admin's list

    # Keys, the model with its provider key, and the team are shut in LiteLLM.
    assert chat(key, f"{slug}/m1").status_code == 401
    names = [m["model_name"] for m in httpx.get(f"{litellm}/v1/model/info", headers=headers).json()["data"]]
    assert f"{slug}/m1" not in names and f"orga-{RUN}/m1" in names             # only this org's model
    info = httpx.get(f"{litellm}/team/info", params={"team_id": team}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True

    # Nobody can reach it any more: lead, member, invitee, or the admin's own org page.
    assert not_invited(lead) and not_invited(member)
    for token, path in ((W["lead_b_token"], f"/orgs/{org}"), (W["lead_b_token"], f"/teams/{team}/manage")):
        assert broker("GET", path, token).status_code == 403
    assert member.api_get(f"/teams/{team}").status_code == 403
    assert invite_is_dead(pending_token)
    assert alice.api_get(f"/orgs/{org}").status_code == 403
    for path, body in ((f"/admin/orgs/{org}/resume", None), (f"/admin/orgs/{org}/ceiling", {"budget_ceiling": 1}),
                       (f"/admin/orgs/{org}/leads", {"email": email("x")}), (f"/admin/orgs/{org}/remove", {"confirm_slug": slug})):
        assert alice.api_post(path, body).status_code == 404, path

    # Records are kept, and the short name is not handed out again.
    assert one("SELECT status FROM org WHERE id = %s", (org,))["status"] == "removed"
    assert one("SELECT count(*) AS n FROM consent WHERE org_id = %s AND team_id = %s", (org, team))["n"] == 1
    assert one("SELECT count(*) AS n FROM audit_event WHERE org_id = %s AND action = 'org.remove'", (org,))["n"] == 1
    assert "taken" in said(alice.api_post("/admin/orgs", {"name": "Again", "slug": slug, "budget_ceiling": 1}))
    # Org A is untouched.
    assert broker("GET", f"/orgs/{W['org_a']}", W["lead_a_token"]).status_code == 200


def test_audit_log_records_who_did_what():
    page = W["alice"].api_get("/admin/audit")
    assert page.status_code == 200
    events = page.json()["events"]
    for action in ("org.create", "org.appoint_lead", "model.add", "team.create", "team.invite", "invite.accept",
                   "my.consent", "my.key.create", "team.remove_member", "team.archive", "org.suspend", "org.remove_lead", "team.cancel_invite", "my.key.rotate", "team.revoke_key", "team.rotate_key", "org.remove", "team.remove"):
        assert action in {e["action"] for e in events}, action
    assert "denied" in {e["result"] for e in events} and PROVIDER_KEY_A not in page.text
    assert set(events[0]) == {"at", "actor_email", "actor_role", "action", "result", "org_name", "team_name"}


def test_sign_out_ends_the_session():
    p1 = W["p1"]
    assert p1.api_get(f"/teams/{W['team_a']}").status_code == 200
    p1.post("/logout")
    assert p1.api_get("/session").json() == {"signed_in": False}   # so the application shows "Sign in" again
    assert p1.api_get(f"/teams/{W['team_a']}").status_code == 401
