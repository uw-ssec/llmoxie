"""CLI for LLMaven API.

This module provides command-line interface functionality for the LLMaven project.
"""

from __future__ import annotations

from pathlib import Path
import sys
from enum import Enum
from datetime import datetime, time, timezone, timedelta
from typing import TYPE_CHECKING, NoReturn, Optional

import typer
from rich.console import Console

if TYPE_CHECKING:
    from datetime import date
    from mlflow import MlflowClient
    from llmaven.deployment.loadtest import LoadTestResults

console = Console()
console_err = Console(stderr=True)

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


# Shared --env-file option: enforces consistent Typer Path validation
# across `infra validate`, `infra deploy`, and `infra extract`.
ENV_FILE_OPTION = typer.Option(
    None,
    "--env-file",
    "-e",
    help="Path to .env file containing LLMAVEN_SECRETS_* variables",
    exists=True,
    dir_okay=False,
    file_okay=True,
    readable=True,
    resolve_path=True,
    path_type=Path,
)


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
    env_file: Optional[Path] = ENV_FILE_OPTION,
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

    try:
        validate_config(
            config_path=config_path,
            strict=strict,
            skip_secrets=skip_secrets,
            env_file_path=env_file,
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
    env_file: Optional[Path] = ENV_FILE_OPTION,
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

    try:
        deploy_infrastructure(
            config_path=config_path,
            preview=preview,
            auto_approve=auto_approve,
            env_file_path=env_file,
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


class ExtractSource(str, Enum):
    litellm = "litellm"
    mlflow = "mlflow"


def _get_llmaven_secrets(env_file: Optional[Path]) -> dict:
    """Wrapper to keep secrets import local and easy to mock in tests."""
    from llmaven.infrastructure.utils.secrets import get_llmaven_secrets

    # TODO: Deduplicate the get_llmaven_secrets definition method across codebase (https://github.com/uw-ssec/llmaven/issues/89.
    return get_llmaven_secrets(env_file)


def _get_litellm_credentials(env_file: Optional[Path]) -> tuple[str, str]:
    secrets = _get_llmaven_secrets(env_file)

    # Secrets are normalized to kebab-case when loaded from LLMAVEN_SECRETS_*.
    litellm_master_key = secrets.get("litellm-master-key")
    if not litellm_master_key:
        _fail_extract("Missing: LLMAVEN_SECRETS_LITELLM_MASTER_KEY")

    litellm_base_url = secrets.get("litellm-base-url")
    if not litellm_base_url:
        _fail_extract("Missing: LLMAVEN_SECRETS_LITELLM_BASE_URL")

    return litellm_base_url, litellm_master_key


def _parse_utc_date(date_value: str) -> "date":
    """Parse a YYYY-MM-DD date, exiting with a helpful message on failure."""

    try:
        return datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError as exc:
        _fail_extract(f"Invalid date format for {date_value}: {exc}. Use YYYY-MM-DD.")


def _fail_extract(message: str, code: int = 1) -> NoReturn:
    console_err.print(f"[red]✗[/red] {message}")
    raise typer.Exit(code=code)


def _serialize_to_jsonl(records: list[object]) -> str:
    import io
    import json

    import jsonlines

    buffer = io.StringIO()
    with jsonlines.Writer(
        buffer,
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False),
    ) as writer:
        writer.write_all(records)

    return buffer.getvalue()


def _prepare_extract_output_file(
    output_file: Optional[Path],
    source: "ExtractSource",
    from_date: str,
    to_date: str,
) -> Path:
    use_default_path = output_file is None
    filename_prefix = "llmaven_"
    filename_suffix = f"_{from_date}_to_{to_date}.zip"

    if source.value == ExtractSource.litellm:
        path = output_file or Path(
            f"{filename_prefix}litellm_spend_logs{filename_suffix}"
        )
    elif source.value == ExtractSource.mlflow:
        path = output_file or Path(
            f"{filename_prefix}mlflow_experiment_traces{filename_suffix}"
        )
    else:
        _fail_extract(f"Source is not supported: {source}")

    # Guard only for the default path (Typer can't validate a value that wasn't provided)
    if use_default_path and path.exists() and path.is_dir():
        _fail_extract(f"Default output path is a directory: {path}")

    # If user provided --out, ensure parent exists (argument parsing doesn’t create directories)
    if not use_default_path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            _fail_extract(f"Cannot create output directory: {e}")

    if path.exists() and not typer.confirm(f"Output path exists: {path}. Overwrite?"):
        console.print("[yellow]![/yellow] Extraction cancelled.")
        raise typer.Exit(code=0)

    return path


def _extract_litellm_logs(
    start_date_obj: "date",
    end_date_obj: "date",
    output_file: Path,
    env_file: Optional[Path],
) -> None:
    import json
    import zipfile

    import httpx

    litellm_base_url, litellm_master_key = _get_litellm_credentials(env_file)

    endpoint = f"{litellm_base_url.rstrip('/')}/spend/logs"
    headers = {"Authorization": f"Bearer {litellm_master_key}"}

    console.print(
        f"[blue]→[/blue] Extracting LiteLLM logs "
        f"{start_date_obj.isoformat()} → {end_date_obj.isoformat()} (inclusive UTC dates)"
    )

    total_records = 0

    # TODO: Make zipfile output optional (https://github.com/uw-ssec/llmaven/issues/87).
    with zipfile.ZipFile(
        output_file, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        # TODO: Add retry logic (https://github.com/uw-ssec/llmaven/issues/88).
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
                except httpx.HTTPError as exc:
                    _fail_extract(f"LiteLLM /spend/logs failed for {date_str}: {exc}")

                try:
                    data = resp.json()
                except json.JSONDecodeError as exc:
                    _fail_extract(f"Invalid JSON response for {date_str}: {exc}")

                if not isinstance(data, list):
                    _fail_extract(
                        f"Invalid JSON response for {date_str}: expected list"
                    )

                total_records += len(data)

                try:
                    jsonl_payload = _serialize_to_jsonl(data)
                except Exception as exc:
                    _fail_extract(f"Failed to serialize records for {date_str}: {exc}")

                zipf.writestr(
                    f"litellm_spend_logs_{date_str}.jsonl",
                    jsonl_payload,
                )

                console.print(f"[green]✓[/green] {date_str}: {len(data)} records")
                current_date += timedelta(days=1)

    console.print(
        "[green]✓[/green] Extraction complete! "
        f"{total_records} total records written to: {output_file}"
    )


def _utc_date_to_epoch_ms(d: "date") -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_mlflow_experiment_ids_for_date_range(
    mlflow_client: MlflowClient, start_date_obj: date, end_date_obj: date
) -> list[str]:
    from mlflow.entities import ViewType

    experiment_ids: list[str] = []
    page_token: Optional[str] = None

    # Use only creation_time as a coarse pre-filter for experiments.
    # If an experiment was created after the requested window ends, it cannot
    # contain traces from that window, so excluding it is safe.
    #
    # We intentionally do NOT filter on search_experiment's last_update_time here:
    # in practice, experiment-level update metadata is not a reliable proxy for
    # whether the experiment contains traces in the requested time range. Using it
    # can false negatives by excluding experiments that still had matching traces.
    #
    # The authoritative time filter remains the trace-level predicate in
    # search_traces(...), which filters directly on trace.timestamp_ms.
    end_ms = _utc_date_to_epoch_ms(end_date_obj)
    date_filter_string = f"creation_time < {end_ms}"

    while True:
        experiments = mlflow_client.search_experiments(
            view_type=ViewType.ACTIVE_ONLY,
            filter_string=date_filter_string,
            max_results=1000,
            page_token=page_token,
        )

        experiment_ids.extend(exp.experiment_id for exp in experiments)

        page_token = experiments.token
        if not page_token:
            break

    return experiment_ids


def _fetch_mlflow_experiment_traces_in_date_range(
    client: MlflowClient,
    experiment_ids: list[str],
    start_ms: int,
    end_ms: int,
) -> list[object]:
    if not experiment_ids:
        return []

    date_filter_string = (
        f"trace.timestamp_ms >= {start_ms} AND trace.timestamp_ms < {end_ms}"
    )

    all_traces = []
    page_token: Optional[str] = None
    page_num = 0

    with console.status("[blue]Fetching MLflow traces...[/blue]") as status:
        while True:
            page_num += 1
            status.update(
                f"[blue]Fetching MLflow traces...[/blue] "
                f"(page {page_num}, {len(all_traces)} collected)"
            )

            traces = client.search_traces(
                locations=experiment_ids,
                filter_string=date_filter_string,
                max_results=500,
                order_by=["timestamp_ms ASC"],
                page_token=page_token,
                include_spans=True,
            )

            all_traces.extend(traces)

            page_token = traces.token
            if not page_token:
                break

    return all_traces


def _get_mlflow_tracking_uri(env_file: Optional[Path]) -> str:
    secrets = _get_llmaven_secrets(env_file)

    # Secrets are normalized to kebab-case when loaded from LLMAVEN_SECRETS_*.
    mlflow_tracking_uri = secrets.get("mlflow-tracking-uri")
    if not mlflow_tracking_uri:
        _fail_extract("Missing: LLMAVEN_SECRETS_MLFLOW_TRACKING_URI")

    return mlflow_tracking_uri


def _extract_mlflow_logs(
    start_date_obj: "date",
    end_date_obj: "date",
    output_file: Path,
    env_file: Optional[Path],
) -> None:
    import zipfile
    from collections import defaultdict

    import mlflow
    from mlflow import MlflowClient

    # Initialize the MLflow client from the configured tracking backend.
    mlflow_tracking_uri = _get_mlflow_tracking_uri(env_file)
    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow_client = MlflowClient(tracking_uri=mlflow_tracking_uri)

    console.print(
        f"[blue]→[/blue] Extracting MLflow traces "
        f"{start_date_obj.isoformat()} → {end_date_obj.isoformat()} "
        f"(inclusive UTC dates; relevant experiments)"
    )

    # Fetch the candidate experiment ids once for the overall requested window.
    # This is only a coarse pre-filter; the authoritative date filtering happens
    # later at the trace level via trace.timestamp_ms.
    try:
        experiment_ids = _fetch_mlflow_experiment_ids_for_date_range(
            mlflow_client,
            start_date_obj,
            end_date_obj,
        )
    except Exception as exc:
        _fail_extract(f"MLflow experiment search failed: {exc}")

    console.print(f"[blue]→[/blue] Found {len(experiment_ids)} MLflow experiment(s)")

    total_records = 0
    total_files_written = 0

    with zipfile.ZipFile(
        output_file, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        current_date = start_date_obj

        # Partition the export by UTC day using half-open windows [D, D+1).
        while current_date <= end_date_obj:
            next_date = current_date + timedelta(days=1)
            date_str = current_date.isoformat()

            # Fetch all traces for this UTC day across the candidate experiments.
            try:
                traces = _fetch_mlflow_experiment_traces_in_date_range(
                    client=mlflow_client,
                    experiment_ids=experiment_ids,
                    start_ms=_utc_date_to_epoch_ms(current_date),
                    end_ms=_utc_date_to_epoch_ms(next_date),
                )
            except Exception as exc:
                _fail_extract(f"MLflow trace search failed for {date_str}: {exc}")

            total_records += len(traces)

            # Group the day's traces by experiment id so the zip contains one file
            # per (experiment_id, UTC day) instead of mixing multiple experiments
            # into a single daily file.
            traces_by_experiment_id: dict[str, list[dict]] = defaultdict(list)

            try:
                for trace in traces:
                    # Normalize the MLflow trace object to a plain dict once, then
                    # reuse it both for grouping and JSON serialization.
                    trace_dict = trace.to_dict()
                    experiment_id = str(
                        trace_dict["info"]["trace_location"]["mlflow_experiment"][
                            "experiment_id"
                        ]
                    )
                    traces_by_experiment_id[experiment_id].append(trace_dict)
            except Exception as exc:
                _fail_extract(
                    f"Failed to group MLflow traces by experiment for {date_str}: {exc}"
                )

            # Write one JSONL file per experiment for this UTC day.
            for experiment_id, experiment_traces in traces_by_experiment_id.items():
                try:
                    jsonl_payload = _serialize_to_jsonl(experiment_traces)
                except Exception as exc:
                    _fail_extract(
                        "Failed to JSON-serialize MLflow traces for "
                        f"{date_str}, experiment {experiment_id}: {exc}"
                    )

                zipf.writestr(
                    f"mlflow_traces_{date_str}_experiment_{experiment_id}.jsonl",
                    jsonl_payload,
                )
                total_files_written += 1

            console.print(
                f"[green]✓[/green] {date_str}: {len(traces)} records "
                f"across {len(traces_by_experiment_id)} experiment(s)"
            )
            current_date = next_date

    console.print(
        "[green]✓[/green] Extraction complete! "
        f"{total_records} total records across {total_files_written} file(s) "
        f"written to: {output_file}"
    )


@infra_app.command()
def extract(
    source: ExtractSource = typer.Option(
        ExtractSource.litellm,
        "--source",
        case_sensitive=False,
        help="Extraction source: litellm or mlflow",
    ),
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
    output_file: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Output zip file path",
        dir_okay=False,
        file_okay=True,
        writable=True,
        resolve_path=True,
        path_type=Path,
    ),
    env_file: Optional[Path] = ENV_FILE_OPTION,
) -> None:
    """Extract source logs/traces into a day-partitioned JSONL zip.

    Source semantics:
      - litellm: extracts /spend/logs records
      - mlflow: extracts traces across all experiments

    Timezone:
      - Input dates (--from_date/--to_date) are interpreted as UTC calendar dates.

    Date semantics:
      - Records are partitioned by UTC day using half-open intervals [D, D+1).

    Note:
      - A future enhancement could add --tz to interpret --from/--to as calendar
        dates in an arbitrary timezone, then fetch a UTC-date superset from LiteLLM
        and filter records client-side by timestamp into the desired local ranges.
    """
    if source != ExtractSource.litellm and source != ExtractSource.mlflow:
        _fail_extract(f"Source is not supported: {source}")

    # Parse & validate dates
    start_date_obj = _parse_utc_date(from_date)
    end_date_obj = _parse_utc_date(to_date)

    if start_date_obj > end_date_obj:
        _fail_extract("--from must be <= --to")

    # Validate output file
    output_file = _prepare_extract_output_file(
        output_file,
        source,
        from_date,
        to_date,
    )

    if source == ExtractSource.litellm:
        _extract_litellm_logs(
            start_date_obj,
            end_date_obj,
            output_file,
            env_file,
        )
    elif source == ExtractSource.mlflow:
        _extract_mlflow_logs(
            start_date_obj,
            end_date_obj,
            output_file,
            env_file,
        )
    # else: source is validated in the initial check.


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


def _print_loadtest_results(results: "LoadTestResults") -> None:
    from rich.table import Table

    table = Table(title="Load Test Results", show_header=True, header_style="bold")
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    rows = [
        ("Workers", str(results.workers)),
        ("Duration", f"{results.duration_s}s"),
        ("Dataset size", f"{results.dataset_size:,} request(s)"),
        ("Total requests sent", f"{results.total_requests:,}"),
        ("Failed requests", f"{results.failed_requests:,}"),
        ("  Content policy (400)", f"{results.content_policy_errors:,}"),
        ("Error rate", f"{results.error_rate_pct:.2f}%"),
        ("Throughput", f"{results.throughput_rps:.1f} req/s"),
        ("Latency p50", f"{results.latency_p50_ms:.0f} ms"),
        ("Latency p95", f"{results.latency_p95_ms:.0f} ms"),
        ("Latency p99", f"{results.latency_p99_ms:.0f} ms"),
        ("Latency avg", f"{results.latency_avg_ms:.0f} ms"),
        ("Tokens in  (total)", f"{results.tokens_in_total:,}"),
        ("Tokens out (total)", f"{results.tokens_out_total:,}"),
        ("Tokens in  (avg)", f"{results.tokens_in_avg:.1f}"),
        ("Tokens out (avg)", f"{results.tokens_out_avg:.1f}"),
    ]
    for label, value in rows:
        table.add_row(label, value)
    console.print(table)


@infra_app.command()
def loadtest(
    requests_file: Path = typer.Argument(
        ...,
        help="JSONL file of LiteLLM proxy log entries (each line must contain a proxy_server_request field)",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    workers: int = typer.Option(
        50, "--workers", "-w", min=1, help="Number of concurrent virtual users"
    ),
    duration: int = typer.Option(
        60, "--duration", "-d", min=5, help="Test duration in seconds (after ramp-up)"
    ),
    ramp_up: int = typer.Option(
        10, "--ramp-up", min=0, help="Seconds to ramp up to full concurrency"
    ),
    api_path: str = typer.Option(
        "/chat/completions",
        "--api-path",
        help="OpenAI-compatible proxy endpoint path",
    ),
    model: str = typer.Option(
        ...,
        "--model",
        "-m",
        help="Model name to test (e.g. claude-haiku-4-5-20251001, gpt-4o). Must match a model configured on the proxy.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save results to a file (.json or .csv)",
        dir_okay=False,
        resolve_path=True,
    ),
    error_log: Optional[Path] = typer.Option(
        None,
        "--error-log",
        help="Append failed request details to this file (JSONL, capped at 50 entries)",
        dir_okay=False,
        resolve_path=True,
    ),
    env_file: Optional[Path] = ENV_FILE_OPTION,
) -> None:
    """Load test the LiteLLM proxy using user messages from historical requests.

    Reads LLMAVEN_SECRETS_LITELLM_BASE_URL and LLMAVEN_SECRETS_LITELLM_MASTER_KEY
    from the environment (or --env-file).  Only the user message text is extracted
    from each log entry and sent as a plain OpenAI chat/completions request, so
    the same JSONL file (which may contain mixed providers) works against any model.

    Examples:
        Quick smoke test (10 workers, 30 s):
            llmaven infra loadtest requests.jsonl --model claude-haiku-4-5-20251001 --workers 10 --duration 30

        Full concurrency test with results saved:
            llmaven infra loadtest requests.jsonl \\
                --model claude-haiku-4-5-20251001 \\
                --workers 150 --duration 120 --ramp-up 30 \\
                --output results.json --env-file .env
    """
    from llmaven.deployment.loadtest import (
        LoadTestError,
        _load_requests,
        preflight_check,
        run_load_test,
        save_results,
    )

    base_url, api_key = _get_litellm_credentials(env_file)

    # ── Preflight: fire one request so failures are immediately visible ──────
    console.print(
        f"[blue]→[/blue] Preflight check against {base_url.rstrip('/')}{api_path}"
    )
    try:
        sample_dataset = _load_requests(requests_file, model=model)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Failed to load requests file: {e}")
        raise typer.Exit(code=1)
    console.print(
        f"[blue]→[/blue] Loaded {len(sample_dataset):,} request(s) from {requests_file.name}"
    )

    if not sample_dataset:
        console_err.print("[red]✗[/red] No valid requests found in JSONL file")
        raise typer.Exit(code=1)

    pf = preflight_check(base_url, api_key, api_path, sample_dataset[0])
    if pf.error:
        console_err.print(f"[red]✗[/red] Preflight failed — {pf.error}")
        console_err.print(f"  URL: {pf.url}")
        raise typer.Exit(code=1)
    elif not pf.ok:
        console_err.print(
            f"[red]✗[/red] Preflight got HTTP {pf.status_code} — aborting load test"
        )
        console_err.print(f"  URL:      {pf.url}")
        console_err.print(f"  Response: {pf.response_body}")
        raise typer.Exit(code=1)
    else:
        console.print("[green]✓[/green] Preflight OK (HTTP 200)")

    console.print(
        f"[blue]→[/blue] Starting load test: {workers} workers × {duration}s "
        f"(ramp-up {ramp_up}s)"
    )

    try:
        results = run_load_test(
            requests_file=requests_file,
            base_url=base_url,
            api_key=api_key,
            model=model,
            workers=workers,
            duration=duration,
            ramp_up=ramp_up,
            api_path=api_path,
            error_log=error_log,
        )
    except LoadTestError as e:
        console_err.print(f"[red]✗[/red] Load test failed: {e}")
        raise typer.Exit(code=1)

    _print_loadtest_results(results)

    if output:
        save_results(results, output)
        console.print(f"[green]✓[/green] Results saved to {output}")

    if error_log and error_log.exists():
        n = sum(1 for _ in error_log.open())
        console.print(f"[yellow]![/yellow] {n} error(s) logged to {error_log}")


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
    from pathlib import Path
    from llmaven.agentic.ingestion import IngestionPipeline
    from llmaven.agentic.exceptions import AgenticRAGError

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
    from llmaven.agentic.search import HybridSearcher
    from llmaven.agentic.exceptions import AgenticRAGError

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
    from rich.markdown import Markdown
    from rich.panel import Panel

    from llmaven.agentic.agent import RAGAgent
    from llmaven.agentic.exceptions import AgenticRAGError
    from llmaven.agentic.settings import config

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
