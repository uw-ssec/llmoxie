"""Knowledge for organizations made before the hub: the console's `know` job.

An organization made while knowledge was off has no Keycloak client, no MCP server and no `mcp_server_id`,
and its teams may use no MCP server. The job (`knowledge_backfill.py`) sets each such organization up the
way creating it with the hub on would have. Here an organization is made through the API, with knowledge,
and then stripped of it as the superuser, to stand in for one made while the hub was off.

The job runs as a process of its own, with only the settings the deploy gives it: the broker's modules
read their settings at import.
"""

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest

from .helpers import (KEYCLOAK, REALM, _keycloak_admin, create_user, invite_token, mcp, mcp_tool, sign_in,
                      sql)

RUN = uuid.uuid4().hex[:6]
PASSWORD = "Correct-horse-9"
HUB = os.environ["KNOWLEDGE_HUB_URL"]
LITELLM = os.environ["LITELLM_URL"]
MASTER = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
CONSOLE_DIR = Path(__file__).resolve().parent.parent
W: dict = {}


def email(name: str) -> str:
    return f"{name}-{RUN}@example.com"


def one(query: str, params=()):
    return sql("SUPERUSER_DATABASE_URL", query, params)[0]


def slug(letter: str) -> str:
    return f"fill{letter}-{RUN}"


def tools(letter: str) -> str:
    return "knowledge_" + slug(letter).replace("-", "_")


def server_id(letter: str) -> str | None:
    return one("SELECT mcp_server_id FROM org WHERE slug = %s", (slug(letter),))["mcp_server_id"]


def keycloak_clients(letter: str) -> list:
    return httpx.get(f"{KEYCLOAK}/admin/realms/litellm/clients", params={"clientId": f"okf-org-{slug(letter)}"},
                     headers=_keycloak_admin()).json()


def litellm_servers() -> dict:
    return {s["server_name"]: s for s in httpx.get(f"{LITELLM}/v1/mcp/server", headers=MASTER).json()}


def make_org(alice, letter: str) -> str:
    alice.api_post("/admin/orgs", {"name": f"Backfill {letter.upper()} {RUN}", "slug": slug(letter),
                                   "budget_ceiling": 100})
    org = str(one("SELECT id FROM org WHERE slug = %s", (slug(letter),))["id"])
    W[f"org_{letter}"] = org
    return org


def make_member(alice, letter: str) -> str:
    """A lead for the org, a team with one member, and that member's key."""
    org = W[f"org_{letter}"]
    create_user(email(f"lead-{letter}"), PASSWORD)
    alice.api_post(f"/admin/orgs/{org}/leads", {"email": email(f"lead-{letter}")})
    lead = sign_in(email(f"lead-{letter}"), PASSWORD, start=(f"/invite/{invite_token(email(f'lead-{letter}'))}", {}))
    lead.api_post(f"/orgs/{org}/teams", {"name": "One", "team_budget": 50, "key_budget": 5, "key_limit": 2,
                                         "key_expiry_days": 7, "consent_text": "You agree that leads see your usage totals."})
    team = str(one("SELECT id FROM team WHERE org_id = %s AND name = 'One'", (org,))["id"])
    create_user(email(f"member-{letter}"), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": email(f"member-{letter}")})
    member = sign_in(email(f"member-{letter}"), PASSWORD, start=(f"/invite/{invite_token(email(f'member-{letter}'))}", {}))
    member.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})
    W[f"team_{letter}"] = team
    return member.api_post(f"/teams/{team}/my/keys", {"name": "k"}).json()["key"]["key"]


def strip_knowledge(letter: str, keep_client: bool = False) -> None:
    """Leave the org as if it had been made while the hub was off. `keep_client` leaves its Keycloak client
    behind, as a run that stopped after making it would."""
    httpx.delete(f"{LITELLM}/v1/mcp/server/{server_id(letter)}", headers=MASTER).raise_for_status()
    if not keep_client:
        for client in keycloak_clients(letter):
            httpx.delete(f"{KEYCLOAK}/admin/realms/litellm/clients/{client['id']}",
                         headers=_keycloak_admin()).raise_for_status()
    if f"team_{letter}" in W:  # a team made with the hub off may use no MCP server
        httpx.post(f"{LITELLM}/team/update", headers=MASTER, json={
            "team_id": W[f"team_{letter}"], "object_permission": {"mcp_servers": ["no-mcp-servers"]}}).raise_for_status()
    sql("SUPERUSER_DATABASE_URL", "UPDATE org SET mcp_server_id = NULL WHERE slug = %s", (slug(letter),))


def backfill() -> list[str]:
    """Run the job's script with the settings the deploy gives it, and return the short names it set up."""
    with tempfile.TemporaryDirectory() as tmp:
        key_file = Path(tmp, "admin-key")
        key_file.write_text(os.environ["LITELLM_MASTER_KEY"])
        env = {
            "PATH": os.environ["PATH"],
            "LITELLM_URL": LITELLM,
            "LITELLM_ADMIN_KEY_FILE": str(key_file),
            "CONSOLE_BROKER_DATABASE_URL": os.environ["BROKER_DATABASE_URL"],
            "KNOWLEDGE_HUB_URL": HUB,
            "KEYCLOAK_ADMIN_URL": f"{KEYCLOAK}/admin/realms/litellm",
            "KEYCLOAK_TOKEN_URL": f"{REALM}/protocol/openid-connect/token",
            "KEYCLOAK_PROVISIONER_CLIENT_ID": "console-provisioner",
            "KEYCLOAK_PROVISIONER_CLIENT_SECRET": "console-provisioner-dev-secret",
            "KNOWLEDGE_READER_CLIENT_ID": "console-knowledge",
            "KNOWLEDGE_READER_CLIENT_SECRET": "console-knowledge-dev-secret",
        }
        done = subprocess.run([sys.executable, "knowledge_backfill.py"], cwd=CONSOLE_DIR, env=env,
                              capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, (done.stdout, done.stderr)
    # Each audit event is also printed, as one JSON line, for the job's log.
    lines = [line for line in done.stdout.splitlines() if not line.startswith('{"audit"')]
    assert lines and lines[-1] == f"backfilled {len(lines) - 1} organizations", done.stdout
    return lines[:-1]


@pytest.fixture(scope="module")
def first_run():
    """Four organizations made without knowledge, one in each state, and the job run once over them."""
    alice = sign_in("alice@example.com", "alice123")
    W["alice"] = alice
    for letter in "pshr":
        make_org(alice, letter)
    W["key_p"] = make_member(alice, "p")
    W["key_s"] = make_member(alice, "s")
    for letter in "ps":
        strip_knowledge(letter)
    strip_knowledge("h", keep_client=True)
    alice.api_post(f"/admin/orgs/{W['org_s']}/suspend")
    alice.api_post(f"/admin/orgs/{W['org_r']}/remove", {"confirm_slug": slug("r")})
    # Before the job, the member's key reaches no knowledge.
    status, reply = mcp(W["key_p"], "tools/list")
    assert status != 200 or not reply["result"]["tools"], reply
    return backfill()


def test_an_org_made_without_knowledge_gets_it(first_run):
    assert slug("p") in first_run
    server = server_id("p")
    assert server
    client = keycloak_clients("p")
    assert len(client) == 1 and client[0]["serviceAccountsEnabled"] and not client[0]["standardFlowEnabled"]
    listed = litellm_servers()[tools("p")]
    assert listed["server_id"] == server and listed["url"] == f"{HUB}/mcp?bundle=orgs/oidc-{slug('p')}"
    ok, _ = mcp_tool(W["key_p"], f"{tools('p')}-okf_search", query="anything")
    assert ok
    audited = one("""SELECT count(*) AS n FROM audit_event WHERE org_id = %s AND action = 'org.knowledge'
                     AND result = 'ok' AND target = %s AND detail->>'backfill' = 'true'""", (W["org_p"], slug("p")))
    assert audited["n"] == 1


def test_a_suspended_org_gets_the_server_but_its_teams_stay_closed(first_run):
    assert slug("s") in first_run
    assert server_id("s") and len(keycloak_clients("s")) == 1 and tools("s") in litellm_servers()
    status, reply = mcp(W["key_s"], "tools/list")
    assert status != 200 or not reply["result"]["tools"], reply
    W["alice"].api_post(f"/admin/orgs/{W['org_s']}/resume")
    ok, _ = mcp_tool(W["key_s"], f"{tools('s')}-okf_search", query="anything")
    assert ok


def test_a_removed_org_is_skipped(first_run):
    assert slug("r") not in first_run
    assert server_id("r") is None
    assert keycloak_clients("r") == []
    assert tools("r") not in litellm_servers()


def test_a_half_finished_run_is_finished(first_run):
    assert slug("h") in first_run
    assert len(keycloak_clients("h")) == 1   # the one left behind was replaced, not added to
    assert litellm_servers()[tools("h")]["server_id"] == server_id("h")


def test_a_second_run_changes_nothing(first_run):
    before = {letter: server_id(letter) for letter in "psh"}
    assert backfill() == []
    assert {letter: server_id(letter) for letter in "psh"} == before
    servers = litellm_servers()
    assert {letter: servers[tools(letter)]["server_id"] for letter in "psh"} == before
