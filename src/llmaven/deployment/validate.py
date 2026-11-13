"""Validate LLMaven deployment configuration.

This module provides the implementation for the 'llmaven validate' command.
"""

import re
import subprocess
from pathlib import Path

from ..infrastructure.config.loader import ConfigLoadError, load_config
from ..infrastructure.config.litellm_models import missing_foundry_deployments
from ..infrastructure.config.schema import (
    FOUNDRY_MANAGED_SECRETS,
    LLMavenConfig,
    foundry_secret_collisions,
)
from ..infrastructure.utils.secrets import get_llmaven_secrets


class ValidationError(Exception):
    """Exception raised when validation fails."""


# RFC 2606 reserved domains. The generated configs ship ops@example.org, so an
# address at one of these means alerting was deployed but never wired up.
PLACEHOLDER_EMAIL_DOMAINS = ("@example.org", "@example.com", "@example.net")


def check_azure_cli() -> tuple[bool, str]:
    """Check if Azure CLI is installed and logged in.

    `az account show` reads only the local account cache, so it passes even
    when the login has expired. check_subscription_access tests the token for
    the configured subscription; an expired session in the CLI default
    subscription must not fail a deploy to another one.

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
            return (
                False,
                "Azure CLI is not installed. Install it from: https://aka.ms/InstallAzureCLI",
            )
    except FileNotFoundError:
        return (
            False,
            "Azure CLI is not installed. Install it from: https://aka.ms/InstallAzureCLI",
        )
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

    return True, "Azure CLI is installed and logged in"


def check_subscription_access(subscription_id: str) -> tuple[bool, str]:
    """Check that the Azure CLI can get an access token for the subscription.

    `az account get-access-token` refreshes the token, so unlike
    `az account show` it fails when the login has expired.

    Args:
        subscription_id: Azure subscription ID

    Returns:
        Tuple of (success, message)
    """
    if not subscription_id:
        return False, "Azure subscription ID is not set in configuration"

    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--subscription",
                subscription_id,
                "--query",
                "expiresOn",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return (
                False,
                f"Subscription {subscription_id} is not accessible: "
                f"{result.stderr.strip()}\n"
                "     If your Azure login has expired, run: az login",
            )
        return True, f"Subscription {subscription_id} is accessible"
    except subprocess.TimeoutExpired:
        return False, "Subscription check timed out"
    except Exception as e:
        return False, f"Failed to check subscription: {e}"


def check_required_providers(
    subscription_id: str, foundry_enabled: bool = False, redis_enabled: bool = False
) -> tuple[bool, str]:
    """Check if required Azure resource providers are registered.

    Args:
        subscription_id: Azure subscription ID
        foundry_enabled: Also require Microsoft.CognitiveServices
        redis_enabled: Also require Microsoft.Cache for Azure Managed Redis

    Returns:
        Tuple of (success, message)
    """
    required_providers = [
        "Microsoft.App",  # Container Apps
        "Microsoft.DBforPostgreSQL",  # PostgreSQL
        "Microsoft.Storage",  # Blob Storage
        "Microsoft.KeyVault",  # Key Vault
        "Microsoft.OperationalInsights",  # Log Analytics
        "Microsoft.Insights",  # Azure Monitor alerts and action groups
    ]
    if foundry_enabled:
        required_providers.append("Microsoft.CognitiveServices")  # Foundry
    if redis_enabled:
        required_providers.append("Microsoft.Cache")  # Azure Managed Redis

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
                return (
                    False,
                    f"Provider {provider} is not registered (state: {state}). Register it with: az provider register --namespace {provider}",
                )

        return True, "All required resource providers are registered"
    except subprocess.TimeoutExpired:
        return False, "Provider check timed out"
    except Exception as e:
        return False, f"Failed to check providers: {e}"


def check_secrets(
    config: LLMavenConfig,
    skip_secrets: bool = False,
    env_file_path: Path | None = None,
) -> tuple[bool, list[str]]:
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
        messages.append(
            f"Found {len(available_secrets)} LLMAVEN_SECRETS_* environment variables:"
        )
        for secret_name in sorted(available_secrets.keys()):
            messages.append(f"  ✓ {secret_name}")
    else:
        messages.append("⚠️  No LLMAVEN_SECRETS_* environment variables found")

    # Check required secrets for MLflow
    if config.mlflow and config.mlflow.enabled:
        mlflow_secrets = (
            list(config.mlflow.key_vault_secret_refs.values())
            if config.mlflow.key_vault_secret_refs
            else []
        )
        for secret_name in mlflow_secrets:
            # Skip auto-generated secrets
            if secret_name in [
                "db-connection-string-mlflow-db",
                "storage-account-key",
                "mlflow-artifact-root",
                "storage-connection-string",
            ]:
                continue

            if secret_name not in available_secrets:
                env_var_name = (
                    f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"
                )
                messages.append(f"  ✗ Missing: {secret_name} (set {env_var_name})")
                all_secrets_found = False

    # Check required secrets for LiteLLM
    if config.litellm and config.litellm.enabled:
        litellm_secrets = (
            list(config.litellm.key_vault_secret_refs.values())
            if config.litellm.key_vault_secret_refs
            else []
        )
        for secret_name in litellm_secrets:
            # Skip auto-generated secrets (derived from Pulumi-created Azure resources)
            if secret_name in [
                "db-connection-string-litellm-db",
                "mlflow-tracking-uri",
                "storage-connection-string",
            ]:
                continue
            if config.foundry.enabled and secret_name in FOUNDRY_MANAGED_SECRETS:
                continue

            if secret_name not in available_secrets:
                env_var_name = (
                    f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"
                )
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

    collisions = foundry_secret_collisions(
        config.foundry.enabled, list(available_secrets)
    )
    if collisions:
        all_secrets_found = False
        for secret_name in collisions:
            env_var_name = f"LLMAVEN_SECRETS_{secret_name.upper().replace('-', '_')}"
            messages.append(
                f"  ✗ {secret_name} is managed by the stack when foundry.enabled; "
                f"unset {env_var_name}"
            )

    for secret_name, secret_value in available_secrets.items():
        for pattern in placeholder_patterns:
            if re.search(pattern, secret_value, re.IGNORECASE):
                messages.append(
                    f"  ⚠️  Warning: {secret_name} looks like a placeholder value"
                )
                break

    if not all_secrets_found:
        messages.append("")
        messages.append("Set missing secrets as environment variables:")
        messages.append(
            '  export LLMAVEN_SECRETS_LITELLM_MASTER_KEY="$(openssl rand -base64 32)"'
        )
        messages.append(
            '  export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-azure-openai-key"'
        )
        messages.append(
            '  export LLMAVEN_SECRETS_ANTHROPIC_API_KEY="your-anthropic-key"'
        )

    return all_secrets_found, messages


def check_config_for_hardcoded_secrets(config_path: Path) -> tuple[bool, list[str]]:
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
        (r"sk-[a-zA-Z0-9]{32,}", "OpenAI/Anthropic API key"),
        (r"[a-zA-Z0-9]{32,}", "Generic API key (32+ chars)"),
        (r"postgres://[^:]+:[^@]+@", "Database connection string with password"),
        (r'password:\s*["\'][^"\']{8,}["\']', "Password field"),
    ]

    try:
        with open(config_path, "r") as f:
            content = f.read()

        for pattern, description in secret_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                messages.append(
                    f"   ⚠️  Potential hardcoded secret detected: {description}"
                )
                has_hardcoded_secrets = True

        if not has_hardcoded_secrets:
            messages.append("   ✓ No hardcoded secrets detected in configuration file")

    except Exception as e:
        messages.append(f"   ⚠️  Failed to scan for hardcoded secrets: {e}")

    return not has_hardcoded_secrets, messages


# Pulumi state store: a Standard LRS storage account that holds the Pulumi
# state blobs. State files are small and transaction volume is low, so the cost
# is modest, but every Azure deployment provisions one (auto-created when
# project.pulumi_state_store is not supplied), so it is always included.
STATE_STORE_MIN_COST = 1.0
STATE_STORE_MAX_COST = 3.0

# Azure Managed Redis, $/hour per node (Azure Retail Prices API, eastus,
# 2026-11-02). High availability runs two nodes, so it doubles the price.
REDIS_HOURLY_PRICE_PER_NODE = {
    "Balanced_B0": 0.016,
    "Balanced_B1": 0.032,
    "Balanced_B3": 0.065,
    "Balanced_B5": 0.156,
}
HOURS_PER_MONTH = 730
# A private endpoint is about $0.01/hour plus data processing.
PRIVATE_ENDPOINT_MIN_COST = 7.3
PRIVATE_ENDPOINT_MAX_COST = 10.0
# Unconfirmed estimate; see docs/superpowers/plans/2026-11-05-monitoring-alerts-pr1.md "Verified facts" row 6.
METRIC_ALERT_MONTHLY_COST = 0.10
# Unconfirmed estimate; see docs/superpowers/plans/2026-11-05-monitoring-alerts-pr1.md "Verified facts" row 6.
LOG_ALERT_MONTHLY_COST = 0.50


def estimate_redis_monthly_cost(config: LLMavenConfig) -> float | None:
    """Return the monthly Azure Managed Redis node cost, or None if the SKU is unpriced."""
    hourly = REDIS_HOURLY_PRICE_PER_NODE.get(config.redis.sku_name)
    if hourly is None:
        return None
    nodes = 2 if config.redis.high_availability else 1
    return hourly * nodes * HOURS_PER_MONTH


def estimate_alerts_monthly_cost(config: LLMavenConfig) -> float:
    """Return the monthly cost of the enabled alert rules.

    Gateway alerts only exist when LiteLLM is enabled. replica_restarts is
    created once per enabled container app (LiteLLM, MLflow). cloud_budget is free.
    """
    enabled = set(config.monitoring.alerts.enabled_alerts)
    metric_count = len(enabled & {"db_storage", "db_cpu"})
    if config.litellm.enabled:
        metric_count += len(enabled & {"gateway_errors", "gateway_latency"})
    if "replica_restarts" in enabled:
        metric_count += int(bool(config.litellm.enabled)) + int(
            bool(config.mlflow.enabled)
        )
    log_count = (
        1 if "backup_job_failures" in enabled and config.backup_job.enabled else 0
    )
    return metric_count * METRIC_ALERT_MONTHLY_COST + log_count * LOG_ALERT_MONTHLY_COST


def estimate_monthly_cost(config: LLMavenConfig) -> tuple[float, float]:
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

    # Pulumi state store (separate storage account used as the Pulumi backend)
    min_cost += STATE_STORE_MIN_COST
    max_cost += STATE_STORE_MAX_COST

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

    # Azure Managed Redis and its private endpoint
    if config.redis.enabled:
        min_cost += PRIVATE_ENDPOINT_MIN_COST
        max_cost += PRIVATE_ENDPOINT_MAX_COST
        redis_cost = estimate_redis_monthly_cost(config)
        if redis_cost is not None:
            min_cost += redis_cost
            max_cost += redis_cost

    # Monitoring costs
    alerts_cost = estimate_alerts_monthly_cost(config)
    min_cost += alerts_cost
    max_cost += alerts_cost

    return min_cost, max_cost


def validate_config(
    config_path: Path,
    strict: bool = False,
    skip_secrets: bool = False,
    env_file_path: Path | None = None,
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
        print("   ✗ Configuration validation failed:")
        print(f"     {e}")
        errors.append(str(e))
    print()

    if errors:
        raise ValidationError(
            "Configuration validation failed. Fix errors above and try again."
        )

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
        success, message = check_required_providers(
            config.azure.subscription_id,
            foundry_enabled=config.foundry.enabled,
            redis_enabled=bool(config.redis.enabled),
        )
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
        errors.append("Required secrets are missing or conflict with Foundry")
    print()

    # 4.1. Foundry model deployments
    if config.foundry.enabled:
        print("4.1. Foundry Model Deployments")
        for d in config.foundry.deployments:
            print(
                f"   ✓ {d.name}: {d.model_format} {d.model_name} {d.model_version} "
                f"({d.sku}, capacity {d.capacity}, {d.version_upgrade_option})"
            )
        if not config.foundry.deployments:
            warnings.append("foundry.enabled but foundry.deployments is empty")
            print("   ⚠️  No model deployments configured")
        for message in missing_foundry_deployments(config, config_path):
            print(f"   ✗ {message}")
            errors.append(message)
        print(
            "   ℹ️  Quota and regional model availability are checked by Azure, "
            "not here; they surface at deploy time"
        )
        print()

    # 4.2. Alert recipients
    alerts = config.monitoring.alerts
    if alerts.enabled_alerts:
        print("4.2. Alert Recipients")
        placeholders = [
            address
            for address in alerts.email_receivers
            if address.lower().endswith(PLACEHOLDER_EMAIL_DOMAINS)
        ]
        if placeholders:
            message = (
                "monitoring.alerts.email_receivers still uses the placeholder "
                f"address(es) {', '.join(placeholders)}; alerts would be "
                "created but nobody would receive them"
            )
            warnings.append(message)
            print(f"   ⚠️  {message}")
        else:
            print(
                f"   ✓ {len(alerts.enabled_alerts)} alert(s) notify "
                f"{len(alerts.email_receivers)} address(es)"
            )
        print()

    # 5. Cost Estimation
    print("5. Cost Estimation")
    min_cost, max_cost = estimate_monthly_cost(config)
    print(f"   Estimated monthly cost: ${min_cost:.2f} - ${max_cost:.2f}")
    if config.redis.enabled and estimate_redis_monthly_cost(config) is None:
        print(
            f"   ℹ️  Redis SKU {config.redis.sku_name} has no price in the estimate; "
            "check the Azure pricing calculator"
        )

    if config.project.environment == "dev" and max_cost > 100:
        warnings.append(f"Development environment cost (${max_cost:.2f}) seems high")
        print("   ⚠️  Development environment cost seems high")
    elif config.project.environment == "prod" and max_cost < 50:
        warnings.append(
            "Production environment cost seems low (may not have HA enabled)"
        )
        print("   ⚠️  Production environment cost seems low (consider HA settings)")

    print()

    # Edge-only settings with the edge off have no effect
    if not config.edge.enabled:
        ignored = [
            name
            for name, value in (
                ("litellm.hostname", config.litellm.hostname),
                ("litellm.admin_allowed_ips", config.litellm.admin_allowed_ips),
                ("mlflow.hostname", config.mlflow.hostname),
            )
            if value
        ]
        for name in ignored:
            message = (
                f"{name} is set but edge.enabled is false, so it has no effect"
                + (
                    "; the admin surface is not restricted unless the proxy "
                    "sidecar or ingress restrictions do it"
                    if name == "litellm.admin_allowed_ips"
                    else ""
                )
            )
            warnings.append(message)
            print(f"   ⚠️  {message}")
        if ignored:
            print()

    # 6. Production Validation
    if config.project.environment == "prod":
        print("6. Production Environment Checks")

        if not config.database.high_availability:
            warnings.append(
                "Production environment should enable high availability for database"
            )
            print("   ⚠️  High availability not enabled for database")

        if not config.security.enable_private_endpoints:
            warnings.append("Production environment should enable private endpoints")
            print("   ⚠️  Private endpoints not enabled")

        if config.database.geo_redundant_backup is False:
            warnings.append(
                "Production environment should enable geo-redundant backups"
            )
            print("   ⚠️  Geo-redundant backup not enabled")

        if config.edge.enabled and config.edge.min_replicas < 2:
            warnings.append(
                "Production environment should run the edge with edge.min_replicas "
                "of at least 2: it is the single entry point"
            )
            print("   ⚠️  edge.min_replicas is below 2")

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
