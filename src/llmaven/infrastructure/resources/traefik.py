"""Traefik sidecar that puts path-level access control in front of LiteLLM.

Container Apps ingress sends every request (platform FQDN and custom domains)
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
"""

from __future__ import annotations

import hashlib
import json

import pulumi_azure_native as azure_native
import yaml

from ..config.schema import LiteLLMProxyConfig

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
POLICY_SUFFIX_LENGTH = 8
ENTRYPOINT = "web"

# Envoy appends the client address as the last X-Forwarded-For entry.
_CLIENT_IP_STRATEGY = {"depth": 1}

# With no admin IPs, the admin router still exists but matches no real client:
# Envoy never reports 127.0.0.1 as the client.
_NO_ADMIN_IPS = ["127.0.0.1/32"]


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
