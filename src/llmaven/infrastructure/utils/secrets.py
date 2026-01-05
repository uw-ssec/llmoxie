"""Secrets management utilities.

This module provides utilities for secure secrets handling, including:
- Auto-generation of cryptographically secure passwords
- Connection string building
- Secret validation
- Secret name transformation
"""

import os
import re
import secrets
import string
from pathlib import Path
from typing import Dict, List, Optional, Set

import pulumi
from pulumi import Output


def generate_secure_password(
    length: int = 32,
    include_special: bool = True,
    special_chars: str = "!#$%&*()-_=+[]{}<>:?",
) -> str:
    """
    Generate a cryptographically secure random password.

    Args:
        length: Password length (default: 32)
        include_special: Include special characters (default: True)
        special_chars: Special characters to use

    Returns:
        Cryptographically secure random password

    Example:
        >>> password = generate_secure_password(32)
        >>> len(password)
        32
    """
    if length < 16:
        raise ValueError("Password length must be at least 16 characters")

    # Character sets
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits

    # Build character pool
    char_pool = lowercase + uppercase + digits
    if include_special:
        char_pool += special_chars

    # Generate password ensuring it contains at least one of each type
    while True:
        password = "".join(secrets.choice(char_pool) for _ in range(length))

        # Validate password complexity
        has_lower = any(c in lowercase for c in password)
        has_upper = any(c in uppercase for c in password)
        has_digit = any(c in digits for c in password)
        has_special = (
            any(c in special_chars for c in password) if include_special else True
        )

        if has_lower and has_upper and has_digit and has_special:
            return password


def build_postgres_connection_string(
    server_fqdn: str,
    database_name: str,
    admin_login: str,
    admin_password: str,
    port: int = 5432,
    ssl_mode: str = "require",
) -> str:
    """
    Build PostgreSQL connection string.

    Args:
        server_fqdn: Fully qualified domain name of the server
        database_name: Database name
        admin_login: Admin username
        admin_password: Admin password
        port: PostgreSQL port (default: 5432)
        ssl_mode: SSL mode (require, verify-ca, verify-full)

    Returns:
        PostgreSQL connection string

    Example:
        >>> build_postgres_connection_string(
        ...     "myserver.postgres.database.azure.com",
        ...     "llmaven",
        ...     "admin",
        ...     "password123"
        ... )
        'postgresql://admin:password123@myserver.postgres.database.azure.com:5432/llmaven?sslmode=require'
    """
    return f"postgresql://{admin_login}:{admin_password}@{server_fqdn}:{port}/{database_name}?sslmode={ssl_mode}"


def build_mlflow_tracking_uri(fqdn: str, protocol: str = "https") -> str:
    """
    Build MLflow tracking URI from Container App FQDN.

    Args:
        fqdn: Fully qualified domain name of MLflow Container App
        protocol: Protocol (http or https, default: https)

    Returns:
        MLflow tracking URI

    Example:
        >>> build_mlflow_tracking_uri("myapp.azurecontainerapps.io")
        'https://myapp.azurecontainerapps.io'
    """
    return f"{protocol}://{fqdn}"


def validate_secret_name(secret_name: str) -> bool:
    """
    Validate Key Vault secret name.

    Key Vault secret names must:
    - Be 1-127 characters long
    - Contain only alphanumeric characters and hyphens
    - Start with a letter
    - End with a letter or digit

    Args:
        secret_name: Secret name to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> validate_secret_name("litellm-master-key")
        True
        >>> validate_secret_name("123-invalid")
        False
    """
    # Check length
    if not 1 <= len(secret_name) <= 127:
        return False

    # Check pattern: starts with letter, ends with letter/digit, contains only alphanumeric and hyphens
    pattern = r"^[a-zA-Z][a-zA-Z0-9-]*[a-zA-Z0-9]$"
    return bool(re.match(pattern, secret_name))


def validate_environment_secrets(
    required_secrets: List[str],
    environment: Optional[str] = None,
) -> tuple[bool, List[str], List[str]]:
    """
    Validate that required secrets are present in environment variables.

    Args:
        required_secrets: List of required secret names (Key Vault format)
        environment: Environment name (for logging)

    Returns:
        Tuple of (all_present, found_secrets, missing_secrets)

    Example:
        >>> os.environ["LLMAVEN_SECRETS_API_KEY"] = "test123"
        >>> validate_environment_secrets(["api-key"])
        (True, ['api-key'], [])
    """
    found = []
    missing = []

    for secret_name in required_secrets:
        # Convert secret name to environment variable name
        env_var_name = transform_secret_name_to_env_var(secret_name)

        # Check if environment variable exists
        if env_var_name in os.environ and os.environ[env_var_name]:
            found.append(secret_name)
        else:
            missing.append(secret_name)

    all_present = len(missing) == 0
    return all_present, found, missing


def load_env_file(env_file_path: Optional[Path] = None) -> None:
    """
    Load environment variables from a .env file.

    This function reads a .env file and loads any LLMAVEN_SECRETS_* variables
    into the environment. It does not override existing environment variables.

    Args:
        env_file_path: Path to .env file. If None, no file is loaded.

    Example:
        >>> load_env_file(Path(".env"))
        # Loads all LLMAVEN_SECRETS_* variables from .env file
    """
    if env_file_path is None:
        return

    env_file_path = Path(env_file_path)

    if not env_file_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file_path}")

    try:
        from dotenv import dotenv_values
    except ImportError:
        raise ImportError(
            "python-dotenv is required to load .env files. "
            "Install it with: pip install python-dotenv"
        )

    # Load the .env file
    env_vars = dotenv_values(env_file_path)

    # Only set LLMAVEN_SECRETS_* variables, and don't override existing ones
    prefix = "LLMAVEN_SECRETS_"
    loaded_count = 0

    for key, value in env_vars.items():
        if key.startswith(prefix) and value is not None:
            # Only set if not already in environment (env vars take precedence)
            if key not in os.environ:
                os.environ[key] = value
                loaded_count += 1
                pulumi.log.info(f"✓ Loaded secret from file: {key}")
            else:
                pulumi.log.info(
                    f"⚠ Skipping {key} from file (already set in environment)"
                )

    pulumi.log.info(f"✓ Loaded {loaded_count} secrets from {env_file_path}")


def get_llmaven_secrets(env_file_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Get all LLMAVEN_SECRETS_* environment variables.

    Optionally loads secrets from a .env file first, then reads from environment.
    Environment variables take precedence over .env file values.

    Args:
        env_file_path: Optional path to .env file to load secrets from

    Returns:
        Dictionary mapping secret names (kebab-case) to values

    Example:
        >>> os.environ["LLMAVEN_SECRETS_API_KEY"] = "test123"
        >>> get_llmaven_secrets()
        {'api-key': 'test123'}

        >>> get_llmaven_secrets(Path(".env"))
        # Loads secrets from .env file first, then from environment
    """
    # Load from .env file if provided
    if env_file_path is not None:
        load_env_file(env_file_path)

    secrets = {}
    prefix = "LLMAVEN_SECRETS_"

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Remove prefix and convert to kebab-case
            secret_name = key[len(prefix) :].lower().replace("_", "-")
            secrets[secret_name] = value
            pulumi.log.info(f"✓ Found secret: {secret_name} (from {key})")

    return secrets


def transform_secret_name_to_env_var(secret_name: str) -> str:
    """
    Transform Key Vault secret name to environment variable name.

    Reverse transformation of transform_env_var_to_secret_name.

    Transformation rules:
    1. Convert to uppercase
    2. Replace hyphens with underscores
    3. Add LLMAVEN_SECRETS_ prefix

    Args:
        secret_name: Key Vault secret name (e.g., litellm-master-key)

    Returns:
        Environment variable name (e.g., LLMAVEN_SECRETS_LITELLM_MASTER_KEY)

    Example:
        >>> transform_secret_name_to_env_var("litellm-master-key")
        'LLMAVEN_SECRETS_LITELLM_MASTER_KEY'
        >>> transform_secret_name_to_env_var("azure-openai-api-key")
        'LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY'
    """
    return f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"


def check_for_placeholder_secrets() -> List[tuple[str, str]]:
    """
    Check environment variables for common placeholder values.

    This helps catch cases where users forgot to replace example values
    with real secrets.

    Returns:
        List of tuples (env_var_name, placeholder_value) for any placeholders found

    Common placeholders:
    - "your-key-here"
    - "your-api-key"
    - "changeme"
    - "replace-me"
    - "example"
    - "test"
    - "placeholder"
    """
    placeholder_patterns = [
        r"your[_-]?key[_-]?here",
        r"your[_-]?api[_-]?key",
        r"change[_-]?me",
        r"replace[_-]?me",
        r"example",
        r"^test$",
        r"placeholder",
        r"^demo$",
        r"^sample$",
    ]

    placeholders_found = []
    prefix = "LLMAVEN_SECRETS_"

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Check if value matches any placeholder pattern
            value_lower = value.lower()
            for pattern in placeholder_patterns:
                if re.search(pattern, value_lower, re.IGNORECASE):
                    placeholders_found.append((key, value))
                    break

    return placeholders_found


def get_required_secrets_for_config(config_dict: Dict) -> Set[str]:
    """
    Extract required secrets from configuration.

    Parses the configuration to find all secrets that need to be provided
    via environment variables (excludes auto-generated secrets).

    Args:
        config_dict: Configuration dictionary (parsed from llmaven-config.yaml)

    Returns:
        Set of required secret names (in Key Vault format)

    Example:
        >>> config = {
        ...     "mlflow": {"secrets": ["db-connection-string", "storage-account-key"]},
        ...     "litellm": {"secrets": ["litellm-master-key", "azure-openai-api-key"]}
        ... }
        >>> get_required_secrets_for_config(config)
        {'litellm-master-key', 'azure-openai-api-key'}
    """
    # Auto-generated secrets that don't need to be in environment
    auto_generated_secrets = {
        "db-admin-password",
        "postgresql-admin-password",
        "storage-account-key",
        "db-connection-string-litellm-db",
        "db-connection-string-mlflow-db",
        "mlflow-tracking-uri",
    }

    required_secrets = set()

    # Extract secrets from mlflow config
    if "mlflow" in config_dict and config_dict["mlflow"].get("enabled"):
        mlflow_secrets = config_dict["mlflow"].get("secrets", [])
        for secret in mlflow_secrets:
            if secret not in auto_generated_secrets:
                required_secrets.add(secret)

    # Extract secrets from litellm config
    if "litellm" in config_dict and config_dict["litellm"].get("enabled"):
        litellm_secrets = config_dict["litellm"].get("secrets", [])
        for secret in litellm_secrets:
            if secret not in auto_generated_secrets:
                required_secrets.add(secret)

    # Extract secrets from llmaven_api config
    if "llmaven_api" in config_dict and config_dict["llmaven_api"].get("enabled"):
        api_secrets = config_dict["llmaven_api"].get("secrets", [])
        for secret in api_secrets:
            if secret not in auto_generated_secrets:
                required_secrets.add(secret)

    return required_secrets


def redact_secret_in_logs(secret_value: str, visible_chars: int = 4) -> str:
    """
    Redact secret value for logging purposes.

    Shows only the first few characters followed by asterisks.

    Args:
        secret_value: Secret value to redact
        visible_chars: Number of characters to show (default: 4)

    Returns:
        Redacted secret value

    Example:
        >>> redact_secret_in_logs("sk-1234567890abcdef")
        'sk-1***'
        >>> redact_secret_in_logs("my-secret-key", visible_chars=3)
        'my-***'
    """
    if len(secret_value) <= visible_chars:
        return "***"

    return secret_value[:visible_chars] + "***"


def create_auto_generated_secrets(
    postgres_server_fqdn: Output[str],
    postgres_admin_login: str,
    postgres_admin_password: Output[str],
    storage_account_key: Output[str],
    mlflow_fqdn: Optional[Output[str]] = None,
    database_names: Optional[List[str]] = None,
) -> Dict[str, Output[str]]:
    """
    Create auto-generated secrets for the deployment.

    These secrets are derived from infrastructure resources and don't need
    to be provided by the user via environment variables.

    Args:
        postgres_server_fqdn: PostgreSQL server FQDN
        postgres_admin_login: PostgreSQL admin username
        postgres_admin_password: PostgreSQL admin password
        storage_account_key: Storage account primary key
        mlflow_fqdn: MLflow Container App FQDN (optional)
        database_names: List of database names (default: ["llmaven", "mlflow_db", "litellm_db"])

    Returns:
        Dictionary mapping secret names to secret values
    """
    if database_names is None:
        database_names = ["llmaven", "mlflow_db", "litellm_db"]

    secrets = {}

    # PostgreSQL admin password (already generated)
    secrets["db-admin-password"] = postgres_admin_password
    secrets["postgresql-admin-password"] = postgres_admin_password

    # Storage account key
    secrets["storage-account-key"] = storage_account_key

    # Database connection strings
    for db_name in database_names:
        connection_string = Output.all(
            postgres_server_fqdn, postgres_admin_password
        ).apply(
            lambda args: build_postgres_connection_string(
                server_fqdn=args[0],
                database_name=db_name,
                admin_login=postgres_admin_login,
                admin_password=args[1],
            )
        )
        secrets[f"db-connection-string-{db_name}"] = connection_string

    # Generic db-connection-string (points to main llmaven database)
    secrets["db-connection-string"] = Output.all(
        postgres_server_fqdn, postgres_admin_password
    ).apply(
        lambda args: build_postgres_connection_string(
            server_fqdn=args[0],
            database_name="llmaven",
            admin_login=postgres_admin_login,
            admin_password=args[1],
        )
    )

    # MLflow tracking URI (if MLflow FQDN is provided)
    if mlflow_fqdn is not None:
        mlflow_uri = mlflow_fqdn.apply(
            lambda fqdn: build_mlflow_tracking_uri(fqdn) if fqdn else None
        )
        secrets["mlflow-tracking-uri"] = mlflow_uri

    pulumi.log.info(f"✓ Created {len(secrets)} auto-generated secrets")

    return secrets
