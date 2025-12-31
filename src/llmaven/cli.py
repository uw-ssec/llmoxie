"""CLI for LLMaven API.

This module provides command-line interface functionality for the LLMaven project.
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import Optional

import typer

app = typer.Typer(
    name="llmaven",
    help="LLMaven - CLI for Scientific Discovery",
    add_completion=False,
)

# Create subcommand for server operations
server_app = typer.Typer(
    name="server",
    help="Server management commands",
    add_completion=False,
)
app.add_typer(server_app)

# Create subcommand for infrastructure management
infra_app = typer.Typer(
    name="infra",
    help="Infrastructure deployment and management commands",
    add_completion=False,
)
app.add_typer(infra_app)


class Environment(str, Enum):
    """Environment modes for the server."""

    development = "development"
    production = "production"


@server_app.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        "-h",
        help="Host to bind the server to",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to bind the server to",
    ),
    env: Environment = typer.Option(
        Environment.development,
        "--env",
        "-e",
        help="Environment mode (development or production)",
        case_sensitive=False,
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        "-w",
        help="Number of worker processes (production mode only, defaults to CPU count + 1)",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        "-r",
        is_flag=True,
        help="Enable auto-reload on code changes (development mode only)",
    ),
    access_log: bool = typer.Option(
        True,
        is_flag=True,
        help="Enable access logging",
    ),
) -> None:
    """Start the LLMaven API server.

    Uses uvicorn for development mode and gunicorn with uvicorn workers for production mode.

    Examples:
        Development mode with auto-reload:
            llmaven serve --env development --reload

        Production mode with 4 workers:
            llmaven serve --env production --workers 4

        Custom host and port:
            llmaven serve --host 127.0.0.1 --port 5000
    """
    if env == Environment.development:
        # Use uvicorn for development
        try:
            import uvicorn
        except ImportError:
            typer.echo(
                "Error: uvicorn is not installed. "
                "Please install it with: pip install uvicorn",
                err=True,
            )
            raise typer.Exit(code=1)

        typer.echo(f"Starting LLMaven API in development mode on {host}:{port}")
        if reload:
            typer.echo("Auto-reload enabled - watching for file changes")

        uvicorn.run(
            "llmaven.main:app",
            host=host,
            port=port,
            reload=reload,
            access_log=access_log,
            log_level="info",
        )

    else:
        # Use gunicorn for production
        try:
            import gunicorn.app.base
        except ImportError:
            typer.echo(
                "Error: gunicorn is not installed. "
                "Please install it with: pip install gunicorn",
                err=True,
            )
            raise typer.Exit(code=1)

        if reload:
            typer.echo(
                "Warning: --reload flag is ignored in production mode",
                err=True,
            )

        # Calculate workers if not specified
        if workers is None:
            import multiprocessing
            workers = (multiprocessing.cpu_count() * 2) + 1

        typer.echo(
            f"Starting LLMaven API in production mode on {host}:{port} "
            f"with {workers} workers"
        )

        class StandaloneApplication(gunicorn.app.base.BaseApplication):
            """Gunicorn application wrapper."""

            def __init__(self, app_uri: str, options: dict | None = None):
                self.options = options or {}
                self.app_uri = app_uri
                super().__init__()

            def load_config(self):
                """Load gunicorn configuration."""
                for key, value in self.options.items():
                    if key in self.cfg.settings and value is not None:
                        self.cfg.set(key.lower(), value)

            def load(self):
                """Load the application."""
                return self.app_uri

        options = {
            "bind": f"{host}:{port}",
            "workers": workers,
            "worker_class": "uvicorn.workers.UvicornWorker",
            "accesslog": "-" if access_log else None,
            "errorlog": "-",
            "loglevel": "info",
        }

        StandaloneApplication("llmaven.main:app", options).run()


@server_app.command()
def ui(
    host: str = typer.Option(
        "localhost",
        "--host",
        "-h",
        help="Host to bind the Streamlit app to",
    ),
    port: int = typer.Option(
        8501,
        "--port",
        "-p",
        help="Port to bind the Streamlit app to",
    ),
    browser: bool = typer.Option(
        True,
        is_flag=True,
        help="Automatically open the app in a browser",
    ),
) -> None:
    """Launch the LLMaven Streamlit UI.

    This starts the Streamlit frontend application for interacting with LLMaven.

    Examples:
        Launch UI on default port (8501):
            llmaven ui

        Launch on custom host and port:
            llmaven ui --host 0.0.0.0 --port 8080

        Launch without opening browser:
            llmaven ui --no-browser
    """
    import os
    import subprocess
    from pathlib import Path

    # Get the path to the frontend app
    frontend_app = Path(__file__).parent / "frontend" / "app.py"

    if not frontend_app.exists():
        typer.echo(
            f"Error: Streamlit app not found at {frontend_app}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Build streamlit command
    cmd = [
        "streamlit",
        "run",
        str(frontend_app),
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]

    if not browser:
        cmd.extend(["--server.headless", "true"])

    typer.echo(f"Starting LLMaven UI on {host}:{port}")
    if browser:
        typer.echo("Opening browser...")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        typer.echo(f"Error: Failed to start Streamlit app: {e}", err=True)
        raise typer.Exit(code=1)
    except FileNotFoundError:
        typer.echo(
            "Error: streamlit is not installed. "
            "Please install it with: pip install streamlit",
            err=True,
        )
        raise typer.Exit(code=1)


@infra_app.command()
def init(
    environment: str = typer.Option(
        "dev",
        "--environment",
        "-e",
        help="Environment to configure (dev, staging, prod)",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path for configuration file",
    ),
    interactive: bool = typer.Option(
        True,
        is_flag=True,
        help="Interactive mode with prompts",
    ),
) -> None:
    """Initialize LLMaven deployment configuration.

    Generates llmaven-config.yaml with sensible defaults for the specified environment.

    Examples:
        Interactive setup for dev:
            llmaven infra init

        Generate prod config non-interactively:
            llmaven infra init -e prod -o llmaven-config.prod.yaml --no-interactive
    """
    from pathlib import Path

    from llmaven.deployment.init import initialize_config

    output_path = Path(output) if output else Path("llmaven-config.yaml")

    initialize_config(
        environment=environment,
        output_path=output_path,
        interactive=interactive,
    )


@infra_app.command()
def validate(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        is_flag=True,
        help="Fail on warnings (useful for CI/CD)",
    ),
    skip_secrets: bool = typer.Option(
        False,
        "--skip-secrets",
        is_flag=True,
        help="Skip secrets validation (use with caution)",
    ),
    env_file: Optional[str] = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to .env file containing LLMAVEN_SECRETS_* variables",
    ),
) -> None:
    """Validate LLMaven deployment configuration.

    Validates:
    - Configuration file syntax and schema
    - Azure prerequisites and permissions
    - Resource quotas and limits
    - Secrets presence via LLMAVEN_SECRETS_* environment variables
    - Cost estimation

    Examples:
        Validate default config:
            llmaven infra validate

        Strict validation for CI/CD:
            llmaven infra validate --config llmaven-config.prod.yaml --strict

        Skip secrets check (infrastructure-only validation):
            llmaven infra validate --skip-secrets

        Load secrets from .env file:
            llmaven infra validate --env-file .env.secrets
    """
    from pathlib import Path

    from llmaven.deployment.validate import ValidationError, validate_config

    config_path = Path(config) if config else Path("llmaven-config.yaml")
    env_file_path = Path(env_file) if env_file else None

    try:
        validate_config(
            config_path=config_path,
            strict=strict,
            skip_secrets=skip_secrets,
            env_file_path=env_file_path,
        )
    except ValidationError as e:
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Validation failed: {e}", err=True)
        sys.exit(1)


@infra_app.command()
def deploy(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        "-p",
        is_flag=True,
        help="Preview changes without deploying",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--yes",
        "-y",
        is_flag=True,
        help="Automatically approve deployment",
    ),
    env_file: Optional[str] = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to .env file containing LLMAVEN_SECRETS_* variables",
    ),
) -> None:
    """Deploy LLMaven infrastructure to Azure.

    Deploys all resources defined in the configuration file.
    Automatically validates configuration before deployment.

    Examples:
        Preview deployment:
            llmaven infra deploy --preview

        Deploy with auto-approval:
            llmaven infra deploy --yes

        Deploy specific config:
            llmaven infra deploy --config llmaven-config.staging.yaml

        Deploy with secrets from .env file:
            llmaven infra deploy --env-file .env.secrets
    """
    from pathlib import Path

    from llmaven.deployment.deploy import DeploymentError, deploy_infrastructure

    config_path = Path(config) if config else Path("llmaven-config.yaml")
    env_file_path = Path(env_file) if env_file else None

    try:
        deploy_infrastructure(
            config_path=config_path,
            preview=preview,
            auto_approve=auto_approve,
            env_file_path=env_file_path,
        )
    except DeploymentError as e:
        typer.echo(f"✗ Deployment failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Deployment failed: {e}", err=True)
        sys.exit(1)


@infra_app.command()
def destroy(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--yes",
        "-y",
        is_flag=True,
        help="Automatically approve destruction",
    ),
) -> None:
    """Destroy LLMaven infrastructure in Azure.

    WARNING: This will delete all resources defined in the configuration.
    Data will be lost unless backups exist.

    Examples:
        Destroy with confirmation:
            llmaven infra destroy

        Destroy with auto-approval:
            llmaven infra destroy --yes
    """
    from pathlib import Path

    from llmaven.deployment.deploy import DeploymentError, destroy_infrastructure

    config_path = Path(config) if config else Path("llmaven-config.yaml")

    if not auto_approve:
        confirm = typer.confirm(
            "⚠️  This will destroy all infrastructure. Are you sure?",
            abort=True,
        )

    try:
        destroy_infrastructure(config_path=config_path)
    except DeploymentError as e:
        typer.echo(f"✗ Destruction failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Destruction failed: {e}", err=True)
        sys.exit(1)


@infra_app.command()
def status(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Show deployment status and outputs.

    Displays:
    - Stack information
    - Resource URLs
    - Connection strings
    - Deployment status

    Examples:
        Show status:
            llmaven infra status
    """
    from pathlib import Path

    from llmaven.deployment.deploy import DeploymentError, show_deployment_status

    config_path = Path(config) if config else Path("llmaven-config.yaml")

    try:
        show_deployment_status(config_path=config_path)
    except DeploymentError as e:
        typer.echo(f"✗ Status check failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Status check failed: {e}", err=True)
        sys.exit(1)


@infra_app.command()
def refresh(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--yes",
        "-y",
        is_flag=True,
        help="Automatically approve refresh",
    ),
) -> None:
    """Refresh Pulumi stack state from actual cloud resources.

    Compares the actual state of cloud resources with Pulumi's state
    without making any changes. Useful for detecting drift and updating
    the state file.

    Examples:
        Refresh stack state:
            llmaven infra refresh

        Refresh with auto-approval:
            llmaven infra refresh --yes
    """
    from pathlib import Path

    from llmaven.deployment.deploy import DeploymentError, refresh_infrastructure

    config_path = Path(config) if config else Path("llmaven-config.yaml")

    try:
        refresh_infrastructure(
            config_path=config_path,
            auto_approve=auto_approve,
        )
    except DeploymentError as e:
        typer.echo(f"✗ Refresh failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Refresh failed: {e}", err=True)
        sys.exit(1)


@infra_app.command()
def cancel(
    config: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Cancel an in-progress Pulumi stack operation.

    Cancels any currently running update, refresh, or destroy operation
    on the stack. This is useful when an operation is stuck or taking
    too long.

    Examples:
        Cancel in-progress operation:
            llmaven infra cancel

        Cancel operation for specific config:
            llmaven infra cancel --config llmaven-config.staging.yaml
    """
    from pathlib import Path

    from llmaven.deployment.deploy import DeploymentError, cancel_stack_operation

    config_path = Path(config) if config else Path("llmaven-config.yaml")

    try:
        cancel_stack_operation(config_path=config_path)
    except DeploymentError as e:
        typer.echo(f"✗ Cancel failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"✗ Cancel failed: {e}", err=True)
        sys.exit(1)


@app.command()
def version() -> None:
    """Display the LLMaven version."""
    from llmaven import __version__

    typer.echo(f"LLMaven version {__version__}")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
