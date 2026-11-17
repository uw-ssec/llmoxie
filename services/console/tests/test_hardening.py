"""Security fixes: each test sets up what it needs in an org of its own, so they run in any order."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest

from .helpers import (SERVICE_REDIRECT, access_token, api, broker, chat, create_service_client, create_user,
                      invite_token, service_token, sign_in, sql)

RUN = uuid.uuid4().hex[:6]
PASSWORD = "Correct-horse-9"


def email(name: str) -> str:
    return f"{name}-{RUN}@example.com"


def one(query: str, params=()):
    return sql("SUPERUSER_DATABASE_URL", query, params)[0]


def said(response) -> str:
    body = response.json()
    return body.get("message") or body.get("error", {}).get("message", "")


@pytest.fixture(scope="module")
def org() -> dict:
    """An org with a lead, one mock model, and a team that allows it."""
    alice = sign_in("alice", "alice123")
    slug = f"hard-{RUN}"
    alice.api_post("/admin/orgs", {"name": f"Hardening {RUN}", "slug": slug, "budget_ceiling": 100})
    org_id = str(one("SELECT id FROM org WHERE slug = %s", (slug,))["id"])
    create_user(email("lead"), PASSWORD)
    alice.api_post(f"/admin/orgs/{org_id}/leads", {"email": email("lead")})
    lead = sign_in(email("lead"), PASSWORD, start=(f"/invite/{invite_token(email('lead'))}", {}))
    lead.api_post(f"/orgs/{org_id}/models", {"provider": "mock", "model": "m1", "api_key": "sk-provider"})
    lead.api_post(f"/orgs/{org_id}/teams", {"name": "Hardening", "team_budget": 50, "key_budget": 5, "key_limit": 3,
                                            "key_expiry_days": 7, "consent_text": "You agree that leads see your usage."})
    team = str(one("SELECT id FROM team WHERE org_id = %s", (org_id,))["id"])
    model = str(one("SELECT id FROM org_model WHERE org_id = %s", (org_id,))["id"])
    lead.api_post(f"/teams/{team}/models", {"model_ids": [model]})
    return {"alice": alice, "lead": lead, "org": org_id, "team": team, "model": f"{slug}/m1"}


def person_id(who: str) -> str:
    return str(one("SELECT id FROM person WHERE email = %s", (who,))["id"])


def join(org: dict, name: str):
    """A new participant who accepted an invitation to the org's team."""
    who = email(name)
    create_user(who, PASSWORD)
    org["lead"].api_post(f"/teams/{org['team']}/invites", data={"emails": who})
    member = sign_in(who, PASSWORD, start=(f"/invite/{invite_token(who)}", {}))
    assert member.landed_path == f"/teams/{org['team']}"
    return member, who


# ── 1. Removal revokes outstanding invitations ──────────────────────────────

def test_a_removed_lead_cannot_return_through_a_second_invitation(org):
    alice, org_id, who = org["alice"], org["org"], email("lead-twice")
    create_user(who, PASSWORD)
    alice.api_post(f"/admin/orgs/{org_id}/leads", {"email": who})
    sign_in(who, PASSWORD, start=(f"/invite/{invite_token(who)}", {}))
    alice.api_post(f"/admin/orgs/{org_id}/leads", {"email": who})  # a second invitation, still pending
    second = invite_token(who)
    person = person_id(who)
    assert broker("GET", f"/orgs/{org_id}", access_token(who, PASSWORD)).status_code == 200

    assert "Lead removed" in said(alice.api_post(f"/admin/orgs/{org_id}/leads/{person}/remove"))
    assert one("SELECT count(*) AS n FROM invite WHERE org_id = %s AND email = %s AND status = 'pending'",
               (org_id, who))["n"] == 0
    again = sign_in(who, PASSWORD, start=(f"/invite/{second}", {}))
    assert again.landed_path == "/invite-result/invalid"
    assert broker("GET", f"/orgs/{org_id}", access_token(who, PASSWORD)).status_code == 403
    assert one("SELECT count(*) AS n FROM org_lead WHERE org_id = %s AND person_id = %s", (org_id, person))["n"] == 0


def test_a_removed_participant_cannot_return_through_an_outstanding_invitation(org):
    lead, team = org["lead"], org["team"]
    _, who = join(org, "p-twice")
    person = person_id(who)
    lead.api_post(f"/teams/{team}/invites", data={"emails": who})  # a second invitation, still pending
    second = invite_token(who)
    # And a link meant for someone else that this person used: it waits for the lead's approval.
    other = email("p-other")
    lead.api_post(f"/teams/{team}/invites", data={"emails": other})
    waiting = sign_in(who, PASSWORD, start=(f"/invite/{invite_token(other)}", {}))
    assert waiting.landed_path == "/invite-result/waiting"
    request = one("SELECT id FROM invite WHERE team_id = %s AND email = %s", (team, other))["id"]

    assert "Removed" in said(lead.api_post(f"/teams/{team}/members/{person}/remove"))
    again = sign_in(who, PASSWORD, start=(f"/invite/{second}", {}))
    assert again.landed_path == "/invite-result/invalid"
    assert again.api_get(f"/teams/{team}").status_code == 403
    assert lead.api_post(f"/teams/{team}/requests/{request}", {"approve": True}).status_code == 404
    assert one("SELECT status FROM team_member WHERE team_id = %s AND person_id = %s", (team, person))["status"] == "removed"


# ── 2. A provider key is a value, never a reference to a secret LiteLLM holds ─

def test_a_provider_key_cannot_name_a_secret_litellm_holds(org):
    token, org_id = access_token(email("lead"), PASSWORD), org["org"]
    azure = {"provider": "azure", "api_base": "https://x.openai.azure.com", "api_version": "2024-12-01-preview"}
    for body in ({"provider": "mock", "model": "ref1", "api_key": "os.environ/GENERIC_USER_ID_ATTRIBUTE"},
                 {"provider": "mock", "model": "ref2", "api_key": "  OS.Environ/LITELLM_MASTER_KEY"},
                 {"provider": "openai", "model": "ref3", "api_key": "oidc/env/LITELLM_MASTER_KEY"},
                 {**azure, "model": "ref4", "api_key": "os.environ/AZURE_API_KEY"}):
        refused = broker("POST", f"/orgs/{org_id}/models", token, body)
        assert refused.status_code == 400, (body, refused.status_code)
        assert "reference" in refused.json()["detail"]
    shown = org["lead"].api_post(f"/orgs/{org_id}/models", {"provider": "mock", "model": "ref5", "api_key": "os.environ/X"})
    assert shown.status_code == 400 and "reference" in said(shown)   # the lead is told why
    assert one("SELECT count(*) AS n FROM org_model WHERE org_id = %s AND model LIKE 'ref%%'", (org_id,))["n"] == 0


# ── Races: a test holds a row lock so two calls overlap in a known order ─────

def lock_waiters() -> int:
    """How many of the broker's queries are waiting for a lock right now."""
    return one("""SELECT count(*) AS n FROM pg_stat_activity
                  WHERE datname = 'console_db' AND usename = 'console_broker' AND wait_event_type = 'Lock'""")["n"]


def wait_until(condition, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def held(query: str, params=()):
    """A transaction holding the row locks `query` takes; rolled back to let them go."""
    conn = psycopg.connect(os.environ["SUPERUSER_DATABASE_URL"])
    assert conn.execute(query, params).fetchall(), "nothing to lock"
    return conn


# ── 3. Disconnecting an integration wins against a key it is issuing ─────────

def test_disconnecting_an_integration_stops_a_key_it_is_issuing(org):
    client, secret = f"race-{RUN}", f"race-secret-{RUN}"
    create_service_client(client, secret)
    connected = org["alice"].api_post(f"/admin/teams/{org['team']}/integrations",
                                      {"client_id": client, "name": "Race", "can_enroll": True})
    assert connected.status_code == 200, connected.text[:300]
    integration = str(one("SELECT id FROM integration WHERE client_id = %s AND removed_at IS NULL", (client,))["id"])
    who = email("svc-user")
    create_user(who, PASSWORD)
    user, service = access_token(who, PASSWORD, client, secret, SERVICE_REDIRECT), service_token(client, secret)
    assert api("enroll", user, service).status_code == 200
    sign_in(who, PASSWORD).api_post(f"/teams/{org['team']}/my/consent", {"terms_accepted": True})

    # The key request stops at the user's membership row, after the service's tokens were checked.
    lock = held("SELECT 1 FROM team_member WHERE team_id = %s AND person_id = %s FOR UPDATE",
                (org["team"], person_id(who)))
    with ThreadPoolExecutor(2) as pool:
        try:
            issuing = pool.submit(api, "key", user, service)
            wait_until(lambda: lock_waiters() == 1)
            removing = pool.submit(org["alice"].api_post, f"/admin/integrations/{integration}/remove")
            wait_until(lambda: removing.done() or lock_waiters() == 2)
        finally:
            lock.rollback()
            lock.close()
        issued, removed = issuing.result(), removing.result()
    assert removed.status_code == 200, removed.text[:300]
    if issued.status_code == 200:  # issued before the disconnection went through: it must be dead now
        assert chat(issued.json()["key"], org["model"]).status_code == 401
    else:
        assert issued.status_code == 403, issued.text[:300]
    assert one("SELECT count(*) AS n FROM api_key WHERE integration_id = %s AND status <> 'deleted'",
               (integration,))["n"] == 0

    # Connected again, then disconnected while a key request waits at the integration's row: it is refused.
    org["alice"].api_post(f"/admin/teams/{org['team']}/integrations", {"client_id": client, "name": "Race"})
    again = str(one("SELECT id FROM integration WHERE client_id = %s AND removed_at IS NULL", (client,))["id"])
    lock = held("SELECT 1 FROM integration WHERE id = %s FOR UPDATE", (again,))
    with ThreadPoolExecutor(1) as pool:
        try:
            issuing = pool.submit(api, "key", user, service)
            wait_until(lambda: lock_waiters() == 1)
            lock.execute("UPDATE integration SET removed_at = now() WHERE id = %s", (again,))
            lock.commit()
        finally:
            lock.close()
        assert issuing.result().status_code == 403
    assert one("SELECT count(*) AS n FROM api_key WHERE integration_id = %s", (again,))["n"] == 0


# ── 4. Withdrawing consent wins against a key being made ────────────────────

def test_withdrawing_consent_stops_a_key_being_made(org):
    team = org["team"]
    member, who = join(org, "p-withdraw")
    member.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})
    first = member.api_post(f"/teams/{team}/my/keys", {"name": "first"})
    assert first.status_code == 200, first.text[:300]
    token, person = access_token(who, PASSWORD), person_id(who)
    first_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (person,))["id"]

    # The withdrawal stops while deleting the existing key, so a new key request overlaps it.
    lock = held("SELECT 1 FROM api_key WHERE id = %s FOR UPDATE", (first_id,))
    with ThreadPoolExecutor(2) as pool:
        try:
            withdrawing = pool.submit(member.api_post, f"/teams/{team}/my/consent", {"terms_accepted": False})
            wait_until(lambda: lock_waiters() == 1)
            making = pool.submit(broker, "POST", f"/my/teams/{team}/keys", token, {"name": "racing"})
            wait_until(lambda: making.done() or lock_waiters() == 2)
        finally:
            lock.rollback()
            lock.close()
        withdrawn, made = withdrawing.result(), making.result()
    assert withdrawn.status_code == 200, withdrawn.text[:300]
    if made.status_code == 200:  # made before the withdrawal went through: it must be dead now
        assert chat(made.json()["key"], org["model"]).status_code == 401
    else:
        assert made.status_code == 409, made.text[:300]
    assert one("SELECT count(*) AS n FROM api_key WHERE person_id = %s AND status <> 'deleted'", (person,))["n"] == 0


# ── 7. The broker holds one LiteLLM admin key ───────────────────────────────

def test_the_broker_holds_exactly_one_litellm_admin_key():
    """console-init deletes the broker's earlier keys whenever it makes a new one."""
    listing = httpx.get(f"{os.environ['LITELLM_URL']}/key/list",
                        params={"user_id": "console-broker", "return_full_object": "true", "size": 100},
                        headers={"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}).json()
    assert len(listing["keys"]) == 1, [k["key_alias"] for k in listing["keys"]]
