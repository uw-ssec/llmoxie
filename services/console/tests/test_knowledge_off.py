"""The broker on a console with no knowledge hub, and before its setup jobs have run. No stack needed.

Without KNOWLEDGE_HUB_URL the broker starts with no KEYCLOAK_* or KNOWLEDGE_* setting, and does none of
the knowledge steps: no Keycloak client and no MCP server per organization, none for a team. On a first
deploy it also starts before console-init has written the LiteLLM admin key and before the database job
has made its role and schema; it must stay up and fail per request instead.

Each test imports the broker afresh under its own settings, and forgets it again afterwards.
"""

import inspect
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

BROKER_ENV = {
    "CONSOLE_PUBLIC_URL": "http://console.test",
    "SMTP_HOST": "mail.test",
    "OIDC_ISSUER": "http://auth.test/realms/test",
    "OIDC_CLIENT_ID": "console",
    "OIDC_JWKS_URL": "http://auth.test/realms/test/certs",
    "CONSOLE_BROKER_CALLER_SECRET": "caller-secret",
    # Nothing listens here: as on a first deploy, before the database job has made the broker's role.
    "CONSOLE_BROKER_DATABASE_URL": "postgresql://console_broker@127.0.0.1:1/console_db?connect_timeout=1",
    "LITELLM_URL": "http://litellm.test",
}
WEB_ENV = {
    "CONSOLE_BROKER_URL": "http://broker.test",
    "CONSOLE_BROKER_CALLER_SECRET": "caller-secret",
    "CONSOLE_WEB_DATABASE_URL": "postgresql://console_web@127.0.0.1:1/console_db",
    "CONSOLE_PUBLIC_URL": "http://console.test",
    "OIDC_ISSUER": "http://auth.test/realms/test",
    "OIDC_CLIENT_ID": "console",
    "OIDC_CLIENT_SECRET": "web-secret",
    "OIDC_AUTH_URL": "http://auth.test/auth",
    "OIDC_TOKEN_URL": "http://auth.test/token",
    "OIDC_LOGOUT_URL": "http://auth.test/logout",
    "OIDC_JWKS_URL": "http://auth.test/certs",
}
OFF = {"error": "knowledge_off", "message": "Knowledge isn't set up on this console."}

ORG_ID, TEAM_ID, PERSON_ID = str(uuid4()), str(uuid4()), str(uuid4())
ORG = {"id": ORG_ID, "name": "Astro", "slug": "astro", "status": "active", "budget_ceiling": 50,
       "mcp_server_id": None}
TEAM = {"id": TEAM_ID, "org_id": ORG_ID, "name": "Workshop", "status": "active", "org_name": "Astro",
        "org_slug": "astro", "org_status": "active", "org_mcp_server_id": None, "org_budget_ceiling": 50,
        "key_limit": 2, "key_budget": 1, "key_expiry_days": 30, "consent_text": "Leads see totals."}


def _forget(prefix: str) -> None:
    for name in [m for m in sys.modules if m.startswith(prefix)]:
        del sys.modules[name]


@pytest.fixture
def broker_env_without_hub(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(("KEYCLOAK_", "KNOWLEDGE_")):
            monkeypatch.delenv(name)
    for name, value in BROKER_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LITELLM_ADMIN_KEY_FILE", str(tmp_path / "litellm-admin-key"))  # not written yet
    _forget("console_app.broker")
    yield tmp_path / "litellm-admin-key"
    _forget("console_app.broker")


class _Result:
    def __init__(self, rows):
        self.rows, self.rowcount = rows, len(rows) or 1

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _Conn:
    """Answers the broker's SQL with one organization, one team and nothing else."""

    def execute(self, sql, params=None):
        if "RETURNING *" in sql or "FROM org WHERE id" in sql:
            return _Result([dict(ORG)])
        if "FROM team t JOIN org o" in sql:
            return _Result([dict(TEAM)])
        if "SELECT id FROM team WHERE status = 'active'" in sql:
            return _Result([{"id": TEAM_ID}])
        return _Result([])


class _Tx:
    def __enter__(self):
        return _Conn()

    def __exit__(self, *_):
        return False


@pytest.fixture
def calls(broker_env_without_hub, monkeypatch):
    """Every LiteLLM and Keycloak call the broker makes, by function name, with its arguments by name."""
    from console_app.broker import db, keycloak, litellm

    made: dict[str, SimpleNamespace] = {}

    def record(module, name, answer=None):
        signature = inspect.signature(getattr(module, name))

        def stand_in(*args, **kwargs):
            made[name] = SimpleNamespace(**signature.bind(*args, **kwargs).arguments)
            return answer
        monkeypatch.setattr(module, name, stand_in)

    for name in ("team_new", "team_set_knowledge", "team_block", "team_unblock", "team_set_models",
                 "model_delete", "key_delete", "mcp_server_delete"):
        record(litellm, name)
    record(litellm, "mcp_server_new", "mcp-1")
    record(keycloak, "org_client_create", "secret")
    record(keycloak, "org_client_delete")
    monkeypatch.setattr(db, "system_tx", lambda: _Tx())
    monkeypatch.setattr(db, "org_tx", lambda _org_id: _Tx())
    return made


@pytest.fixture
def app_client(calls):
    """The broker as an SSEC admin who also leads the org and belongs to its team. No lifespan, so no pool."""
    from console_app.broker import app as broker
    from console_app.broker.auth import Session, current_session
    from console_app.policy import Actor

    actor = Actor(person_id=PERSON_ID, is_admin=True, lead_orgs=frozenset({ORG_ID}), member_teams={TEAM_ID: ORG_ID})
    session = Session({"id": PERSON_ID, "participant_id": "part-1"}, actor, "a@uw.edu")
    broker.app.dependency_overrides[current_session] = lambda: session
    return TestClient(broker.app)


def test_broker_imports_without_hub_or_keycloak_settings(broker_env_without_hub):
    import console_app.broker.app  # noqa: F401
    from console_app.broker import keycloak

    assert keycloak.ENABLED is False


def test_org_create_skips_knowledge(app_client, calls):
    r = app_client.post("/admin/orgs", json={"name": "Astro", "slug": "astro", "budget_ceiling": 50})
    assert r.status_code == 200 and r.json()["mcp_server_id"] is None
    assert "org_client_create" not in calls and "mcp_server_new" not in calls


def test_team_create_gets_no_mcp_server(app_client, calls):
    r = app_client.post(f"/orgs/{ORG_ID}/teams", json={
        "name": "Workshop", "key_limit": 2, "key_budget": 1, "key_expiry_days": 30, "team_budget": 5,
        "consent_text": "Leads can see how many requests you make."})
    assert r.status_code == 200
    assert calls["team_new"].mcp_server_id is None


def test_knowledge_route_says_off(app_client):
    r = app_client.get(f"/orgs/{ORG_ID}/knowledge")
    assert r.status_code == 404 and r.json() == OFF


def test_team_view_has_no_knowledge_tools(app_client):
    r = app_client.get(f"/my/teams/{TEAM_ID}")
    assert r.status_code == 200 and r.json()["knowledge_tools"] is None


def test_org_suspend_and_resume_skip_knowledge(app_client, calls):
    assert app_client.post(f"/admin/orgs/{ORG_ID}/suspend").status_code == 200
    assert app_client.post(f"/admin/orgs/{ORG_ID}/resume").status_code == 200
    assert "team_block" in calls and "team_unblock" in calls
    assert "team_set_knowledge" not in calls


def test_org_remove_skips_client_delete(app_client, calls):
    r = app_client.post(f"/admin/orgs/{ORG_ID}/remove", json={"confirm_slug": "astro"})
    assert r.status_code == 200
    assert "org_client_delete" not in calls and "mcp_server_delete" not in calls


def test_healthz_without_key_file_or_schema(broker_env_without_hub):
    from console_app.broker.app import app

    with TestClient(app) as client:  # runs the lifespan: the database is not there yet
        assert client.get("/healthz").status_code == 200


def test_admin_key_is_read_when_needed(broker_env_without_hub):
    from console_app.broker import litellm

    with pytest.raises(litellm.LiteLLMError) as missing:
        litellm.admin_key()
    assert (missing.value.operation, missing.value.status) == ("admin_key", 503)
    broker_env_without_hub.write_text("sk-admin\n")  # console-init has run since the broker started
    assert litellm.admin_key() == "sk-admin"


@pytest.fixture
def visit(monkeypatch):
    for name, value in WEB_ENV.items():
        monkeypatch.setenv(name, value)
    _forget("console_app.web")
    from console_app.web import visit as module
    yield module
    _forget("console_app.web")


def _visit_answered_by(module, monkeypatch, status: int, body: dict):
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, json=body))
    real_client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    v = object.__new__(module.Visit)
    v.api, v.sid, v.data = True, "sid", {"access_token": "token"}
    return v


def test_web_passes_knowledge_off_through(visit, monkeypatch):
    v = _visit_answered_by(visit, monkeypatch, 404, OFF)
    with pytest.raises(visit.ApiError) as refused:
        v.broker("GET", f"/orgs/{ORG_ID}/knowledge")
    assert (refused.value.status, refused.value.message) == (404, OFF["message"])


def test_web_still_hides_why_something_was_not_found(visit, monkeypatch):
    v = _visit_answered_by(visit, monkeypatch, 404, {"detail": "no such organization"})
    with pytest.raises(visit.ApiError) as refused:
        v.broker("GET", f"/orgs/{ORG_ID}")
    assert (refused.value.status, refused.value.message) == (404, visit.NOT_FOUND)
