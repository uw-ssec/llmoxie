"""Secrets Manager - Orchestrates complete secrets lifecycle.

This module orchestrates the complete secrets management workflow:
1. Read user-provided secrets from LLMAVEN_SECRETS_* environment variables
2. Generate auto-managed secrets (DB passwords, connection strings)
3. Store all secrets in Azure Key Vault
4. Provide secret references for Container Apps
"""

import pulumi
import pulumi_azure_native as azure_native
import pulumi_random as random
from pulumi import Output

from ..config.schema import LLMavenConfig
from ..utils.secrets import build_mlflow_tracking_uri, build_postgres_connection_string
from .key_vault import (
    create_secret,
    get_llmaven_secrets_from_env,
)


BACKUP_STORAGE_SECRET_NAME = "backup-storage-connection-string"

KEYCLOAK_SECRET_NAMES = {
    "admin_password": "keycloak-admin-password",
    "db_url": "keycloak-db-url",
    "db_username": "keycloak-db-username",
    "db_password": "keycloak-db-password",
    "client_mlflow_gate": "keycloak-client-mlflow-gate",
    "client_litellm_gate": "keycloak-client-litellm-gate",
    "client_litellm": "keycloak-client-litellm",
    "client_llmaven_cli": "keycloak-client-llmaven-cli",
    "cookie_mlflow": "oauth2-proxy-cookie-mlflow",
    "cookie_litellm": "oauth2-proxy-cookie-litellm",
}
# oauth2-proxy needs a cookie secret of exactly 16, 24 or 32 bytes.
_COOKIE_SECRET_LENGTH = 32
_GENERATED_SECRET_LENGTH = 48


class SecretsManager:
    """
    Manages the complete lifecycle of secrets for LLMaven deployment.

    This class:
    - Reads user-provided secrets from environment variables
    - Generates auto-managed secrets (passwords, connection strings)
    - Stores all secrets in Azure Key Vault
    - Provides secret references for Container Apps
    """

    def __init__(
        self,
        resource_group_name: Output[str],
        vault_name: Output[str],
        config: LLMavenConfig,
        environment: str,
    ):
        """
        Initialize SecretsManager.

        Args:
            resource_group_name: Name of the resource group
            vault_name: Key Vault name
            config: LLMaven configuration
            environment: Environment name
        """
        self.resource_group_name = resource_group_name
        self.vault_name = vault_name
        self.config = config
        self.environment = environment

        # Storage for created secrets
        self.user_secrets: dict[str, azure_native.keyvault.Secret] = {}
        self.auto_secrets: dict[str, azure_native.keyvault.Secret] = {}
        self.all_secrets: dict[str, azure_native.keyvault.Secret] = {}

    def create_user_provided_secrets(self) -> dict[str, azure_native.keyvault.Secret]:
        """
        Create Key Vault secrets from LLMAVEN_SECRETS_* environment variables.

        Returns:
            Dictionary mapping secret names to Secret resources
        """
        env_secrets = get_llmaven_secrets_from_env()

        if not env_secrets:
            pulumi.log.warn(
                "⚠ No LLMAVEN_SECRETS_* environment variables found. "
                "User-provided secrets (API keys, etc.) will not be available."
            )

        for secret_name, secret_value in env_secrets.items():
            secret_resource = create_secret(
                resource_group_name=self.resource_group_name,
                vault_name=self.vault_name,
                secret_name=secret_name,
                secret_value=Output.secret(secret_value),
                environment=self.environment,
                tags={
                    "ManagedBy": "Pulumi",
                    "Source": "EnvironmentVariable",
                    "Environment": self.environment,
                },
            )
            self.user_secrets[secret_name] = secret_resource
            self.all_secrets[secret_name] = secret_resource

        pulumi.log.info(
            f"✓ Created {len(self.user_secrets)} user-provided secrets from environment variables"
        )

        return self.user_secrets

    def create_postgres_admin_password(self) -> Output[str]:
        """
        Generate and store PostgreSQL admin password.

        Returns:
            PostgreSQL admin password (as Pulumi Output)
        """
        # Check if user provided a password via environment variable
        env_secrets = get_llmaven_secrets_from_env()
        if (
            "db-admin-password" in env_secrets
            or "postgresql-admin-password" in env_secrets
        ):
            # User provided password - use it
            password_value = env_secrets.get("db-admin-password") or env_secrets.get(
                "postgresql-admin-password"
            )
            pulumi.log.info(
                "✓ Using user-provided PostgreSQL admin password from environment"
            )
            return Output.secret(password_value)

        # Generate secure random password
        # No special characters to avoid issues with connection strings
        db_password = random.RandomPassword(
            f"postgres-admin-password-{self.environment}",
            length=32,
            special=False,
            override_special="!#$%&*()-_=+[]{}<>:?",
            min_lower=1,
            min_upper=1,
            min_numeric=1,
            min_special=0,
        )

        # Also store with alternative name
        secret_resource_alt = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="postgresql-admin-password",
            secret_value=db_password.result,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AutoGenerated",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["postgresql-admin-password"] = secret_resource_alt
        self.all_secrets["postgresql-admin-password"] = secret_resource_alt

        pulumi.log.info("✓ Auto-generated PostgreSQL admin password")

        return db_password.result

    def create_database_connection_strings(
        self,
        postgres_server_fqdn: Output[str],
        admin_login: str,
        admin_password: Output[str],
        database_names: list[str] | None = None,
    ) -> dict[str, azure_native.keyvault.Secret]:
        """
        Create database connection strings for all databases.

        Args:
            postgres_server_fqdn: PostgreSQL server FQDN
            admin_login: Admin username
            admin_password: Admin password
            database_names: List of database names

        Returns:
            Dictionary mapping secret names to Secret resources
        """
        if database_names is None:
            database_names = self.config.database.databases

        connection_string_secrets = {}

        for db_name in database_names:
            # Build connection string
            # Use default parameter to capture db_name value (avoid closure bug)
            connection_string = Output.all(postgres_server_fqdn, admin_password).apply(
                lambda args, db=db_name: build_postgres_connection_string(
                    server_fqdn=args[0],
                    database_name=db,
                    admin_login=admin_login,
                    admin_password=args[1],
                )
            )

            # Store in Key Vault with database-specific name
            secret_name = f"db-connection-string-{db_name}".replace("_", "-")
            secret_resource = create_secret(
                resource_group_name=self.resource_group_name,
                vault_name=self.vault_name,
                secret_name=secret_name,
                secret_value=connection_string,
                environment=self.environment,
                tags={
                    "ManagedBy": "Pulumi",
                    "Source": "AutoGenerated",
                    "Environment": self.environment,
                    "Database": db_name,
                },
            )
            connection_string_secrets[secret_name] = secret_resource
            self.auto_secrets[secret_name] = secret_resource
            self.all_secrets[secret_name] = secret_resource

        pulumi.log.info(
            f"✓ Created {len(connection_string_secrets)} database connection strings"
        )

        return connection_string_secrets

    def create_storage_account_key_secret(
        self,
        storage_account_key: Output[str],
    ) -> azure_native.keyvault.Secret:
        """
        Store storage account key in Key Vault.

        Args:
            storage_account_key: Storage account primary key

        Returns:
            Secret resource
        """
        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="storage-account-key",
            secret_value=storage_account_key,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AzureResource",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["storage-account-key"] = secret_resource
        self.all_secrets["storage-account-key"] = secret_resource

        pulumi.log.info("✓ Stored storage account key in Key Vault")

        return secret_resource

    def create_blob_endpoint_url_secret(
        self,
        blob_endpoint_url: Output[str],
    ) -> azure_native.keyvault.Secret:
        """
        Store blob endpoint URL in Key Vault.

        Args:
            blob_endpoint_url: Storage account blob endpoint URL

        Returns:
            Secret resource
        """
        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="blob-endpoint-url",
            secret_value=blob_endpoint_url,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AzureResource",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["blob-endpoint-url"] = secret_resource
        self.all_secrets["blob-endpoint-url"] = secret_resource

        pulumi.log.info("✓ Stored blob endpoint URL in Key Vault")

        return secret_resource

    def create_storage_connection_string_secret(
        self,
        storage_account_name: Output[str],
        storage_account_key: Output[str],
    ) -> azure_native.keyvault.Secret:
        """
        Create and store Azure Storage connection string in Key Vault.

        Args:
            storage_account_name: Storage account name
            storage_account_key: Storage account primary key

        Returns:
            Secret resource
        """
        # Build Azure Storage connection string
        connection_string = Output.all(storage_account_name, storage_account_key).apply(
            lambda args: (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={args[0]};"
                f"AccountKey={args[1]};"
                f"EndpointSuffix=core.windows.net"
            )
        )

        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="storage-connection-string",
            secret_value=connection_string,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AzureResource",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["storage-connection-string"] = secret_resource
        self.all_secrets["storage-connection-string"] = secret_resource

        pulumi.log.info("✓ Created storage connection string secret in Key Vault")

        return secret_resource

    def ensure_backup_storage_connection_string_secret(
        self,
        connection_string: str,
        source_env_var: str,
    ) -> azure_native.keyvault.Secret:
        """
        Get the Key Vault secret holding the backup storage connection string.

        LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING, the default source,
        already created this secret in create_user_provided_secrets, so reuse it
        rather than registering a second owner of the same secret. If that
        variable is set alongside a different source, refuse to guess which
        credential the job should use.

        Args:
            connection_string: Backup storage account connection string
            source_env_var: Environment variable the value was read from

        Returns:
            Secret resource
        """
        existing = self.user_secrets.get(BACKUP_STORAGE_SECRET_NAME)
        if existing is not None:
            if (
                get_llmaven_secrets_from_env()[BACKUP_STORAGE_SECRET_NAME]
                != connection_string
            ):
                raise ValueError(
                    "LLMAVEN_SECRETS_BACKUP_STORAGE_CONNECTION_STRING and "
                    f"{source_env_var} hold different values. Unset one of them."
                )
            return existing

        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name=BACKUP_STORAGE_SECRET_NAME,
            secret_value=Output.secret(connection_string),
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "EnvironmentVariable",
                "Environment": self.environment,
            },
        )
        self.all_secrets[BACKUP_STORAGE_SECRET_NAME] = secret_resource

        return secret_resource

    def create_mlflow_artifact_root_secret(
        self,
        storage_account_name: Output[str],
        container_name: str = "mlflow",
    ) -> azure_native.keyvault.Secret:
        """
        Create MLflow artifact root URL for Azure Blob Storage.

        Args:
            storage_account_name: Storage account name
            container_name: Container name for MLflow artifacts (default: mlflow)

        Returns:
            Secret resource
        """
        # Build MLflow artifact root URL for Azure Blob
        # Format: wasbs://container@storageaccount.blob.core.windows.net/
        artifact_root = storage_account_name.apply(
            lambda name: f"wasbs://{container_name}@{name}.blob.core.windows.net/"
        )

        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="mlflow-artifact-root",
            secret_value=artifact_root,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AutoGenerated",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["mlflow-artifact-root"] = secret_resource
        self.all_secrets["mlflow-artifact-root"] = secret_resource

        pulumi.log.info("✓ Created MLflow artifact root secret in Key Vault")

        return secret_resource

    def create_mlflow_tracking_uri_secret(
        self,
        mlflow_fqdn: Output[str],
    ) -> azure_native.keyvault.Secret:
        """
        Create MLflow tracking URI secret.

        Args:
            mlflow_fqdn: MLflow Container App FQDN

        Returns:
            Secret resource
        """
        mlflow_uri = mlflow_fqdn.apply(
            lambda fqdn: build_mlflow_tracking_uri(fqdn) if fqdn else None
        )

        secret_resource = create_secret(
            resource_group_name=self.resource_group_name,
            vault_name=self.vault_name,
            secret_name="mlflow-tracking-uri",
            secret_value=mlflow_uri,
            environment=self.environment,
            tags={
                "ManagedBy": "Pulumi",
                "Source": "AutoGenerated",
                "Environment": self.environment,
            },
        )
        self.auto_secrets["mlflow-tracking-uri"] = secret_resource
        self.all_secrets["mlflow-tracking-uri"] = secret_resource

        pulumi.log.info("✓ Created MLflow tracking URI secret")

        return secret_resource

    def create_foundry_secrets(
        self,
        api_base: Output[str],
        api_key: Output[str],
        api_version: str,
    ) -> list[azure_native.keyvault.Secret]:
        """
        Store the stack-managed Foundry endpoint, key and API version in Key Vault.

        These replace the user-provided azure-api-* secrets when foundry.enabled.

        Args:
            api_base: Azure OpenAI endpoint of the Foundry account
            api_key: Account key (a Pulumi secret)
            api_version: Azure OpenAI API version

        Returns:
            The three Secret resources
        """
        values = {
            "azure-api-base": Output.from_input(api_base),
            "azure-api-key": Output.secret(api_key),
            "azure-api-version": Output.from_input(api_version),
        }
        created = []
        for secret_name, value in values.items():
            secret_resource = create_secret(
                resource_group_name=self.resource_group_name,
                vault_name=self.vault_name,
                secret_name=secret_name,
                secret_value=value,
                environment=self.environment,
                tags={
                    "ManagedBy": "Pulumi",
                    "Source": "AzureResource",
                    "Environment": self.environment,
                },
            )
            self.auto_secrets[secret_name] = secret_resource
            self.all_secrets[secret_name] = secret_resource
            created.append(secret_resource)

        pulumi.log.info("✓ Stored Foundry endpoint, key and API version in Key Vault")

        return created

    def create_redis_secrets(
        self,
        host_name: Output[str],
        port: int,
        access_key: Output[str],
    ) -> dict[str, azure_native.keyvault.Secret]:
        """
        Store Azure Managed Redis connection details in Key Vault.

        Args:
            host_name: Redis host name
            port: Redis TLS port
            access_key: Redis database access key

        Returns:
            Dictionary mapping secret names to Secret resources
        """
        values = {
            "redis-host": host_name,
            "redis-port": Output.from_input(str(port)),
            "redis-password": Output.secret(access_key),
        }
        redis_secrets = {}
        for secret_name, secret_value in values.items():
            secret_resource = create_secret(
                resource_group_name=self.resource_group_name,
                vault_name=self.vault_name,
                secret_name=secret_name,
                secret_value=secret_value,
                environment=self.environment,
                tags={
                    "ManagedBy": "Pulumi",
                    "Source": "AzureResource",
                    "Environment": self.environment,
                },
            )
            redis_secrets[secret_name] = secret_resource
            self.auto_secrets[secret_name] = secret_resource
            self.all_secrets[secret_name] = secret_resource

        pulumi.log.info("✓ Stored Redis connection secrets in Key Vault")

        return redis_secrets

    def create_keycloak_secrets(
        self,
        postgres_host: Output[str],
        admin_login: str,
        admin_password: Output[str],
        config: LLMavenConfig,
    ) -> dict[str, azure_native.keyvault.Secret]:
        """
        Store Keycloak's database login and generated secrets in Key Vault.

        Keycloak uses the server admin login, like litellm_db and mlflow_db; a
        least-privilege role is the open #193 gap. Client and cookie secrets are
        created only for the logins that are enabled.

        Args:
            postgres_host: PostgreSQL server FQDN
            admin_login: Server admin login
            admin_password: Server admin password
            config: LLMaven configuration

        Returns:
            Dictionary mapping secret names to Secret resources
        """
        names = KEYCLOAK_SECRET_NAMES
        generated: list[tuple[str, int]] = [
            (names["admin_password"], _GENERATED_SECRET_LENGTH)
        ]
        if config.mlflow.login.enabled:
            generated += [
                (names["client_mlflow_gate"], _GENERATED_SECRET_LENGTH),
                (names["client_llmaven_cli"], _GENERATED_SECRET_LENGTH),
                (names["cookie_mlflow"], _COOKIE_SECRET_LENGTH),
            ]
        if config.litellm.login.enabled:
            generated += [
                (names["client_litellm_gate"], _GENERATED_SECRET_LENGTH),
                (names["client_litellm"], _GENERATED_SECRET_LENGTH),
                (names["cookie_litellm"], _COOKIE_SECRET_LENGTH),
            ]

        values: dict[str, Output[str]] = {
            names["db_url"]: Output.from_input(postgres_host).apply(
                lambda host: (
                    f"jdbc:postgresql://{host}:5432/keycloak_db?sslmode=require"
                )
            ),
            names["db_username"]: Output.secret(admin_login),
            names["db_password"]: Output.secret(admin_password),
        }
        for secret_name, length in generated:
            # No special characters: these end up in URLs and env vars.
            password = random.RandomPassword(
                f"{secret_name}-{self.environment}",
                length=length,
                special=False,
                min_lower=1,
                min_upper=1,
                min_numeric=1,
            )
            values[secret_name] = password.result

        keycloak_secrets = {}
        for secret_name, secret_value in values.items():
            secret_resource = create_secret(
                resource_group_name=self.resource_group_name,
                vault_name=self.vault_name,
                secret_name=secret_name,
                secret_value=secret_value,
                environment=self.environment,
                tags={
                    "ManagedBy": "Pulumi",
                    "Source": "AutoGenerated",
                    "Environment": self.environment,
                },
            )
            keycloak_secrets[secret_name] = secret_resource
            self.auto_secrets[secret_name] = secret_resource
            self.all_secrets[secret_name] = secret_resource

        pulumi.log.info(f"✓ Created {len(keycloak_secrets)} Keycloak secrets")

        return keycloak_secrets

    def get_secret(self, secret_name: str) -> azure_native.keyvault.Secret | None:
        """
        Get a secret by name.

        Args:
            secret_name: Name of the secret

        Returns:
            Secret resource, or None if not found
        """
        return self.all_secrets.get(secret_name)

    def get_secret_value(self, secret_name: str) -> Output[str] | None:
        """
        Get a secret value by name.

        Args:
            secret_name: Name of the secret

        Returns:
            Secret value as Pulumi Output, or None if not found
        """
        secret = self.all_secrets.get(secret_name)
        if secret:
            return secret.properties.value
        return None

    def get_secret_names(self) -> list[str]:
        """
        Get list of all secret names.

        Returns:
            List of secret names
        """
        return list(self.all_secrets.keys())

    def get_user_secret_names(self) -> list[str]:
        """
        Get list of user-provided secret names.

        Returns:
            List of user-provided secret names
        """
        return list(self.user_secrets.keys())

    def get_auto_secret_names(self) -> list[str]:
        """
        Get list of auto-generated secret names.

        Returns:
            List of auto-generated secret names
        """
        return list(self.auto_secrets.keys())

    def export_secret_summary(self) -> None:
        """
        Export summary of secrets to Pulumi outputs.
        """
        pulumi.export(
            f"secrets_summary_{self.environment}",
            {
                "total_secrets": len(self.all_secrets),
                "user_provided": len(self.user_secrets),
                "auto_generated": len(self.auto_secrets),
                "user_secret_names": self.get_user_secret_names(),
                "auto_secret_names": self.get_auto_secret_names(),
            },
        )

        pulumi.log.info(
            f"✓ Secrets Summary: {len(self.all_secrets)} total "
            f"({len(self.user_secrets)} user-provided, {len(self.auto_secrets)} auto-generated)"
        )
