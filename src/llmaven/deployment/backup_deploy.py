"""Deploy LLMaven backup infrastructure to Azure.

This module provides the implementation for 'llmaven infra backup' commands.
Uses Pulumi Automation API to deploy an Azure Backup Vault in an isolated
resource group, separate from the primary infrastructure stack.

The backup Pulumi project is named 'infrastructure-backup' and uses its own
Azure Blob Storage backend (in the backup resource group), so it is independent
of the primary stack's state store.
"""

import json
import os
import subprocess
from pathlib import Path

from pulumi import automation as auto

from ..infrastructure_backup.config.loader import (
    BackupConfigLoadError,
    load_backup_config,
    update_backup_config_fields,
)
from ..infrastructure_backup.config.defaults import get_backup_config_template_yaml
from ..infrastructure_backup.main import create_backup_program

CONTAINER_NAME = "pulumi-state"
PULUMI_BACKEND_URL = "azblob://{container}?storage_account={storage_account}"
BACKUP_PROJECT_NAME = "infrastructure-backup"


class BackupDeploymentError(Exception):
    """Exception raised when backup deployment fails."""

    pass


def _run_az_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run an Azure CLI command."""
    try:
        return subprocess.run(
            ["az"] + args,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        raise BackupDeploymentError(f"Azure CLI command failed: {e.stderr.strip()}")
    except FileNotFoundError:
        raise BackupDeploymentError(
            "Azure CLI is not installed. Install it from: https://aka.ms/InstallAzureCLI"
        )


def _get_storage_key(rg_name: str, storage_account: str) -> str | None:
    """Get storage account key if the account exists."""
    try:
        result = _run_az_command(
            [
                "storage",
                "account",
                "show",
                "--name",
                storage_account,
                "--resource-group",
                rg_name,
                "--output",
                "json",
            ],
            check=False,
        )
        if result.returncode == 0:
            keys_result = _run_az_command(
                [
                    "storage",
                    "account",
                    "keys",
                    "list",
                    "--account-name",
                    storage_account,
                    "--resource-group",
                    rg_name,
                    "--output",
                    "json",
                ]
            )
            return json.loads(keys_result.stdout)[0]["value"]
        return None
    except Exception:
        return None


def _get_unique_name(base_name: str, max_len: int = 24) -> str:
    """Generate a unique name by appending a UUID fragment."""
    import uuid

    return (base_name + uuid.uuid4().hex)[:max_len]


def initialize_backup_azure_infra(config_path: Path) -> None:
    """Initialize Azure infrastructure for the backup Pulumi state.

    Creates a dedicated resource group and storage account for the backup
    stack's Pulumi state. This is separate from the primary stack's state
    storage, ensuring the backup state survives deletion of the primary RG.

    Also creates the backup resource group that will hold the Backup Vault.
    Since the same resource group holds both the Pulumi state and the Backup
    Vault resources, the backup stack is fully contained and isolated.

    Args:
        config_path: Path to llmaven-backup-config.yaml

    Raises:
        BackupDeploymentError: If Azure CLI commands fail
    """
    config = load_backup_config(config_path)

    if config.project.pulumi_state_store:
        backend_url = PULUMI_BACKEND_URL.format(
            container=CONTAINER_NAME,
            storage_account=config.project.pulumi_state_store,
        )
        print(f"   Using existing backup backend: {backend_url}")
        return

    subscription_id = config.azure.subscription_id
    project_name = config.project.name
    environment = config.project.environment
    location = config.project.location

    # Backup resource group: separate from primary RG
    rg_name = f"rg-{project_name}-{environment}-{location}"
    storage_account = _get_unique_name("pulumibackup", 24)

    if not (
        storage_account.isalnum()
        and storage_account == storage_account.lower()
        and 3 <= len(storage_account) <= 24
    ):
        raise BackupDeploymentError(
            "Storage account name must be lowercase alphanumeric and 3-24 characters."
        )

    try:
        _run_az_command(["account", "set", "--subscription", subscription_id])

        storage_key = _get_storage_key(rg_name, storage_account)

        if storage_key is not None:
            print(f"   ✓ Backup storage account already exists: {storage_account}")
        else:
            _run_az_command(
                [
                    "group",
                    "create",
                    "--name",
                    rg_name,
                    "--location",
                    location,
                    "--tags",
                    "purpose=llmaven-backup",
                    f"project={project_name}",
                    f"environment={environment}",
                ]
            )
            print(f"   ✓ Backup resource group created: {rg_name}")

            _run_az_command(
                [
                    "storage",
                    "account",
                    "create",
                    "--name",
                    storage_account,
                    "--resource-group",
                    rg_name,
                    "--location",
                    location,
                    "--sku",
                    "Standard_LRS",
                    "--kind",
                    "StorageV2",
                    "--tags",
                    "purpose=pulumi-backup-state",
                    f"project={project_name}",
                ]
            )
            print(f"   ✓ Backup state storage account created: {storage_account}")

            result = _run_az_command(
                [
                    "storage",
                    "account",
                    "keys",
                    "list",
                    "--account-name",
                    storage_account,
                    "--resource-group",
                    rg_name,
                    "--output",
                    "json",
                ]
            )
            storage_key = json.loads(result.stdout)[0]["value"]

            _run_az_command(
                [
                    "storage",
                    "container",
                    "create",
                    "--name",
                    CONTAINER_NAME,
                    "--account-name",
                    storage_account,
                    "--account-key",
                    storage_key,
                ]
            )
            print(f"   ✓ Pulumi state container created: {CONTAINER_NAME}")

        print()
        print("   ✓ Backup Pulumi backend configured.")

        update_backup_config_fields(
            config_path,
            {
                "azure.resource_group": rg_name,
                "project.pulumi_state_store": storage_account,
            },
        )

    except BackupDeploymentError:
        raise
    except Exception as e:
        raise BackupDeploymentError(f"Failed to create backup Pulumi backend: {e}")


def populate_from_primary_stack(
    backup_config_path: Path,
    primary_config_path: Path,
) -> None:
    """Populate primary_stack.* fields in the backup config from primary stack outputs.

    Reads the deployed primary stack and copies the PostgreSQL server name,
    resource group, and state store into the backup config file.

    Args:
        backup_config_path: Path to llmaven-backup-config.yaml (will be updated)
        primary_config_path: Path to the primary llmaven-config.yaml

    Raises:
        BackupDeploymentError: If primary stack outputs cannot be read
    """
    from ..deployment.deploy import get_stack as get_primary_stack, PULUMI_BACKEND_URL as PRIMARY_BACKEND_URL
    from ..infrastructure.config.loader import load_config as load_primary_config

    try:
        primary_config = load_primary_config(primary_config_path)
    except Exception as e:
        raise BackupDeploymentError(f"Failed to load primary config: {e}")

    primary_state_store = primary_config.project.pulumi_state_store
    primary_rg = primary_config.azure.resource_group

    if not primary_state_store or not primary_rg:
        raise BackupDeploymentError(
            "Primary stack has not been initialized yet. "
            "Run 'llmaven infra deploy' first to deploy the primary infrastructure."
        )

    # Set up env to point at the primary backend
    os.environ["PULUMI_BACKEND_URL"] = PRIMARY_BACKEND_URL.format(
        storage_account=primary_state_store
    )
    os.environ["AZURE_STORAGE_ACCOUNT"] = primary_state_store
    storage_key = _get_storage_key(primary_rg, primary_state_store)
    if storage_key:
        os.environ["AZURE_STORAGE_KEY"] = storage_key

    if not primary_config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    try:
        stack_name = f"{primary_config.project.name}-{primary_config.project.environment}"
        primary_stack = get_primary_stack(
            stack_name=stack_name,
            project_name=primary_config.project.name,
            config_path=primary_config_path,
        )
        outputs = primary_stack.outputs()
    except Exception as e:
        raise BackupDeploymentError(f"Failed to read primary stack outputs: {e}")

    postgres_server_name = outputs.get("postgres_server_name")
    if not postgres_server_name:
        raise BackupDeploymentError(
            "Could not find 'postgres_server_name' in primary stack outputs. "
            "Ensure the primary stack has been deployed successfully."
        )

    update_backup_config_fields(
        backup_config_path,
        {
            "azure.subscription_id": primary_config.azure.subscription_id,
            "azure.tenant_id": primary_config.azure.tenant_id,
            "primary_stack.resource_group_name": primary_rg,
            "primary_stack.postgres_server_name": postgres_server_name.value,
            "primary_stack.pulumi_state_store": primary_state_store,
        },
    )

    print(f"   ✓ Populated from primary stack '{stack_name}':")
    print(f"     postgres_server_name : {postgres_server_name.value}")
    print(f"     resource_group_name  : {primary_rg}")
    print(f"     pulumi_state_store   : {primary_state_store}")


def get_backup_stack(stack_name: str, config_path: Path) -> auto.Stack:
    """Get or create the backup Pulumi stack.

    Args:
        stack_name: Stack name (e.g., llmaven-backup-dev)
        config_path: Path to llmaven-backup-config.yaml

    Returns:
        Pulumi Stack object

    Raises:
        BackupDeploymentError: If stack creation fails
    """
    try:
        config = load_backup_config(config_path)
        rg_name = config.azure.resource_group
        storage_account = config.project.pulumi_state_store

        if not rg_name or not storage_account:
            raise BackupDeploymentError(
                "Backup Pulumi backend is not configured. "
                "Run 'llmaven infra backup init' first."
            )

        os.environ["PULUMI_BACKEND_URL"] = PULUMI_BACKEND_URL.format(
            container=CONTAINER_NAME,
            storage_account=storage_account,
        )
        os.environ["AZURE_STORAGE_ACCOUNT"] = storage_account
        storage_key = _get_storage_key(rg_name, storage_account)
        if storage_key:
            os.environ["AZURE_STORAGE_KEY"] = storage_key

        program = create_backup_program(config_path)

        try:
            stack = auto.create_or_select_stack(
                stack_name=stack_name,
                project_name=BACKUP_PROJECT_NAME,
                program=program,
            )
        except Exception as e:
            raise BackupDeploymentError(f"Failed to create or select backup stack: {e}")

        return stack

    except BackupDeploymentError:
        raise
    except Exception as e:
        raise BackupDeploymentError(f"Failed to initialize backup stack: {e}")


def deploy_backup(
    config_path: Path,
    preview: bool = False,
    auto_approve: bool = False,
) -> None:
    """Deploy the backup infrastructure.

    Args:
        config_path: Path to llmaven-backup-config.yaml
        preview: Preview changes without deploying
        auto_approve: Skip confirmation prompt

    Raises:
        BackupDeploymentError: If deployment fails
    """
    print("🛡️  LLMaven Backup Infrastructure Deployment")
    print()

    config = load_backup_config(config_path)
    _validate_backup_config_ready(config)

    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    print("Step 1: Initializing backup Azure infrastructure...")
    initialize_backup_azure_infra(config_path)
    # Reload config after init (resource_group and pulumi_state_store may have been set)
    config = load_backup_config(config_path)

    print()
    print("=" * 70)
    print()

    environment = config.project.environment
    stack_name = f"{config.project.name}-{environment}"

    print(f"Step 2: {'Previewing' if preview else 'Deploying'} backup infrastructure...")
    print(f"Stack: {stack_name}")
    print(f"Backup RG: {config.azure.resource_group}")
    print(f"Target PostgreSQL server: {config.primary_stack.postgres_server_name}")
    print()

    try:
        print("Initializing Pulumi backup stack...")
        stack = get_backup_stack(stack_name=stack_name, config_path=config_path)
        print(f"✓ Backup stack initialized: {stack_name}")
        print()

        print("Installing required Pulumi plugins...")
        stack.workspace.install_plugin("azure-native", "v2.0.0")
        print("✓ Plugins installed")
        print()

        if preview:
            print("Running Pulumi preview...")
            preview_result = stack.preview(on_output=lambda msg: print(msg))
            print()
            print("✓ Preview completed")
            print(f"Resources to create: {preview_result.change_summary.get('create', 0)}")
            print(f"Resources to update: {preview_result.change_summary.get('update', 0)}")
            print(f"Resources to delete: {preview_result.change_summary.get('delete', 0)}")
        else:
            if not auto_approve:
                print("⚠️  This will deploy backup infrastructure to Azure.")
                print()
                try:
                    confirm = input("Continue? (yes/no): ").strip().lower()
                    if confirm != "yes":
                        print("Deployment cancelled.")
                        return
                except (KeyboardInterrupt, EOFError):
                    print("\nDeployment cancelled.")
                    return

            print("Running Pulumi deployment...")
            print()
            up_result = stack.up(on_output=lambda msg: print(msg))

            print()
            print("=" * 70)
            print()
            print("✅ Backup deployment completed successfully!")
            print()

            if up_result.outputs:
                print("Deployment Outputs:")
                for key, output in up_result.outputs.items():
                    print(f"  {key}: {output.value}")
                print()

    except auto.errors.CommandError as e:
        raise BackupDeploymentError(f"Pulumi command failed: {e}")
    except Exception as e:
        raise BackupDeploymentError(f"Backup deployment failed: {e}")


def destroy_backup(config_path: Path) -> None:
    """Destroy the backup infrastructure.

    WARNING: This removes the Backup Vault and all recovery points.
    If immutability is enabled on the vault, destruction will fail —
    you must first disable immutability in the Azure Portal.

    Args:
        config_path: Path to llmaven-backup-config.yaml

    Raises:
        BackupDeploymentError: If destruction fails
    """
    print("🗑️  LLMaven Backup Infrastructure Destruction")
    print()
    print("⚠️  WARNING: This will delete the Backup Vault and ALL recovery points!")
    print("⚠️  If vault immutability is enabled, you must disable it in the Azure")
    print("   Portal before this command can succeed.")
    print()

    config = load_backup_config(config_path)

    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    environment = config.project.environment
    stack_name = f"{config.project.name}-{environment}"

    print(f"Stack: {stack_name}")
    print()

    try:
        stack = get_backup_stack(stack_name=stack_name, config_path=config_path)

        print("Running Pulumi destroy...")
        stack.destroy(on_output=lambda msg: print(msg))

        print()
        print("✅ Backup infrastructure destroyed successfully")

        try:
            confirm = input("Remove stack history? (yes/no): ").strip().lower()
            if confirm == "yes":
                stack.workspace.remove_stack(stack_name)
                print(f"✓ Stack {stack_name} removed")
        except (KeyboardInterrupt, EOFError):
            print("\nStack history preserved")

    except auto.errors.CommandError as e:
        raise BackupDeploymentError(f"Pulumi destroy failed: {e}")
    except Exception as e:
        raise BackupDeploymentError(f"Backup destruction failed: {e}")


def refresh_backup(config_path: Path, auto_approve: bool = False) -> None:
    """Refresh the backup Pulumi state from actual cloud resources.

    Args:
        config_path: Path to llmaven-backup-config.yaml
        auto_approve: Skip confirmation prompt

    Raises:
        BackupDeploymentError: If refresh fails
    """
    print("🔄 LLMaven Backup Infrastructure Refresh")
    print()

    config = load_backup_config(config_path)

    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    environment = config.project.environment
    stack_name = f"{config.project.name}-{environment}"

    print(f"Stack: {stack_name}")
    print()

    try:
        stack = get_backup_stack(stack_name=stack_name, config_path=config_path)
        stack.workspace.install_plugin("azure-native", "v2.0.0")

        if not auto_approve:
            print("⚠️  This will update the backup stack state from actual cloud resources.")
            try:
                confirm = input("Continue? (yes/no): ").strip().lower()
                if confirm != "yes":
                    print("Refresh cancelled.")
                    return
            except (KeyboardInterrupt, EOFError):
                print("\nRefresh cancelled.")
                return

        print("Running Pulumi refresh...")
        stack.refresh(on_output=lambda msg: print(msg))

        print()
        print("✅ Backup refresh completed successfully!")

    except auto.errors.StackNotFoundError:
        print("⚠️  Backup stack not found. Deploy it first:")
        print(f"  llmaven infra backup deploy --config {config_path}")
    except auto.errors.CommandError as e:
        raise BackupDeploymentError(f"Pulumi refresh failed: {e}")
    except Exception as e:
        raise BackupDeploymentError(f"Backup refresh failed: {e}")


def show_backup_status(config_path: Path) -> None:
    """Show current backup deployment status and outputs.

    Args:
        config_path: Path to llmaven-backup-config.yaml

    Raises:
        BackupDeploymentError: If status check fails
    """
    print("📊 LLMaven Backup Deployment Status")
    print()

    config = load_backup_config(config_path)

    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    environment = config.project.environment
    stack_name = f"{config.project.name}-{environment}"

    print(f"Stack: {stack_name}")
    print()

    try:
        stack = get_backup_stack(stack_name=stack_name, config_path=config_path)
        outputs = stack.outputs()

        if not outputs:
            print("⚠️  No backup deployment found or stack has no outputs")
            print()
            print("Deploy backup infrastructure first:")
            print(f"  llmaven infra backup deploy --config {config_path}")
            return

        print("Deployment Outputs:")
        for key, output in sorted(outputs.items()):
            print(f"  {key}: {output.value}")

        print()
        print("✓ Backup deployment is active")

    except auto.errors.StackNotFoundError:
        print("⚠️  Backup stack not found. Deploy it first:")
        print(f"  llmaven infra backup deploy --config {config_path}")
    except auto.errors.CommandError as e:
        raise BackupDeploymentError(f"Failed to get backup stack status: {e}")
    except Exception as e:
        raise BackupDeploymentError(f"Backup status check failed: {e}")


def _validate_backup_config_ready(config) -> None:
    """Raise BackupDeploymentError if required fields are not set."""
    errors = []

    if not config.azure.subscription_id:
        errors.append("azure.subscription_id is required")
    if not config.primary_stack.resource_group_name:
        errors.append(
            "primary_stack.resource_group_name is not set — "
            "run 'llmaven infra backup init --from-primary-stack' to populate it"
        )
    if not config.primary_stack.postgres_server_name:
        errors.append(
            "primary_stack.postgres_server_name is not set — "
            "run 'llmaven infra backup init --from-primary-stack' to populate it"
        )

    if errors:
        raise BackupDeploymentError(
            "Backup configuration is incomplete:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )
