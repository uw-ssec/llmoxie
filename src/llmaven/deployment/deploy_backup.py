"""Deploy LLMaven backup storage infrastructure to Azure.

Provisions the isolated backup storage stack (resource group + storage account +
pg-backups container). Intended to be deployed once, independently of the main
stack, so that the backups survive a main-stack destroy.

After deployment, copy the `backup_storage_connection_string` output value into
the BACKUP_STORAGE_CONNECTION_STRING environment variable before deploying the
main stack to wire the Container Apps backup job.
"""

import os
from pathlib import Path

from pulumi import automation as auto

from .deploy import DeploymentError, _get_storage_key
from ..infrastructure_backup.main import create_backup_storage_program

CONTAINER_NAME = "pulumi-state"
PULUMI_BACKEND_URL = "azblob://{container}?storage_account={storage_account}"
BACKUP_PROJECT_NAME = "llmaven-backup"


def _load_backup_config(config_path: Path) -> dict:
    import yaml

    if not config_path.exists():
        raise DeploymentError(f"Backup config file not found: {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_backup_stack(config_path: Path) -> auto.Stack:
    """Get or create the backup storage Pulumi stack.

    Args:
        config_path: Path to llmaven-backup-config.yaml

    Returns:
        Stack object

    Raises:
        DeploymentError: If stack creation fails
    """
    cfg = _load_backup_config(config_path)
    rg_name = cfg["azure"]["resource_group"]
    state_store = cfg["project"]["pulumi_state_store"]
    environment = cfg["project"]["environment"]
    stack_name = f"{BACKUP_PROJECT_NAME}-{environment}"

    if not rg_name or not state_store:
        raise DeploymentError(
            "azure.resource_group and project.pulumi_state_store must be set in the backup config."
        )

    os.environ.setdefault(
        "PULUMI_BACKEND_URL",
        PULUMI_BACKEND_URL.format(
            container=CONTAINER_NAME, storage_account=state_store
        ),
    )
    os.environ.setdefault("AZURE_STORAGE_ACCOUNT", state_store)
    storage_key = _get_storage_key(rg_name, state_store)
    if storage_key:
        os.environ.setdefault("AZURE_STORAGE_KEY", storage_key)

    program = create_backup_storage_program(config_path)

    try:
        stack = auto.create_or_select_stack(
            stack_name=stack_name,
            project_name=BACKUP_PROJECT_NAME,
            program=program,
        )
    except Exception as e:
        raise DeploymentError(f"Failed to create or select backup stack: {e}")

    return stack


def deploy_backup_storage(
    config_path: Path,
    preview: bool = False,
    auto_approve: bool = False,
) -> None:
    """Deploy the backup storage stack.

    Args:
        config_path: Path to llmaven-backup-config.yaml
        preview: Preview changes without deploying
        auto_approve: Skip confirmation prompt

    Raises:
        DeploymentError: If deployment fails
    """
    print("🗄️  LLMaven Backup Storage Deployment")
    print()

    cfg = _load_backup_config(config_path)
    if not cfg.get("project", {}).get("enable_passphrase", False):
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    environment = cfg["project"]["environment"]
    stack_name = f"{BACKUP_PROJECT_NAME}-{environment}"

    print(f"Stack:    {stack_name}")
    print(f"Location: {cfg['project']['location']}")
    print()

    try:
        stack = get_backup_stack(config_path)
        stack.workspace.install_plugin("azure-native", "v2.0.0")

        if preview:
            result = stack.preview(on_output=lambda msg: print(msg))
            print()
            print(f"Resources to create: {result.change_summary.get('create', 0)}")
            print(f"Resources to update: {result.change_summary.get('update', 0)}")
            return

        if not auto_approve:
            print("⚠️  This will create a storage account for PostgreSQL backups.")
            print()
            try:
                confirm = input("Continue? (yes/no): ").strip().lower()
                if confirm != "yes":
                    print("Deployment cancelled.")
                    return
            except (KeyboardInterrupt, EOFError):
                print("\nDeployment cancelled.")
                return

        up_result = stack.up(on_output=lambda msg: print(msg))

        print()
        print("=" * 70)
        print()
        print("✅ Backup storage deployed successfully!")
        print()

        if up_result.outputs:
            print("Outputs:")
            for key, output in up_result.outputs.items():
                value = "(secret)" if output.secret else output.value
                print(f"  {key}: {value}")
            print()

        conn_str_output = up_result.outputs.get("backup_storage_connection_string")
        if conn_str_output:
            print("Next step — set this before deploying the main stack:")
            print()
            print(
                "  export BACKUP_STORAGE_CONNECTION_STRING=$(llmaven backup-infra output \\"
            )
            print(
                f"    --config {config_path} --secret backup_storage_connection_string)"
            )
            print()

    except auto.errors.CommandError as e:
        raise DeploymentError(f"Pulumi command failed: {e}")
    except Exception as e:
        raise DeploymentError(f"Backup storage deployment failed: {e}")


def get_backup_stack_output(
    config_path: Path, output_name: str, reveal_secret: bool = False
) -> str:
    """Print a specific stack output value.

    Args:
        config_path: Path to llmaven-backup-config.yaml
        output_name: Output key to retrieve
        reveal_secret: Whether to reveal secret values

    Returns:
        Output value string
    """
    cfg = _load_backup_config(config_path)
    if not cfg.get("project", {}).get("enable_passphrase", False):
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")

    stack = get_backup_stack(config_path)
    outputs = stack.outputs()

    if output_name not in outputs:
        raise DeploymentError(
            f"Output '{output_name}' not found. Available: {list(outputs.keys())}"
        )

    output = outputs[output_name]
    if output.secret and not reveal_secret:
        raise DeploymentError(
            f"'{output_name}' is a secret. Use --reveal-secret to show its value."
        )

    return output.value
