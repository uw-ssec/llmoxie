"""Security fixes: each test sets up what it needs in an org of its own, so they run in any order."""

import uuid

import pytest

from .helpers import access_token, broker, create_user, invite_token, sign_in, sql

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
