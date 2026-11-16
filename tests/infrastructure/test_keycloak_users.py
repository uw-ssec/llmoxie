"""keycloak-users: CSV parsing, planning, creating and the CLI, with no network."""

import json
import secrets
import stat
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.deployment.keycloak_users import (
    open_admin_client,
    KeycloakUsersError,
    _AdminAuth,
    create_users,
    plan_users,
    read_emails,
)

REALM = "llmoxie"
ADMIN_PASSWORD = secrets.token_urlsafe(16)  # made per run; not a real credential


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://kc.example.org", transport=httpx.MockTransport(handler)
    )


def test_bom_mixed_case_spaces_blank_and_duplicates(tmp_path):
    f = tmp_path / "team.csv"
    f.write_bytes(
        b"\xef\xbb\xbfName, Email \r\n"
        b"Alice, Alice@X.org \r\n"
        b"\r\n"
        b",\r\n"
        b"Bob,bob@x.org\r\n"
        b"Alice again,ALICE@x.org\r\n"
    )
    assert read_emails(f) == ["alice@x.org", "bob@x.org"]


def test_missing_email_column_is_refused(tmp_path):
    f = tmp_path / "team.csv"
    f.write_text("name,mail\nAlice,a@x.org\n")
    with pytest.raises(ValueError, match="email"):
        read_emails(f)


def test_existing_users_are_skipped():
    def handler(request):
        assert request.url.path == f"/admin/realms/{REALM}/users"
        assert request.url.params["exact"] == "true"
        found = request.url.params["email"] == "old@x.org"
        return httpx.Response(200, json=[{"email": "old@x.org"}] if found else [])

    plan = plan_users(_client(handler), REALM, ["old@x.org", "new@x.org"])
    assert plan.existing == ["old@x.org"]
    assert plan.create == ["new@x.org"]


def test_created_user_payload(tmp_path):
    posted = []

    def handler(request):
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(201)

    out = tmp_path / "out.csv"
    assert create_users(_client(handler), REALM, ["a@x.org"], out) == 1
    path, body = posted[0]
    assert path == f"/admin/realms/{REALM}/users"
    cred = body.pop("credentials")[0]
    assert body == {
        "username": "a@x.org",
        "email": "a@x.org",
        "emailVerified": True,
        "enabled": True,
        "requiredActions": ["UPDATE_PASSWORD"],
    }
    assert cred["type"] == "password" and cred["temporary"] is True
    lines = out.read_text().splitlines()
    assert lines[0] == "email,temporary_password"
    assert lines[1] == f"a@x.org,{cred['value']}"


def test_conflict_is_reported_and_header_only_file_removed(tmp_path):
    out = tmp_path / "out.csv"
    existed = []
    n = create_users(
        _client(lambda r: httpx.Response(409)), REALM, ["a@x.org"], out, existed
    )
    assert n == 0 and existed == ["a@x.org"]
    assert not out.exists()


def test_out_file_is_0600_and_not_overwritten(tmp_path):
    calls = []
    out = tmp_path / "out.csv"
    create_users(
        _client(lambda r: calls.append(r) or httpx.Response(201)),
        REALM,
        ["a@x.org"],
        out,
    )
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    before = out.read_text()
    calls.clear()
    with pytest.raises(KeycloakUsersError, match="already exists"):
        create_users(_client(lambda r: calls.append(r)), REALM, ["b@x.org"], out)
    assert calls == []
    assert out.read_text() == before


def test_edge_403_is_a_clear_error():
    with pytest.raises(KeycloakUsersError, match="admin_allowed_ips"):
        plan_users(_client(lambda r: httpx.Response(403)), REALM, ["a@x.org"])


def _cli_env(handler):
    config = type(
        "C",
        (),
        {"keycloak": type("K", (), {"hostname": "kc.example.org"})()},
    )()
    realm = "llmoxie"
    return (
        patch(
            "llmaven.deployment.keycloak_users.open_admin_client",
            return_value=(_client(handler), realm),
        ),
        config,
    )


def _csv(tmp_path) -> Path:
    f = tmp_path / "team.csv"
    f.write_text("email\nnew@x.org\nold@x.org\n")
    return f


def _handler(posts):
    def handler(request):
        if request.method == "GET":
            found = request.url.params["email"] == "old@x.org"
            return httpx.Response(200, json=[{}] if found else [])
        posts.append(request)
        return httpx.Response(201)

    return handler


def test_cli_never_prints_a_password(tmp_path):
    posts = []
    out = tmp_path / "out.csv"
    p, _ = _cli_env(_handler(posts))
    with p:
        result = CliRunner().invoke(
            app,
            [
                "infra",
                "keycloak-users",
                "--csv",
                str(_csv(tmp_path)),
                "--out",
                str(out),
                "--yes",
            ],
        )
    assert result.exit_code == 0, result.output
    password = out.read_text().splitlines()[1].split(",")[1]
    assert password and password not in result.stdout + result.stderr
    assert str(out) in result.stdout
    assert len(posts) == 1


def test_confirmation_declined_creates_nothing(tmp_path):
    posts = []
    out = tmp_path / "out.csv"
    p, _ = _cli_env(_handler(posts))
    with p:
        result = CliRunner().invoke(
            app,
            [
                "infra",
                "keycloak-users",
                "--csv",
                str(_csv(tmp_path)),
                "--out",
                str(out),
            ],
            input="n\n",
        )
    assert result.exit_code != 0
    assert posts == [] and not out.exists()


def test_dry_run_creates_nothing(tmp_path):
    posts = []
    out = tmp_path / "no-such-dir" / "out.csv"
    p, _ = _cli_env(_handler(posts))
    with p:
        result = CliRunner().invoke(
            app,
            [
                "infra",
                "keycloak-users",
                "--csv",
                str(_csv(tmp_path)),
                "--out",
                str(out),
                "--dry-run",
            ],
        )
    assert result.exit_code == 0, result.output
    assert posts == [] and not out.exists()
    assert "1 to create" in result.stdout


def test_cli_without_email_column_creates_nothing(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("name\nAlice\n")
    out = tmp_path / "out.csv"
    result = CliRunner().invoke(
        app,
        ["infra", "keycloak-users", "--csv", str(f), "--out", str(out), "--yes"],
    )
    assert result.exit_code == 1
    assert "email" in result.stderr and not out.exists()


def test_failure_midway_reports_created_and_not_attempted(tmp_path):
    out = tmp_path / "out.csv"

    def handler(request):
        email = json.loads(request.content)["email"]
        return httpx.Response(500 if email == "b@x.org" else 201)

    with pytest.raises(KeycloakUsersError) as e:
        create_users(_client(handler), REALM, ["a@x.org", "b@x.org", "c@x.org"], out)
    msg = str(e.value)
    assert "1 created" in msg and str(out) in msg
    assert "failed at b@x.org" in msg and "not attempted: c@x.org" in msg
    assert out.read_text().splitlines()[1].startswith("a@x.org,")


def test_timeout_on_post_says_state_is_unknown(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    out = tmp_path / "out.csv"
    with pytest.raises(KeycloakUsersError, match="unknown"):
        create_users(_client(handler), REALM, ["a@x.org"], out)
    assert not out.exists()


def test_connect_error_on_lookup_is_a_clear_error():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(KeycloakUsersError, match="a@x.org"):
        plan_users(_client(handler), REALM, ["a@x.org"])


def test_cli_lists_addresses_in_dry_run(tmp_path):
    p, _ = _cli_env(_handler([]))
    with p:
        result = CliRunner().invoke(
            app,
            [
                "infra",
                "keycloak-users",
                "--csv",
                str(_csv(tmp_path)),
                "--out",
                str(tmp_path / "o.csv"),
                "--dry-run",
            ],
        )
    assert "new@x.org" in result.stdout and "old@x.org" in result.stdout


def test_cli_all_conflicts_does_not_announce_a_password_file(tmp_path):
    out = tmp_path / "out.csv"

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(409)

    p, _ = _cli_env(handler)
    with p:
        result = CliRunner().invoke(
            app,
            [
                "infra",
                "keycloak-users",
                "--csv",
                str(_csv(tmp_path)),
                "--out",
                str(out),
                "--yes",
            ],
        )
    assert result.exit_code == 0
    assert "already existed" in result.stdout and "new@x.org" in result.stdout
    assert "Temporary passwords" not in result.stdout and not out.exists()


# --- open_admin_client -------------------------------------------------


class _Cfg:
    def __init__(self, enabled=True, hostname="kc.example.org"):
        self.keycloak = type(
            "K",
            (),
            {
                "enabled": enabled,
                "hostname": hostname,
                "realm": type("R", (), {"name": "llmoxie"})(),
            },
        )()
        self.project = type(
            "P", (), {"enable_passphrase": False, "name": "p", "environment": "dev"}
        )()
        self.azure = type("A", (), {"subscription_id": "sub-1"})()


def _patch_open(cfg, outputs, az_calls):
    stack = type("S", (), {"outputs": lambda self: outputs})()

    def az(args, check=True, subscription_id=None):
        az_calls.append((args, subscription_id))
        return type("R", (), {"stdout": ADMIN_PASSWORD + "\n"})()

    return (
        patch("llmaven.infrastructure.config.loader.load_config", return_value=cfg),
        patch("llmaven.deployment.deploy.get_stack", return_value=stack),
        patch("llmaven.deployment.deploy._run_az_command", side_effect=az),
    )


@pytest.mark.parametrize("cfg", [_Cfg(enabled=False), _Cfg(hostname=None)])
def test_open_admin_client_needs_keycloak_and_hostname(cfg):
    ps = _patch_open(cfg, {}, [])
    with ps[0], ps[1], ps[2], pytest.raises(KeycloakUsersError, match="hostname"):
        open_admin_client(Path("c.yaml"))


def test_open_admin_client_needs_key_vault_output():
    ps = _patch_open(_Cfg(), {}, [])
    with ps[0], ps[1], ps[2], pytest.raises(KeycloakUsersError, match="key_vault_name"):
        open_admin_client(Path("c.yaml"))


def test_open_admin_client_token_az_args_and_refresh_on_401():
    az_calls, token_forms, seen = [], [], []
    issued = iter(["tok1", "tok2"])

    def handler(request):
        if request.url.path == "/realms/master/protocol/openid-connect/token":
            token_forms.append(dict(httpx.QueryParams(request.content.decode())))
            return httpx.Response(200, json={"access_token": next(issued)})
        seen.append(request.headers["authorization"])
        return httpx.Response(401 if len(seen) == 1 else 200, json=[])

    out = {"key_vault_name": type("O", (), {"value": "kv-1"})()}
    ps = _patch_open(_Cfg(), out, az_calls)
    with ps[0], ps[1], ps[2]:
        client, realm = open_admin_client(
            Path("c.yaml"), transport=httpx.MockTransport(handler)
        )
    assert realm == "llmoxie"
    args, sub = az_calls[0]
    assert args[:4] == ["keyvault", "secret", "show", "--vault-name"]
    assert "kv-1" in args and "keycloak-admin-password" in args
    assert args[-4:] == ["--query", "value", "-o", "tsv"] and sub == "sub-1"
    assert client.get("/admin/realms/llmoxie/users").status_code == 200
    assert seen == ["Bearer tok1", "Bearer tok2"]
    assert (
        token_forms
        == [
            {
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": "admin",
                "password": ADMIN_PASSWORD,
            }
        ]
        * 2
    )


def test_open_admin_client_unexpected_token_body_is_a_clear_error():
    out = {"key_vault_name": type("O", (), {"value": "kv-1"})()}
    ps = _patch_open(_Cfg(), out, [])
    with ps[0], ps[1], ps[2]:
        client, _ = open_admin_client(
            Path("c.yaml"),
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text="<html>login</html>")
            ),
        )
        with pytest.raises(KeycloakUsersError, match="token") as e:
            client.get("/admin/realms/llmoxie/users")
    assert ADMIN_PASSWORD not in str(e.value)


def _auth_client(handler, fetch) -> httpx.Client:
    return httpx.Client(
        base_url="https://kc.example.org",
        auth=_AdminAuth(fetch),
        transport=httpx.MockTransport(handler),
    )


def test_token_refresh_failure_midway_is_reported_like_any_failure(tmp_path):
    tokens = iter(["t1"])

    def fetch():
        try:
            return next(tokens)
        except StopIteration:
            raise KeycloakUsersError("Getting the admin token failed with HTTP 503")

    def handler(request):
        email = json.loads(request.content)["email"]
        if email == "a@x.org":
            return httpx.Response(409)
        if email == "b@x.org":
            return httpx.Response(201)
        return httpx.Response(401)

    out = tmp_path / "out.csv"
    with pytest.raises(KeycloakUsersError) as e:
        create_users(
            _auth_client(handler, fetch),
            REALM,
            ["a@x.org", "b@x.org", "c@x.org", "d@x.org"],
            out,
        )
    msg = str(e.value)
    assert "1 created" in msg and str(out) in msg
    assert "failed at c@x.org" in msg and "503" in msg
    assert "not attempted: d@x.org" in msg
    assert "already existed: a@x.org" in msg


def test_token_refresh_failure_with_nothing_created_removes_out(tmp_path):
    def fetch():
        raise KeycloakUsersError("Getting the admin token failed with HTTP 503")

    out = tmp_path / "out.csv"
    with pytest.raises(KeycloakUsersError, match="no password file kept"):
        create_users(
            _auth_client(lambda r: httpx.Response(201), fetch), REALM, ["a@x.org"], out
        )
    assert not out.exists()


def test_persistent_401_is_bounded_and_names_the_cause(tmp_path):
    requests, fetches = [], []

    def fetch():
        fetches.append(1)
        return f"t{len(fetches)}"

    def handler(request):
        requests.append(request)
        return httpx.Response(401)

    with pytest.raises(KeycloakUsersError, match="admin token was refused"):
        create_users(
            _auth_client(handler, fetch), REALM, ["a@x.org"], tmp_path / "o.csv"
        )
    assert len(requests) == 2 and len(fetches) == 2
