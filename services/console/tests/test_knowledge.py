"""Each organization's shared knowledge: okf-hub, reached as MCP tools through LiteLLM.

A person uses their LiteLLM key at the gateway's /mcp. LiteLLM calls the hub with a Keycloak token for
that key's organization, and the hub lets that token touch one bundle only. So two things each keep
organizations apart: LiteLLM (which server a team's keys may use) and the hub (which bundle a token may touch).
"""

import json
import os
import re
import uuid

import httpx

from .helpers import (KEYCLOAK, Browser, _keycloak_admin, access_token, broker, create_user, invite_token, mcp,
                      mcp_tool, sign_in, sql)

RUN = uuid.uuid4().hex[:6]
PASSWORD = "Correct-horse-9"
HUB = os.environ["KNOWLEDGE_HUB_URL"]
LITELLM = os.environ["LITELLM_URL"]
MASTER = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
W: dict = {}


def email(name: str) -> str:
    return f"{name}-{RUN}@example.com"


def one(query: str, params=()):
    return sql("SUPERUSER_DATABASE_URL", query, params)[0]


def slug(letter: str) -> str:
    return f"know{letter}-{RUN}"


def tools(letter: str) -> str:
    """The prefix of an org's tool names: LiteLLM's name for its MCP server."""
    return "knowledge_" + slug(letter).replace("-", "_")


def make_org(alice: Browser, letter: str) -> None:
    alice.api_post("/admin/orgs", {"name": f"Knowledge {letter.upper()} {RUN}", "slug": slug(letter), "budget_ceiling": 100})
    org = str(one("SELECT id FROM org WHERE slug = %s", (slug(letter),))["id"])
    create_user(email(f"lead-{letter}"), PASSWORD)
    alice.api_post(f"/admin/orgs/{org}/leads", {"email": email(f"lead-{letter}")})
    lead = sign_in(email(f"lead-{letter}"), PASSWORD, start=(f"/invite/{invite_token(email(f'lead-{letter}'))}", {}))
    W.update({f"org_{letter}": org, f"lead_{letter}": lead})


def make_member(letter: str, team_name: str, person: str) -> str:
    """A team in the org with one member, and that member's key."""
    org, lead = W[f"org_{letter}"], W[f"lead_{letter}"]
    lead.api_post(f"/orgs/{org}/teams", {"name": team_name, "team_budget": 50, "key_budget": 5, "key_limit": 2,
                                         "key_expiry_days": 7, "consent_text": "You agree that leads see your usage totals."})
    team = str(one("SELECT id FROM team WHERE org_id = %s AND name = %s", (org, team_name))["id"])
    create_user(email(person), PASSWORD)
    lead.api_post(f"/teams/{team}/invites", data={"emails": email(person)})
    member = sign_in(email(person), PASSWORD, start=(f"/invite/{invite_token(email(person))}", {}))
    member.api_post(f"/teams/{team}/my/consent", {"terms_accepted": True})
    created = member.api_post(f"/teams/{team}/my/keys", {"name": "k"})
    W.update({f"team_{person}": team, f"browser_{person}": member})
    return created.json()["key"]["key"]


def keycloak_clients(client_id: str) -> list:
    return httpx.get(f"{KEYCLOAK}/admin/realms/litellm/clients", params={"clientId": client_id},
                     headers=_keycloak_admin()).json()


def test_a_new_org_gets_its_own_keycloak_client_and_mcp_server():
    alice = sign_in("alice@example.com", "alice123")
    W["alice"] = alice
    make_org(alice, "a")
    make_org(alice, "b")
    for letter in "ab":
        client = keycloak_clients(f"okf-org-{slug(letter)}")
        # Nobody signs in through it: it only ever gets tokens for itself.
        assert len(client) == 1 and client[0]["serviceAccountsEnabled"] and not client[0]["standardFlowEnabled"]
    servers = {s["server_name"]: s for s in httpx.get(f"{LITELLM}/v1/mcp/server", headers=MASTER).json()}
    for letter in "ab":
        server = servers[tools(letter)]
        assert server["url"] == f"{HUB}/mcp?bundle=orgs/oidc-{slug(letter)}" and server["allow_all_keys"] is False
        assert server["server_id"] == one("SELECT mcp_server_id FROM org WHERE slug = %s", (slug(letter),))["mcp_server_id"]
    W["key_a1"] = make_member("a", "One", "a1")
    W["key_a2"] = make_member("a", "Two", "a2")
    W["key_b1"] = make_member("b", "One", "b1")


def test_a_key_lists_its_orgs_knowledge_tools_and_no_others():
    status, reply = mcp(W["key_a1"], "tools/list")
    assert status == 200
    names = {tool["name"] for tool in reply["result"]["tools"]}
    assert {f"{tools('a')}-okf_search", f"{tools('a')}-okf_create", f"{tools('a')}-okf_show"} <= names
    assert all(name.startswith(f"{tools('a')}-") for name in names)
    assert mcp(None, "tools/list")[0] == 401 and mcp("sk-not-a-key", "tools/list")[0] == 401
    # What the member's team page builds the MCP address and the tool names from.
    member = W["browser_a1"]
    assert member.api_get("/session").json()["config"]["gateway_url"] == os.environ["GATEWAY_URL"]
    assert member.api_get(f"/teams/{W['team_a1']}").json()["knowledge_tools"] == tools("a")


def test_knowledge_is_shared_by_every_team_of_the_org():
    ok, text = mcp_tool(W["key_a1"], f"{tools('a')}-okf_create", concept_id="facts/lab-door", type="fact",
                        title="Lab door code", description="How to get in", body=f"The marker is DOOR-{RUN}.")
    assert ok and f"orgs/oidc-{slug('a')}" in text, text
    # Another team of the same org finds it and can read it.
    ok, text = mcp_tool(W["key_a2"], f"{tools('a')}-okf_search", query="lab door")
    assert ok and "facts/lab-door" in text
    ok, text = mcp_tool(W["key_a2"], f"{tools('a')}-okf_show", concept_id="facts/lab-door")
    assert ok and f"DOOR-{RUN}" in text


def test_another_org_cannot_see_or_reach_it():
    key, mine, theirs = W["key_b1"], tools("b"), tools("a")
    ok, text = mcp_tool(key, f"{mine}-okf_search", query="lab door")
    assert ok and "lab-door" not in text
    # LiteLLM: org A's server is not one this key's team may use.
    ok, text = mcp_tool(key, f"{theirs}-okf_show", concept_id="facts/lab-door")
    assert not ok and f"DOOR-{RUN}" not in text
    # The hub: its own tools take a bundle name, but org B's token is good for org B's bundle only.
    for tool, arguments in (("okf_show", {"concept_id": "facts/lab-door"}), ("okf_search", {"query": "lab door"}),
                            ("okf_create", {"concept_id": "facts/x", "type": "fact", "title": "x", "description": "x",
                                            "body": "x"})):
        ok, text = mcp_tool(key, f"{mine}-{tool}", bundle=f"orgs/oidc-{slug('a')}", **arguments)
        assert not ok and "Access denied" in text, text
    ok, text = mcp_tool(key, f"{mine}-okf_search", query="lab door", bundle="default")
    assert not ok and "Access denied" in text


def test_the_hub_takes_only_an_orgs_own_keycloak_token():
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    url = f"{HUB}/mcp?bundle=orgs/oidc-{slug('a')}"
    assert httpx.post(url, json=request).status_code == 401
    # Not a LiteLLM key, not the master key, and not a person's token, even an admin's.
    for token in (W["key_a1"], os.environ["LITELLM_MASTER_KEY"], access_token("alice@example.com", "alice123")):
        assert httpx.post(url, json=request, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    # A token someone sends along with their key replaces LiteLLM's, so the hub checks that one instead.
    status, reply = mcp(W["key_b1"], "tools/call",
                        {"name": f"{tools('b')}-okf_search", "arguments": {"query": "lab door", "bundle": f"orgs/oidc-{slug('a')}"}},
                        headers={"x-mcp-auth": f"Bearer {access_token('alice@example.com', 'alice123')}"})
    assert f"DOOR-{RUN}" not in str(reply) and "lab-door" not in str(reply)


def test_a_lead_browses_the_orgs_knowledge_and_its_graph():
    org, lead, mine = W["org_a"], W["lead_a"], tools("a")
    untrusted = ("## Why\n\nMarker **BADGE-{run}**.\n\n- one\n- two\n\n<script>alert(1)</script> <b>raw</b>\n\n"
                 "[bad](javascript:alert(1)) [file](file:///etc/passwd) [gone](../facts/gone.md) "
                 "[site](https://example.org/x) ![pic](https://example.org/p.png)").format(run=RUN)
    ok, _ = mcp_tool(W["key_a2"], f"{mine}-okf_create", concept_id="decisions/badge-readers", type="decision",
                     title="Badge readers", description="Doors get badge readers", body=untrusted, tags=["doors"])
    assert ok
    ok, _ = mcp_tool(W["key_a2"], f"{mine}-okf_relate", source_id="decisions/badge-readers", target_id="facts/lab-door",
                     description="replaces")
    assert ok
    assert lead.api_get(f"/orgs/{org}").json()["is_lead"] is True   # what puts the link to the knowledge on the page

    page = lead.api_get(f"/orgs/{org}/knowledge")
    assert page.status_code == 200
    view = page.json()
    assert set(view) == {"org", "tools", "edge_count", "concepts", "concept", "graph", "log_html"}
    assert len(view["concepts"]) == 2 and view["edge_count"] == 1 and view["tools"] == mine
    assert {c["id"]: c["title"] for c in view["concepts"]} == {"facts/lab-door": "Lab door code",
                                                               "decisions/badge-readers": "Badge readers"}
    assert all(set(c) == {"id", "title", "type", "description", "tags", "links", "written_at"} for c in view["concepts"])
    # The graph: a dot per concept, one arrow carrying the relation's description, and the bundle's own log.
    assert len(view["graph"]["nodes"]) == 2 and len(view["graph"]["legend"]) == 2
    assert [line["note"] for line in view["graph"]["lines"]] == ["replaces"] and view["log_html"]
    # A body shows only once selected, and never as the Markdown it was written in.
    assert view["concept"] is None and f"DOOR-{RUN}" not in json.dumps({**view, "log_html": ""})
    assert '"body"' not in page.text and '"log"' not in page.text

    one_concept = lead.api_get(f"/orgs/{org}/knowledge?concept=facts/lab-door").json()["concept"]
    assert f"The marker is DOOR-{RUN}." in one_concept["html"]
    assert one_concept["links_in"] == [{"id": "decisions/badge-readers", "title": "Badge readers", "note": "replaces"}]
    assert one_concept["links_out"] == []
    missing = lead.api_get(f"/orgs/{org}/knowledge?concept=no/such")
    assert missing.status_code == 200 and missing.json()["concept"] is None

    # The text is shown as formatted Markdown. It is members' writing, so nothing in it can act on the reader:
    # HTML stays text, images are not loaded, and only links to http(s) addresses or other concepts survive.
    shown = lead.api_get(f"/orgs/{org}/knowledge?concept=decisions/badge-readers")
    doc = shown.json()["concept"]["html"]
    rest = {**shown.json(), "log_html": "", "concept": {**shown.json()["concept"], "html": ""}}
    assert f"BADGE-{RUN}" not in json.dumps(rest)   # the text travels as sanitized HTML and nowhere else
    assert f"<h2>Why</h2>" in doc and f"<strong>BADGE-{RUN}</strong>" in doc and "<li>one</li>" in doc
    assert "<script" not in doc and "<b>" not in doc and "&lt;script&gt;" in doc and "<img" not in doc
    assert "javascript:" not in re.sub(r"\[bad\]\(javascript:alert\(1\)\)", "", doc) and 'href="file:' not in doc
    assert "<a>gone</a>" in doc and '<a href="https://example.org/x" rel="noopener noreferrer">site</a>' in doc
    assert '<a href="?concept=facts/lab-door#concept">Lab door code</a>' in doc    # the relation, as a link on this page

    view = broker("GET", f"/orgs/{org}/knowledge", access_token(email("lead-a"), PASSWORD)).json()
    assert view["edges"] == [{"source": "decisions/badge-readers", "target": "facts/lab-door", "note": "replaces"}]
    assert {c["id"]: (c["type"], c["tags"]) for c in view["concepts"]} == {
        "decisions/badge-readers": ("decision", ["doors"]), "facts/lab-door": ("fact", [])}
    assert one("SELECT count(*) AS n FROM audit_event WHERE org_id = %s AND action = 'org.knowledge' AND result = 'ok'",
               (org,))["n"] >= 3

    # An org with nothing written yet has an empty page, not an error.
    empty = W["lead_b"].api_get(f"/orgs/{W['org_b']}/knowledge")
    assert empty.status_code == 200 and empty.json()["concepts"] == [] and "lab-door" not in empty.text
    assert empty.json()["tools"] == tools("b")   # the page names the tools to write with


def test_only_the_orgs_own_leads_get_that_view():
    org = W["org_a"]
    people = {"the SSEC admin": (W["alice"], access_token("alice@example.com", "alice123")),
              "another org's lead": (W["lead_b"], access_token(email("lead-b"), PASSWORD)),
              "a member of the org": (W["browser_a1"], access_token(email("a1"), PASSWORD))}
    for who, (browser, token) in people.items():
        page = browser.api_get(f"/orgs/{org}/knowledge")
        assert page.status_code == 403 and "lab-door" not in page.text and f"DOOR-{RUN}" not in page.text, who
        refused = broker("GET", f"/orgs/{org}/knowledge", token)
        assert refused.status_code == 403 and "lab-door" not in refused.text, who
    # The admin can open the org's page, but is offered no way in.
    assert W["alice"].api_get(f"/orgs/{org}").json()["is_lead"] is False
    assert one("SELECT count(*) AS n FROM audit_event WHERE org_id = %s AND action = 'org.knowledge' AND result = 'denied'",
               (org,))["n"] >= 3
    # The console's reader can read bundles in the hub and write none.
    reader = httpx.post(f"{KEYCLOAK}/realms/litellm/protocol/openid-connect/token", data={
        "grant_type": "client_credentials", "client_id": "console-knowledge",
        "client_secret": "console-knowledge-dev-secret"}).json()["access_token"]
    write = httpx.post(f"{HUB}/mcp?bundle=orgs/oidc-{slug('a')}", headers={"Authorization": f"Bearer {reader}"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "okf_create", "arguments": {
            "concept_id": "facts/planted", "type": "fact", "title": "x", "description": "x", "body": "x"}}}).json()
    assert write["result"]["isError"] and "Access denied" in write["result"]["content"][0]["text"]


def test_suspending_an_org_closes_its_knowledge_until_resumed():
    alice, org = W["alice"], W["org_a"]
    alice.api_post(f"/admin/orgs/{org}/suspend")
    assert "Lab door code" in W["lead_a"].api_get(f"/orgs/{org}/knowledge").text    # its lead can still read it
    # Blocking a team does not stop MCP in LiteLLM, so the console takes the knowledge away from its teams.
    for key in (W["key_a1"], W["key_a2"]):
        status, reply = mcp(key, "tools/call", {"name": f"{tools('a')}-okf_search", "arguments": {"query": "lab door"}})
        assert "lab-door" not in str(reply) and (status != 200 or reply["result"]["isError"]), reply
        status, reply = mcp(key, "tools/list")
        assert status != 200 or reply["result"]["tools"] == [], reply
    alice.api_post(f"/admin/orgs/{org}/resume")
    ok, text = mcp_tool(W["key_a1"], f"{tools('a')}-okf_search", query="lab door")
    assert ok and "facts/lab-door" in text


def test_removing_an_org_ends_access_to_its_knowledge():
    alice, org = W["alice"], W["org_a"]
    alice.api_post(f"/admin/orgs/{org}/remove", {"confirm_slug": slug("a")})
    assert one("SELECT status, mcp_server_id FROM org WHERE id = %s", (org,)) == {"status": "removed", "mcp_server_id": None}
    assert keycloak_clients(f"okf-org-{slug('a')}") == []
    names = [s["server_name"] for s in httpx.get(f"{LITELLM}/v1/mcp/server", headers=MASTER).json()]
    assert tools("a") not in names and tools("b") in names
    assert mcp(W["key_a1"], "tools/list")[0] == 401
    # Org B carries on.
    ok, _ = mcp_tool(W["key_b1"], f"{tools('b')}-okf_search", query="anything")
    assert ok
