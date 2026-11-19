"""The know job when some organizations fail: the others are still set up, and the job exits non-zero.

No stack needed: Keycloak, LiteLLM, the database and the audit log are stand-ins. Each test imports the
broker afresh with the hub's settings, and forgets it again afterwards.
"""

from types import SimpleNamespace

import pytest

from .test_knowledge_off import BROKER_ENV, _forget, _Result

HUB_ENV = {
    "KNOWLEDGE_HUB_URL": "http://hub.test",
    "KEYCLOAK_ADMIN_URL": "http://auth.test/admin/realms/test",
    "KEYCLOAK_TOKEN_URL": "http://auth.test/realms/test/protocol/openid-connect/token",
    "KEYCLOAK_PROVISIONER_CLIENT_ID": "console-provisioner",
    "KEYCLOAK_PROVISIONER_CLIENT_SECRET": "provisioner-secret",
    "KNOWLEDGE_READER_CLIENT_ID": "console-knowledge",
    "KNOWLEDGE_READER_CLIENT_SECRET": "knowledge-secret",
}
# bravo fails at Keycloak, delta at LiteLLM with an error whose text must not reach the audit log.
SLUGS = ("alpha", "bravo", "charlie", "delta")
LEAK = "http://litellm.test/v1/mcp/server?body=not-for-the-log"


class _Conn:
    def __init__(self, org_id):
        self.org_id = org_id

    def execute(self, sql, params=None):
        if "FROM org WHERE status" in sql:
            return _Result([{"id": f"id-{slug}", "slug": slug} for slug in SLUGS])
        if sql.lstrip().startswith("UPDATE org"):
            return _Result([{"status": "active"}])
        if "FROM team" in sql:
            return _Result([{"id": f"team-{self.org_id}"}])
        return _Result([])


class _Tx:
    def __init__(self, org_id=None):
        self.org_id = org_id

    def __enter__(self):
        return _Conn(self.org_id)

    def __exit__(self, *_):
        return False


@pytest.fixture
def job(monkeypatch, tmp_path):
    for name, value in {**BROKER_ENV, **HUB_ENV}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LITELLM_ADMIN_KEY_FILE", str(tmp_path / "litellm-admin-key"))
    _forget("console_app.broker")
    _forget("knowledge_backfill")
    from console_app.broker import db, keycloak, knowledge_backfill, litellm

    made = SimpleNamespace(audits=[], teams=[])

    def org_client_create(slug):
        if slug == "bravo":
            raise keycloak.KeycloakError("create client", 500)
        return "client-secret"

    def mcp_server_new(slug, *_):
        if slug == "delta":
            raise ValueError(LEAK)
        return f"mcp-{slug}"

    monkeypatch.setattr(keycloak, "org_client_create", org_client_create)
    monkeypatch.setattr(litellm, "mcp_server_new", mcp_server_new)
    monkeypatch.setattr(litellm, "team_set_knowledge", lambda team, server: made.teams.append((team, server)))
    monkeypatch.setattr(db, "system_tx", lambda: _Tx())
    monkeypatch.setattr(db, "org_tx", lambda org_id: _Tx(org_id))
    monkeypatch.setattr(db, "pool", SimpleNamespace(open=lambda **_: None, close=lambda: None))
    monkeypatch.setattr(knowledge_backfill, "audit",
                        lambda s, action, result, **detail: made.audits.append((action, result, detail)))
    made.module = knowledge_backfill
    yield made
    _forget("console_app.broker")
    _forget("knowledge_backfill")


def test_one_failure_does_not_stop_the_others(job):
    with pytest.raises(job.module.BackfillIncomplete) as raised:
        job.module.backfill()
    assert raised.value.done == ["alpha", "charlie"]
    assert raised.value.failed == ["bravo", "delta"]
    assert job.teams == [("team-id-alpha", "mcp-alpha"), ("team-id-charlie", "mcp-charlie")]


def test_each_organization_is_audited_and_unknown_errors_only_by_type(job):
    with pytest.raises(job.module.BackfillIncomplete):
        job.module.backfill()
    results = {detail["target"]: (result, detail.get("error")) for _, result, detail in job.audits}
    assert results == {
        "alpha": ("ok", None),
        "bravo": ("error", "Keycloak create client failed with HTTP 500"),
        "charlie": ("ok", None),
        "delta": ("error", "ValueError"),
    }
    assert all(action == "org.knowledge" and detail["backfill"] is True for action, _, detail in job.audits)
    assert LEAK not in repr(job.audits)


def test_the_job_finishes_the_others_then_exits_non_zero(job, capsys):
    import knowledge_backfill

    assert knowledge_backfill.main() == 1
    out, err = capsys.readouterr()
    assert out.splitlines() == ["alpha", "charlie", "backfilled 2 organizations"]
    assert "not set up: bravo (see the audit log)" in err
    assert "not set up: delta (see the audit log)" in err
    assert LEAK not in out + err
