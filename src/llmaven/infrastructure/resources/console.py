"""The console's Container Apps, the file share they use, and its two jobs.

``console-web`` and ``console-broker`` run on internal ingress; the edge routes
the console's hostname to ``console-web``, which calls the broker. Each app runs
as its own identity and reads Key Vault references only from its own vault
(``console_secrets``), so ``console-web`` never sees the broker's secrets, the
master key or the broker's LiteLLM key.

The broker's LiteLLM key never passes through Pulumi or Key Vault:
``console-init`` makes it with the master key and writes it to an Azure Files
share that the broker mounts read-only. Container Apps sets read-only per
environment storage, not per mount, so the share is registered twice.

``console-db`` and ``console-init`` are manual jobs that run as the shared
identity and read the main vault; ``infra deploy`` starts them after ``up``.
With a knowledge hub, ``console-know`` follows them: it sets up knowledge for
organizations made while the hub was off, as the broker would, with the
broker's knowledge settings and the read-only share's LiteLLM key.
"""

import re
from dataclasses import dataclass

import pulumi
import pulumi_azure_native as azure_native

from ..config.schema import (
    CONSOLE_BROKER_APP_SUFFIX,
    CONSOLE_DB,
    CONSOLE_WEB_APP_SUFFIX,
    ConsoleAppSize,
    LLMavenConfig,
    console_job_name,
    container_app_environment,
)
from .console_secrets import ConsoleSecrets
from .container_apps import create_container_app_with_key_vault_secrets

WEB_PORT = 8200
BROKER_PORT = 8100
HEALTH_PATH = "/healthz"
OIDC_CLIENT_ID = "console"
_OIDC_PATH = "protocol/openid-connect"

SHARE_NAME = "console-run"
SHARE_QUOTA_GIB = 1
RW_STORAGE = "console-run-rw"  # mounted only by console-init
RO_STORAGE = "console-run-ro"  # mounted only by the broker
RUN_DIR = "/run/console"
ADMIN_KEY_FILE = f"{RUN_DIR}/admin-key"
# SMB mounts are owned by root unless told otherwise; the image runs as
# `console` (uid 10001, Dockerfile), which must write the key and read it back.
SHARE_MOUNT_OPTIONS = "uid=10001,gid=10001,dir_mode=0700,file_mode=0600"
_VOLUME = "console-run"

MASTER_KEY_SECRET = "litellm-master-key"
JOB_REPLICA_TIMEOUT = 600

_STORAGE_ACCOUNT_NAME = re.compile(r"[a-z0-9]{3,24}")


@dataclass
class ConsoleApps:
    web: azure_native.app.ContainerApp
    broker: azure_native.app.ContainerApp
    db_job: azure_native.app.Job
    init_job: azure_native.app.Job
    # The knowledge backfill; only with a knowledge hub.
    knowledge_job: azure_native.app.Job | None = None


def console_storage_account_name(project: str, environment: str, location: str) -> str:
    """The console share's storage account: ``<project><env><region>con``.

    Built like the main account's name (region prefix, hyphens dropped), so it
    is deterministic per stack. The app and vault name checks keep project and
    environment to 17 characters together, so this fits in 24; dev
    (``llmaven-dev``, ``dev``, ``westus2``) gives ``llmavendevdevwestcon``, 20.
    """
    region = location[:4].replace("-", "").lower()
    name = f"{project}{environment}{region}con".replace("-", "").lower()
    if not _STORAGE_ACCOUNT_NAME.fullmatch(name):
        raise ValueError(
            f"Console storage account name {name!r} is not 3-24 lowercase letters "
            "and digits, which Azure requires. Shorten project.name."
        )
    return name


def _share(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env: azure_native.app.ManagedEnvironment,
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None,
) -> dict[str, azure_native.app.ManagedEnvironmentsStorage]:
    """The storage account, the share and its read-write and read-only storages.

    The account is its own, not the stack's: that one may be ADLS Gen2
    (hierarchical namespace), where Azure Files isn't offered.
    """
    environment = config.project.environment
    account = azure_native.storage.StorageAccount(
        f"console-storage-{environment}",
        opts=opts,
        resource_group_name=resource_group_name,
        account_name=console_storage_account_name(
            config.project.name, environment, location
        ),
        location=location,
        tags=tags,
        sku=azure_native.storage.SkuArgs(
            name=azure_native.storage.SkuName.STANDARD_LRS
        ),
        kind=azure_native.storage.Kind.STORAGE_V2,
        is_hns_enabled=False,
        enable_https_traffic_only=True,
        minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
        allow_blob_public_access=False,
    )
    share = azure_native.storage.FileShare(
        f"console-share-{environment}",
        opts=opts,
        resource_group_name=resource_group_name,
        account_name=account.name,
        share_name=SHARE_NAME,
        share_quota=SHARE_QUOTA_GIB,
    )
    key = pulumi.Output.secret(
        azure_native.storage.list_storage_account_keys_output(
            resource_group_name=resource_group_name, account_name=account.name
        )
        .keys[0]
        .value
    )
    return {
        name: azure_native.app.ManagedEnvironmentsStorage(
            f"{name}-{environment}",
            opts=pulumi.ResourceOptions.merge(
                opts,
                pulumi.ResourceOptions(
                    depends_on=[share], additional_secret_outputs=["properties"]
                ),
            ),
            resource_group_name=resource_group_name,
            environment_name=container_env.name,
            storage_name=name,
            properties=azure_native.app.ManagedEnvironmentStoragePropertiesArgs(
                azure_file=azure_native.app.AzureFilePropertiesArgs(
                    account_name=account.name,
                    account_key=key,
                    share_name=SHARE_NAME,
                    access_mode=mode,
                )
            ),
        )
        for name, mode in (
            (RW_STORAGE, azure_native.app.AccessMode.READ_WRITE),
            (RO_STORAGE, azure_native.app.AccessMode.READ_ONLY),
        )
    }


def _share_volume(storage_name: str) -> tuple[list, list]:
    """The share as one volume mounted at /run/console, through ``storage_name``."""
    return (
        [
            azure_native.app.VolumeArgs(
                name=_VOLUME,
                storage_type=azure_native.app.StorageType.AZURE_FILE,
                storage_name=storage_name,
                mount_options=SHARE_MOUNT_OPTIONS,
            )
        ],
        [azure_native.app.VolumeMountArgs(volume_name=_VOLUME, mount_path=RUN_DIR)],
    )


def _uvicorn(module: str, port: int) -> list[str]:
    # The image has no ENTRYPOINT, so the args are the whole command.
    return [
        "uvicorn",
        f"console_app.{module}.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]


def _job(
    kind: str,
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env: azure_native.app.ManagedEnvironment,
    main_vault: azure_native.keyvault.Vault,
    shared_identity_id: pulumi.Input[str],
    script: str,
    env: dict[str, pulumi.Input[str]],
    secret_refs: dict[str, str],
    tags: dict[str, str],
    opts: pulumi.ResourceOptions,
    storage_name: str | None = None,
) -> azure_native.app.Job:
    """A manual job running ``python <script>`` as the shared identity.

    Its Key Vault references point at the main vault, which the shared identity
    can read.
    """
    environment = config.project.environment
    volumes, mounts = _share_volume(storage_name) if storage_name else (None, None)
    return azure_native.app.Job(
        f"console-{kind}-job-{environment}",
        opts=pulumi.ResourceOptions.merge(
            opts, pulumi.ResourceOptions(ignore_changes=["workloadProfileName"])
        ),
        resource_group_name=resource_group_name,
        job_name=console_job_name(config.project.name, environment, kind),
        location=location,
        tags=tags,
        environment_id=container_env.id,
        identity=azure_native.app.ManagedServiceIdentityArgs(
            type=azure_native.app.ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED,
            user_assigned_identities=[shared_identity_id],
        ),
        configuration=azure_native.app.JobConfigurationArgs(
            trigger_type=azure_native.app.TriggerType.MANUAL,
            replica_retry_limit=0,
            replica_timeout=JOB_REPLICA_TIMEOUT,
            manual_trigger_config=azure_native.app.JobConfigurationManualTriggerConfigArgs(
                parallelism=1,
                replica_completion_count=1,
            ),
            secrets=[
                azure_native.app.SecretArgs(
                    name=secret_name,
                    key_vault_url=main_vault.properties.vault_uri.apply(
                        lambda uri, sn=secret_name: f"{uri.rstrip('/')}/secrets/{sn}"
                    ),
                    identity=shared_identity_id,
                )
                for secret_name in dict.fromkeys(secret_refs.values())
            ],
        ),
        template=azure_native.app.JobTemplateArgs(
            containers=[
                azure_native.app.ContainerArgs(
                    name=f"console-{kind}",
                    image=config.console.image,
                    args=["python", script],
                    resources=azure_native.app.ContainerResourcesArgs(
                        cpu=0.25, memory="0.5Gi"
                    ),
                    env=[
                        *[
                            azure_native.app.EnvironmentVarArgs(name=n, value=v)
                            for n, v in env.items()
                        ],
                        *[
                            azure_native.app.EnvironmentVarArgs(name=n, secret_ref=s)
                            for n, s in secret_refs.items()
                        ],
                    ],
                    volume_mounts=mounts,
                )
            ],
            volumes=volumes,
        ),
    )


def create_console(
    config: LLMavenConfig,
    resource_group_name: pulumi.Input[str],
    location: str,
    container_env: azure_native.app.ManagedEnvironment,
    main_vault: azure_native.keyvault.Vault,
    shared_identity_id: pulumi.Input[str],
    secrets: ConsoleSecrets,
    sender_address: str,
    litellm_fqdn: pulumi.Input[str],
    keycloak_fqdn: pulumi.Input[str],
    postgres_host: pulumi.Input[str],
    tags: dict[str, str],
    opts: pulumi.ResourceOptions | None = None,
    knowledge_hub_job_secret_names: dict[str, str] | None = None,
    knowledge_hub_url: pulumi.Input[str] | None = None,
) -> ConsoleApps:
    """Create the console's apps, share and jobs (spec sections 4 to 6)."""
    console = config.console
    project = config.project.name
    environment = config.project.environment
    realm = config.keycloak.realm.name
    issuer = f"https://{config.keycloak.hostname}/realms/{realm}"

    def internal_oidc(endpoint: str) -> pulumi.Output[str]:
        # Token and key fetches go straight to Keycloak's internal FQDN, as the
        # oauth2-proxy logins do; the browser and the issuer use the public host.
        return pulumi.Output.concat(
            "https://", keycloak_fqdn, f"/realms/{realm}/{_OIDC_PATH}/{endpoint}"
        )

    litellm_url = pulumi.Output.concat("https://", litellm_fqdn)
    public_url = f"https://{console.hostname}"
    storages = _share(config, resource_group_name, location, container_env, tags, opts)
    after_secrets = pulumi.ResourceOptions.merge(
        opts, pulumi.ResourceOptions(depends_on=secrets.resources)
    )

    def app(
        suffix: str,
        port: int,
        module: str,
        size: ConsoleAppSize,
        identity: azure_native.managedidentity.UserAssignedIdentity,
        vault: azure_native.keyvault.Vault,
        env: dict[str, pulumi.Input[str]],
        secret_refs: dict[str, str],
        storage_name: str | None = None,
    ) -> azure_native.app.ContainerApp:
        base_name = f"{project}-{environment}-{suffix}"
        volumes, mounts = _share_volume(storage_name) if storage_name else (None, None)
        depends = [storages[storage_name]] if storage_name else []
        return create_container_app_with_key_vault_secrets(
            app_name=base_name,
            resource_group_name=resource_group_name,
            location=location,
            managed_environment_id=container_env.id,
            key_vault_uri=vault.properties.vault_uri,
            container_image=console.image,
            container_port=port,
            cpu=size.cpu,
            memory=size.memory,
            min_replicas=size.min_replicas,
            max_replicas=size.max_replicas,
            env_vars=env,
            key_vault_secret_refs=secret_refs,
            command_args=_uvicorn(module, port),
            volumes=volumes,
            volume_mounts=mounts,
            managed_identity_id=identity.id,
            environment=container_app_environment(base_name),
            tags=tags,
            enable_ingress=True,
            ingress_external=False,
            revision_suffix=console.revision_suffix,
            refresh_trigger=console.refresh_trigger,
            health_probe_port=port,
            health_probe_path=HEALTH_PATH,
            opts=pulumi.ResourceOptions.merge(
                after_secrets, pulumi.ResourceOptions(depends_on=depends)
            ),
        )

    broker_knowledge_env: dict[str, pulumi.Input[str]] = {}
    broker_knowledge_refs: dict[str, str] = {}
    if knowledge_hub_url is not None:
        # The broker provisions each organization's client and reads the hub;
        # console-web never needs either.
        broker_knowledge_env = {
            "KNOWLEDGE_HUB_URL": knowledge_hub_url,
            "KEYCLOAK_ADMIN_URL": pulumi.Output.concat(
                "https://", keycloak_fqdn, f"/admin/realms/{realm}"
            ),
            "KEYCLOAK_TOKEN_URL": internal_oidc("token"),
            "KEYCLOAK_PROVISIONER_CLIENT_ID": "console-provisioner",
            "KNOWLEDGE_READER_CLIENT_ID": "console-knowledge",
        }
        broker_knowledge_refs = {
            "KEYCLOAK_PROVISIONER_CLIENT_SECRET": secrets.provisioner_secret_name,
            "KNOWLEDGE_READER_CLIENT_SECRET": secrets.knowledge_secret_name,
        }

    broker = app(
        CONSOLE_BROKER_APP_SUFFIX,
        BROKER_PORT,
        "broker",
        console.broker,
        secrets.broker_identity,
        secrets.broker_vault,
        env={
            "LITELLM_URL": litellm_url,
            "LITELLM_ADMIN_KEY_FILE": ADMIN_KEY_FILE,
            "MAIL_BACKEND": "acs",
            "MAIL_FROM": sender_address,
            "CONSOLE_ADMIN_SUBJECTS": ",".join(console.admin_subjects),
            "CONSOLE_INVITE_TTL_HOURS": str(console.invite_ttl_hours),
            "OIDC_ISSUER": issuer,
            "OIDC_CLIENT_ID": OIDC_CLIENT_ID,
            "OIDC_JWKS_URL": internal_oidc("certs"),
            "CONSOLE_PUBLIC_URL": public_url,
            **broker_knowledge_env,
        },
        secret_refs={**secrets.broker_secret_names, **broker_knowledge_refs},
        storage_name=RO_STORAGE,
    )
    broker_url = broker.configuration.apply(
        lambda c: f"https://{c.ingress.fqdn}" if c and c.ingress else None
    )
    web = app(
        CONSOLE_WEB_APP_SUFFIX,
        WEB_PORT,
        "web",
        console.web,
        secrets.web_identity,
        secrets.web_vault,
        env={
            "OIDC_ISSUER": issuer,
            "OIDC_CLIENT_ID": OIDC_CLIENT_ID,
            "OIDC_AUTH_URL": f"{issuer}/{_OIDC_PATH}/auth",
            "OIDC_LOGOUT_URL": f"{issuer}/{_OIDC_PATH}/logout",
            "OIDC_TOKEN_URL": internal_oidc("token"),
            "OIDC_JWKS_URL": internal_oidc("certs"),
            "CONSOLE_PUBLIC_URL": public_url,
            "GATEWAY_PUBLIC_URL": f"https://{config.litellm.hostname}",
            "LITELLM_ADMIN_URL": f"https://{config.litellm.ui_hostname}",
            "CONSOLE_BROKER_URL": broker_url,
        },
        secret_refs=secrets.web_secret_names,
    )

    job_args = dict(
        config=config,
        resource_group_name=resource_group_name,
        location=location,
        container_env=container_env,
        main_vault=main_vault,
        shared_identity_id=shared_identity_id,
        tags=tags,
    )
    db_job = _job(
        "db",
        script="db_setup.py",
        env={
            "PGHOST": postgres_host,
            "PGUSER": config.database.admin_login,
            "CONSOLE_OTHER_DATABASES": ",".join(
                d for d in config.database.databases if d != CONSOLE_DB
            ),
        },
        # PGPASSWORD is the console's own copy of the server admin password.
        secret_refs={
            **secrets.job_secret_names,
            # The knowledge hub's database password, when the hub is on.
            **(knowledge_hub_job_secret_names or {}),
        },
        opts=after_secrets,
        **job_args,
    )
    init_job = _job(
        "init",
        script="init_admin_key.py",
        env={"LITELLM_URL": litellm_url, "LITELLM_ADMIN_KEY_FILE": ADMIN_KEY_FILE},
        secret_refs={
            "LITELLM_MASTER_KEY": config.litellm.key_vault_secret_refs.get(
                "LITELLM_MASTER_KEY", MASTER_KEY_SECRET
            )
        },
        storage_name=RW_STORAGE,
        opts=pulumi.ResourceOptions.merge(
            opts, pulumi.ResourceOptions(depends_on=[storages[RW_STORAGE]])
        ),
        **job_args,
    )
    knowledge_job = None
    if knowledge_hub_url is not None:
        knowledge_job = _job(
            "know",
            script="knowledge_backfill.py",
            env={
                "LITELLM_URL": litellm_url,
                "LITELLM_ADMIN_KEY_FILE": ADMIN_KEY_FILE,
                **broker_knowledge_env,
            },
            secret_refs=secrets.knowledge_job_secret_names,
            storage_name=RO_STORAGE,
            opts=pulumi.ResourceOptions.merge(
                after_secrets,
                pulumi.ResourceOptions(depends_on=[storages[RO_STORAGE]]),
            ),
            **job_args,
        )
    return ConsoleApps(
        web=web,
        broker=broker,
        db_job=db_job,
        init_job=init_job,
        knowledge_job=knowledge_job,
    )
