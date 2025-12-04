"""Pulumi resource modules for Azure infrastructure."""

from .container_apps import (
    create_container_app_with_key_vault_secrets,
    create_container_apps_environment,
)
from .database import (
    configure_firewall_rules,
    configure_server_parameters,
    create_databases,
    create_postgres_server,
    get_connection_string,
)
from .helpers import (
    create_litellm_app,
    create_log_analytics_workspace,
    create_mlflow_app,
    create_postgres_flexible_server,
    create_resource_group,
    create_user_assigned_managed_identity,
    create_virtual_network,
)
from .key_vault import (
    create_key_vault,
    create_secret,
    create_secrets_from_environment,
    get_llmaven_secrets_from_env,
    get_secret_reference,
    grant_key_vault_access,
    transform_env_var_to_secret_name,
)
from .secrets_manager import SecretsManager
from .storage import (
    create_blob_containers,
    create_lifecycle_management_policy,
    create_storage_account,
    enable_blob_versioning,
    get_blob_connection_string,
    get_storage_account_key,
)

__all__ = [
    # Database resources
    "create_postgres_server",
    "create_databases",
    "configure_firewall_rules",
    "configure_server_parameters",
    "get_connection_string",
    # Storage resources
    "create_storage_account",
    "create_blob_containers",
    "create_lifecycle_management_policy",
    "enable_blob_versioning",
    "get_storage_account_key",
    "get_blob_connection_string",
    # Container Apps resources
    "create_container_apps_environment",
    "create_container_app_with_key_vault_secrets",
    # Key Vault resources
    "create_key_vault",
    "create_secret",
    "create_secrets_from_environment",
    "get_llmaven_secrets_from_env",
    "get_secret_reference",
    "grant_key_vault_access",
    "transform_env_var_to_secret_name",
    # Secrets Manager
    "SecretsManager",
    # Helper functions for high-level resource creation
    "create_resource_group",
    "create_virtual_network",
    "create_log_analytics_workspace",
    "create_postgres_flexible_server",
    "create_mlflow_app",
    "create_litellm_app",
    "create_user_assigned_managed_identity",
]
