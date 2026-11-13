"""A connected service (think JupyterHub) enrolling its signed-in users and fetching their keys.

The service is a Keycloak client. For every call it presents the user's own access token, which it got
when that user signed in through it, and its own client-credentials token.
"""

import os
import re
import uuid

import httpx

from .helpers import (SERVICE_REDIRECT, Browser, access_token, api, broker, chat, create_service_client, create_user,
                      invite_token, service_token, sign_in, sql)

RUN = uuid.uuid4().hex[:6]
PASSWORD = "Correct-horse-9"
HUB, HUB_SECRET = f"hub-{RUN}", f"hub-secret-{RUN}"            # may add members
LAB, LAB_SECRET = f"lab-{RUN}", f"lab-secret-{RUN}"            # may only fetch keys for existing members
W: dict = {}


def email(name: str) -> str:
    return f"{name}-{RUN}@example.com"


def one(query: str, params=()):
    return sql("SUPERUSER_DATABASE_URL", query, params)[0]


def flash(response) -> str:
    found = re.search(r'class="flash \w+" role="status">([^<]+)<', response.text)
    return found.group(1) if found else ""


def user_token(name: str, client: str = HUB, secret: str = HUB_SECRET) -> str:
    return access_token(email(name), PASSWORD, client, secret, SERVICE_REDIRECT)


def make_team(alice: Browser, letter: str) -> None:
    """An org with a lead, one mock model, and a team that allows it. One key per person."""
    slug = f"int{letter}-{RUN}"
    alice.page("/admin")
    alice.post("/admin/orgs", {"name": f"Integration {letter.upper()} {RUN}", "slug": slug, "budget_ceiling": "100"})
    org = str(one("SELECT id FROM org WHERE slug = %s", (slug,))["id"])
    create_user(email(f"lead-{letter}"), PASSWORD)
    alice.post(f"/admin/orgs/{org}/leads", {"email": email(f"lead-{letter}")})
    lead = sign_in(email(f"lead-{letter}"), PASSWORD, start=(f"/invite/{invite_token(email(f'lead-{letter}'))}", {}))
    lead.post(f"/orgs/{org}/models", {"provider": "mock", "model": "m1", "api_key": "sk-provider"})
    lead.post(f"/orgs/{org}/teams", {"name": "Notebooks", "team_budget": "50", "key_budget": "5", "key_limit": "1",
                                     "key_expiry_days": "7", "consent_text": "You agree that leads see your usage totals."})
    team = str(one("SELECT id FROM team WHERE org_id = %s", (org,))["id"])
    model = one("SELECT id FROM org_model WHERE org_id = %s", (org,))["id"]
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/models", {"model_ids": model})
    W.update({f"org_{letter}": org, f"team_{letter}": team, f"lead_{letter}": lead, f"slug_{letter}": slug})


def test_admin_connects_services_and_leads_cannot():
    W["alice"] = alice = sign_in("alice", "alice123")
    make_team(alice, "a")
    make_team(alice, "b")
    create_service_client(HUB, HUB_SECRET)
    create_service_client(LAB, LAB_SECRET)
    team_a, team_b, lead = W["team_a"], W["team_b"], W["lead_a"]

    lead.page(f"/teams/{team_a}/manage")
    assert lead.post(f"/admin/teams/{team_a}/integrations", {"client_id": HUB, "name": "JupyterHub"}).status_code == 403
    assert ">Connect service</button>" not in lead.page(f"/teams/{team_a}/manage").text

    alice.page(f"/teams/{team_a}/manage")
    connected = alice.post(f"/admin/teams/{team_a}/integrations", {"client_id": HUB, "name": "JupyterHub", "can_enroll": "yes"})
    assert "Connected JupyterHub" in flash(connected) and HUB in connected.text
    alice.page(f"/teams/{team_b}/manage")
    assert "Connected Lab" in flash(alice.post(f"/admin/teams/{team_b}/integrations", {"client_id": LAB, "name": "Lab"}))
    # One client, one team; and the console's own client cannot be made an integration.
    assert "already connected" in flash(alice.post(f"/admin/teams/{team_b}/integrations", {"client_id": HUB, "name": "Again"}))
    assert "console itself" in flash(alice.post(f"/admin/teams/{team_b}/integrations", {"client_id": "console", "name": "Self"}))
    assert "JupyterHub" in lead.page(f"/teams/{team_a}/manage").text      # the lead can see what is connected
    W["hub"], W["lab"] = service_token(HUB, HUB_SECRET), service_token(LAB, LAB_SECRET)


def test_calls_need_both_tokens_from_one_registered_service():
    create_user(email("u1"), PASSWORD)
    W["u1"] = u1 = user_token("u1")
    hub, lab = W["hub"], W["lab"]
    console_user = access_token(email("u1"), PASSWORD)              # the same person, signed in to the console instead
    stranger_client, stranger_secret = f"other-{RUN}", f"other-secret-{RUN}"
    create_service_client(stranger_client, stranger_secret)         # a real Keycloak client nobody connected
    cases = {
        "no tokens": (None, None, 401), "user token only": (u1, None, 401), "service token only": (None, hub, 401),
        "another service's token": (u1, lab, 401), "service token used as the user": (hub, hub, 401),
        "user token used as the service": (u1, u1, 401), "a console sign-in": (console_user, hub, 401),
        "tampered user token": (u1[:-6] + "AAAAAA", hub, 401),
        "unconnected service": (user_token("u1", stranger_client, stranger_secret),
                                service_token(stranger_client, stranger_secret), 403),
    }
    for operation in ("enroll", "key", "key/revoke"):
        for name, (user, service, status) in cases.items():
            assert api(operation, user, service).status_code == status, (operation, name)
    # A browser cannot be made to call it from another site, and the broker itself is not asking for less.
    assert api("enroll", u1, hub, headers={"Origin": "http://evil.example"}).status_code == 403
    assert broker("POST", "/integration/enroll", u1).status_code == 401
    assert one("SELECT count(*) AS n FROM team_member WHERE team_id = %s", (W["team_a"],))["n"] == 0


def test_service_enrolls_a_user_but_no_key_before_consent():
    u1, hub, team = W["u1"], W["hub"], W["team_a"]
    assert api("key", u1, hub).json()["error"] == "not_member"

    enrolled = api("enroll", u1, hub)
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json() == {"member": True, "newly_enrolled": True, "terms_accepted": False,
                               "consent_url": f"{os.environ['CONSOLE_URL']}/teams/{team}",
                               "team": {"id": team, "name": "Notebooks"}}
    assert api("enroll", u1, hub).json()["newly_enrolled"] is False   # asking again changes nothing

    refused = api("key", u1, hub)
    assert refused.status_code == 409 and refused.json()["error"] == "consent_required"
    assert refused.json()["consent_url"] == enrolled.json()["consent_url"]
    assert one("SELECT count(*) AS n FROM api_key WHERE team_id = %s", (team,))["n"] == 0

    # The user follows the link and accepts in the console themselves.
    consent_path = f"/teams/{team}"
    signed_out = Browser().get(consent_path)
    assert "Sign in" in signed_out.text and f'name="next" value="{consent_path}"' in signed_out.text
    W["u1_browser"] = browser = sign_in(email("u1"), PASSWORD, start=("/login", {"next": consent_path}))
    assert browser.landed_path == consent_path and "You agree that leads see your usage totals." in browser.landed.text
    for elsewhere in ("//evil.example/x", "https://evil.example", "/\\evil.example", "javascript:alert(1)"):
        assert sign_in(email("u1"), PASSWORD, start=("/login", {"next": elsewhere})).landed_path == "/"
    browser.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes"})
    assert api("enroll", u1, hub).json()["terms_accepted"] is True


def test_service_gets_a_working_key_and_a_new_one_each_session():
    u1, hub, team, slug = W["u1"], W["hub"], W["team_a"], W["slug_a"]
    litellm, master = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}

    first = api("key", u1, hub)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["name"] == "JupyterHub" and body["replaced_previous"] is False and body["models"] == [f"{slug}/m1"]
    assert body["base_url"] == f"{os.environ['GATEWAY_URL']}/v1" and body["expires_in_days"] == 7
    # Exactly what the service would inject: base URL, key and model name are enough to make a call.
    call = httpx.post(f"{body['base_url']}/chat/completions", headers={"Authorization": f"Bearer {body['key']}"},
                      json={"model": body["models"][0], "messages": [{"role": "user", "content": "hi"}]})
    assert call.status_code == 200

    httpx.post(f"{litellm}/key/update", headers=master, json={"key": body["key"], "spend": 2.5}).raise_for_status()
    second = api("key", u1, hub).json()                                  # the next session
    assert second["replaced_previous"] is True and second["key"] != body["key"]
    assert chat(body["key"], f"{slug}/m1").status_code == 401 and chat(second["key"], f"{slug}/m1").status_code == 200
    info = httpx.get(f"{litellm}/key/info", params={"key": second["key"]}, headers=master).json()["info"]
    assert info["spend"] == 2.5                                          # same budget, not a fresh one
    live = sql("SUPERUSER_DATABASE_URL", "SELECT name FROM api_key WHERE team_id = %s AND status <> 'deleted'", (team,))
    assert [k["name"] for k in live] == ["JupyterHub"]                   # the team allows one key each; still one

    # The user and the lead see it in the console like any other key, never the secret.
    assert "JupyterHub" in W["u1_browser"].page(f"/teams/{team}").text
    page = W["lead_a"].page(f"/teams/{team}/manage")
    assert "JupyterHub" in page.text and second["key"] not in page.text
    W["u1_key"] = second["key"]


def test_the_teams_key_limit_still_applies():
    team, hub = W["team_a"], W["hub"]
    create_user(email("u2"), PASSWORD)
    u2 = user_token("u2")
    api("enroll", u2, hub)
    browser = sign_in(email("u2"), PASSWORD)
    browser.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes"})
    browser.post(f"/teams/{team}/my/keys", {"name": "my own"})          # uses the one slot this team allows
    refused = api("key", u2, hub)
    assert refused.status_code == 409 and refused.json()["error"] == "key_limit"


def test_service_revokes_the_key_when_the_session_ends():
    u1, hub, slug = W["u1"], W["hub"], W["slug_a"]
    assert api("key/revoke", u1, hub).json() == {"revoked": True}
    assert chat(W["u1_key"], f"{slug}/m1").status_code == 401
    assert api("key/revoke", u1, hub).json() == {"revoked": False}
    W["u1_key"] = api("key", u1, hub).json()["key"]                       # and can fetch one again later
    assert chat(W["u1_key"], f"{slug}/m1").status_code == 200


def test_a_service_only_ever_touches_its_own_team():
    lab, team_b, lead_b = W["lab"], W["team_b"], W["lead_b"]
    create_user(email("u3"), PASSWORD)
    u3 = user_token("u3", LAB, LAB_SECRET)
    # Lab may not add members: the lead has to invite them.
    refused = api("enroll", u3, lab)
    assert refused.status_code == 403 and refused.json()["error"] == "not_allowed"
    assert api("key", u3, lab).json()["error"] == "not_member"
    lead_b.page(f"/teams/{team_b}/manage")
    lead_b.post(f"/teams/{team_b}/invites", {"emails": email("u3")})
    member = sign_in(email("u3"), PASSWORD, start=(f"/invite/{invite_token(email('u3'))}", {}))
    member.post(f"/teams/{team_b}/my/consent", {"terms_accepted": "yes"})
    issued = api("key", u3, lab).json()
    assert issued["team"]["id"] == team_b and issued["models"] == [f"{W['slug_b']}/m1"]
    assert chat(issued["key"], f"{W['slug_a']}/m1").status_code in (401, 403)   # not the other org's model
    # u1 belongs to the hub's team. Signing in to Lab gives Lab nothing of theirs.
    u1_at_lab = access_token(email("u1"), PASSWORD, LAB, LAB_SECRET, SERVICE_REDIRECT)
    assert api("key", u1_at_lab, lab).json()["error"] == "not_member"
    assert chat(W["u1_key"], f"{W['slug_a']}/m1").status_code == 200


def test_a_removed_member_is_not_brought_back_by_the_service():
    u1, hub, team, lead = W["u1"], W["hub"], W["team_a"], W["lead_a"]
    person = one("SELECT id FROM person WHERE email = %s", (email("u1"),))["id"]
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/members/{person}/remove")
    assert chat(W["u1_key"], f"{W['slug_a']}/m1").status_code == 401
    assert api("enroll", u1, hub).json()["error"] == "removed"
    assert api("key", u1, hub).json()["error"] == "not_member"


def test_everything_is_audited_under_the_services_name():
    events = sql("SUPERUSER_DATABASE_URL",
                 "SELECT action, result FROM audit_event WHERE actor_role = %s ORDER BY id", (f"integration:{HUB}",))
    actions = [(e["action"], e["result"]) for e in events]
    for expected in (("integration.enroll", "ok"), ("integration.issue_key", "ok"), ("integration.revoke_key", "ok")):
        assert expected in actions, expected
    assert ("integration.enroll", "denied") in [
        (e["action"], e["result"]) for e in sql(
            "SUPERUSER_DATABASE_URL", "SELECT action, result FROM audit_event WHERE actor_role = %s", (f"integration:{LAB}",))]
    page = W["alice"].get("/admin/audit")
    assert f"integration:{HUB}" in page.text and "integration.register" in page.text


def test_closing_the_team_or_disconnecting_the_service_shuts_it_out():
    alice, hub, lab, team_a, team_b = W["alice"], W["hub"], W["lab"], W["team_a"], W["team_b"]
    create_user(email("u4"), PASSWORD)
    u4 = user_token("u4")
    api("enroll", u4, hub)
    browser = sign_in(email("u4"), PASSWORD)
    browser.post(f"/teams/{team_a}/my/consent", {"terms_accepted": "yes"})
    key = api("key", u4, hub).json()["key"]

    # Disconnecting deletes the keys the service issued and refuses it from then on.
    integration = one("SELECT id FROM integration WHERE client_id = %s", (HUB,))["id"]
    alice.page(f"/teams/{team_a}/manage")
    assert "Integration disconnected. 1 key(s) deleted" in flash(alice.post(f"/admin/integrations/{integration}/remove"))
    assert chat(key, f"{W['slug_a']}/m1").status_code == 401
    for operation in ("enroll", "key", "key/revoke"):
        assert api(operation, u4, hub).status_code == 403
    assert W["lead_a"].post(f"/admin/integrations/{integration}/remove").status_code in (403, 404)

    # An archived team answers "closed" to its service.
    u3 = user_token("u3", LAB, LAB_SECRET)
    W["lead_b"].page(f"/teams/{team_b}/manage")
    W["lead_b"].post(f"/teams/{team_b}/archive")
    closed = api("key", u3, lab)
    assert closed.status_code == 409 and closed.json()["error"] == "team_closed"
