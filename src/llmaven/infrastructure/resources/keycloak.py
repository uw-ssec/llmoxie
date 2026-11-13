"""The Keycloak Container App and the Container Apps Job that imports its realm."""

import hashlib
from typing import Literal

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import (
    KEYCLOAK_APP_SUFFIX,
    LITELLM_LOGIN_APP_SUFFIX,
    MLFLOW_LOGIN_APP_SUFFIX,
    LLMavenConfig,
    container_app_environment,
    realm_job_name,
)
from .container_apps import create_container_app_with_key_vault_secrets
from .keycloak_realm import CLIENT_SECRET_ENV, render_realm_document
from .secrets_manager import KEYCLOAK_SECRET_NAMES
from .traefik import LOGIN_COOKIE

KEYCLOAK_HTTP_PORT = 8080
# Keycloak serves health on its management port, not the application port.
KEYCLOAK_MANAGEMENT_PORT = 9000
KEYCLOAK_HEALTH_PATH = "/health/ready"
KEYCLOAK_ADMIN_USER = "admin"

# The realm document is an inline job secret, mounted as a file. A job template
# does not change when a secret does, so a digest of the document goes into an
# env var and a realm change always yields a new job template.
REALM_SECRET = "realm-json"
REALM_VOLUME_NAME = "realm-volume"
REALM_CONFIG_DIR = "/config"
REALM_FILE = "realm.json"
REALM_DIGEST_ENV = "REALM_DOCUMENT_SHA256"
REALM_REPLICA_TIMEOUT = 600

# Which stack clients each login brings into the realm.
_LOGIN_CLIENTS = {
    "mlflow": ("mlflow-gate", "llmaven-cli"),
    "litellm": ("litellm-gate", "litellm"),
}
# Client id -> its Key Vault secret key in KEYCLOAK_SECRET_NAMES.
_CLIENT_SECRET_KEY = {
    "mlflow-gate": "client_mlflow_gate",
    "llmaven-cli": "client_llmaven_cli",
    "litellm-gate": "client_litellm_gate",
    "litellm": "client_litellm",
}

OAUTH2_PROXY_PORT = 4180
OAUTH2_PROXY_PING_PATH = "/ping"
_OIDC_PATH = "protocol/openid-connect"
# kind -> (app suffix, gate client id, Key Vault key of its client secret,
# Key Vault key of its cookie secret).
_LOGIN_APPS = {
    "mlflow": (
        MLFLOW_LOGIN_APP_SUFFIX,
        "mlflow-gate",
        "client_mlflow_gate",
        "cookie_mlflow",
    ),
    "litellm": (
        LITELLM_LOGIN_APP_SUFFIX,
        "litellm-gate",
        "client_litellm_gate",
        "cookie_litellm",
    ),
}


def _identity(managed_identity_id) -> azure_native.app.ManagedServiceIdentityArgs:
    return azure_native.app.ManagedServiceIdentityArgs(
        type=azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED,
        user_assigned_identities=[managed_identity_id],
    )


def create_keycloak_app(
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env_id: pulumi.Input[str],
    key_vault: azure_native.keyvault.Vault,
    config: LLMavenConfig,
    managed_identity_id: pulumi.Input[str],
    tags: dict[str, str] | None = None,
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.app.ContainerApp:
    """Create the Keycloak Container App, reachable only through the edge.

    A single replica runs ``start --optimized --cache=local`` (the image is
    built with the local cache), so ingress is internal and the edge routes the
    public hostname to it. Secrets come from Key Vault through the shared
    managed identity.
    """
    kc = config.keycloak
    base_name = (
        f"{config.project.name}-{config.project.environment}-{KEYCLOAK_APP_SUFFIX}"
    )
    names = KEYCLOAK_SECRET_NAMES

    return create_container_app_with_key_vault_secrets(
        app_name=base_name,
        resource_group_name=resource_group_name,
        location=location,
        managed_environment_id=container_env_id,
        key_vault_uri=key_vault.properties.vault_uri,
        container_image=kc.image,
        container_port=KEYCLOAK_HTTP_PORT,
        cpu=kc.cpu,
        memory=kc.memory,
        min_replicas=1,
        max_replicas=1,
        env_vars={
            "KC_HOSTNAME": f"https://{kc.hostname}",
            "KC_HOSTNAME_BACKCHANNEL_DYNAMIC": "true",
            "KC_PROXY_HEADERS": "xforwarded",
            "KC_HTTP_ENABLED": "true",
            "KC_HEALTH_ENABLED": "true",
            "KC_BOOTSTRAP_ADMIN_USERNAME": KEYCLOAK_ADMIN_USER,
        },
        key_vault_secret_refs={
            "KC_DB_URL": names["db_url"],
            "KC_DB_USERNAME": names["db_username"],
            "KC_DB_PASSWORD": names["db_password"],
            "KC_BOOTSTRAP_ADMIN_PASSWORD": names["admin_password"],
        },
        command_args=["start", "--optimized", "--cache=local"],
        managed_identity_id=managed_identity_id,
        environment=container_app_environment(base_name),
        tags=tags,
        enable_ingress=True,
        ingress_external=False,
        revision_suffix=kc.revision_suffix,
        refresh_trigger=kc.refresh_trigger,
        health_probe_port=KEYCLOAK_MANAGEMENT_PORT,
        health_probe_path=KEYCLOAK_HEALTH_PATH,
        opts=opts,
    )


def create_login_app(
    kind: Literal["mlflow", "litellm"],
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env_id: pulumi.Input[str],
    key_vault: azure_native.keyvault.Vault,
    config: LLMavenConfig,
    keycloak_fqdn: pulumi.Input[str],
    managed_identity_id: pulumi.Input[str],
    tags: dict[str, str] | None = None,
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.app.ContainerApp:
    """Create the oauth2-proxy app that answers Traefik's ForwardAuth for ``kind``.

    Traefik sends each request to ``https://<this app>/``; with no session the
    proxy answers 401 and the edge sends the browser through ``/oauth2/`` on
    the app's own host. Ingress is internal. The browser-facing URLs use the
    public Keycloak host; the token and key fetches go straight to Keycloak's
    internal FQDN. Discovery is skipped because the issuer (public) and the
    back-channel host differ.

    Role check (oauth2-proxy v7.15.6, read at that tag): ``OAUTH2_PROXY_ALLOWED_ROLES``
    is the ``allowed_roles`` option (pkg/apis/options/options.go, flag
    ``allowed-role``; the plural env form is the one that is read) and
    ``KeycloakOIDCProvider.addAllowedRoles`` puts each into the provider's
    allowed groups as ``role:<name>`` (providers/keycloak_oidc.go:40-47). It
    applies to bearer tokens too: with ``--skip-jwt-bearer-tokens`` the session
    chain loads sessions through ``provider.CreateSessionFromToken``
    (oauthproxy.go:412-420), the Keycloak override of which calls
    ``extractRoles`` and so adds the token's roles to ``Groups``
    (providers/keycloak_oidc.go:49-61, 86-100), and ``Proxy`` then runs
    ``getAuthenticatedSession``, which calls ``provider.Authorize`` for every
    session, bearer or cookie (oauthproxy.go:1078, 1192;
    providers/provider_default.go:129-141). Task 13 confirms it at runtime.

    The skip-auth switches (SKIP_AUTH_ROUTES, SKIP_AUTH_PREFLIGHT,
    SKIP_AUTH_REGEX, TRUSTED_IPS) are never set: Traefik forwards with
    ``trustForwardHeader``, so a client can send ``X-Forwarded-*`` headers that
    reach this proxy.
    """
    suffix, client_id, client_secret_key, cookie_secret_key = _LOGIN_APPS[kind]
    app_config = getattr(config, kind)
    kc = config.keycloak
    base_name = f"{config.project.name}-{config.project.environment}-{suffix}"
    realm = kc.realm.name
    realm_url = f"https://{kc.hostname}/realms/{realm}"

    env_vars: dict[str, pulumi.Input[str]] = {
        "OAUTH2_PROXY_PROVIDER": "keycloak-oidc",
        "OAUTH2_PROXY_CLIENT_ID": client_id,
        "OAUTH2_PROXY_ALLOWED_ROLES": app_config.login.role,
        "OAUTH2_PROXY_OIDC_ISSUER_URL": realm_url,
        "OAUTH2_PROXY_SKIP_OIDC_DISCOVERY": "true",
        "OAUTH2_PROXY_LOGIN_URL": f"{realm_url}/{_OIDC_PATH}/auth",
        "OAUTH2_PROXY_REDEEM_URL": pulumi.Output.concat(
            "https://", keycloak_fqdn, f"/realms/{realm}/{_OIDC_PATH}/token"
        ),
        "OAUTH2_PROXY_OIDC_JWKS_URL": pulumi.Output.concat(
            "https://", keycloak_fqdn, f"/realms/{realm}/{_OIDC_PATH}/certs"
        ),
        "OAUTH2_PROXY_REDIRECT_URL": f"https://{app_config.hostname}/oauth2/callback",
        "OAUTH2_PROXY_CODE_CHALLENGE_METHOD": "S256",
        "OAUTH2_PROXY_REVERSE_PROXY": "true",
        "OAUTH2_PROXY_UPSTREAMS": "static://202",
        "OAUTH2_PROXY_COOKIE_SECURE": "true",
        # Traefik's session-cookie rule matches this name (and its split
        # `<name>_<n>` form), so it must not change.
        "OAUTH2_PROXY_COOKIE_NAME": LOGIN_COOKIE[kind],
        "OAUTH2_PROXY_EMAIL_DOMAINS": "*",
        "OAUTH2_PROXY_SKIP_PROVIDER_BUTTON": "true",
        "OAUTH2_PROXY_WHITELIST_DOMAINS": app_config.hostname,
        "OAUTH2_PROXY_HTTP_ADDRESS": f"0.0.0.0:{OAUTH2_PROXY_PORT}",
    }
    if kind == "mlflow":
        # `infra extract` calls MLflow with a Keycloak access token. LiteLLM's
        # bearer keys are not Keycloak tokens, so its proxy never verifies any.
        env_vars["OAUTH2_PROXY_SKIP_JWT_BEARER_TOKENS"] = "true"

    return create_container_app_with_key_vault_secrets(
        app_name=base_name,
        resource_group_name=resource_group_name,
        location=location,
        managed_environment_id=container_env_id,
        key_vault_uri=key_vault.properties.vault_uri,
        container_image=kc.oauth2_proxy_image,
        container_port=OAUTH2_PROXY_PORT,
        cpu=0.25,
        memory="0.5Gi",
        min_replicas=1,
        max_replicas=1,
        env_vars=env_vars,
        key_vault_secret_refs={
            "OAUTH2_PROXY_CLIENT_SECRET": KEYCLOAK_SECRET_NAMES[client_secret_key],
            "OAUTH2_PROXY_COOKIE_SECRET": KEYCLOAK_SECRET_NAMES[cookie_secret_key],
        },
        managed_identity_id=managed_identity_id,
        environment=container_app_environment(base_name),
        tags=tags,
        enable_ingress=True,
        ingress_external=False,
        health_probe_port=OAUTH2_PROXY_PORT,
        health_probe_path=OAUTH2_PROXY_PING_PATH,
        opts=opts,
    )


def _job_secret_refs(config: LLMavenConfig) -> dict[str, str]:
    """Env var -> Key Vault secret name for what the realm import needs."""
    refs = {"KEYCLOAK_PASSWORD": KEYCLOAK_SECRET_NAMES["admin_password"]}
    for login, clients in _LOGIN_CLIENTS.items():
        if getattr(config, login).login.enabled:
            for client in clients:
                refs[CLIENT_SECRET_ENV[client]] = KEYCLOAK_SECRET_NAMES[
                    _CLIENT_SECRET_KEY[client]
                ]
    refs.update(config.keycloak.realm.secret_refs)
    return refs


def create_realm_job(
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env_id: pulumi.Input[str],
    key_vault: azure_native.keyvault.Vault,
    config: LLMavenConfig,
    keycloak_fqdn: pulumi.Input[str],
    managed_identity_id: pulumi.Input[str],
    tags: dict[str, str] | None = None,
    opts: pulumi.ResourceOptions | None = None,
) -> azure_native.app.Job:
    """Create the manual Job that imports the realm with keycloak-config-cli.

    The rendered realm document is mounted from an inline secret; its SHA-256
    is in the template so a changed realm yields a new job template. Secrets are
    Key Vault references through the shared managed identity.
    """
    kc = config.keycloak
    environment = config.project.environment
    document = render_realm_document(config)
    digest = hashlib.sha256(document.encode()).hexdigest()
    refs = _job_secret_refs(config)

    kv_secrets = [
        azure_native.app.SecretArgs(
            name=secret_name,
            key_vault_url=key_vault.properties.vault_uri.apply(
                lambda uri, sn=secret_name: f"{uri.rstrip('/')}/secrets/{sn}"
            ),
            identity=managed_identity_id,
        )
        for secret_name in dict.fromkeys(refs.values())
    ]

    env = [
        azure_native.app.EnvironmentVarArgs(name=name, value=value)
        for name, value in {
            "KEYCLOAK_URL": pulumi.Output.concat("https://", keycloak_fqdn),
            "KEYCLOAK_USER": KEYCLOAK_ADMIN_USER,
            "KEYCLOAK_AVAILABILITYCHECK_ENABLED": "true",
            "IMPORT_FILES_LOCATIONS": f"{REALM_CONFIG_DIR}/{REALM_FILE}",
            "IMPORT_VARSUBSTITUTION_ENABLED": "true",
            "IMPORT_REMOTESTATE_ENABLED": "true",
            "IMPORT_MANAGED_CLIENT": "no-delete",
            "IMPORT_MANAGED_ROLE": "no-delete",
            "IMPORT_MANAGED_IDENTITYPROVIDER": "no-delete",
            "IMPORT_MANAGED_GROUP": "no-delete",
            "IMPORT_MANAGED_CLIENTSCOPE": "no-delete",
            REALM_DIGEST_ENV: digest,
        }.items()
    ] + [
        azure_native.app.EnvironmentVarArgs(name=name, secret_ref=secret_name)
        for name, secret_name in refs.items()
    ]

    job = azure_native.app.Job(
        f"realm-job-{environment}",
        opts=pulumi.ResourceOptions.merge(
            opts,
            pulumi.ResourceOptions(ignore_changes=["workloadProfileName"]),
        ),
        resource_group_name=resource_group_name,
        job_name=realm_job_name(config.project.name, environment),
        location=location,
        tags=tags or {},
        environment_id=container_env_id,
        identity=_identity(managed_identity_id),
        configuration=azure_native.app.JobConfigurationArgs(
            trigger_type=azure_native.app.TriggerType.MANUAL,
            replica_retry_limit=0,
            replica_timeout=REALM_REPLICA_TIMEOUT,
            manual_trigger_config=azure_native.app.JobConfigurationManualTriggerConfigArgs(
                parallelism=1,
                replica_completion_count=1,
            ),
            secrets=[
                *kv_secrets,
                azure_native.app.SecretArgs(name=REALM_SECRET, value=document),
            ],
        ),
        template=azure_native.app.JobTemplateArgs(
            containers=[
                azure_native.app.ContainerArgs(
                    name="realm-import",
                    image=kc.config_cli_image,
                    resources=azure_native.app.ContainerResourcesArgs(
                        cpu=0.5, memory="1Gi"
                    ),
                    env=env,
                    volume_mounts=[
                        azure_native.app.VolumeMountArgs(
                            volume_name=REALM_VOLUME_NAME,
                            mount_path=REALM_CONFIG_DIR,
                        )
                    ],
                )
            ],
            volumes=[
                azure_native.app.VolumeArgs(
                    name=REALM_VOLUME_NAME,
                    storage_type="Secret",
                    secrets=[
                        azure_native.app.SecretVolumeItemArgs(
                            secret_ref=REALM_SECRET, path=REALM_FILE
                        )
                    ],
                )
            ],
        ),
    )

    pulumi.export(f"realm_job_name_{environment}", job.name)
    return job
