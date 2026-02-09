"""Deploy LLMaven infrastructure to Azure.

This module provides the implementation for the 'llmaven deploy' command.
Uses Pulumi Automation API for programmatic infrastructure deployment.
"""

import os
from pathlib import Path

from pulumi import automation as auto

from .validate import ValidationError, validate_config
from ..infrastructure.main import create_pulumi_program


class DeploymentError(Exception):
    """Exception raised when deployment fails."""

    pass


def get_stack(
    stack_name: str,
    project_name: str,
    config_path: Path,
) -> auto.Stack:
    """Get or create a Pulumi stack using Automation API with inline program.

    Args:
        stack_name: Name of the stack
        project_name: Name of the Pulumi project
        config_path: Path to LLMaven configuration file

    Returns:
        Stack object

    Raises:
        DeploymentError: If stack creation fails
    """
    try:
        # Create inline Pulumi program
        program = create_pulumi_program(config_path)

        # Create or select stack with inline program
        try:
            stack = auto.create_or_select_stack(
                stack_name=stack_name,
                project_name=project_name,
                program=program,
            )
        except Exception as e:
            raise DeploymentError(f"Failed to create or select stack: {e}")

        return stack

    except Exception as e:
        raise DeploymentError(f"Failed to initialize stack: {e}")


def deploy_infrastructure(
    config_path: Path,
    preview: bool = False,
    auto_approve: bool = False,
    env_file_path: Path | None = None,
) -> None:
    """Deploy LLMaven infrastructure to Azure.

    Args:
        config_path: Path to configuration file
        preview: Preview changes without deploying
        auto_approve: Automatically approve deployment
        env_file_path: Optional path to .env file to load secrets from

    Raises:
        DeploymentError: If deployment fails
    """
    print("🚀 LLMaven Infrastructure Deployment")
    print()

    # Validate configuration first
    print("Step 1: Validating configuration...")
    print()
    try:
        validate_config(
            config_path, strict=False, skip_secrets=False, env_file_path=env_file_path
        )
    except ValidationError as e:
        print()
        print("❌ Configuration validation failed. Fix errors and try again.")
        raise DeploymentError(str(e))

    print()
    print("=" * 70)
    print()

    # Get stack name from config
    from ..infrastructure.config.loader import load_config

    config = load_config(config_path)

    # Handle Pulumi passphrase setting
    if not config.project.enable_passphrase:
        # Disable passphrase requirement by setting empty string
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    else:
        # Passphrase required - check if it's set
        if (
            "PULUMI_CONFIG_PASSPHRASE" not in os.environ
            or not os.environ["PULUMI_CONFIG_PASSPHRASE"]
        ):
            raise DeploymentError(
                "Passphrase protection is enabled in config but PULUMI_CONFIG_PASSPHRASE "
                "environment variable is not set. Either set the environment variable or "
                "disable passphrase protection by setting 'enable_passphrase: false' in the config."
            )

    stack_name = f"{config.project.name}-{config.project.environment}"
    project_name = "llmaven"

    print(f"Step 2: {'Previewing' if preview else 'Deploying'} infrastructure...")
    print(f"Stack: {stack_name}")
    print(f"Location: {config.project.location}")
    print()

    try:
        # Get or create stack
        print("Initializing Pulumi stack...")
        stack = get_stack(
            stack_name=stack_name,
            project_name=project_name,
            config_path=config_path,
        )
        print(f"✓ Stack initialized: {stack_name}")
        print()

        # Install plugins
        print("Installing required Pulumi plugins...")
        stack.workspace.install_plugin("azure-native", "v2.0.0")
        stack.workspace.install_plugin("azuread", "v5.0.0")
        stack.workspace.install_plugin("random", "v4.0.0")
        print("✓ Plugins installed")
        print()

        # Run preview or update
        if preview:
            print("Running Pulumi preview...")
            print()

            preview_result = stack.preview(
                on_output=lambda msg: print(msg),
            )

            print()
            print("✓ Preview completed")
            print()
            print(
                f"Resources to create: {preview_result.change_summary.get('create', 0)}"
            )
            print(
                f"Resources to update: {preview_result.change_summary.get('update', 0)}"
            )
            print(
                f"Resources to delete: {preview_result.change_summary.get('delete', 0)}"
            )
            print()
            print("To deploy, run:")
            print(f"  llmaven infra deploy --config {config_path}")
        else:
            # Confirm deployment
            if not auto_approve:
                print("⚠️  This will deploy infrastructure to Azure.")
                print(f"   Estimated cost: ${estimate_cost(config)}/month")
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

            # Run update
            up_result = stack.up(
                on_output=lambda msg: print(msg),
            )

            print()
            print("=" * 70)
            print()
            print("✅ Deployment completed successfully!")
            print()

            # Show outputs
            if up_result.outputs:
                print("Deployment Outputs:")
                for key, output in up_result.outputs.items():
                    print(f"  {key}: {output.value}")
                print()

            print("Next steps:")
            print(
                f"  1. Check deployment status: llmaven status --config {config_path}"
            )
            print("  2. View resources in Azure Portal")
            print("  3. Access your services via the URLs shown above")
            print()

    except auto.errors.CommandError as e:
        raise DeploymentError(f"Pulumi command failed: {e}")
    except Exception as e:
        raise DeploymentError(f"Deployment failed: {e}")


def destroy_infrastructure(config_path: Path) -> None:
    """Destroy LLMaven infrastructure in Azure.

    Args:
        config_path: Path to configuration file

    Raises:
        DeploymentError: If destruction fails
    """
    print("🗑️  LLMaven Infrastructure Destruction")
    print()
    print("⚠️  WARNING: This will delete all resources!")
    print("⚠️  Data will be lost unless backups exist!")
    print()

    # Get stack name
    from ..infrastructure.config.loader import load_config

    config = load_config(config_path)

    # Handle Pulumi passphrase setting
    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    else:
        if (
            "PULUMI_CONFIG_PASSPHRASE" not in os.environ
            or not os.environ["PULUMI_CONFIG_PASSPHRASE"]
        ):
            raise DeploymentError(
                "Passphrase protection is enabled in config but PULUMI_CONFIG_PASSPHRASE "
                "environment variable is not set."
            )

    stack_name = f"{config.project.name}-{config.project.environment}"
    project_name = "llmaven"

    print(f"Stack: {stack_name}")
    print()

    try:
        # Get stack
        stack = get_stack(
            stack_name=stack_name,
            project_name=project_name,
            config_path=config_path,
        )

        # Run destroy
        print("Running Pulumi destroy...")
        stack.destroy(
            on_output=lambda msg: print(msg),
        )

        print()
        print("✅ Infrastructure destroyed successfully")
        print()

        # Optionally remove the stack
        try:
            confirm = input("Remove stack history? (yes/no): ").strip().lower()
            if confirm == "yes":
                stack.workspace.remove_stack(stack_name)
                print(f"✓ Stack {stack_name} removed")
        except (KeyboardInterrupt, EOFError):
            print("\nStack history preserved")

    except auto.errors.CommandError as e:
        raise DeploymentError(f"Pulumi destroy failed: {e}")
    except Exception as e:
        raise DeploymentError(f"Destruction failed: {e}")


def refresh_infrastructure(
    config_path: Path,
    auto_approve: bool = False,
) -> None:
    """Refresh Pulumi stack state from actual cloud resources.

    Compares the actual state of cloud resources with Pulumi's state
    without making any changes. Useful for detecting drift.

    Args:
        config_path: Path to configuration file
        auto_approve: Automatically approve refresh

    Raises:
        DeploymentError: If refresh fails
    """
    print("🔄 LLMaven Infrastructure Refresh")
    print()

    # Get stack name
    from ..infrastructure.config.loader import load_config

    config = load_config(config_path)

    # Handle Pulumi passphrase setting
    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    else:
        if (
            "PULUMI_CONFIG_PASSPHRASE" not in os.environ
            or not os.environ["PULUMI_CONFIG_PASSPHRASE"]
        ):
            raise DeploymentError(
                "Passphrase protection is enabled in config but PULUMI_CONFIG_PASSPHRASE "
                "environment variable is not set."
            )

    stack_name = f"{config.project.name}-{config.project.environment}"
    project_name = "llmaven"

    print(f"Stack: {stack_name}")
    print()

    try:
        # Get stack
        print("Initializing Pulumi stack...")
        stack = get_stack(
            stack_name=stack_name,
            project_name=project_name,
            config_path=config_path,
        )
        print(f"✓ Stack initialized: {stack_name}")
        print()

        # Install plugins
        print("Installing required Pulumi plugins...")
        stack.workspace.install_plugin("azure-native", "v2.0.0")
        stack.workspace.install_plugin("azuread", "v5.0.0")
        stack.workspace.install_plugin("random", "v4.0.0")
        print("✓ Plugins installed")
        print()

        # Confirm refresh
        if not auto_approve:
            print("⚠️  This will update the stack state from actual cloud resources.")
            print("   No changes will be made to resources.")
            print()
            try:
                confirm = input("Continue? (yes/no): ").strip().lower()
                if confirm != "yes":
                    print("Refresh cancelled.")
                    return
            except (KeyboardInterrupt, EOFError):
                print("\nRefresh cancelled.")
                return

        print("Running Pulumi refresh...")
        print()

        # Run refresh
        refresh_result = stack.refresh(
            on_output=lambda msg: print(msg),
        )

        print()
        print("=" * 70)
        print()
        print("✅ Refresh completed successfully!")
        print()

        # Show summary if available
        if hasattr(refresh_result, "summary") and refresh_result.summary:
            summary = refresh_result.summary
            print("Refresh Summary:")
            if hasattr(summary, "resource_changes") and summary.resource_changes:
                for action, count in summary.resource_changes.items():
                    print(f"  {action}: {count}")
            print()

        print("Stack state has been updated from actual cloud resources.")
        print()
        print("Next steps:")
        print(f"  1. Check deployment status: llmaven status --config {config_path}")
        print("  2. If drift detected, run: llmaven deploy to reconcile")
        print()

    except auto.errors.StackNotFoundError:
        print("⚠️  Stack not found")
        print()
        print("Deploy infrastructure first:")
        print(f"  llmaven deploy --config {config_path}")
    except auto.errors.CommandError as e:
        raise DeploymentError(f"Pulumi refresh failed: {e}")
    except Exception as e:
        raise DeploymentError(f"Refresh failed: {e}")


def cancel_stack_operation(config_path: Path) -> None:
    """Cancel an in-progress Pulumi stack operation.

    Args:
        config_path: Path to configuration file

    Raises:
        DeploymentError: If cancel operation fails
    """
    print("🛑 Cancelling Pulumi Stack Operation")
    print()

    # Get stack name
    from ..infrastructure.config.loader import load_config

    config = load_config(config_path)

    # Handle Pulumi passphrase setting
    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    else:
        if (
            "PULUMI_CONFIG_PASSPHRASE" not in os.environ
            or not os.environ["PULUMI_CONFIG_PASSPHRASE"]
        ):
            raise DeploymentError(
                "Passphrase protection is enabled in config but PULUMI_CONFIG_PASSPHRASE "
                "environment variable is not set."
            )

    stack_name = f"{config.project.name}-{config.project.environment}"
    project_name = "llmaven"

    print(f"Stack: {stack_name}")
    print()

    try:
        # Get stack
        print("Initializing Pulumi stack...")
        stack = get_stack(
            stack_name=stack_name,
            project_name=project_name,
            config_path=config_path,
        )
        print(f"✓ Stack initialized: {stack_name}")
        print()

        # Cancel the stack operation
        print("Attempting to cancel in-progress operation...")
        print()

        try:
            stack.cancel()
            print()
            print("=" * 70)
            print()
            print("✅ Stack operation cancelled successfully!")
            print()
            print("Note: The operation may take a moment to fully stop.")
            print()
            print("Next steps:")
            print(f"  1. Check stack status: llmaven status --config {config_path}")
            print("  2. If needed, retry the operation")
            print()
        except Exception as e:
            # Check if there's actually no operation in progress
            if (
                "no update in progress" in str(e).lower()
                or "not found" in str(e).lower()
            ):
                print("ℹ️  No operation currently in progress on this stack.")
                print()
            else:
                raise

    except auto.errors.StackNotFoundError:
        print("⚠️  Stack not found")
        print()
        print("Deploy infrastructure first:")
        print(f"  llmaven deploy --config {config_path}")
    except auto.errors.CommandError as e:
        raise DeploymentError(f"Failed to cancel stack operation: {e}")
    except Exception as e:
        raise DeploymentError(f"Cancel operation failed: {e}")


def show_deployment_status(config_path: Path) -> None:
    """Show deployment status and outputs.

    Args:
        config_path: Path to configuration file

    Raises:
        DeploymentError: If status check fails
    """
    print("📊 LLMaven Deployment Status")
    print()

    # Get stack name
    from ..infrastructure.config.loader import load_config

    config = load_config(config_path)

    # Handle Pulumi passphrase setting
    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    else:
        if (
            "PULUMI_CONFIG_PASSPHRASE" not in os.environ
            or not os.environ["PULUMI_CONFIG_PASSPHRASE"]
        ):
            raise DeploymentError(
                "Passphrase protection is enabled in config but PULUMI_CONFIG_PASSPHRASE "
                "environment variable is not set."
            )

    stack_name = f"{config.project.name}-{config.project.environment}"
    project_name = "llmaven"

    print(f"Stack: {stack_name}")
    print()

    try:
        # Get stack
        stack = get_stack(
            stack_name=stack_name,
            project_name=project_name,
            config_path=config_path,
        )

        # Get stack outputs
        outputs = stack.outputs()

        if not outputs:
            print("⚠️  No deployment found or stack has no outputs")
            print()
            print("Deploy infrastructure first:")
            print(f"  llmaven deploy --config {config_path}")
            return

        print("Deployment Outputs:")
        print()

        for key, output in sorted(outputs.items()):
            print(f"  {key}: {output.value}")

        print()
        print("✓ Deployment is active")
        print()

        # Get stack info
        try:
            info = stack.info()
            if info:
                print("Stack Information:")
                # Access available attributes from UpdateSummary
                if hasattr(info, "result") and info.result:
                    print(f"  Last update result: {info.result}")
                if hasattr(info, "start_time") and info.start_time:
                    print(f"  Start time: {info.start_time}")
                if hasattr(info, "end_time") and info.end_time:
                    print(f"  End time: {info.end_time}")
                if hasattr(info, "resource_changes") and info.resource_changes:
                    print(f"  Resource changes: {info.resource_changes}")
                print()
        except Exception as e:
            # Stack info may not be available in all cases
            print(f"  (Stack details unavailable: {e})")
            print()

    except auto.errors.StackNotFoundError:
        print("⚠️  Stack not found")
        print()
        print("Deploy infrastructure first:")
        print(f"  llmaven deploy --config {config_path}")
    except auto.errors.CommandError as e:
        raise DeploymentError(f"Failed to get stack status: {e}")
    except Exception as e:
        raise DeploymentError(f"Status check failed: {e}")


def estimate_cost(config) -> str:
    """Estimate monthly cost.

    Args:
        config: Configuration object

    Returns:
        Cost estimate string
    """
    from .validate import estimate_monthly_cost

    min_cost, max_cost = estimate_monthly_cost(config)
    return f"{min_cost:.2f}-{max_cost:.2f}"
