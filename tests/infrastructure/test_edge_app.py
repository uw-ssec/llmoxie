"""The standalone Traefik edge Container App."""

import contextlib
from types import SimpleNamespace
from unittest.mock import patch

import pulumi
import pytest
import yaml
from pulumi._utils import ContextProperty

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources import container_apps, helpers, traefik

LITELLM_HOST = "ai.example.org"
MLFLOW_HOST = "mlflow.example.org"
BACKENDS = {"litellm": "litellm.internal.test", "mlflow": "mlflow.internal.test"}
URLS = {key: f"https://{fqdn}" for key, fqdn in BACKENDS.items()}


class _Mocks(pulumi.runtime.Mocks):
    def new_resource(self, args):
        return f"{args.name}-id", dict(args.inputs)

    def call(self, args):
        return {}


def _runtime_state() -> dict:
    """Every context-backed attribute of the global Pulumi runtime settings."""
    settings = pulumi.runtime.settings
    names = [
        name
        for name, attr in vars(type(settings.SETTINGS)).items()
        if isinstance(attr, ContextProperty)
    ]
    return {
        **{name: getattr(settings.SETTINGS, name) for name in names},
        "root": settings.ROOT.get(),
    }


@contextlib.contextmanager
def _isolated_mocks(mocks=None):
    """Run under Pulumi mocks, then put back the runtime settings and root.

    set_mocks overwrites the attributes of the global SETTINGS object in place,
    so a saved reference to it would see the mocks too; snapshot its attributes.
    """
    settings = pulumi.runtime.settings
    saved = _runtime_state()
    pulumi.runtime.set_mocks(
        mocks or _Mocks(), project="llmaven", stack="dev", preview=False
    )
    try:
        yield
    finally:
        saved_root = saved.pop("root")
        for name, value in saved.items():
            setattr(settings.SETTINGS, name, value)
        settings.ROOT.set(saved_root)


@pytest.fixture(autouse=True)
def _mocks():
    with _isolated_mocks():
        yield


def test_mocks_leave_the_runtime_settings_as_they_were():
    before = _runtime_state()
    with _isolated_mocks():
        assert pulumi.runtime.settings.SETTINGS.monitor is not before["monitor"]
    assert _runtime_state() == before


def _config(**edge) -> LLMavenConfig:
    return LLMavenConfig.model_validate(
        {
            "networking": {
                "vnet_address_space": "172.16.0.0/16",
                "container_apps_subnet": "172.16.0.0/23",
                "postgres_subnet": "172.16.2.0/24",
            },
            "edge": {
                "enabled": True,
                "trusted_proxy_ips": ["100.100.0.0/17"],
                "custom_domains": [
                    {"name": LITELLM_HOST, "certificate_name": "cert-0"},
                    {"name": MLFLOW_HOST, "certificate_name": "cert-1"},
                ],
                **edge,
            },
            "litellm": {"cpu": 2, "memory": "4Gi", "hostname": LITELLM_HOST},
            "mlflow": {"hostname": MLFLOW_HOST},
        }
    )


def _create(config: LLMavenConfig, backends: dict = BACKENDS) -> dict:
    """Run create_edge_app and return the ContainerApp kwargs, Outputs resolved."""
    captured: dict = {}

    @pulumi.runtime.test
    def run():
        with (
            patch.object(
                container_apps.azure_native.app,
                "ContainerApp",
                return_value=SimpleNamespace(
                    name="app", configuration=pulumi.Output.from_input(None)
                ),
            ) as create_app,
            patch.object(container_apps.pulumi, "export"),
        ):
            helpers.create_edge_app(
                name="llmaven-dev-traefik",
                resource_group_name="rg",
                location="westus2",
                container_env_id="env-id",
                config=config,
                backends={k: pulumi.Output.from_input(v) for k, v in backends.items()},
            )
        kwargs = create_app.call_args.kwargs
        container = kwargs["template"].containers[0]
        return pulumi.Output.all(
            secrets=[s.value for s in kwargs["configuration"].secrets],
            secret_names=[s.name for s in kwargs["configuration"].secrets],
            env={e.name: e.value for e in container.env},
            suffix=kwargs["template"].revision_suffix,
        ).apply(lambda r: captured.update(r, kwargs=kwargs, container=container))

    run()
    return captured


def test_edge_ingress_is_external_with_all_public_hostnames():
    config = _config()
    ingress = _create(config)["kwargs"]["configuration"].ingress
    assert ingress.external is True
    assert ingress.target_port == 8080
    assert [d.name for d in ingress.custom_domains] == [
        d.name for d in config.edge.custom_domains
    ]


def test_edge_probes_use_ping():
    probes = _create(_config())["container"].probes
    assert {p.type for p in probes} == {"Liveness", "Readiness", "Startup"}
    for probe in probes:
        assert probe.http_get.path == traefik.EDGE_PING_PATH == "/ping"
        assert probe.http_get.port == 8082


def test_edge_mounts_rendered_config():
    config = _config()
    result = _create(config)
    secrets = dict(zip(result["secret_names"], result["secrets"]))
    assert yaml.safe_load(secrets[traefik.TRAEFIK_DYNAMIC_SECRET]) == (
        traefik.build_edge_dynamic_config(config, URLS)
    )

    volumes = result["kwargs"]["template"].volumes
    assert [v.name for v in volumes] == [traefik.TRAEFIK_VOLUME_NAME]
    expected = traefik.build_traefik_volume()
    assert volumes[0].secrets[0].secret_ref == expected.secrets[0].secret_ref
    assert volumes[0].secrets[0].path == expected.secrets[0].path
    (mount,) = result["container"].volume_mounts
    assert mount.volume_name == traefik.TRAEFIK_VOLUME_NAME
    assert mount.mount_path == traefik.TRAEFIK_CONFIG_DIR
    assert result["container"].args == traefik.build_edge_static_args(config.edge)


def test_edge_template_carries_policy_digest():
    config = _config(revision_suffix="stable")
    result = _create(config)
    dynamic = result["secrets"][
        result["secret_names"].index(traefik.TRAEFIK_DYNAMIC_SECRET)
    ]
    digest = traefik.edge_policy_digest(config.edge, dynamic)
    assert result["env"][traefik.POLICY_DIGEST_ENV] == digest
    assert result["suffix"] == f"stable-p{digest[:8]}"


def test_edge_has_no_key_vault_secrets_or_identity():
    with patch.object(helpers.azure_native.keyvault, "AccessPolicy") as access_policy:
        result = _create(_config())
    kwargs = result["kwargs"]
    assert all(s.key_vault_url is None for s in kwargs["configuration"].secrets)
    assert all(s.identity is None for s in kwargs["configuration"].secrets)
    assert not kwargs["identity"].user_assigned_identities
    access_policy.assert_not_called()


def test_edge_with_only_mlflow_mounts_only_the_mlflow_route():
    config = _config()
    config.litellm.enabled = False
    backends = {"mlflow": BACKENDS["mlflow"]}
    result = _create(config, backends)
    secrets = dict(zip(result["secret_names"], result["secrets"]))
    mounted = yaml.safe_load(secrets[traefik.TRAEFIK_DYNAMIC_SECRET])
    assert mounted == traefik.build_edge_dynamic_config(
        config, {"mlflow": URLS["mlflow"]}
    )
    assert list(mounted["http"]["routers"]) == ["mlflow"]
    assert list(mounted["http"]["services"]) == ["mlflow"]
