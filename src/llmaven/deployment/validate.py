"""Validate LLMaven deployment configuration.

This module provides the implementation for the 'llmaven validate' command.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..infrastructure.config.loader import ConfigLoadError, load_config
from ..infrastructure.config.schema import LLMavenConfig


class ValidationError(Exception):
    """Exception raised when validation fails."""

    pass


def check_azure_cli() -> Tuple[bool, str]:
    """Check if Azure CLI is installed and authenticated.

    Returns:
        Tuple of (success, message)
    """
    try:
        result = subprocess.run(
            ["az", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, "Azure CLI is not installed. Install it from: https://aka.ms/InstallAzureCLI"
    except FileNotFoundError:
        return False, "Azure CLI is not installed. Install it from: https://aka.ms/InstallAzureCLI"
    except subprocess.TimeoutExpired:
        return False, "Azure CLI check timed out"

    # Check if logged in
    try:
        result = subprocess.run(
            ["az", "account", "show"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, "Not logged in to Azure. Run: az login"
    except subprocess.TimeoutExpired:
        return False, "Azure login check timed out"

    return True, "Azure CLI is installed and authenticated"


def check_subscription_access(subscription_id: str) -> Tuple[bool, str]:
    """Check if subscription is accessible.

    Args:
        subscription_id: Azure subscription ID

    Returns:
        Tuple of (success, message)
    """
    if not subscription_id:
        return False, "Azure subscription ID is not set in configuration"

    try:
        result = subprocess.run(
            ["az", "account", "show", "--subscription", subscription_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, f"Subscription {subscription_id} is not accessible or does not exist"
        return True, f"Subscription {subscription_id} is accessible"
    except subprocess.TimeoutExpired:
        return False, "Subscription check timed out"
    except Exception as e:
        return False, f"Failed to check subscription: {e}"


def check_required_providers(subscription_id: str) -> Tuple[bool, str]:
    """Check if required Azure resource providers are registered.

    Args:
        subscription_id: Azure subscription ID

    Returns:
        Tuple of (success, message)
    """
    required_providers = [
        "Microsoft.App",  # Container Apps
        "Microsoft.DBforPostgreSQL",  # PostgreSQL
        "Microsoft.Storage",  # Blob Storage
        "Microsoft.KeyVault",  # Key Vault
        "Microsoft.OperationalInsights",  # Log Analytics
        "Microsoft.Insights",  # Application Insights
    ]

    try:
        for provider in required_providers:
            result = subprocess.run(
                [
                    "az",
                    "provider",
                    "show",
                    "--namespace",
                    provider,
                    "--subscription",
                    subscription_id,
                    "--query",
                    "registrationState",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return False, f"Failed to check provider {provider}"

            state = result.stdout.strip()
            if state != "Registered":
                return False, f"Provider {provider} is not registered (state: {state}). Register it with: az provider register --namespace {provider}"

        return True, "All required resource providers are registered"
    except subprocess.TimeoutExpired:
        return False, "Provider check timed out"
    except Exception as e:
        return False, f"Failed to check providers: {e}"


def get_llmaven_secrets(env_file_path: Optional[Path] = None) -> Dict[str, str]:
    """Get all LLMAVEN_SECRETS_* environment variables.

    Args:
        env_file_path: Optional path to .env file to load secrets from

    Returns:
        Dictionary mapping secret names (kebab-case) to values
    """
    # Load from .env file if provided
    if env_file_path is not None:
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
        for key, value in env_vars.items():
            if key.startswith(prefix) and value is not None:
                # Only set if not already in environment (env vars take precedence)
                if key not in os.environ:
                    os.environ[key] = value

    secrets = {}
    prefix = "LLMAVEN_SECRETS_"

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Remove prefix and convert to kebab-case
            secret_name = key[len(prefix):].lower().replace("_", "-")
            secrets[secret_name] = value

    return secrets


def check_secrets(
    config: LLMavenConfig,
    skip_secrets: bool = False,
    env_file_path: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """Check if required secrets are available as environment variables.

    Args:
        config: Configuration object
        skip_secrets: Skip secrets validation
        env_file_path: Optional path to .env file to load secrets from

    Returns:
        Tuple of (success, list of messages)
    """
    if skip_secrets:
        return True, ["Secrets validation skipped (--skip-secrets flag)"]

    messages = []
    all_secrets_found = True

    # Get available secrets from environment
    available_secrets = get_llmaven_secrets(env_file_path)

    if available_secrets:
        messages.append(f"Found {len(available_secrets)} LLMAVEN_SECRETS_* environment variables:")
        for secret_name in sorted(available_secrets.keys()):
            messages.append(f"  ✓ {secret_name}")
    else:
        messages.append("⚠️  No LLMAVEN_SECRETS_* environment variables found")

    # Check required secrets for MLflow
    if config.mlflow and config.mlflow.enabled:
        mlflow_secrets = config.mlflow.secrets or []
        for secret_name in mlflow_secrets:
            # Skip auto-generated secrets
            if secret_name in ["db-connection-string-mlflow-db", "storage-account-key"]:
                continue

            if secret_name not in available_secrets:
                env_var_name = f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"
                messages.append(f"  ✗ Missing: {secret_name} (set {env_var_name})")
                all_secrets_found = False

    # Check required secrets for LiteLLM
    if config.litellm and config.litellm.enabled:
        litellm_secrets = config.litellm.secrets or []
        for secret_name in litellm_secrets:
            # Skip auto-generated secrets
            if secret_name in ["db-connection-string-litellm-db", "mlflow-tracking-uri"]:
                continue

            if secret_name not in available_secrets:
                env_var_name = f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"
                messages.append(f"  ✗ Missing: {secret_name} (set {env_var_name})")
                all_secrets_found = False

    # Check for placeholder values
    placeholder_patterns = [
        "your-key-here",
        "changeme",
        "your-.*-key",
        "placeholder",
        "example",
    ]

    for secret_name, secret_value in available_secrets.items():
        for pattern in placeholder_patterns:
            if re.search(pattern, secret_value, re.IGNORECASE):
                messages.append(f"  ⚠️  Warning: {secret_name} looks like a placeholder value")
                break

    if not all_secrets_found:
        messages.append("")
        messages.append("Set missing secrets as environment variables:")
        messages.append('  export LLMAVEN_SECRETS_LITELLM_MASTER_KEY="$(openssl rand -base64 32)"')
        messages.append('  export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-azure-openai-key"')
        messages.append('  export LLMAVEN_SECRETS_ANTHROPIC_API_KEY="your-anthropic-key"')

    return all_secrets_found, messages


def check_config_for_hardcoded_secrets(config_path: Path) -> Tuple[bool, List[str]]:
    """Check if configuration file contains hardcoded secrets.

    Args:
        config_path: Path to configuration file

    Returns:
        Tuple of (success, list of messages)
    """
    messages = []
    has_hardcoded_secrets = False

    # Patterns that might indicate hardcoded secrets
    secret_patterns = [
        (r'sk-[a-zA-Z0-9]{32,}', "OpenAI/Anthropic API key"),
        (r'[a-zA-Z0-9]{32,}', "Generic API key (32+ chars)"),
        (r'postgres://[^:]+:[^@]+@', "Database connection string with password"),
        (r'password:\s*["\'][^"\']{8,}["\']', "Password field"),
    ]

    try:
        with open(config_path, "r") as f:
            content = f.read()

        for pattern, description in secret_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                messages.append(f"  ⚠️  Potential hardcoded secret detected: {description}")
                has_hardcoded_secrets = True

        if not has_hardcoded_secrets:
            messages.append("  ✓ No hardcoded secrets detected in configuration file")

    except Exception as e:
        messages.append(f"  ⚠️  Failed to scan for hardcoded secrets: {e}")

    return not has_hardcoded_secrets, messages


def estimate_monthly_cost(config: LLMavenConfig) -> Tuple[float, float]:
    """Estimate monthly Azure cost based on configuration.

    Args:
        config: Configuration object

    Returns:
        Tuple of (minimum monthly cost, maximum monthly cost)
    """
    min_cost = 0.0
    max_cost = 0.0

    # PostgreSQL costs (based on SKU)
    postgres_sku = config.database.sku_name.upper()
    if postgres_sku.startswith("B_"):
        # Burstable tier
        min_cost += 13.0
        max_cost += 20.0
    elif postgres_sku.startswith("GP_"):
        # General Purpose tier
        min_cost += 150.0
        max_cost += 300.0
    elif postgres_sku.startswith("MO_"):
        # Memory Optimized tier
        min_cost += 300.0
        max_cost += 600.0

    # Storage costs (rough estimate)
    storage_gb = config.database.storage_size_gb
    min_cost += storage_gb * 0.115  # Approximate $/GB/month

    # Blob Storage (rough estimate)
    min_cost += 2.0
    max_cost += 5.0

    # Container Apps (based on CPU/memory allocation)
    if config.mlflow and config.mlflow.enabled:
        cpu = float(config.mlflow.cpu)
        min_cost += cpu * 15.0  # Rough estimate per vCPU/month
        max_cost += cpu * 30.0

    if config.litellm and config.litellm.enabled:
        cpu = float(config.litellm.cpu)
        min_cost += cpu * 15.0
        max_cost += cpu * 30.0

    if config.llmaven_api and config.llmaven_api.enabled:
        cpu = float(config.llmaven_api.cpu)
        min_cost += cpu * 15.0
        max_cost += cpu * 30.0

    # Monitoring costs
    if config.monitoring.enable_application_insights:
        min_cost += 5.0
        max_cost += 20.0

    return min_cost, max_cost


def validate_config(
    config_path: Path,
    strict: bool = False,
    skip_secrets: bool = False,
    env_file_path: Optional[Path] = None,
) -> None:
    """Validate LLMaven deployment configuration.

    Args:
        config_path: Path to configuration file
        strict: Fail on warnings
        skip_secrets: Skip secrets validation
        env_file_path: Optional path to .env file to load secrets from

    Raises:
        ValidationError: If validation fails
    """
    print(f"🔍 Validating configuration: {config_path}")
    print()

    warnings = []
    errors = []

    # 1. Load and validate configuration syntax
    print("1. Configuration Syntax")
    try:
        config = load_config(config_path)
        print("   ✓ Valid YAML format")
        print("   ✓ All required fields present")
        print("   ✓ Data types are correct")
    except ConfigLoadError as e:
        print(f"   ✗ Configuration validation failed:")
        print(f"     {e}")
        errors.append(str(e))
    print()

    if errors:
        raise ValidationError("Configuration validation failed. Fix errors above and try again.")

    # 2. Check for hardcoded secrets
    print("2. Security Check")
    success, messages = check_config_for_hardcoded_secrets(config_path)
    for msg in messages:
        print(msg)
    if not success:
        warnings.append("Configuration file may contain hardcoded secrets")
    print()

    # 3. Azure Prerequisites
    print("3. Azure Prerequisites")

    # Check Azure CLI
    success, message = check_azure_cli()
    if success:
        print(f"   ✓ {message}")
    else:
        print(f"   ✗ {message}")
        errors.append(message)

    # Check subscription access
    if not errors:
        success, message = check_subscription_access(config.azure.subscription_id)
        if success:
            print(f"   ✓ {message}")
        else:
            print(f"   ✗ {message}")
            errors.append(message)

    # Check required providers
    if not errors:
        success, message = check_required_providers(config.azure.subscription_id)
        if success:
            print(f"   ✓ {message}")
        else:
            print(f"   ⚠️  {message}")
            warnings.append(message)

    print()

    # 4. Secrets Validation
    print("4. Secrets Validation")
    if env_file_path:
        print(f"   Loading secrets from: {env_file_path}")
    success, messages = check_secrets(config, skip_secrets, env_file_path)
    for msg in messages:
        print(msg)
    if not success:
        errors.append("Required secrets are missing")
    print()

    # 5. Cost Estimation
    print("5. Cost Estimation")
    min_cost, max_cost = estimate_monthly_cost(config)
    print(f"   Estimated monthly cost: ${min_cost:.2f} - ${max_cost:.2f}")

    if config.project.environment == "dev" and max_cost > 100:
        warnings.append(f"Development environment cost (${max_cost:.2f}) seems high")
        print(f"   ⚠️  Development environment cost seems high")
    elif config.project.environment == "prod" and max_cost < 50:
        warnings.append("Production environment cost seems low (may not have HA enabled)")
        print(f"   ⚠️  Production environment cost seems low (consider HA settings)")

    print()

    # 6. Production Validation
    if config.project.environment == "prod":
        print("6. Production Environment Checks")

        if not config.database.high_availability:
            warnings.append("Production environment should enable high availability for database")
            print("   ⚠️  High availability not enabled for database")

        if not config.security.enable_private_endpoints:
            warnings.append("Production environment should enable private endpoints")
            print("   ⚠️  Private endpoints not enabled")

        if config.database.geo_redundant_backup is False:
            warnings.append("Production environment should enable geo-redundant backups")
            print("   ⚠️  Geo-redundant backup not enabled")

        print()

    # Summary
    print("=" * 70)
    print()
    if errors:
        print("❌ Validation Failed")
        print()
        print("Errors:")
        for error in errors:
            print(f"  • {error}")
        print()
        raise ValidationError("Validation failed with errors")
    elif warnings and strict:
        print("⚠️  Validation Failed (strict mode)")
        print()
        print("Warnings:")
        for warning in warnings:
            print(f"  • {warning}")
        print()
        raise ValidationError("Validation failed with warnings (strict mode)")
    elif warnings:
        print("⚠️  Validation Passed with Warnings")
        print()
        print("Warnings:")
        for warning in warnings:
            print(f"  • {warning}")
        print()
        print("✓ Configuration is valid (warnings can be addressed later)")
    else:
        print("✅ Validation Passed")
        print()
        print("✓ Configuration is valid and ready for deployment")

    print()
