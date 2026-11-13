"""Traefik path-level access control for LiteLLM, as a sidecar or a standalone edge.

Sidecar (``build_dynamic_config`` and friends): Container Apps ingress sends every request (platform FQDN and custom domains)
to Traefik, which forwards to LiteLLM on 127.0.0.1. Routing is an allowlist:

- health paths: public, not rate limited (the platform probes use them)
- public inference paths: public, rate limited per client IP
- everything else (admin UI, key/team/model/MCP management, other /health/*):
  only from ``admin_allowed_ips``, rate limited

TLS ends at the Container Apps Envoy, which appends the client IP as the
rightmost ``X-Forwarded-For`` entry. Traefik keeps that header only from
``trusted_proxy_ips`` (it deletes X-Forwarded-* from any other peer), and the
allowlist and rate limiter read the rightmost entry (``depth: 1``), so a
client-supplied X-Forwarded-For value is never used.

Edge (``build_edge_*``): a separate Container App is the only public entry
point. Routing is by ``Host``: only the configured LiteLLM and MLflow hostnames
match, so the edge's own FQDN and any other host get 404. LiteLLM keeps the
same path allowlist on its host; MLflow's host is open, as its ingress is.
Backends are reached by their internal FQDN without the original Host header.
"""

from __future__ import annotations

import hashlib
import json

import pulumi_azure_native as azure_native
import yaml

from ..config.schema import (
    POLICY_SUFFIX_LENGTH,
    EdgeConfig,
    LiteLLMProxyConfig,
    LLMavenConfig,
)

TRAEFIK_CONTAINER_NAME = "traefik"
TRAEFIK_VOLUME_NAME = "traefik-config-volume"
TRAEFIK_CONFIG_DIR = "/etc/traefik/dynamic"
TRAEFIK_DYNAMIC_FILE = "dynamic.yaml"
TRAEFIK_DYNAMIC_SECRET = "traefik-dynamic-yaml"
# The dynamic config is an app-level secret, and Container Apps does not
# restart revisions when a secret changes (Traefik's file watch is also off).
# A digest of it plus the sidecar's static settings goes into the template, so
# a policy change (such as revoking admin_allowed_ips) always rolls a new
# revision, and a pinned revision suffix changes whenever the sidecar does.
POLICY_DIGEST_ENV = "TRAEFIK_POLICY_SHA256"
ENTRYPOINT = "web"
EDGE_PING_PATH = "/ping"
EDGE_PING_ENTRYPOINT = "ping"

# Envoy appends the client address as the last X-Forwarded-For entry.
_CLIENT_IP_STRATEGY = {"depth": 1}

# With no admin IPs, the admin router still exists but matches no real client:
# Envoy never reports 127.0.0.1 as the client.
_NO_ADMIN_IPS = ["127.0.0.1/32"]


LOGIN_COOKIE = {"mlflow": "_llmoxie_mlflow", "litellm": "_llmoxie_litellm"}

# Every path a browser login or the UI touches on LiteLLM. These always need a
# Keycloak session: the bearer-key route (an Authorization header from an
# allowed IP) never serves them, whatever headers come with the request. Read
# from uw-ssec/llmoxie-litellm, branch sso-enabled, commit
# a20162ca8ab85c4ee0ce31f2afa9af64ee80eae5 (proxy_server.py, ui_sso.py,
# discovery_endpoints/ui_discovery_endpoints.py):
LITELLM_UI_PATHS: tuple[str, ...] = (
    "/ui",  # StaticFiles mount of the dashboard; redirect target after login
    "/_next",  # dashboard JS/CSS, mounted at the root
    "/litellm-asset-prefix",  # the same assets under the asset prefix
    "/login",  # master-key / username form POST
    "/v2/login",  # form login through the API
    "/v3/login",  # control-plane login, and /v3/login/exchange
    "/fallback/login",  # fallback login page
    "/sso",  # /sso/key/generate, /sso/callback, /sso/saml/*, /sso/cli/*, ...
    "/onboarding",  # invitation links: get_token, claim_token
    "/get_image",  # login page logo
    "/get_logo_url",
    "/get_favicon",
    "/.well-known/litellm-ui-config",  # the dashboard's discovery document
    "/litellm/.well-known/litellm-ui-config",
)


def _path_rule(paths: list[str]) -> str:
    return " || ".join(f"Path(`{path}`)" for path in paths)


def build_dynamic_config(proxy: LiteLLMProxyConfig, litellm_port: int) -> dict:
    """Build the Traefik file-provider (dynamic) configuration."""
    routers: dict[str, dict] = {}
    if proxy.health_paths:
        routers["litellm-health"] = {
            "entryPoints": [ENTRYPOINT],
            "rule": _path_rule(proxy.health_paths),
            "priority": 300,
            "service": "litellm",
        }
    if proxy.public_paths:
        routers["litellm-public"] = {
            "entryPoints": [ENTRYPOINT],
            "rule": _path_rule(proxy.public_paths),
            "priority": 200,
            "middlewares": ["client-rate-limit"],
            "service": "litellm",
        }
    routers["litellm-admin"] = {
        "entryPoints": [ENTRYPOINT],
        "rule": "PathPrefix(`/`)",
        "priority": 1,
        "middlewares": ["admin-ip-allowlist", "client-rate-limit"],
        "service": "litellm",
    }

    return {
        "http": {
            "routers": routers,
            "middlewares": {
                "admin-ip-allowlist": {
                    "ipAllowList": {
                        "sourceRange": proxy.admin_allowed_ips or _NO_ADMIN_IPS,
                        "ipStrategy": dict(_CLIENT_IP_STRATEGY),
                    }
                },
                "client-rate-limit": {
                    "rateLimit": {
                        "average": proxy.rate_limit_average,
                        "burst": proxy.rate_limit_burst,
                        "period": "1s",
                        "sourceCriterion": {"ipStrategy": dict(_CLIENT_IP_STRATEGY)},
                    }
                },
            },
            "services": {
                "litellm": {
                    "loadBalancer": {
                        "servers": [{"url": f"http://127.0.0.1:{litellm_port}"}],
                        "passHostHeader": True,
                        # Streamed (SSE) completions are flushed immediately;
                        # other responses at least this often.
                        "responseForwarding": {"flushInterval": "100ms"},
                    }
                }
            },
        }
    }


def build_static_args(proxy: LiteLLMProxyConfig) -> list[str]:
    """Build Traefik static configuration as CLI arguments.

    Only the file provider is enabled. The API, dashboard and ping endpoint stay
    off (Traefik's defaults). Access logs keep Traefik's default of dropping all
    request headers, so Authorization is never logged.
    """
    trusted = ",".join(proxy.trusted_proxy_ips or [])
    access_log = ["--accessLog=true"]
    if proxy.log_forwarded_for:
        # Staging diagnostics: JSON records ClientAddr (the raw TCP peer) and
        # the X-Forwarded-For chain. Every other header, including
        # Authorization, stays dropped.
        access_log += [
            "--accessLog.format=json",
            "--accessLog.fields.headers.defaultMode=drop",
            "--accessLog.fields.headers.names.X-Forwarded-For=keep",
        ]
    return [
        f"--entryPoints.{ENTRYPOINT}.address=:{proxy.port}",
        f"--entryPoints.{ENTRYPOINT}.forwardedHeaders.trustedIPs={trusted}",
        # Large prompts can take a while to upload; responses are not limited
        # (writeTimeout stays 0) so long completions are not cut off.
        f"--entryPoints.{ENTRYPOINT}.transport.respondingTimeouts.readTimeout=300s",
        f"--providers.file.filename={TRAEFIK_CONFIG_DIR}/{TRAEFIK_DYNAMIC_FILE}",
        "--providers.file.watch=false",
        *access_log,
        "--log.level=INFO",
        "--global.checkNewVersion=false",
        "--global.sendAnonymousUsage=false",
    ]


def render_dynamic_config(proxy: LiteLLMProxyConfig, litellm_port: int) -> str:
    return yaml.safe_dump(
        build_dynamic_config(proxy, litellm_port), sort_keys=False, width=1000
    )


def policy_digest(proxy: LiteLLMProxyConfig, dynamic_config: str) -> str:
    """SHA-256 of everything the proxy contributes to the revision.

    Covers the rendered dynamic config and the sidecar's static settings (args,
    image, resources), so changing e.g. log_forwarded_for or trusted_proxy_ips
    also changes a pinned revision suffix.
    """
    static = {
        "args": build_static_args(proxy),
        "image": proxy.image,
        "cpu": proxy.cpu,
        "memory": proxy.memory,
    }
    payload = json.dumps(static, sort_keys=True) + "\n" + dynamic_config
    return hashlib.sha256(payload.encode()).hexdigest()


# Router priorities with a login: health 300 > public 200 > /oauth2/ > session
# > bearer key > catch-all.
_OAUTH2_PRIORITY = 150
_SESSION_PRIORITY = 100
_BEARER_PRIORITY = 50


def _forward_auth(login_base_url: str) -> dict:
    return {
        "forwardAuth": {
            "address": f"{login_base_url}/",
            "trustForwardHeader": True,
        }
    }


def _litellm_ui_rule() -> str:
    # Each entry matches itself and its sub-paths, never a look-alike such as
    # /loginx, so the exclusion is exact in both directions.
    return " || ".join(f"Path(`{p}`) || PathPrefix(`{p}/`)" for p in LITELLM_UI_PATHS)


def _add_litellm_login_routes(
    routers: dict, middlewares: dict, services: dict, host: str, backends: dict
) -> None:
    """LiteLLM's host with the Keycloak login in front of the admin surface.

    A request with the login cookie goes through ForwardAuth from any IP. A
    bearer key with no cookie passes only from the admin IPs (LiteLLM checks the
    key), and never on the UI paths. Anything else needs a session.
    """
    cookie = f"HeaderRegexp(`Cookie`, `(^|;\\s*){LOGIN_COOKIE['litellm']}=`)"
    bearer = "HeaderRegexp(`Authorization`, `^Bearer `)"
    routers["litellm-oauth2"] = {
        "entryPoints": [ENTRYPOINT],
        "rule": f"{host} && PathPrefix(`/oauth2/`)",
        "priority": _OAUTH2_PRIORITY,
        "service": "litellm-auth",
    }
    routers["litellm-session"] = {
        "entryPoints": [ENTRYPOINT],
        "rule": f"{host} && {cookie}",
        "priority": _SESSION_PRIORITY,
        "middlewares": ["litellm-login", "client-rate-limit"],
        "service": "litellm",
    }
    routers["litellm-bearer"] = {
        "entryPoints": [ENTRYPOINT],
        "rule": f"{host} && {bearer} && !{cookie} && !({_litellm_ui_rule()})",
        "priority": _BEARER_PRIORITY,
        "middlewares": ["litellm-admin-ip-allowlist", "client-rate-limit"],
        "service": "litellm",
    }
    routers["litellm-admin"] = {
        "entryPoints": [ENTRYPOINT],
        "rule": host,
        "priority": 1,
        "middlewares": ["litellm-login", "client-rate-limit"],
        "service": "litellm",
    }
    middlewares["litellm-login"] = _forward_auth(backends["litellm-auth"])
    services["litellm-auth"] = {
        "loadBalancer": {
            "servers": [{"url": backends["litellm-auth"]}],
            "passHostHeader": False,
            "responseForwarding": {"flushInterval": "100ms"},
        }
    }


def build_edge_dynamic_config(config: LLMavenConfig, backends: dict[str, str]) -> dict:
    """Build the edge's Traefik file-provider config, routed by Host.

    ``backends`` maps ``"litellm"`` / ``"mlflow"`` to a base URL, with a key
    only for enabled backends. With Keycloak on it may also carry ``"keycloak"``
    and the login apps ``"mlflow-auth"`` / ``"litellm-auth"``.
    """
    edge = config.edge
    routers: dict[str, dict] = {}
    middlewares: dict[str, dict] = {
        "client-rate-limit": {
            "rateLimit": {
                "average": edge.rate_limit_average,
                "burst": edge.rate_limit_burst,
                "period": "1s",
                "sourceCriterion": {"ipStrategy": dict(_CLIENT_IP_STRATEGY)},
            }
        }
    }
    services: dict[str, dict] = {}
    keycloak_on = config.keycloak.enabled

    def _service(url: str) -> dict:
        return {
            "loadBalancer": {
                "servers": [{"url": url}],
                # The backend's own FQDN is what its ingress expects.
                "passHostHeader": False,
                "responseForwarding": {"flushInterval": "100ms"},
            }
        }

    if "litellm" in backends:
        litellm = config.litellm
        host = f"Host(`{litellm.hostname}`)"
        for name, paths, priority, limited in (
            ("litellm-health", litellm.health_paths, 300, False),
            ("litellm-public", litellm.public_paths, 200, True),
        ):
            if paths:
                router = {
                    "entryPoints": [ENTRYPOINT],
                    "rule": f"{host} && ({_path_rule(paths)})",
                    "priority": priority,
                    "service": "litellm",
                }
                if limited:
                    router["middlewares"] = ["client-rate-limit"]
                routers[name] = router
        allowlist = {
            "ipAllowList": {
                "sourceRange": litellm.admin_allowed_ips or _NO_ADMIN_IPS,
                "ipStrategy": dict(_CLIENT_IP_STRATEGY),
            }
        }
        middlewares["litellm-admin-ip-allowlist"] = allowlist
        if keycloak_on and litellm.login.enabled:
            _add_litellm_login_routes(routers, middlewares, services, host, backends)
        else:
            routers["litellm-admin"] = {
                "entryPoints": [ENTRYPOINT],
                "rule": host,
                "priority": 1,
                "middlewares": ["litellm-admin-ip-allowlist", "client-rate-limit"],
                "service": "litellm",
            }
        services["litellm"] = _service(backends["litellm"])
    if "mlflow" in backends:
        mlflow_host = f"Host(`{config.mlflow.hostname}`)"
        routers["mlflow"] = {
            "entryPoints": [ENTRYPOINT],
            "rule": mlflow_host,
            "service": "mlflow",
        }
        if keycloak_on and config.mlflow.login.enabled:
            routers["mlflow"]["priority"] = 1
            routers["mlflow"]["middlewares"] = ["mlflow-login"]
            routers["mlflow-oauth2"] = {
                "entryPoints": [ENTRYPOINT],
                "rule": f"{mlflow_host} && PathPrefix(`/oauth2/`)",
                "priority": _OAUTH2_PRIORITY,
                "service": "mlflow-auth",
            }
            middlewares["mlflow-login"] = _forward_auth(backends["mlflow-auth"])
            services["mlflow-auth"] = _service(backends["mlflow-auth"])
        services["mlflow"] = _service(backends["mlflow"])
    if keycloak_on and "keycloak" in backends:
        kc_host = f"Host(`{config.keycloak.hostname}`)"
        for name, prefix in (
            ("keycloak-realms", "/realms/"),
            ("keycloak-resources", "/resources/"),
        ):
            routers[name] = {
                "entryPoints": [ENTRYPOINT],
                "rule": f"{kc_host} && PathPrefix(`{prefix}`)",
                "middlewares": ["client-rate-limit"],
                "service": "keycloak",
            }
        routers["keycloak-admin"] = {
            "entryPoints": [ENTRYPOINT],
            "rule": f"{kc_host} && PathPrefix(`/admin/`)",
            "middlewares": ["keycloak-admin-ip-allowlist", "client-rate-limit"],
            "service": "keycloak",
        }
        middlewares["keycloak-admin-ip-allowlist"] = {
            "ipAllowList": {
                "sourceRange": config.keycloak.admin_allowed_ips or _NO_ADMIN_IPS,
                "ipStrategy": dict(_CLIENT_IP_STRATEGY),
            }
        }
        services["keycloak"] = _service(backends["keycloak"])

    return {
        "http": {"routers": routers, "middlewares": middlewares, "services": services}
    }


def build_edge_static_args(edge: EdgeConfig) -> list[str]:
    """Build the edge's Traefik static configuration as CLI arguments.

    Only the file provider is enabled and the API and dashboard stay off. Ping
    runs on its own entrypoint so health probes never reach the public one.
    """
    trusted = ",".join(edge.trusted_proxy_ips or [])
    access_log = ["--accessLog=true"]
    if edge.log_forwarded_for:
        access_log += [
            "--accessLog.format=json",
            "--accessLog.fields.headers.defaultMode=drop",
            "--accessLog.fields.headers.names.X-Forwarded-For=keep",
        ]
    return [
        f"--entryPoints.{ENTRYPOINT}.address=:{edge.port}",
        f"--entryPoints.{ENTRYPOINT}.forwardedHeaders.trustedIPs={trusted}",
        f"--entryPoints.{ENTRYPOINT}.transport.respondingTimeouts.readTimeout=300s",
        f"--entryPoints.{EDGE_PING_ENTRYPOINT}.address=:{edge.ping_port}",
        "--ping=true",
        f"--ping.entryPoint={EDGE_PING_ENTRYPOINT}",
        f"--providers.file.filename={TRAEFIK_CONFIG_DIR}/{TRAEFIK_DYNAMIC_FILE}",
        "--providers.file.watch=false",
        *access_log,
        "--log.level=INFO",
        "--global.checkNewVersion=false",
        "--global.sendAnonymousUsage=false",
    ]


def render_edge_dynamic_config(config: LLMavenConfig, backends: dict[str, str]) -> str:
    return yaml.safe_dump(
        build_edge_dynamic_config(config, backends), sort_keys=False, width=1000
    )


def edge_policy_digest(edge: EdgeConfig, dynamic_config: str) -> str:
    """SHA-256 of the edge's static settings plus its rendered dynamic config."""
    static = {
        "args": build_edge_static_args(edge),
        "image": edge.image,
        "cpu": edge.cpu,
        "memory": edge.memory,
    }
    payload = json.dumps(static, sort_keys=True) + "\n" + dynamic_config
    return hashlib.sha256(payload.encode()).hexdigest()


def policy_revision_suffix(revision_suffix: str, digest: str) -> str:
    """Pinned revision suffix with the policy digest appended.

    Container Apps rejects a template change that reuses an existing suffix, so a
    pinned suffix must change with the policy.
    """
    return f"{revision_suffix}-p{digest[:POLICY_SUFFIX_LENGTH]}"


def build_traefik_volume() -> azure_native.app.VolumeArgs:
    """Secret volume that holds only the Traefik dynamic config."""
    return azure_native.app.VolumeArgs(
        name=TRAEFIK_VOLUME_NAME,
        storage_type="Secret",
        secrets=[
            azure_native.app.SecretVolumeItemArgs(
                secret_ref=TRAEFIK_DYNAMIC_SECRET, path=TRAEFIK_DYNAMIC_FILE
            )
        ],
    )


def build_traefik_container(
    proxy: LiteLLMProxyConfig, digest: str
) -> azure_native.app.ContainerArgs:
    """Traefik sidecar container, with TCP probes on its own port.

    ``digest`` is the policy digest; it is set as an env var so the template
    changes whenever the dynamic config does.
    """

    def _tcp() -> azure_native.app.ContainerAppProbeTcpSocketArgs:
        return azure_native.app.ContainerAppProbeTcpSocketArgs(port=proxy.port)

    return azure_native.app.ContainerArgs(
        name=TRAEFIK_CONTAINER_NAME,
        image=proxy.image,
        args=build_static_args(proxy),
        env=[azure_native.app.EnvironmentVarArgs(name=POLICY_DIGEST_ENV, value=digest)],
        resources=azure_native.app.ContainerResourcesArgs(
            cpu=proxy.cpu, memory=proxy.memory
        ),
        volume_mounts=[
            azure_native.app.VolumeMountArgs(
                volume_name=TRAEFIK_VOLUME_NAME, mount_path=TRAEFIK_CONFIG_DIR
            )
        ],
        probes=[
            azure_native.app.ContainerAppProbeArgs(
                type="Liveness",
                tcp_socket=_tcp(),
                period_seconds=10,
                timeout_seconds=5,
                success_threshold=1,
                failure_threshold=3,
            ),
            azure_native.app.ContainerAppProbeArgs(
                type="Readiness",
                tcp_socket=_tcp(),
                period_seconds=5,
                timeout_seconds=5,
                success_threshold=1,
                failure_threshold=3,
            ),
        ],
    )
