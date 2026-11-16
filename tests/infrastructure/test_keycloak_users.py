"""keycloak-users: CSV parsing, planning, creating and the CLI, with no network."""

import json
import stat
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from llmaven.cli import app
from llmaven.deployment.keycloak_users import (
    KeycloakUsersError,
    create_users,
    plan_users,
    read_emails,
)

REALM = "llmoxie"


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


def test_conflict_counts_as_existing(tmp_path):
    out = tmp_path / "out.csv"
    n = create_users(
        _client(lambda r: httpx.Response(409)), REALM, ["a@x.org"], out
    )
    assert n == 0
    assert out.read_text().splitlines() == ["email,temporary_password"]


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
            ["infra", "keycloak-users", "--csv", str(_csv(tmp_path)), "--out", str(out)],
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
