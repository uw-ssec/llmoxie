"""Run the whole Pulumi program under mocks to check the edge wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pulumi
import pytest
import yaml

from llmaven.infrastructure.main import create_pulumi_program
from llmaven.infrastructure.resources import helpers

from .test_edge_app import _isolated_mocks

REPO_ROOT = Path(__file__).resolve().parents[2]
LITELLM_HOST = "ai.example.org"
MLFLOW_HOST = "mlflow.example.org"

EDGE = {
    "enabled": True,
    "trusted_proxy_ips": ["100.100.0.0/17"],
    "custom_domains": [
        {"name": LITELLM_HOST, "certificate_name": "cert-0"},
        {"name": MLFLOW_HOST, "certificate_name": "cert-1"},
    ],
}


class _Mocks(pulumi.runtime.Mocks):
    def __init__(self):
        self.resources: list[pulumi.runtime.MockResourceArgs] = []

    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        self.resources.append(args)
        # Only echo scalar inputs; nested input shapes differ from output types.
        outputs = {
            k: v for k, v in args.inputs.items() if isinstance(v, (str, int, bool))
        }
        if args.typ == "azure-native:storage:StorageAccount":
            outputs["primaryEndpoints"] = {"blob": "https://sa.blob.core.windows.net/"}
        if args.typ == "azure-native:keyvault:Vault":
            outputs["properties"] = {
                **outputs.get("properties", {}),
                "vaultUri": "https://kv.vault.azure.net/",
            }
        return f"{args.name}-id", outputs

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "azure-native:storage:listStorageAccountKeys":
            return {"keys": [{"keyName": "key1", "value": "storage-key"}]}
        if args.token == "azure-native:authorization:getClientConfig":
            return {
                "clientId": "c",
                "objectId": "00000000-0000-0000-0000-000000000000",
                "subscriptionId": "s",
                "tenantId": "00000000-0000-0000-0000-000000000000",
            }
        return {}


def _run(tmp_path: Path, monkeypatch, **overrides):
    """Run the program; return (resources, exports, container app kwargs)."""
    config = {
        "project": {"name": "llmaven", "environment": "dev", "location": "eastus"},
        "azure": {
            "subscription_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "resource_group": "rg-test",
        },
        "monitoring": {"enable_log_analytics": False},
        "litellm": {"config_file": str(REPO_ROOT / "docker" / "config.yaml")},
        **overrides,
    }
    config_path = tmp_path / "llmaven-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.delenv("PULUMI_CONFIG_PASSPHRASE", raising=False)

    # Container apps are stubbed: their identity input trips the mock
    # serializer. The fake mirrors the platform FQDN, which is internal
    # (".internal.") when the app's ingress is not external.
    apps: dict[str, dict] = {}

    def fake_create_app(**kwargs):
        apps[kwargs["app_name"]] = kwargs
        suffix = ".env.test" if kwargs.get("ingress_external") else ".internal.env.test"
        fqdn = f"{kwargs['app_name']}{suffix}"
        # A real resource, so the program can list it in depends_on.
        app = pulumi.ComponentResource("test:index:App", kwargs["app_name"])
        app.id = pulumi.Output.from_input(f"{kwargs['app_name']}-id")
        app.configuration = pulumi.Output.from_input(
            SimpleNamespace(ingress=SimpleNamespace(fqdn=fqdn))
        )
        return app

    monkeypatch.setattr(
        helpers, "create_container_app_with_key_vault_secrets", fake_create_app
    )

    exports: dict = {}
    monkeypatch.setattr(
        pulumi, "export", lambda name, value: exports.__setitem__(name, value)
    )

    mocks = _Mocks()
    with _isolated_mocks(mocks):
        program = create_pulumi_program(config_path)

        @pulumi.runtime.test
        def run():
            program()
            return pulumi.Output.all(**exports).apply(
                lambda resolved: exports.update(resolved)
            )

        run()
    return mocks.resources, exports, apps


def _with_edge(**litellm):
    return {
        "edge": EDGE,
        "litellm": {
            "config_file": str(REPO_ROOT / "docker" / "config.yaml"),
            "hostname": LITELLM_HOST,
            **litellm,
        },
        "mlflow": {"hostname": MLFLOW_HOST},
    }


@pytest.fixture(scope="module")
def with_edge(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        return _run(tmp_path_factory.mktemp("edge"), monkeypatch, **_with_edge())


def test_with_edge_backends_are_internal(with_edge):
    apps = with_edge[2]
    for name in ("llmaven-dev-litellm", "llmaven-dev-mlflow"):
        assert apps[name]["ingress_external"] is False
        assert not apps[name]["custom_domains"]


def test_with_edge_traefik_is_the_only_public_app(with_edge):
    public = [a for a in with_edge[2].values() if a["ingress_external"]]
    assert len(public) == 1
    assert public[0]["app_name"] == "llmaven-dev-traefik"
    assert {d.name for d in public[0]["custom_domains"]} == {LITELLM_HOST, MLFLOW_HOST}


def test_with_edge_tracking_uri_is_internal(with_edge):
    [secret] = [
        r
        for r in with_edge[0]
        if r.typ == "azure-native:keyvault:Secret"
        and r.inputs["secretName"] == "mlflow-tracking-uri"
    ]
    assert ".internal.env.test" in secret.inputs["properties"]["value"]


def test_with_edge_urls_are_public_hostnames(with_edge):
    exports = with_edge[1]
    assert exports["litellm_url"] == f"https://{LITELLM_HOST}"
    assert exports["mlflow_url"] == f"https://{MLFLOW_HOST}"
    assert exports["edge_url"] == "https://llmaven-dev-traefik.env.test"


def test_without_edge_apps_keep_public_ingress_and_sidecar(tmp_path, monkeypatch):
    _, exports, apps = _run(
        tmp_path,
        monkeypatch,
        litellm={
            "config_file": str(REPO_ROOT / "docker" / "config.yaml"),
            "proxy": {"enabled": True},
            "custom_domains": [{"name": LITELLM_HOST, "certificate_name": "cert-0"}],
        },
    )
    assert "llmaven-dev-traefik" not in apps
    assert apps["llmaven-dev-litellm"]["ingress_external"] is True
    assert apps["llmaven-dev-mlflow"]["ingress_external"] is True
    assert len(apps["llmaven-dev-litellm"]["sidecars"]) == 1
    assert exports["litellm_url"] == "https://llmaven-dev-litellm.env.test"
    assert exports["mlflow_url"] == "https://llmaven-dev-mlflow.env.test"
    assert "edge_url" not in exports


def test_with_edge_litellm_gets_its_public_url(with_edge):
    env = with_edge[2]["llmaven-dev-litellm"]["env_vars"]
    assert env["PROXY_BASE_URL"] == f"https://{LITELLM_HOST}"


def test_with_edge_litellm_waits_for_the_tracking_uri_secret(with_edge):
    opts = with_edge[2]["llmaven-dev-litellm"]["opts"]
    names = [d._name for d in opts.depends_on]
    assert any("mlflow-tracking-uri" in n for n in names)


def test_with_edge_operator_proxy_base_url_wins(tmp_path, monkeypatch):
    _, _, apps = _run(
        tmp_path,
        monkeypatch,
        **_with_edge(env_vars={"PROXY_BASE_URL": "https://other.example.org"}),
    )
    env = apps["llmaven-dev-litellm"]["env_vars"]
    assert env["PROXY_BASE_URL"] == "https://other.example.org"


def test_without_edge_litellm_has_no_proxy_base_url(tmp_path, monkeypatch):
    _, _, apps = _run(tmp_path, monkeypatch)
    assert "PROXY_BASE_URL" not in apps["llmaven-dev-litellm"]["env_vars"]
