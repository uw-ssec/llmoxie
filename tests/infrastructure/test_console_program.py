"""Run the whole Pulumi program under mocks to check the console wiring."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from llmaven.infrastructure import resources
from llmaven.infrastructure.config.schema import (
    CONSOLE_BROKER_APP_SUFFIX,
    CONSOLE_DB,
    CONSOLE_WEB_APP_SUFFIX,
    console_job_name,
    container_app_name,
    realm_job_name,
)
from llmaven.infrastructure.resources import console as console_module
from llmaven.infrastructure.resources import (
    SecretsManager,
    console_mail,
    console_secrets,
)

from . import PINNED_CONSOLE_IMAGE
from .test_edge_program import LITELLM_HOST, _run
from .test_keycloak_program import KEYCLOAK_EDGE, _keycloak

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN = "litellm-admin.example.org"
CONSOLE_HOST = "console.example.org"
WEB = f"llmaven-dev-{CONSOLE_WEB_APP_SUFFIX}"
BROKER = f"llmaven-dev-{CONSOLE_BROKER_APP_SUFFIX}"
WEB_NAME = container_app_name("llmaven", "dev", CONSOLE_WEB_APP_SUFFIX)
POLICY = "apps-identity"


def _admin(**litellm):
    """The Keycloak config with the LiteLLM admin host on its own domain."""
    config = _keycloak(**litellm)
    config["edge"] = {
        **KEYCLOAK_EDGE,
        "custom_domains": [
            *KEYCLOAK_EDGE["custom_domains"],
            {"name": ADMIN, "certificate_name": "cert-admin"},
        ],
    }
    config["litellm"]["admin_hostname"] = ADMIN
    return config


def _console(**console):
    config = _admin()
    config["edge"]["custom_domains"].append(
        {"name": CONSOLE_HOST, "certificate_name": "cert-console"}
    )
    config["console"] = {
        "enabled": True,
        "hostname": CONSOLE_HOST,
        "image": PINNED_CONSOLE_IMAGE,
        "admin_subjects": ["00000000-0000-0000-0000-000000000001"],
        "mail": {"domain": "mail.example.org"},
        **console,
    }
    return config


@pytest.fixture(scope="module")
def console_run(tmp_path_factory):
    """(resources, exports, apps, calls) with the console on."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        calls: dict[str, dict] = {}
        for module, name in (
            (resources, "create_edge_app"),
            (console_module, "create_console"),
            (console_secrets, "create_console_secrets"),
            (console_mail, "create_console_mail"),
        ):
            real = getattr(module, name)

            def wrapper(*args, _real=real, _name=name, **kwargs):
                calls[_name] = kwargs
                result = calls[f"{_name}.result"] = _real(*args, **kwargs)
                return result

            monkeypatch.setattr(module, name, wrapper)
        real_keycloak = SecretsManager.create_keycloak_secrets

        def keycloak_spy(self, **kwargs):
            calls["create_keycloak_secrets"] = kwargs
            return real_keycloak(self, **kwargs)

        monkeypatch.setattr(SecretsManager, "create_keycloak_secrets", keycloak_spy)
        run = _run(tmp_path_factory.mktemp("console"), monkeypatch, **_console())
        return (*run, calls)


def _depends_on(kwargs) -> list[str]:
    return [d._name for d in kwargs["opts"].depends_on]


# --- the console off renders as the base code did ---------------------------


def _plain(value):
    """A JSON-ready copy: Azure input classes become their fields.

    A memory address in an object repr is dropped, as it changes per run; dict
    key order is fixed by ``sort_keys`` at dump time (it follows set iteration).
    """
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    cls = type(value)
    if cls.__module__.startswith("pulumi_azure_native") and cls.__name__.endswith(
        "Args"
    ):
        return {"__type__": cls.__name__, **_plain(vars(value))}
    return re.sub(r" at 0x[0-9a-f]+", "", repr(value))


def _dump(stubs) -> str:
    """The stubbed apps or jobs as the goldens were written (opts left out)."""
    return json.dumps(
        _plain(
            {n: {k: v for k, v in kw.items() if k != "opts"} for n, kw in stubs.items()}
        ),
        sort_keys=True,
        indent=1,
    )


def _golden_inputs(created):
    rows = sorted(
        (r.typ, r.name, json.dumps(r.inputs, sort_keys=True, default=repr))
        for r in created
    )
    return "".join(f"{t}\t{n}\t{i}\n" for t, n, i in rows)


def _off_run(tmp_path, monkeypatch):
    return _run(tmp_path, monkeypatch, **_keycloak())


def test_console_off_matches_the_base_render(tmp_path, monkeypatch):
    created, _, apps = _off_run(tmp_path, monkeypatch)
    assert (
        _golden_inputs(created)
        == (FIXTURES / "program_console_off_resources.txt").read_text()
    )
    assert (
        apps["llmaven-dev-traefik"]["resolved_secrets"]["traefik-dynamic-yaml"]
        == (FIXTURES / "program_console_off_edge.yaml").read_text()
    )
    assert _dump(apps) == (FIXTURES / "program_console_off_apps.json").read_text()
    assert _dump(apps.jobs) == (FIXTURES / "program_console_off_jobs.json").read_text()


def test_console_off_creates_nothing_of_the_console(tmp_path, monkeypatch):
    created, exports, apps = _off_run(tmp_path, monkeypatch)
    assert not [k for k in exports if k.startswith("console")]
    assert not [a for a in apps if "con-" in a]
    assert CONSOLE_DB not in {
        r.inputs.get("databaseName")
        for r in created
        if r.typ == "azure-native:dbforpostgresql:Database"
    }


# --- the console on ---------------------------------------------------------


def test_console_apps_and_jobs_exist(console_run):
    created, exports, apps, calls = console_run
    assert {WEB, BROKER} <= set(apps)
    jobs = apps.jobs
    db, init = (console_job_name("llmaven", "dev", k) for k in ("db", "init"))
    assert {db, init} <= set(jobs)
    assert exports["console_db_job"] == db
    assert exports["console_init_job"] == init
    secrets = {r._name for r in calls["create_console_secrets.result"].resources}
    assert secrets <= set(_depends_on(jobs[db]))
    assert any(POLICY in n for n in _depends_on(jobs[db]))
    assert any("console-run" in n for n in _depends_on(jobs[init]))
    databases = {
        r.inputs.get("databaseName")
        for r in created
        if r.typ == "azure-native:dbforpostgresql:Database"
    }
    assert CONSOLE_DB in databases


def test_console_is_wired_from_the_other_pieces(console_run):
    calls = console_run[3]
    secrets = calls["create_console_secrets"]
    assert secrets["mail_connection_string"] is not None
    assert secrets["admin_password"] is not None
    assert secrets["main_vault"] is not None
    console = calls["create_console"]
    assert console["sender_address"] == "console@mail.example.org"
    assert console["keycloak_fqdn"] is not None
    assert console["litellm_fqdn"] is not None
    assert POLICY in " ".join(_depends_on(console))


def test_one_admin_password_output_feeds_keycloak_and_the_console(console_run):
    calls = console_run[3]
    assert (
        calls["create_console_secrets"]["admin_password"]
        is calls["create_keycloak_secrets"]["admin_password"]
    )


def test_apps_wait_for_the_console_secrets(console_run):
    apps, calls = console_run[2], console_run[3]
    secrets = {r._name for r in calls["create_console_secrets.result"].resources}
    assert secrets
    for name in (WEB, BROKER):
        assert secrets <= set(_depends_on(apps[name])), name


def test_realm_job_waits_for_the_console_oidc_secret(console_run):
    """The realm job reads console-oidc-client-secret from the main vault."""
    apps, calls = console_run[2], console_run[3]
    oidc = f"kv-secret-console-main-{console_secrets.OIDC_SECRET}-dev"
    assert oidc in {r._name for r in calls["create_console_secrets.result"].resources}
    realm = apps.jobs[realm_job_name("llmaven", "dev")]
    assert oidc in [d._name for d in realm["opts"].depends_on]


def test_edge_gets_the_console_backend_and_waits_for_it(console_run):
    edge = console_run[3]["create_edge_app"]
    assert "console" in edge["backends"]
    waits = _depends_on(edge)
    assert {WEB, BROKER} <= set(waits)


def test_edge_routes_the_console_host_only_to_console(console_run):
    yaml_text = console_run[2]["llmaven-dev-traefik"]["resolved_secrets"][
        "traefik-dynamic-yaml"
    ]
    http = yaml.safe_load(yaml_text)["http"]
    router = http["routers"]["console"]
    assert router["rule"] == f"Host(`{CONSOLE_HOST}`)"
    assert router["middlewares"] == ["client-rate-limit"]
    assert router["service"] == "console"
    assert http["services"]["console"]["loadBalancer"]["servers"] == [
        {"url": f"https://{WEB}.internal.env.test"}
    ]
    others = [n for n, r in http["routers"].items() if CONSOLE_HOST in r["rule"]]
    assert others == ["console"]


def test_exports(console_run):
    exports = console_run[1]
    assert exports["console_url"] == f"https://{CONSOLE_HOST}"
    assert exports["console_db_job"] == console_job_name("llmaven", "dev", "db")
    assert exports["console_init_job"] == console_job_name("llmaven", "dev", "init")
    assert "console_mail_verification_records" in exports


def test_no_secret_value_is_exported(console_run):
    text = json.dumps(console_run[1], default=repr)
    # The verification records are public DNS values; everything else is a name.
    for needle in ("password", "accesskey", "AccountKey", "endpoint=", "sig="):
        assert needle not in text, needle


# --- LiteLLM's admin host (carried from the admin-host task) ----------------


def test_admin_hostname_sets_proxy_base_url_and_exports_it(tmp_path, monkeypatch):
    _, exports, apps = _run(tmp_path, monkeypatch, **_admin())
    env = apps["llmaven-dev-litellm"]["env_vars"]
    assert env["PROXY_BASE_URL"] == f"https://{ADMIN}"
    assert exports["litellm_admin_url"] == f"https://{ADMIN}"
    assert exports["litellm_url"] == f"https://{LITELLM_HOST}"


def test_without_admin_hostname_nothing_changes(tmp_path, monkeypatch):
    _, exports, apps = _run(tmp_path, monkeypatch, **_keycloak())
    env = apps["llmaven-dev-litellm"]["env_vars"]
    assert env["PROXY_BASE_URL"] == f"https://{LITELLM_HOST}"
    assert "litellm_admin_url" not in exports
    assert exports["litellm_url"] == f"https://{LITELLM_HOST}"
