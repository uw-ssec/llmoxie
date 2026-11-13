"""Host-based Traefik config for the standalone edge."""

import yaml

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources.traefik import (
    EDGE_PING_ENTRYPOINT,
    EDGE_PING_PATH,
    build_edge_dynamic_config,
    build_edge_static_args,
    edge_policy_digest,
    render_edge_dynamic_config,
)

from .test_edge_config import LITELLM_HOST, MLFLOW_HOST, _config

BACKENDS = {
    "litellm": "https://litellm.internal.env.test",
    "mlflow": "https://mlflow.internal.env.test",
}


def _cfg(admin_ips=("203.0.113.0/24",), **kwargs) -> LLMavenConfig:
    litellm = {"admin_allowed_ips": list(admin_ips), **kwargs.pop("litellm", {})}
    return _config(litellm=litellm, **kwargs)


def _http(config=None, backends=None) -> dict:
    return build_edge_dynamic_config(config or _cfg(), backends or BACKENDS)["http"]


def _litellm_routers(http: dict) -> dict:
    return {k: v for k, v in http["routers"].items() if k.startswith("litellm")}


def test_litellm_routes_are_exact_paths_on_its_host():
    config = _cfg()
    routers = _litellm_routers(_http(config))
    for name, paths in (
        ("litellm-health", config.litellm.health_paths),
        ("litellm-public", config.litellm.public_paths),
    ):
        expected = " || ".join(f"Path(`{p}`)" for p in paths)
        assert routers[name]["rule"] == f"Host(`{LITELLM_HOST}`) && ({expected})"
    for router in _http()["routers"].values():
        assert "PathPrefix(`/v1" not in router["rule"]
        assert "PathPrefix(`/health" not in router["rule"]


def test_litellm_catch_all_is_admin_only():
    http = _http()
    admin = http["routers"]["litellm-admin"]
    assert admin["rule"] == f"Host(`{LITELLM_HOST}`)"
    assert admin["middlewares"] == ["litellm-admin-ip-allowlist", "client-rate-limit"]
    assert admin["priority"] == min(r["priority"] for r in _litellm_routers(http).values())
    allow = http["middlewares"]["litellm-admin-ip-allowlist"]["ipAllowList"]
    assert allow["sourceRange"] == ["203.0.113.0/24"]

    empty = _http(_cfg(admin_ips=()))
    allow = empty["middlewares"]["litellm-admin-ip-allowlist"]["ipAllowList"]
    assert allow["sourceRange"] == ["127.0.0.1/32"]


def test_public_routes_are_rate_limited_and_health_is_not():
    routers = _litellm_routers(_http())
    assert "middlewares" not in routers["litellm-health"]
    assert routers["litellm-public"]["middlewares"] == ["client-rate-limit"]
    limit = _http()["middlewares"]["client-rate-limit"]["rateLimit"]
    assert (limit["average"], limit["burst"], limit["period"]) == (50, 100, "1s")


def test_mlflow_host_is_open():
    routers = {k: v for k, v in _http()["routers"].items() if k.startswith("mlflow")}
    assert list(routers) == ["mlflow"]
    assert routers["mlflow"]["rule"] == f"Host(`{MLFLOW_HOST}`)"
    assert "middlewares" not in routers["mlflow"]


def test_only_configured_hosts_are_routed():
    rules = [r["rule"] for r in _http()["routers"].values()]
    assert rules
    for rule in rules:
        assert rule.startswith((f"Host(`{LITELLM_HOST}`)", f"Host(`{MLFLOW_HOST}`)"))


def test_backends_are_internal_and_do_not_pass_host():
    services = _http()["services"]
    assert set(services) == {"litellm", "mlflow"}
    for name, service in services.items():
        lb = service["loadBalancer"]
        assert lb["servers"] == [{"url": BACKENDS[name]}]
        assert lb["passHostHeader"] is False
        assert lb["responseForwarding"]["flushInterval"] == "100ms"


def test_disabled_backend_has_no_routes():
    config = _cfg(litellm={"enabled": False})
    http = _http(config, {"mlflow": BACKENDS["mlflow"]})
    assert "litellm" not in yaml.safe_dump(http).lower()
    assert set(http["services"]) == {"mlflow"}


def test_client_ip_comes_from_rightmost_forwarded_entry():
    http = _http()
    strategies = [
        http["middlewares"]["litellm-admin-ip-allowlist"]["ipAllowList"]["ipStrategy"],
        http["middlewares"]["client-rate-limit"]["rateLimit"]["sourceCriterion"][
            "ipStrategy"
        ],
    ]
    assert strategies == [{"depth": 1}, {"depth": 1}]


def test_static_args_trust_only_configured_peers_and_ping_is_separate():
    args = build_edge_static_args(_cfg().edge)
    assert "--entryPoints.web.address=:8080" in args
    assert "--entryPoints.web.forwardedHeaders.trustedIPs=172.16.0.0/23" in args
    assert "--entryPoints.web.transport.respondingTimeouts.readTimeout=300s" in args
    assert f"--entryPoints.{EDGE_PING_ENTRYPOINT}.address=:8082" in args
    assert "--ping=true" in args
    assert f"--ping.entryPoint={EDGE_PING_ENTRYPOINT}" in args
    assert EDGE_PING_PATH == "/ping"
    assert "--providers.file.watch=false" in args
    assert not any(a.startswith("--api") for a in args)


def test_access_log_forwarded_for_is_opt_in():
    assert "--accessLog.format=json" not in build_edge_static_args(_cfg().edge)
    on = _cfg(edge={"log_forwarded_for": True}).edge
    assert "--accessLog.format=json" in build_edge_static_args(on)


def test_rendered_config_is_yaml_of_the_built_config():
    config = _cfg()
    assert yaml.safe_load(render_edge_dynamic_config(config, BACKENDS)) == (
        build_edge_dynamic_config(config, BACKENDS)
    )


def test_edge_digest_changes_with_policy():
    before, after = _cfg(), _cfg(admin_ips=())
    digests = [
        edge_policy_digest(c.edge, render_edge_dynamic_config(c, BACKENDS))
        for c in (before, after)
    ]
    assert digests[0] != digests[1]
