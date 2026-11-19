"""Knowledge for the organizations made while the console had no hub.

Creating an organization with the hub on gives it a Keycloak client, an MCP server in LiteLLM and
`org.mcp_server_id`, and each of its teams that server (`admin_org_create`, `team_create`). An organization
made with the hub off has none of these. `backfill` gives each active or suspended one all of them, the
same way. A suspended organization's teams stay closed, as suspension leaves them; resuming opens them.

It is safe to run again: an organization that has its server is skipped, and a client or server left
behind by an interrupted run is replaced (`org_client_create`, `mcp_server_new`). The server id is saved
in the same transaction that gives the teams their server, so if a team fails, the next run starts
that organization over.
"""

from . import db, keycloak, litellm
from .app import audit


class BackfillIncomplete(Exception):
    """Some organizations could not be set up. `done` and `failed` hold short names."""

    def __init__(self, done: list[str], failed: list[str]):
        super().__init__(f"knowledge not set up for {len(failed)} organization(s): {', '.join(failed)}")
        self.done, self.failed = done, failed


def _set_up(org: dict) -> None:
    slug = org["slug"]
    secret = keycloak.org_client_create(slug)
    server_id = litellm.mcp_server_new(
        slug, f"{keycloak.HUB_URL}/mcp?bundle={keycloak.bundle(slug)}", keycloak.TOKEN_URL,
        keycloak.client_id(slug), secret)
    with db.org_tx(org["id"]) as conn:
        # The row is locked from here to the commit, so a suspend or resume waits for the teams to be set.
        saved = conn.execute(
            """UPDATE org SET mcp_server_id = %s WHERE id = %s AND mcp_server_id IS NULL AND status <> 'removed'
               RETURNING status""", (server_id, org["id"])).fetchone()
        if not saved:
            raise RuntimeError("the organization was removed or set up while this ran")
        for team in conn.execute("SELECT id FROM team WHERE status = 'active'").fetchall():
            litellm.team_set_knowledge(str(team["id"]), None if saved["status"] == "suspended" else server_id)


def backfill() -> list[str]:
    """Set up knowledge for every organization that has none, and return their short names.

    One organization's failure is audited and does not stop the others; BackfillIncomplete is raised
    at the end.
    """
    if not keycloak.ENABLED:
        raise RuntimeError("KNOWLEDGE_HUB_URL is not set: there is no hub to set up knowledge in")
    with db.system_tx() as conn:
        orgs = conn.execute("""SELECT id, slug FROM org WHERE status <> 'removed' AND mcp_server_id IS NULL
                               ORDER BY slug""").fetchall()
    done, failed = [], []
    for org in orgs:
        try:
            _set_up(org)
        except Exception as exc:  # never str(exc) unless it is ours: an HTTP error can carry a URL or body
            known = isinstance(exc, (keycloak.KeycloakError, litellm.LiteLLMError, RuntimeError))
            audit(None, "org.knowledge", "error", org_id=org["id"], target=org["slug"], backfill=True,
                  error=str(exc) if known else type(exc).__name__)
            failed.append(org["slug"])
            continue
        audit(None, "org.knowledge", "ok", org_id=org["id"], target=org["slug"], backfill=True)
        done.append(org["slug"])
    if failed:
        raise BackfillIncomplete(done, failed)
    return done
