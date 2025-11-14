"""Initialize LLMaven deployment configuration.

This module provides the implementation for the 'llmaven init' command.
"""

import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..infrastructure.config.defaults import get_config_template_yaml


def get_azure_subscription_id() -> Optional[str]:
    """Get current Azure subscription ID from Azure CLI.

    Returns:
        Subscription ID if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["az", "account", "show", "--query", "id", "-o", "tsv"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_azure_tenant_id() -> Optional[str]:
    """Get current Azure tenant ID from Azure CLI.

    Returns:
        Tenant ID if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["az", "account", "show", "--query", "tenantId", "-o", "tsv"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def prompt_for_input(prompt: str, default: Optional[str] = None) -> str:
    """Prompt user for input with optional default value.

    Args:
        prompt: Prompt message
        default: Default value if user presses Enter

    Returns:
        User input or default value
    """
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "

    try:
        user_input = input(prompt).strip()
        return user_input if user_input else (default or "")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(1)


def initialize_config(
    environment: str = "dev",
    output_path: Optional[Path] = None,
    interactive: bool = True,
) -> None:
    """Initialize LLMaven deployment configuration.

    Generates llmaven-config.yaml with sensible defaults for the specified environment.

    Args:
        environment: Environment to configure (dev, staging, prod)
        output_path: Output path for configuration file
        interactive: Enable interactive mode with prompts
    """
    if output_path is None:
        output_path = Path("llmaven-config.yaml")
    else:
        output_path = Path(output_path)

    # Check if file already exists
    if output_path.exists():
        print(f"⚠️  Configuration file already exists: {output_path}")
        if interactive:
            overwrite = (
                prompt_for_input("Do you want to overwrite it? (yes/no)", "no").lower()
                == "yes"
            )
            if not overwrite:
                print("Operation cancelled.")
                return
        else:
            print("Use --force to overwrite or specify a different output path.")
            return

    print(f"🚀 Initializing LLMaven configuration for environment: {environment}")
    print()

    # Get Azure subscription info
    subscription_id = get_azure_subscription_id()
    tenant_id = get_azure_tenant_id()

    if interactive:
        print("📋 Configuration Setup")
        print()

        # Prompt for subscription ID
        if subscription_id:
            print(f"✓ Detected Azure subscription: {subscription_id}")
            use_detected = (
                prompt_for_input("Use this subscription? (yes/no)", "yes").lower()
                == "yes"
            )
            if not use_detected:
                subscription_id = prompt_for_input("Enter Azure subscription ID")
        else:
            print("⚠️  No Azure subscription detected.")
            print("   Make sure you're logged in: az login")
            subscription_id = prompt_for_input(
                "Enter Azure subscription ID (leave empty to set later)", ""
            )

        # Prompt for location
        location = prompt_for_input("Azure region", "eastus")

        print()
        print("ℹ️  Additional configuration can be customized in the generated file.")
        print()

    else:
        # Non-interactive mode
        location = "eastus"
        if not subscription_id:
            print("⚠️  Warning: Azure subscription ID not detected.")
            print("   Please update 'azure.subscription_id' in the generated config.")

    # Generate configuration template
    config_yaml = get_config_template_yaml(environment)

    # Replace placeholders if we have values
    if subscription_id:
        config_yaml = config_yaml.replace(
            'subscription_id: ""', f'subscription_id: "{subscription_id}"'
        )
    if tenant_id:
        config_yaml = config_yaml.replace(
            "tenant_id: null", f'tenant_id: "{tenant_id}"'
        )
    if location and location != "eastus":
        config_yaml = config_yaml.replace("location: eastus", f"location: {location}")

    # Write configuration file
    try:
        with open(output_path, "w") as f:
            f.write(config_yaml)
        print(f"✅ Configuration file created: {output_path}")
    except Exception as e:
        print(f"❌ Failed to write configuration file: {e}")
        sys.exit(1)

    # Print next steps
    print()
    print("📖 Next Steps:")
    print()
    print(f"1. Review and edit the configuration file:")
    print(f"   vim {output_path}")
    print()
    print("2. Set required secrets as environment variables:")
    print("   export LLMAVEN_SECRETS_LITELLM_MASTER_KEY=\"$(openssl rand -base64 32)\"")
    print('   export LLMAVEN_SECRETS_AZURE_OPENAI_API_KEY="your-azure-openai-key"')
    print('   export LLMAVEN_SECRETS_ANTHROPIC_API_KEY="your-anthropic-key"')
    print()
    print("3. Validate the configuration:")
    print(f"   llmaven validate --config {output_path}")
    print()
    print("4. Deploy infrastructure:")
    print(f"   llmaven deploy --config {output_path} --preview")
    print()
    print("📚 Documentation:")
    print("   https://github.com/uw-ssec/llmaven/blob/main/DEPLOYMENT_PLAN.md")
    print()
