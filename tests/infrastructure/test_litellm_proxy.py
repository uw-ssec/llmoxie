"""Optional Traefik sidecar in front of LiteLLM (issue #214)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml
from pydantic import ValidationError

from llmaven.infrastructure.config.schema import (
    DEFAULT_HEALTH_PATHS,
    DEFAULT_PUBLIC_PATHS,
    LLMavenConfig,
)
from llmaven.infrastructure.resources import container_apps, helpers, traefik

LITELLM_CONFIG = Path(__file__).parents[2] / "docker" / "config.yaml"

# Layout of the deployed llmaven-deploy stacks; 2 vCPU / 4Gi as in their configs.
EXISTING_STACK = {
    "networking": {
        "vnet_address_space": "172.16.0.0/16",
        "container_apps_subnet": "172.16.0.0/23",
        "postgres_subnet": "172.16.2.0/24",
    },
}


def _config(proxy: dict | None = None, **litellm) -> LLMavenConfig:
    litellm = {"cpu": 2, "memory": "4Gi", **litellm}
    if proxy is not None:
        litellm["proxy"] = proxy
    return LLMavenConfig.model_validate({**EXISTING_STACK, "litellm": litellm})


def _create(config: LLMavenConfig):
    """Run create_litellm_app and return the ContainerApp keyword arguments."""
    with (
        patch.object(
            container_apps.azure_native.app,
            "ContainerApp",
            return_value=SimpleNamespace(name="app", configuration=Mock()),
        ) as create_app,
        patch.object(container_apps.pulumi, "export"),
    ):
        helpers.create_litellm_app(
            name="llmaven-dev-litellm",
            resource_group_name="rg",
            location="westus2",
            container_env_id="env-id",
            container_env_name="env",
            image="example.test/litellm:1",
            port=config.litellm.port,
            cpu=config.litellm.cpu,
            memory=config.litellm.memory,
            min_replicas=1,
            max_replicas=2,
            env_vars={},
            key_vault=SimpleNamespace(properties=SimpleNamespace(vault_uri=Mock())),
            key_vault_secret_refs={},
            config_file=str(LITELLM_CONFIG),
            proxy=config.litellm.proxy,
            ip_security_restrictions=config.litellm.ip_security_restrictions,
            revision_suffix=config.litellm.revision_suffix,
            refresh_trigger=config.litellm.refresh_trigger,
        )
    return create_app.call_args.kwargs


# --- schema -----------------------------------------------------------------


def test_proxy_is_off_by_default():
    config = LLMavenConfig()
    assert config.litellm.proxy.enabled is False
    assert config.litellm.ip_security_restrictions == []
    assert not hasattr(config.mlflow, "ip_security_restrictions")
    assert "@sha256:" in config.litellm.proxy.image


def test_trusted_proxy_ips_default_to_container_apps_subnet():
    config = _config({"enabled": True})
    assert config.litellm.proxy.trusted_proxy_ips == ["172.16.0.0/23"]


def test_explicit_trusted_proxy_ips_are_kept():
    config = _config({"enabled": True, "trusted_proxy_ips": ["100.100.0.0/16"]})
    assert config.litellm.proxy.trusted_proxy_ips == ["100.100.0.0/16"]


def test_proxy_port_must_differ_from_litellm_port():
    with pytest.raises(ValidationError, match="must differ"):
        _config({"enabled": True, "port": 4000})


@pytest.mark.parametrize(
    ("litellm", "proxy"),
    [
        ({"cpu": 2, "memory": "4Gi"}, {"cpu": 0.25, "memory": "1Gi"}),
        ({"cpu": 4, "memory": "8Gi"}, {}),
    ],
)
def test_invalid_consumption_total_is_rejected(litellm, proxy):
    with pytest.raises(ValidationError, match="Consumption"):
        _config({"enabled": True, **proxy}, **litellm)


def test_valid_consumption_total_is_accepted():
    _config({"enabled": True})  # 2.25 vCPU / 4.5Gi


def test_totals_are_not_checked_while_proxy_is_disabled():
    _config(cpu=4, memory="8Gi")


def test_empty_health_paths_are_rejected_when_enabled():
    with pytest.raises(ValidationError, match="health_paths"):
        _config({"enabled": True, "health_paths": []})


@pytest.mark.parametrize(
    "proxy",
    [
        {"admin_allowed_ips": ["not-an-ip"]},
        {"trusted_proxy_ips": ["10.0.0.0/33"]},
        {"public_paths": ["v1/chat/completions"]},
        {"public_paths": ["/v1/x`) || PathPrefix(`/"]},
    ],
)
def test_invalid_proxy_values_are_rejected(proxy):
    with pytest.raises(ValidationError):
        _config(proxy)


def test_invalid_ip_security_restriction_is_rejected():
    with pytest.raises(ValidationError):
        _config(ip_security_restrictions=[{"name": "x", "ip_address_range": "bad"}])


# --- proxy disabled: unchanged template --------------------------------------


def test_disabled_proxy_keeps_single_container_template():
    kwargs = _create(_config())
    ingress = kwargs["configuration"].ingress
    [container] = kwargs["template"].containers

    assert ingress.target_port == 4000
    assert ingress.ip_security_restrictions is None
    assert container.args == ["--config", "/app/config/config.yaml"]
    assert [v.name for v in kwargs["template"].volumes] == ["litellm-config-volume"]
    assert traefik.TRAEFIK_DYNAMIC_SECRET not in {
        s.name for s in kwargs["configuration"].secrets
    }
    liveness, readiness, startup = container.probes
    assert liveness.tcp_socket.port == 4000 and liveness.http_get is None
    assert readiness.tcp_socket.port == 4000 and readiness.http_get is None
    assert startup.http_get.port == 4000
    assert startup.http_get.path == "/health/liveliness"


# --- proxy enabled -----------------------------------------------------------


def test_enabled_proxy_adds_sidecar_and_moves_ingress():
    config = _config({"enabled": True, "admin_allowed_ips": ["203.0.113.0/24"]})
    kwargs = _create(config)
    ingress = kwargs["configuration"].ingress
    litellm, sidecar = kwargs["template"].containers

    assert ingress.target_port == 8080
    assert litellm.args == [
        "--config",
        "/app/config/config.yaml",
        "--host",
        "127.0.0.1",
    ]
    assert sidecar.name == "traefik"
    assert sidecar.image == config.litellm.proxy.image
    assert (sidecar.resources.cpu, sidecar.resources.memory) == (0.25, "0.5Gi")


def test_litellm_probes_go_through_the_proxy_health_route():
    litellm, sidecar = _create(_config({"enabled": True}))["template"].containers

    for probe in litellm.probes:
        assert probe.tcp_socket is None
        assert probe.http_get.port == 8080
        assert probe.http_get.path == "/health/liveliness"
    assert [p.type for p in litellm.probes] == ["Liveness", "Readiness", "Startup"]
    assert {p.tcp_socket.port for p in sidecar.probes} == {8080}


def test_sidecar_mounts_only_its_own_config():
    kwargs = _create(_config({"enabled": True}))
    litellm, sidecar = kwargs["template"].containers
    volumes = {v.name: v for v in kwargs["template"].volumes}

    [mount] = sidecar.volume_mounts
    assert mount.volume_name == traefik.TRAEFIK_VOLUME_NAME
    assert [i.secret_ref for i in volumes[mount.volume_name].secrets] == [
        traefik.TRAEFIK_DYNAMIC_SECRET
    ]
    assert [m.volume_name for m in litellm.volume_mounts] == ["litellm-config-volume"]


def test_mounted_dynamic_config_matches_builder():
    config = _config({"enabled": True, "admin_allowed_ips": ["203.0.113.0/24"]})
    secrets = {s.name: s for s in _create(config)["configuration"].secrets}
    mounted = yaml.safe_load(secrets[traefik.TRAEFIK_DYNAMIC_SECRET].value)
    assert mounted == traefik.build_dynamic_config(config.litellm.proxy, 4000)


@pytest.mark.parametrize("action", ["Allow", "Deny"])
def test_ip_security_restrictions_pass_through(action):
    config = _config(
        ip_security_restrictions=[
            {"name": "a", "ip_address_range": "198.51.100.0/24", "action": action},
            {
                "name": "b",
                "ip_address_range": "192.0.2.1/32",
                "action": action,
                "description": "note",
            },
        ]
    )
    rules = _create(config)["configuration"].ingress.ip_security_restrictions
    assert [(r.name, r.ip_address_range, r.action, r.description) for r in rules] == [
        ("a", "198.51.100.0/24", action, None),
        ("b", "192.0.2.1/32", action, "note"),
    ]


def test_mixed_ip_security_actions_are_rejected():
    with pytest.raises(ValidationError, match="same action"):
        _config(
            ip_security_restrictions=[
                {"name": "a", "ip_address_range": "198.51.100.0/24"},
                {"name": "b", "ip_address_range": "192.0.2.1/32", "action": "Deny"},
            ]
        )


def test_ipv6_ip_security_restriction_is_rejected():
    with pytest.raises(ValidationError, match="IPv4"):
        _config(
            ip_security_restrictions=[
                {"name": "v6", "ip_address_range": "2001:db8::/32"}
            ]
        )


# --- policy changes roll a new revision --------------------------------------


def _traefik_digest(kwargs) -> str:
    sidecar = kwargs["template"].containers[1]
    [env] = sidecar.env
    assert env.name == traefik.POLICY_DIGEST_ENV
    return env.value


def test_policy_digest_matches_mounted_config():
    config = _config({"enabled": True})
    kwargs = _create(config)
    secrets = {s.name: s.value for s in kwargs["configuration"].secrets}
    assert _traefik_digest(kwargs) == traefik.policy_digest(
        config.litellm.proxy, secrets[traefik.TRAEFIK_DYNAMIC_SECRET]
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # README step 5: turn the staging diagnostics off again.
        ({"log_forwarded_for": True}, {"log_forwarded_for": False}),
        # README step 4 mitigation: narrow the trusted peers.
        ({}, {"trusted_proxy_ips": ["172.16.0.4/32"]}),
        ({}, {"cpu": 0.5, "memory": "1Gi"}),
        ({}, {"image": "docker.io/library/traefik:v3.7.18@sha256:" + "0" * 64}),
    ],
)
def test_static_proxy_changes_roll_pinned_suffix(before, after):
    def suffix(proxy: dict) -> str:
        litellm = {"cpu": 1.75, "memory": "3.5Gi"} if "cpu" in proxy else {}
        config = _config(
            {"enabled": True, **proxy},
            revision_suffix="review",
            refresh_trigger="fixed",
            **litellm,
        )
        kwargs = _create(config)
        return kwargs["template"].revision_suffix, _traefik_digest(kwargs)

    (suffix_before, digest_before), (suffix_after, digest_after) = (
        suffix(before),
        suffix(after),
    )
    assert suffix_before != suffix_after
    assert digest_before != digest_after


def test_revoking_admin_ips_changes_template_with_fixed_refresh_trigger():
    # A secret update alone does not restart the revision, so revocation must
    # change the template even when REFRESH_TRIGGER is pinned.
    granted = _create(
        _config(
            {"enabled": True, "admin_allowed_ips": ["203.0.113.0/24"]},
            refresh_trigger="fixed",
        )
    )
    revoked = _create(_config({"enabled": True}, refresh_trigger="fixed"))

    assert _traefik_digest(granted) != _traefik_digest(revoked)
    assert granted["template"].revision_suffix is None
    litellm_env = {e.name: e.value for e in revoked["template"].containers[0].env}
    assert litellm_env["REFRESH_TRIGGER"] == "fixed"


def test_pinned_revision_suffix_follows_policy():
    def suffix(**proxy) -> str:
        config = _config(
            {"enabled": True, **proxy},
            revision_suffix="v2026-11-5",
            refresh_trigger="x",
        )
        return _create(config)["template"].revision_suffix

    granted = suffix(admin_allowed_ips=["203.0.113.0/24"])
    assert granted.startswith("v2026-11-5-p") and len(granted) == len("v2026-11-5") + 10
    assert granted == suffix(admin_allowed_ips=["203.0.113.0/24"])  # stable
    assert granted != suffix()  # revoked


def test_pinned_revision_suffix_is_untouched_without_proxy():
    config = _config(revision_suffix="v2026-11-5")
    assert _create(config)["template"].revision_suffix == "v2026-11-5"


def test_too_long_revision_suffix_is_rejected_with_proxy():
    with pytest.raises(ValidationError, match="54 characters"):
        _config({"enabled": True}, revision_suffix="a" * 55)
    _config({"enabled": True}, revision_suffix="a" * 54)


# --- Traefik configuration ---------------------------------------------------


def _dynamic(**proxy) -> dict:
    config = _config({"enabled": True, **proxy})
    return traefik.build_dynamic_config(config.litellm.proxy, 4000)["http"]


def test_routing_is_an_allowlist_of_exact_paths():
    routers = _dynamic()["routers"]

    for path in DEFAULT_PUBLIC_PATHS:
        assert f"Path(`{path}`)" in routers["litellm-public"]["rule"]
    for path in DEFAULT_HEALTH_PATHS:
        assert f"Path(`{path}`)" in routers["litellm-health"]["rule"]
    assert "PathPrefix" not in routers["litellm-public"]["rule"]
    assert "PathPrefix" not in routers["litellm-health"]["rule"]

    admin = routers["litellm-admin"]
    assert admin["rule"] == "PathPrefix(`/`)"
    assert admin["middlewares"][0] == "admin-ip-allowlist"
    # The catch-all must lose to every explicit router.
    assert admin["priority"] < routers["litellm-public"]["priority"]
    assert admin["priority"] < routers["litellm-health"]["priority"]


def test_admin_surface_is_closed_without_admin_ips():
    allowlist = _dynamic()["middlewares"]["admin-ip-allowlist"]["ipAllowList"]
    assert allowlist["sourceRange"] == ["127.0.0.1/32"]


def test_client_ip_comes_from_rightmost_forwarded_entry():
    middlewares = _dynamic(admin_allowed_ips=["203.0.113.0/24"])["middlewares"]
    allowlist = middlewares["admin-ip-allowlist"]["ipAllowList"]
    rate_limit = middlewares["client-rate-limit"]["rateLimit"]

    assert allowlist["sourceRange"] == ["203.0.113.0/24"]
    assert allowlist["ipStrategy"] == {"depth": 1}
    assert rate_limit["sourceCriterion"]["ipStrategy"] == {"depth": 1}


def test_public_routes_are_rate_limited_and_health_is_not():
    routers = _dynamic()["routers"]
    assert routers["litellm-public"]["middlewares"] == ["client-rate-limit"]
    assert "middlewares" not in routers["litellm-health"]


def test_backend_is_localhost_and_streams():
    service = _dynamic()["services"]["litellm"]["loadBalancer"]
    assert service["servers"] == [{"url": "http://127.0.0.1:4000"}]
    assert service["responseForwarding"]["flushInterval"] == "100ms"


def test_static_args_trust_only_configured_peers_and_disable_api():
    config = _config({"enabled": True})
    args = traefik.build_static_args(config.litellm.proxy)

    assert "--entryPoints.web.address=:8080" in args
    assert "--entryPoints.web.forwardedHeaders.trustedIPs=172.16.0.0/23" in args
    assert "--providers.file.filename=/etc/traefik/dynamic/dynamic.yaml" in args
    assert not any(
        a.startswith(("--api", "--ping", "--providers.docker")) for a in args
    )
    assert not any("insecure" in a for a in args)
    assert not any("accessLog.fields" in a for a in args)
    assert not any("accessLog.format" in a for a in args)


def test_forwarded_for_logging_keeps_only_xff():
    config = _config({"enabled": True, "log_forwarded_for": True})
    args = traefik.build_static_args(config.litellm.proxy)

    assert "--accessLog.format=json" in args
    assert "--accessLog.fields.headers.defaultMode=drop" in args
    assert "--accessLog.fields.headers.names.X-Forwarded-For=keep" in args
    kept = [a for a in args if a.endswith("=keep")]
    assert kept == ["--accessLog.fields.headers.names.X-Forwarded-For=keep"]
