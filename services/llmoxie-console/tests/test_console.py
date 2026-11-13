"""The console from first sign-in to archiving, then every way of stepping outside one's own org.

The tests run in order and share what earlier ones created (W). Run with `-x`.
"""

import html
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from azure.storage.blob import ContainerClient

from .helpers import (CALLER_SECRET, CONSOLE, Browser, access_token, broker, chat, create_user, invite_token,
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


def flash(response) -> str:
    found = re.search(r'class="flash \w+" role="status">([^<]+)<', response.text)
    return found.group(1) if found else ""


# ── Sign-in and roles ───────────────────────────────────────────────────────

def test_login_page_has_one_button():
    response = Browser().get("/")
    assert response.status_code == 200
    assert response.text.count("<button") == 1 and "Sign in" in response.text
    assert response.headers["cache-control"] == "no-store" and response.headers["referrer-policy"] == "same-origin"


def test_admin_signs_in_and_session_cookie_is_locked_down():
    W["alice"] = sign_in("alice", "alice123")
    assert "SSEC admin" in W["alice"].landed.text
    cookie = next(h for h in W["alice"].set_cookie_headers if h.startswith("__Host-Http-console="))
    lowered = cookie.lower()
    assert "secure" in lowered and "httponly" in lowered and "samesite=strict" in lowered and "path=/" in lowered
    assert "domain=" not in lowered


def test_signed_in_without_membership_is_not_invited():
    create_user(email("stranger"), PASSWORD)
    browser = sign_in(email("stranger"), PASSWORD)
    assert "You are not invited yet" in browser.landed.text
    assert browser.get("/admin").status_code == 403


def test_admin_creates_two_orgs_and_invites_their_leads():
    alice = W["alice"]
    alice.page("/admin")
    for letter in ("a", "b"):
        created = alice.post("/admin/orgs", {"name": f"Org {letter.upper()} {RUN}", "slug": f"org{letter}-{RUN}",
                                             "budget_ceiling": "100"})
        assert created.status_code == 200, created.text[:300]
        W[f"org_{letter}"] = str(one("SELECT id FROM org WHERE slug = %s", (f"org{letter}-{RUN}",))["id"])
        create_user(email(f"lead-{letter}"), PASSWORD)
        invited = alice.post(f"/admin/orgs/{W[f'org_{letter}']}/leads", {"email": email(f"lead-{letter}")})
        assert "Invitation sent" in flash(invited)


def test_opening_an_invite_link_does_not_use_it():
    token = invite_token(email("lead-a"))
    for _ in range(3):  # an email scanner fetching the link
        page = Browser().get(f"/invite/{token}")
        assert page.status_code == 200 and "Accept and sign in" in page.text
        assert page.headers["cache-control"] == "no-store" and page.headers["referrer-policy"] == "same-origin"
    assert one("SELECT status FROM invite WHERE org_id = %s", (W["org_a"],))["status"] == "pending"


def test_leads_accept_their_invites():
    for letter in ("a", "b"):
        token = invite_token(email(f"lead-{letter}"))
        browser = sign_in(email(f"lead-{letter}"), PASSWORD, start=(f"/invite/{token}", {}))
        assert browser.landed_path == f"/orgs/{W[f'org_{letter}']}"
        assert "New team" in browser.landed.text
        W[f"lead_{letter}"] = browser
        W[f"lead_{letter}_token"] = access_token(email(f"lead-{letter}"), PASSWORD)
    assert Browser().get(f"/invite/{invite_token(email('lead-a'))}").text.count("cannot be used") == 1  # used up


# ── The lead's workshop ─────────────────────────────────────────────────────

def test_lead_adds_models_and_the_key_is_write_only():
    for letter, key in (("a", PROVIDER_KEY_A), ("b", PROVIDER_KEY_B)):
        lead, org = W[f"lead_{letter}"], W[f"org_{letter}"]
        added = lead.post(f"/orgs/{org}/models", {"provider": "mock", "model": "m1", "api_key": key})
        assert f"Added org{letter}-{RUN}/m1" in flash(added), added.text[:400]
        assert key not in lead.page(f"/orgs/{org}").text
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
        lead.page(f"/orgs/{org}")
        form = {"name": f"Workshop {letter.upper()}", "team_budget": "500", "key_budget": "5", "key_limit": "2",
                "key_expiry_days": "30", "consent_text": CONSENT}
        assert "ceiling" in flash(lead.post(f"/orgs/{org}/teams", form))  # 500 is over the org's 100
        created = lead.post(f"/orgs/{org}/teams", {**form, "team_budget": "50"})
        assert "Created Workshop" in flash(created), created.text[:400]
        W[f"team_{letter}"] = str(one("SELECT id FROM team WHERE org_id = %s", (org,))["id"])


def test_lead_allows_a_model_and_sets_the_budget():
    lead, team = W["lead_a"], W["team_a"]
    lead.page(f"/teams/{team}/manage")
    assert "Models updated" in flash(lead.post(f"/teams/{team}/models", {"model_ids": W["model_a"]}))
    assert "Team budget updated" in flash(lead.post(f"/teams/{team}/budget", {"team_budget": "60"}))
    assert "ceiling" in flash(lead.post(f"/teams/{team}/budget", {"team_budget": "101"}))
    # Another org's model cannot be attached, whatever id is sent.
    assert broker("POST", f"/teams/{team}/models", W["lead_a_token"],
                  {"model_ids": [W["model_a"], W["model_b"]]}).status_code == 422
    assert broker("POST", f"/teams/{W['team_b']}/models", W["lead_b_token"],
                  {"model_ids": [W["model_b"]]}).status_code == 200


def test_lead_invites_people_by_text_and_csv():
    lead, team = W["lead_a"], W["team_a"]
    for name in ("p1", "p2", "p3"):
        create_user(email(name), PASSWORD)
    lead.page(f"/teams/{team}/manage")
    sent = lead.post(f"/teams/{team}/invites", {"emails": email("p1")},
                     files={"csv_file": ("people.csv", f"name,email\nTwo,{email('p2')}\nThree,{email('p3')}\n")})
    assert "Sent 3 invitation(s)" in flash(sent), sent.text[:400]


def test_lead_cancels_an_invitation_before_it_is_accepted():
    lead, team = W["lead_a"], W["team_a"]
    create_user(email("uninvited"), PASSWORD)
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/invites", {"emails": email("uninvited")})
    token = invite_token(email("uninvited"))
    invite = one("SELECT id FROM invite WHERE team_id = %s AND email = %s", (team, email("uninvited")))["id"]
    assert "Cancel invitation" in lead.page(f"/teams/{team}/manage").text

    assert broker("POST", f"/teams/{team}/invites/{invite}/revoke", W["lead_b_token"]).status_code == 403
    assert "Invitation cancelled" in flash(lead.post(f"/teams/{team}/invites/{invite}/revoke"))
    assert email("uninvited") not in lead.page(f"/teams/{team}/manage").text
    assert "cannot be used" in Browser().get(f"/invite/{token}").text
    late = sign_in(email("uninvited"), PASSWORD, start=(f"/invite/{token}", {}))
    assert "cannot be used" in late.landed.text and late.get(f"/teams/{team}").status_code == 403
    assert lead.post(f"/teams/{team}/invites/{invite}/revoke").status_code == 404   # already cancelled
    # The other invitations sent earlier are untouched.
    assert one("SELECT count(*) AS n FROM invite WHERE team_id = %s AND status = 'pending'", (team,))["n"] == 3


# ── Participants ────────────────────────────────────────────────────────────

def test_participant_registers_consents_and_gets_a_key_shown_once():
    team = W["team_a"]
    p1 = sign_in(email("p1"), PASSWORD, start=(f"/invite/{invite_token(email('p1'))}", {}))
    assert p1.landed_path == f"/teams/{team}" and CONSENT in html.unescape(p1.landed.text)
    assert "API keys" not in p1.landed.text  # nothing about keys before consent

    W["p1_token"] = access_token(email("p1"), PASSWORD)
    assert broker("POST", f"/my/teams/{team}/keys", W["p1_token"], {"name": "early"}).status_code == 409

    agreed = p1.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes"})  # research use left unticked
    assert "Your choices are saved" in flash(agreed) and "API keys" in agreed.text
    consent = one("SELECT terms_accepted, research_use FROM consent WHERE team_id = %s ORDER BY id DESC LIMIT 1", (team,))
    assert consent == {"terms_accepted": True, "research_use": False}

    created = p1.post(f"/teams/{team}/my/keys", {"name": "laptop"})
    key = re.search(r'<code class="key">(sk-[^<]+)</code>', created.text).group(1)
    assert key not in p1.page(f"/teams/{team}").text  # never shown again
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
    assert "you already have 2 keys" in flash(W["p1"].post(f"/teams/{team}/my/keys", {"name": "third"}))


def test_participant_can_delete_and_replace_a_key():
    p1, team = W["p1"], W["team_a"]
    extra = one("SELECT id FROM api_key WHERE team_id = %s AND status = 'active' AND name <> 'laptop'", (team,))["id"]
    assert "Key deleted" in flash(p1.post(f"/teams/{team}/my/keys/{extra}/delete"))
    assert 'Name for a new key' in p1.page(f"/teams/{team}").text


def test_mismatched_email_waits_for_the_lead():
    lead, team = W["lead_a"], W["team_a"]
    create_user(email("other"), PASSWORD)
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/invites", {"emails": email("invited-elsewhere")})
    token = invite_token(email("invited-elsewhere"))

    other = sign_in(email("other"), PASSWORD, start=(f"/invite/{token}", {}))
    assert "Waiting for approval" in other.landed.text
    assert "You are not invited yet" in other.get("/").text and other.get(f"/teams/{team}").status_code == 403
    assert "cannot be used" in Browser().get(f"/invite/{token}").text  # the link is spent either way

    manage = lead.page(f"/teams/{team}/manage")
    assert f"signed in as <strong>{email('other')}</strong>" in manage.text
    request_id = one("SELECT id FROM invite WHERE team_id = %s AND status = 'needs_approval'", (team,))["id"]
    assert "Request approved" in flash(lead.post(f"/teams/{team}/requests/{request_id}", {"decision": "approve"}))
    assert other.get(f"/teams/{team}").status_code == 200


def test_rejected_request_grants_nothing():
    lead, team = W["lead_a"], W["team_a"]
    lead.post(f"/teams/{team}/invites", {"emails": email("invited-again")})
    stranger = sign_in(email("stranger"), PASSWORD, start=(f"/invite/{invite_token(email('invited-again'))}", {}))
    request_id = one("SELECT id FROM invite WHERE team_id = %s AND status = 'needs_approval'", (team,))["id"]
    lead.page(f"/teams/{team}/manage")
    assert "Request rejected" in flash(lead.post(f"/teams/{team}/requests/{request_id}", {"decision": "reject"}))
    assert stranger.get(f"/teams/{team}").status_code == 403


def test_expired_and_reused_invites_fail_safely():
    team = W["team_a"]
    token = invite_token(email("p3"))
    sql("SUPERUSER_DATABASE_URL", "UPDATE invite SET expires_at = now() - interval '1 minute' WHERE team_id = %s AND email = %s",
        (team, email("p3")))
    expired = sign_in(email("p3"), PASSWORD, start=(f"/invite/{token}", {}))
    assert "cannot be used" in expired.landed.text and expired.get(f"/teams/{team}").status_code == 403

    p1_again = sign_in(email("p2"), PASSWORD, start=(f"/invite/{invite_token(email('p1'))}", {}))  # p1's used link
    assert "cannot be used" in p1_again.landed.text and p1_again.get(f"/teams/{team}").status_code == 403
    assert broker("POST", "/invites/accept", W["p1_token"], {"token": "x" * 43}).json()["outcome"] == "invalid"


def test_second_participant_joins():
    team = W["team_a"]
    p2 = sign_in(email("p2"), PASSWORD, start=(f"/invite/{invite_token(email('p2'))}", {}))
    assert p2.landed_path == f"/teams/{team}"
    p2.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes", "research_use": "yes"})
    created = p2.post(f"/teams/{team}/my/keys", {"name": "desk"})
    W["p2_key"] = re.search(r'<code class="key">(sk-[^<]+)</code>', created.text).group(1)
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
    page = W["lead_a"].page(f"/teams/{team}/manage")
    assert "<h2>Keys</h2>" in page.text and "laptop" in page.text and "desk" in page.text
    for text in (view.text, page.text):
        assert W["p1_key"] not in text and W["p2_key"] not in text
        assert W["p1_key"][3:] not in text  # nor the key without its sk- prefix
    assert broker("GET", f"/teams/{team}/manage", W["lead_b_token"]).status_code == 403


def test_participant_rotates_a_key():
    p1, team = W["p1"], W["team_a"]
    old_key = W["p1_key"]
    old_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))["id"]
    p1.page(f"/teams/{team}")
    rotated = p1.post(f"/teams/{team}/my/keys/{old_id}/rotate")
    assert "Your replacement key: laptop" in rotated.text
    new_key = re.search(r'<code class="key">(sk-[^<]+)</code>', rotated.text).group(1)
    assert new_key != old_key and new_key not in p1.page(f"/teams/{team}").text   # shown once
    assert chat(old_key, f"orga-{RUN}/m1").status_code == 401
    assert chat(new_key, f"orga-{RUN}/m1").status_code == 200
    mine = sql("SUPERUSER_DATABASE_URL", "SELECT name, status FROM api_key WHERE person_id = %s ORDER BY created_at",
               (W["p1_person"],))
    assert [k["name"] for k in mine if k["status"] == "active"] == ["laptop"]   # same name, still one slot used
    assert broker("POST", f"/my/teams/{team}/keys/{old_id}/rotate", W["p1_token"]).status_code == 404  # already replaced
    W["p1_key"] = new_key


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
    lead.page(f"/teams/{team}/manage")
    revoked = lead.post(f"/teams/{team}/keys/{key_id}/revoke")
    assert "Key revoked" in flash(revoked) and "desk" not in revoked.text
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 401
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200          # nobody else's key is affected
    assert lead.post(f"/teams/{team}/keys/{key_id}/revoke").status_code == 404
    assert p2.get(f"/teams/{team}").status_code == 200                      # still a member
    p2.page(f"/teams/{team}")
    created = p2.post(f"/teams/{team}/my/keys", {"name": "desk"})
    W["p2_key"] = re.search(r'<code class="key">(sk-[^<]+)</code>', created.text).group(1)
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 200


def test_lead_rotates_a_key_without_ever_seeing_it():
    lead, team, p2 = W["lead_a"], W["team_a"], W["p2"]
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    old_key = W["p2_key"]
    key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p2_person"],))["id"]
    httpx.post(f"{litellm}/key/update", headers=headers, json={"key": old_key, "spend": 1.75}).raise_for_status()
    assert broker("POST", f"/teams/{team}/keys/{key_id}/rotate", W["p1_token"]).status_code == 403  # not a lead

    lead.page(f"/teams/{team}/manage")
    rotated = lead.post(f"/teams/{team}/keys/{key_id}/rotate")
    assert "Key rotated" in flash(rotated) and "rotated, not collected yet" in rotated.text
    assert "sk-" not in re.sub(r"sk-\.\.\.\w+", "", rotated.text)   # no key on the lead's page, only masked hints
    assert chat(old_key, f"orga-{RUN}/m1").status_code == 401            # stopped at once
    assert lead.post(f"/teams/{team}/keys/{key_id}/rotate").status_code == 404   # nothing left to rotate
    notice = httpx.get(f"{os.environ['MAILPIT_URL']}/api/v1/search", params={"query": f'to:{email("p2")} subject:rotated'})
    assert notice.json()["messages"], "the owner was not told"

    # The slot is held for the owner: they cannot make an extra key meanwhile, and they collect the replacement.
    page = p2.page(f"/teams/{team}")
    assert "Get replacement key" in page.text and "rotated by your lead" in page.text
    collected = p2.post(f"/teams/{team}/my/keys/{key_id}/rotate")
    new_key = re.search(r'<code class="key">(sk-[^<]+)</code>', collected.text).group(1)
    assert "Your replacement key: desk" in collected.text and new_key != old_key
    assert chat(new_key, f"orga-{RUN}/m1").status_code == 200
    info = httpx.get(f"{litellm}/key/info", params={"key": new_key}, headers=headers).json()["info"]
    assert info["spend"] == 1.75                                         # the budget was not refilled
    live = sql("SUPERUSER_DATABASE_URL", "SELECT name FROM api_key WHERE person_id = %s AND status <> 'deleted'",
               (W["p2_person"],))
    assert [k["name"] for k in live] == ["desk"]
    W["p2_key"] = new_key


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
    page = W["lead_a"].page(f"/teams/{team}/manage")
    assert email("p1") in page.text and PROMPT_MARKER not in page.text
    assert PROMPT_MARKER not in W["p1"].page(f"/teams/{team}").text


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
        for path in ("/admin", "/admin/audit", f"/orgs/{a_org}", f"/teams/{a_team}/manage"):
            assert browser.get(path).status_code == 403, path
    assert W["lead_b"].get(f"/teams/{a_team}").status_code == 403
    assert W["p1"].get(f"/teams/{b_team}").status_code == 403
    W["p1"].page(f"/teams/{a_team}")
    assert W["p1"].post(f"/teams/{a_team}/archive").status_code == 403
    assert W["p1"].post(f"/admin/orgs/{a_org}/suspend").status_code == 403
    assert W["alice"].get(f"/orgs/{a_org}").status_code == 200  # admins may look
    W["alice"].page(f"/orgs/{a_org}")
    assert W["alice"].post(f"/orgs/{a_org}/teams", {"name": "x"}).status_code in (403, 422)


def test_forms_refuse_cross_site_and_tokenless_posts():
    lead, team = W["lead_a"], W["team_a"]
    lead.page(f"/teams/{team}/manage")
    assert lead.post(f"/teams/{team}/archive", headers={"Origin": "http://evil.example"}).status_code == 403
    assert lead.post(f"/teams/{team}/archive", headers={"Origin": "null"}).status_code == 403
    assert lead.post(f"/teams/{team}/archive", {"csrf": "wrong"}).status_code == 403
    assert one("SELECT status FROM team WHERE id = %s", (team,))["status"] == "active"
    assert Browser().post(f"/teams/{team}/archive", {"csrf": "x"}, follow=False).status_code == 303  # not signed in


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
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/invites", {"emails": email("p-admin")})
    member = sign_in(email("p-admin"), PASSWORD, start=(f"/invite/{invite_token(email('p-admin'))}", {}))
    member.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes"})
    key = re.search(r'<code class="key">(sk-[^<]+)</code>', member.post(f"/teams/{team}/my/keys", {"name": "k"}).text).group(1)
    person = one("SELECT id FROM person WHERE email = %s", (email("p-admin"),))["id"]
    assert chat(key, f"orga-{RUN}/m1").status_code == 200

    # The admin leads no org, yet can open the team from the organization's page.
    assert f'href="/teams/{team}/manage"' in alice.page(f"/orgs/{W['org_a']}").text
    page = alice.page(f"/teams/{team}/manage")
    assert page.status_code == 200 and "viewing this team as an SSEC admin" in page.text and email("p-admin") in page.text
    for lead_only in ("Archive team", "Send invitations", "Save budget", "Save models", "Revoke", "Rotate", "Cancel invitation"):
        assert f">{lead_only}</button>" not in page.text, lead_only   # no such button for the admin
    assert ">Archive team</button>" in lead.page(f"/teams/{team}/manage").text   # the lead still has them
    assert f"/members/{person}/remove" in page.text

    removed = alice.post(f"/teams/{team}/members/{person}/remove")
    assert "Removed. 1 key(s) deleted" in flash(removed)
    assert f"/members/{person}/remove" not in removed.text   # gone from People (past usage stays listed)
    assert one("SELECT status FROM team_member WHERE person_id = %s", (person,))["status"] == "removed"
    assert chat(key, f"orga-{RUN}/m1").status_code == 401
    assert member.get(f"/teams/{team}").status_code == 403
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200       # nobody else is affected
    event = one("SELECT actor_role, result FROM audit_event WHERE action = 'team.remove_member' ORDER BY id DESC LIMIT 1")
    assert event == {"actor_role": "admin", "result": "ok"}

    # Everything else about the team is still the lead's alone.
    key_id = one("SELECT id FROM api_key WHERE person_id = %s AND status = 'active'", (W["p1_person"],))["id"]
    for path, data in ((f"/teams/{team}/archive", {}), (f"/teams/{team}/budget", {"team_budget": "1"}),
                       (f"/teams/{team}/invites", {"emails": "x@example.com"}), (f"/teams/{team}/keys/{key_id}/revoke", {}),
                       (f"/teams/{team}/keys/{key_id}/rotate", {}), (f"/teams/{team}/models", {})):
        assert alice.post(path, data).status_code == 403, path
    assert one("SELECT status FROM team WHERE id = %s", (team,))["status"] == "active"


def test_removing_someone_deletes_their_keys():
    lead, team = W["lead_a"], W["team_a"]
    lead.page(f"/teams/{team}/manage")
    assert "Removed. 1 key(s) deleted" in flash(lead.post(f"/teams/{team}/members/{W['p2_person']}/remove"))
    assert chat(W["p2_key"], f"orga-{RUN}/m1").status_code == 401
    assert W["p2"].get(f"/teams/{team}").status_code == 403
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 200


def test_archiving_stops_every_key_and_freezes_the_team():
    lead, team = W["lead_a"], W["team_a"]
    lead.page(f"/teams/{team}/manage")
    archived = lead.post(f"/teams/{team}/archive")
    assert "Team archived" in flash(archived) and "This team is archived" in archived.text
    assert chat(W["p1_key"], f"orga-{RUN}/m1").status_code == 401
    assert broker("POST", f"/my/teams/{team}/keys", W["p1_token"], {"name": "after"}).status_code == 409
    for method, path, body in lead_operations(W["org_a"], team, W["model_a"], W["p1_person"], str(uuid.uuid4()), str(uuid.uuid4())):
        if "/teams/" in path and method == "POST":
            assert broker(method, path, W["lead_a_token"], body).status_code in (404, 409), path
    assert "This team is closed" in W["p1"].page(f"/teams/{team}").text
    headers = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    info = httpx.get(f"{os.environ['LITELLM_URL']}/team/info", params={"team_id": team}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True
    assert info["team_info"]["models"] == ["no-default-models"]
    # The org's model and provider key stay: other teams may use them.
    assert one("SELECT removed_at FROM org_model WHERE id = %s", (W["model_a"],))["removed_at"] is None


def test_suspended_org_cannot_be_run_until_resumed():
    alice, org, team = W["alice"], W["org_b"], W["team_b"]
    alice.page(f"/orgs/{org}")
    assert "Organization suspended" in flash(alice.post(f"/admin/orgs/{org}/suspend"))
    assert broker("POST", f"/teams/{team}/budget", W["lead_b_token"], {"team_budget": 10}).status_code == 409
    assert broker("GET", f"/orgs/{org}", W["lead_b_token"]).status_code == 200  # still readable
    assert "Organization resumed" in flash(alice.post(f"/admin/orgs/{org}/resume"))
    assert broker("POST", f"/teams/{team}/budget", W["lead_b_token"], {"team_budget": 10}).status_code == 200
    assert "lower that first" in flash(alice.post(f"/admin/orgs/{org}/ceiling", {"budget_ceiling": "5"}))


def test_admin_removes_a_lead_and_cancels_an_invitation():
    alice, org = W["alice"], W["org_b"]
    create_user(email("lead-temp"), PASSWORD)
    alice.page(f"/orgs/{org}")
    alice.post(f"/admin/orgs/{org}/leads", {"email": email("lead-temp")})
    temp = sign_in(email("lead-temp"), PASSWORD, start=(f"/invite/{invite_token(email('lead-temp'))}", {}))
    temp_token = access_token(email("lead-temp"), PASSWORD)
    assert temp.get(f"/orgs/{org}").status_code == 200 and broker("GET", f"/orgs/{org}", temp_token).status_code == 200

    page = alice.page(f"/orgs/{org}")
    assert email("lead-temp") in page.text and email("lead-b") in page.text
    person = one("SELECT id FROM person WHERE email = %s", (email("lead-temp"),))["id"]
    assert "Lead removed" in flash(alice.post(f"/admin/orgs/{org}/leads/{person}/remove"))
    # Access ends at once, in the browser session and for the token they already hold.
    assert temp.get(f"/orgs/{org}").status_code == 403 and "You are not invited yet" in temp.get("/").text
    assert broker("GET", f"/orgs/{org}", temp_token).status_code == 403
    assert broker("POST", f"/teams/{W['team_b']}/budget", temp_token, {"team_budget": 1}).status_code == 403
    assert broker("GET", f"/orgs/{org}", W["lead_b_token"]).status_code == 200      # the other lead is untouched
    assert one("SELECT status FROM team WHERE id = %s", (W["team_b"],))["status"] == "active"  # so is their work
    assert alice.post(f"/admin/orgs/{org}/leads/{person}/remove").status_code == 404  # no longer a lead

    # An invitation that was never accepted can be cancelled, and its link stops working.
    alice.page(f"/orgs/{org}")
    alice.post(f"/admin/orgs/{org}/leads", {"email": email("lead-never")})
    token = invite_token(email("lead-never"))
    invite = one("SELECT id FROM invite WHERE org_id = %s AND email = %s AND status = 'pending'", (org, email("lead-never")))["id"]
    assert "Cancel invitation" in alice.page(f"/orgs/{org}").text
    assert "Invitation cancelled" in flash(alice.post(f"/admin/orgs/{org}/lead-invites/{invite}/revoke"))
    assert "cannot be used" in Browser().get(f"/invite/{token}").text
    assert email("lead-never") not in alice.page(f"/orgs/{org}").text


def test_admin_removes_a_team_and_only_that_team():
    alice, lead, org = W["alice"], W["lead_b"], W["org_b"]
    slug = f"orgb-{RUN}"
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    # A second team in org B, with a member who holds a working key.
    lead.page(f"/orgs/{org}")
    lead.post(f"/orgs/{org}/teams", {"name": "Scratch", "team_budget": "5", "key_budget": "1", "key_limit": "1",
                                     "key_expiry_days": "7", "consent_text": CONSENT})
    scratch = str(one("SELECT id FROM team WHERE org_id = %s AND name = 'Scratch'", (org,))["id"])
    lead.page(f"/teams/{scratch}/manage")
    lead.post(f"/teams/{scratch}/models", {"model_ids": W["model_b"]})
    create_user(email("ps"), PASSWORD)
    lead.post(f"/teams/{scratch}/invites", {"emails": f"{email('ps')}\n{email('ps-pending')}"})
    pending_token = invite_token(email("ps-pending"))
    member = sign_in(email("ps"), PASSWORD, start=(f"/invite/{invite_token(email('ps'))}", {}))
    member.post(f"/teams/{scratch}/my/consent", {"terms_accepted": "yes"})
    key = re.search(r'<code class="key">(sk-[^<]+)</code>', member.post(f"/teams/{scratch}/my/keys", {"name": "k"}).text).group(1)
    assert chat(key, f"{slug}/m1").status_code == 200

    # A lead has no such button or right; the admin must type the team's name.
    assert ">Remove team</button>" not in lead.page(f"/teams/{scratch}/manage").text
    assert lead.post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"}).status_code == 403
    assert ">Remove team</button>" in alice.page(f"/teams/{scratch}/manage").text
    assert "name exactly" in flash(alice.post(f"/admin/teams/{scratch}/remove", {"confirm_name": "scratch"}))
    assert chat(key, f"{slug}/m1").status_code == 200

    removed = alice.post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"})
    assert "Team removed: 1 member(s) removed, 1 key(s) deleted" in flash(removed)
    assert "Scratch" not in re.sub(r'class="flash[^<]*<', "", removed.text) and "Workshop B" in removed.text  # org page

    assert chat(key, f"{slug}/m1").status_code == 401
    info = httpx.get(f"{litellm}/team/info", params={"team_id": scratch}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True
    for browser in (member, lead, alice):
        assert browser.get(f"/teams/{scratch}/manage").status_code == 403
    assert member.get(f"/teams/{scratch}").status_code == 403 and "You are not invited yet" in member.get("/").text
    assert broker("GET", f"/teams/{scratch}/manage", W["lead_b_token"]).status_code == 403
    assert "cannot be used" in Browser().get(f"/invite/{pending_token}").text
    alice.page("/admin")
    assert alice.post(f"/admin/teams/{scratch}/remove", {"confirm_name": "Scratch"}).status_code == 404

    # The rest of the org carries on: its other team, its model, and the freed name.
    assert broker("GET", f"/teams/{W['team_b']}/manage", W["lead_b_token"]).status_code == 200
    assert one("SELECT removed_at FROM org_model WHERE id = %s", (W["model_b"],))["removed_at"] is None
    assert one("SELECT count(*) AS n FROM consent WHERE team_id = %s", (scratch,))["n"] == 1     # records kept
    lead.page(f"/orgs/{org}")
    again = lead.post(f"/orgs/{org}/teams", {"name": "Scratch", "team_budget": "5", "key_budget": "1", "key_limit": "1",
                                             "key_expiry_days": "7", "consent_text": CONSENT})
    assert "Created Scratch" in flash(again)
    # An archived team can be removed too.
    second = str(one("SELECT id FROM team WHERE org_id = %s AND name = 'Scratch' AND status = 'active'", (org,))["id"])
    lead.post(f"/teams/{second}/archive")
    alice.page(f"/teams/{second}/manage")
    assert "Team removed: 0 member(s) removed, 0 key(s) deleted" in flash(
        alice.post(f"/admin/teams/{second}/remove", {"confirm_name": "Scratch"}))


def test_admin_removes_an_org_and_everything_in_it_stops():
    alice, org, team, lead = W["alice"], W["org_b"], W["team_b"], W["lead_b"]
    slug = f"orgb-{RUN}"
    litellm, headers = os.environ["LITELLM_URL"], {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
    # Give org B a member with a working key, and a pending invitation.
    create_user(email("pb"), PASSWORD)
    lead.page(f"/teams/{team}/manage")
    lead.post(f"/teams/{team}/invites", {"emails": f"{email('pb')}\n{email('pb-pending')}"})
    pending_token = invite_token(email("pb-pending"))
    member = sign_in(email("pb"), PASSWORD, start=(f"/invite/{invite_token(email('pb'))}", {}))
    member.post(f"/teams/{team}/my/consent", {"terms_accepted": "yes"})
    key = re.search(r'<code class="key">(sk-[^<]+)</code>', member.post(f"/teams/{team}/my/keys", {"name": "k"}).text).group(1)
    assert chat(key, f"{slug}/m1").status_code == 200

    # The short name must be typed exactly; otherwise nothing happens.
    alice.page(f"/orgs/{org}")
    assert "short name exactly" in flash(alice.post(f"/admin/orgs/{org}/remove", {"confirm_slug": "wrong"}))
    assert chat(key, f"{slug}/m1").status_code == 200 and one("SELECT status FROM org WHERE id = %s", (org,))["status"] == "active"

    removed = alice.post(f"/admin/orgs/{org}/remove", {"confirm_slug": slug})
    assert "Organization removed: 1 team(s) archived, 1 key(s) deleted, 1 model(s) removed" in flash(removed)
    assert f"Org B {RUN}" not in re.sub(r'class="flash[^<]*<', "", removed.text)   # gone from the admin's list

    # Keys, the model with its provider key, and the team are shut in LiteLLM.
    assert chat(key, f"{slug}/m1").status_code == 401
    names = [m["model_name"] for m in httpx.get(f"{litellm}/v1/model/info", headers=headers).json()["data"]]
    assert f"{slug}/m1" not in names and f"orga-{RUN}/m1" in names             # only this org's model
    info = httpx.get(f"{litellm}/team/info", params={"team_id": team}, headers=headers).json()
    assert info["keys"] == [] and info["team_info"]["blocked"] is True

    # Nobody can reach it any more: lead, member, invitee, or the admin's own org page.
    assert "You are not invited yet" in lead.get("/").text and "You are not invited yet" in member.get("/").text
    for token, path in ((W["lead_b_token"], f"/orgs/{org}"), (W["lead_b_token"], f"/teams/{team}/manage")):
        assert broker("GET", path, token).status_code == 403
    assert member.get(f"/teams/{team}").status_code == 403
    assert "cannot be used" in Browser().get(f"/invite/{pending_token}").text
    assert alice.get(f"/orgs/{org}").status_code == 403
    alice.page("/admin")
    for path, data in ((f"/admin/orgs/{org}/resume", {}), (f"/admin/orgs/{org}/ceiling", {"budget_ceiling": "1"}),
                       (f"/admin/orgs/{org}/leads", {"email": email("x")}), (f"/admin/orgs/{org}/remove", {"confirm_slug": slug})):
        assert alice.post(path, data).status_code == 404, path

    # Records are kept, and the short name is not handed out again.
    assert one("SELECT status FROM org WHERE id = %s", (org,))["status"] == "removed"
    assert one("SELECT count(*) AS n FROM consent WHERE org_id = %s AND team_id = %s", (org, team))["n"] == 1
    assert one("SELECT count(*) AS n FROM audit_event WHERE org_id = %s AND action = 'org.remove'", (org,))["n"] == 1
    assert "taken" in flash(alice.post("/admin/orgs", {"name": "Again", "slug": slug, "budget_ceiling": "1"}))
    # Org A is untouched.
    assert broker("GET", f"/orgs/{W['org_a']}", W["lead_a_token"]).status_code == 200


def test_audit_log_records_who_did_what():
    page = W["alice"].get("/admin/audit")
    assert page.status_code == 200
    for action in ("org.create", "org.appoint_lead", "model.add", "team.create", "team.invite", "invite.accept",
                   "my.consent", "my.key.create", "team.remove_member", "team.archive", "org.suspend", "org.remove_lead", "team.cancel_invite", "my.key.rotate", "team.revoke_key", "team.rotate_key", "org.remove", "team.remove"):
        assert f"<code>{action}</code>" in page.text, action
    assert "denied" in page.text and PROVIDER_KEY_A not in page.text


def test_sign_out_ends_the_session():
    p1 = W["p1"]
    p1.page(f"/teams/{W['team_a']}")
    p1.post("/logout")
    assert "Sign in" in p1.get("/").text and p1.get(f"/teams/{W['team_a']}", follow=False).status_code == 303
