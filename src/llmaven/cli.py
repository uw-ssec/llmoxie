"""CLI for LLMaven API.

This module provides command-line interface functionality for the LLMaven project.
"""

from __future__ import annotations

from pathlib import Path
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

# Create subcommand for agentic RAG operations
agentic_app = typer.Typer(
    name="agentic",
    help="Agentic RAG commands",
    add_completion=False,
)
app.add_typer(agentic_app)


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
    except ValidationError:
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
        typer.confirm(
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


def _get_llmaven_secrets(env_file: Optional[str]) -> dict:
    """Small indirection so CLI stays import-safe and tests can mock secrets cleanly."""
    from llmaven.infrastructure.utils.secrets import get_llmaven_secrets

    return get_llmaven_secrets(env_file)


@infra_app.command()
def extract(
    from_date: str = typer.Option(
        ...,
        "--from",
        help="Start date (YYYY-MM-DD, interpreted as a UTC calendar date, inclusive)",
    ),
    to_date: str = typer.Option(
        ...,
        "--to",
        help="End date (YYYY-MM-DD, interpreted as a UTC calendar date, inclusive)",
    ),
    output_file: Path = typer.Option(
        None,
        "--out",
        help="Output zip file path",
    ),
    env_file: Optional[str] = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to .env file containing LLMAVEN_SECRETS_* variables",
    ),
) -> None:
    """Extract LiteLLM /spend/logs into a partitioned JSONL zip.

    Timezone:
      - Input dates (--from/--to) are interpreted as UTC calendar dates.
      - LiteLLM log timestamps (e.g., startTime) are in UTC ("Z").

    Date semantics:
      - LiteLLM /spend/logs (summarize=false) behaves as:
            start_date <= t < end_date  (end_date is exclusive)
      - Each requested UTC calendar date D is queried as [D, D+1).

    Note:
      - A future enhancement could add --tz to interpret --from/--to as calendar
        dates in an arbitrary timezone, then fetch a UTC-date superset from LiteLLM
        and filter records client-side by timestamp into the desired local ranges.
    """
    from datetime import datetime, timedelta
    import json
    import zipfile

    import httpx
    from rich.console import Console

    console = Console()
    console_err = Console(file=sys.stderr)

    # Parse & validate dates
    try:
        start_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError as e:
        console_err.print(f"[red]✗[/red] Invalid date format: {e}. Use YYYY-MM-DD.")
        raise typer.Exit(code=1)

    if start_date_obj > end_date_obj:
        console_err.print("[red]✗[/red] --from date must be <= --to date")
        raise typer.Exit(code=1)

    # Validate output file
    output_file = Path(output_file or f"llmaven_logs_{from_date}_to_{to_date}.zip")

    if output_file.exists() and output_file.is_dir():
        console_err.print("[red]✗[/red] Output path is a directory; expected file")
        raise typer.Exit(code=1)

    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        console_err.print(f"[red]✗[/red] Cannot create output directory: {e}")
        raise typer.Exit(code=1)

    if output_file.exists() and not typer.confirm(
        f"Output file exists: {output_file}. Overwrite?"
    ):
        console.print("[yellow]![/yellow] Extraction cancelled.")
        raise typer.Exit(code=0)

    # Get LiteLLM access credentials (patched in tests via _get_llmaven_secrets)
    secrets = _get_llmaven_secrets(env_file)

    litellm_master_key = secrets.get("litellm-master-key")
    if not litellm_master_key:
        console_err.print("[red]✗[/red] Missing: LLMAVEN_SECRETS_LITELLM_MASTER_KEY")
        raise typer.Exit(code=1)

    litellm_base_url = secrets.get("litellm-base-url")
    if not litellm_base_url:
        console_err.print("[red]✗[/red] Missing: LLMAVEN_SECRETS_LITELLM_BASE_URL")
        raise typer.Exit(code=1)

    endpoint = f"{litellm_base_url.rstrip('/')}/spend/logs"
    headers = {"Authorization": f"Bearer {litellm_master_key}"}

    console.print(
        f"[blue]→[/blue] Extracting LiteLLM logs "
        f"{start_date_obj.isoformat()} → {end_date_obj.isoformat()} (inclusive UTC dates)"
    )

    total_records = 0

    with zipfile.ZipFile(
        output_file, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        with httpx.Client(timeout=30.0) as http_client:
            current_date = start_date_obj
            while current_date <= end_date_obj:
                date_str = current_date.isoformat()
                next_date_str = (current_date + timedelta(days=1)).isoformat()

                params = {
                    "start_date": date_str,
                    "end_date": next_date_str,  # exclusive upper bound
                    "summarize": "false",
                }

                try:
                    resp = http_client.get(endpoint, params=params, headers=headers)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    console_err.print(
                        f"[red]✗[/red] LiteLLM /spend/logs failed for {date_str}: {e}"
                    )
                    raise typer.Exit(code=1)

                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    console_err.print(
                        f"[red]✗[/red] Invalid JSON response for {date_str}: {e}"
                    )
                    raise typer.Exit(code=1)

                if not isinstance(data, list):
                    console_err.print(
                        f"[red]✗[/red] Invalid JSON response for {date_str}: expected list"
                    )
                    raise typer.Exit(code=1)

                total_records += len(data)

                jsonl_payload = "\n".join(
                    json.dumps(item, ensure_ascii=False) for item in data
                )

                zipf.writestr(
                    f"litellm_spend_logs_{date_str}.jsonl",
                    (jsonl_payload + "\n") if jsonl_payload else "",
                )

                console.print(f"[green]✓[/green] {date_str}: {len(data)} records")
                current_date += timedelta(days=1)

    console.print(
        f"[green]✓[/green] Extraction complete! {total_records} total records written to: {output_file}"
    )


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


@agentic_app.command()
def ingest(
    directories: list[str] = typer.Argument(
        ...,
        help="One or more directories containing documents to ingest",
    ),
    collection: Optional[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Collection name (defaults to config)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        is_flag=True,
        help="Overwrite existing collection without confirmation",
    ),
    batch_size: int = typer.Option(
        100,
        "--batch-size",
        "-b",
        help="Number of documents to process per batch",
    ),
) -> None:
    """Ingest documents into Qdrant collection.

    Ingests documents from one or more directories into a Qdrant collection
    with multi-vector embeddings (Dense, Sparse, ColBERT).

    Examples:
        Ingest documents from docs directory:
            llmaven agentic ingest ./docs

        Ingest from multiple directories:
            llmaven agentic ingest ./docs ./papers

        Force overwrite existing collection:
            llmaven agentic ingest ./docs --force

        Use custom collection name:
            llmaven agentic ingest ./docs --collection my-collection
    """
    import sys
    from pathlib import Path
    from rich.console import Console

    from llmaven.agentic.ingestion import IngestionPipeline
    from llmaven.agentic.exceptions import AgenticRAGError

    console = Console()
    console_err = Console(file=sys.stderr)

    try:
        # Validate directories exist
        dir_paths_str = []
        for directory in directories:
            path = Path(directory)
            if not path.exists():
                console_err.print(f"[red]✗[/red] Directory not found: {directory}")
                raise typer.Exit(code=1)
            if not path.is_dir():
                console_err.print(f"[red]✗[/red] Not a directory: {directory}")
                raise typer.Exit(code=1)
            dir_paths_str.append(str(path))

        console.print("[blue]→[/blue] Initializing ingestion pipeline...")

        # Create ingestion pipeline
        pipeline = IngestionPipeline(
            collection_name=collection,
            batch_size=batch_size,
        )

        # Ingest documents
        console.print(
            f"[blue]→[/blue] Ingesting documents from {len(dir_paths_str)} director{'y' if len(dir_paths_str) == 1 else 'ies'}..."
        )

        # Ingest all directories at once (ingest() accepts list of directory strings)
        pipeline.ingest(directories=dir_paths_str, force=force)

        console.print("\n[green]✓[/green] Ingestion complete!")

    except AgenticRAGError as e:
        console_err.print(f"[red]✗[/red] Ingestion failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Unexpected error: {e}")
        raise typer.Exit(code=1)


@agentic_app.command()
def search(
    query: str = typer.Argument(
        ...,
        help="Search query",
    ),
    collection: Optional[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Collection name (defaults to config)",
    ),
    top_k: Optional[int] = typer.Option(
        None,
        "--top-k",
        "-k",
        help="Number of results to return (defaults to config)",
    ),
    prefetch_k: Optional[int] = typer.Option(
        None,
        "--prefetch-k",
        "-p",
        help="Number of prefetch candidates per method (defaults to config)",
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Enable/disable ColBERT reranking",
    ),
) -> None:
    """Search the knowledge base.

    Executes a hybrid search query with Dense, Sparse, and optional
    ColBERT reranking.

    Examples:
        Basic search:
            llmaven agentic search "What is machine learning?"

        Search with custom top-k:
            llmaven agentic search "architecture patterns" --top-k 10

        Search without reranking:
            llmaven agentic search "deployment" --no-rerank

        Search specific collection:
            llmaven agentic search "query" --collection my-collection
    """
    import sys
    from rich.console import Console

    from llmaven.agentic.search import HybridSearcher
    from llmaven.agentic.exceptions import AgenticRAGError

    console = Console()
    console_err = Console(file=sys.stderr)

    try:
        console.print(f"[blue]→[/blue] Searching for: [bold]{query}[/bold]")

        # Create searcher
        searcher = HybridSearcher(
            collection_name=collection,
            enable_rerank=rerank,
            prefetch_top_k=prefetch_k,
            final_top_k=top_k,
        )

        # Execute search
        results = searcher.search(query=query, limit=top_k)

        if not results:
            console.print("[yellow]![/yellow] No results found")
            return

        # Display results
        console.print(
            f"\n[green]✓[/green] Found {len(results)} result{'s' if len(results) != 1 else ''}:\n"
        )

        for i, result in enumerate(results, 1):
            console.print(
                f"[bold cyan]Result {i}[/bold cyan] (score: {result.score:.4f})"
            )
            console.print(f"[dim]Source:[/dim] {result.file_path}")
            if result.heading_hierarchy:
                console.print(f"[dim]Section:[/dim] {result.heading_hierarchy}")
            console.print(
                f"\n{result.text[:300]}{'...' if len(result.text) > 300 else ''}\n"
            )

    except AgenticRAGError as e:
        console_err.print(f"[red]✗[/red] Search failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Unexpected error: {e}")
        raise typer.Exit(code=1)


@agentic_app.command()
def chat(
    collection: Optional[str] = typer.Option(
        None,
        "--collection",
        "-c",
        help="Collection name (defaults to config)",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="LLM provider override (openai, ollama, litellm, azure, huggingface)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model override",
    ),
    litellm_base: Optional[str] = typer.Option(
        None,
        "--litellm-base",
        help="LiteLLM proxy base URL (e.g., http://localhost:4000)",
    ),
    litellm_api_key: Optional[str] = typer.Option(
        None,
        "--litellm-api-key",
        help="LiteLLM API key",
    ),
    litellm_model_prefix: Optional[str] = typer.Option(
        None,
        "--litellm-prefix",
        help="LiteLLM model prefix (e.g., openai/, anthropic/)",
    ),
    azure_endpoint: Optional[str] = typer.Option(
        None,
        "--azure-endpoint",
        help="Azure OpenAI endpoint URL (e.g., https://myresource.openai.azure.com)",
    ),
    azure_api_key: Optional[str] = typer.Option(
        None,
        "--azure-api-key",
        help="Azure API key",
    ),
    azure_deployment: Optional[str] = typer.Option(
        None,
        "--azure-deployment",
        help="Azure deployment name",
    ),
) -> None:
    """Launch interactive RAG chat.

    Starts an interactive REPL for conversing with the RAG agent.
    The agent has access to the knowledge base and can provide
    answers with citations.

    Examples:
        Start chat:
            llmaven agentic chat

        Chat with specific collection:
            llmaven agentic chat --collection my-docs

        Use different LLM:
            llmaven agentic chat --provider ollama --model llama2

        Use LiteLLM proxy:
            llmaven agentic chat --provider litellm --litellm-base http://localhost:4000 --model gpt-4o-mini

        Use Azure OpenAI:
            llmaven agentic chat --provider azure --azure-endpoint https://myresource.openai.azure.com --azure-deployment gpt-4o
    """
    import sys
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    from llmaven.agentic.agent import RAGAgent
    from llmaven.agentic.exceptions import AgenticRAGError
    from llmaven.agentic.settings import config

    console = Console()
    console_err = Console(file=sys.stderr)

    try:
        console.print("[blue]→[/blue] Initializing RAG agent...")

        # Override config with CLI options
        if litellm_base:
            config.litellm_api_base = litellm_base
        if litellm_api_key:
            config.litellm_api_key = litellm_api_key
        if litellm_model_prefix:
            config.litellm_model_prefix = litellm_model_prefix
        if azure_endpoint:
            config.azure_endpoint = azure_endpoint
        if azure_api_key:
            config.azure_api_key = azure_api_key
        if azure_deployment:
            config.azure_deployment_name = azure_deployment

        # Create agent
        agent = RAGAgent(
            collection_name=collection,
            llm_provider=provider,
            llm_model=model,
        )

        console.print(
            Panel(
                "[bold green]RAG Chat Session[/bold green]\n\n"
                "Ask questions about your knowledge base.\n"
                "Type 'exit' or 'quit' to end the session.",
                border_style="green",
            )
        )

        message_history = []

        while True:
            # Get user input
            try:
                query = console.input("\n[bold cyan]You:[/bold cyan] ")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]![/yellow] Session ended")
                break

            if query.strip().lower() in ["exit", "quit"]:
                console.print("[yellow]![/yellow] Session ended")
                break

            if not query.strip():
                continue

            # Get agent response
            console.print("[blue]→[/blue] Thinking...")

            try:
                response = agent.run_sync(query=query, message_history=message_history)

                # Display answer
                console.print("\n[bold green]Assistant:[/bold green]")
                console.print(Markdown(response.answer))

                # Display citations
                if response.citations:
                    console.print(
                        f"\n[dim]Citations ({len(response.citations)}):[/dim]"
                    )
                    for i, citation in enumerate(response.citations, 1):
                        console.print(
                            f"  [{i}] {citation.source_file} "
                            f"(score: {citation.relevance_score:.2f})"
                        )
                        console.print(f"      {citation.quote[:100]}...")

                console.print(
                    f"\n[dim]Confidence: {response.confidence:.2f} | Sources: {response.sources_used}[/dim]"
                )

                # Update message history
                message_history.append({"role": "user", "content": query})
                message_history.append(
                    {"role": "assistant", "content": response.answer}
                )

            except Exception as e:
                console_err.print(f"[red]✗[/red] Error: {e}")

    except AgenticRAGError as e:
        console_err.print(f"[red]✗[/red] Failed to start chat: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Unexpected error: {e}")
        raise typer.Exit(code=1)


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
