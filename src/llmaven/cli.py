"""CLI for LLMaven API.

This module provides command-line interface functionality for the LLMaven project.
"""

from __future__ import annotations

from pathlib import Path
import re
from enum import Enum
from time import sleep
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

# Create subcommand for infrastructure management
infra_app = typer.Typer(
    name="infra",
    help="Infrastructure deployment and management commands",
    add_completion=False,
)
app.add_typer(infra_app)

# Create subcommand for backup storage infrastructure management
backup_infra_app = typer.Typer(
    name="backup-infra",
    help="Backup storage infrastructure commands",
    add_completion=False,
)
app.add_typer(backup_infra_app)


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
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Validation failed: {e}")
        raise typer.Exit(code=1)


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
    expect_no_changes: bool = typer.Option(
        False,
        "--expect-no-changes",
        is_flag=True,
        help="Fail without deploying if the preview plans any resource change",
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

        Deploy only if nothing would change (e.g., to sync state safely):
            llmaven infra deploy --expect-no-changes

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
            expect_no_changes=expect_no_changes,
        )
    except DeploymentError as e:
        console_err.print(f"[red]✗[/red] Deployment failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Deployment failed: {e}")
        raise typer.Exit(code=1)


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
        console_err.print(f"[red]✗[/red] Destruction failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Destruction failed: {e}")
        raise typer.Exit(code=1)


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
        console_err.print(f"[red]✗[/red] Status check failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Status check failed: {e}")
        raise typer.Exit(code=1)


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
        console_err.print(f"[red]✗[/red] Refresh failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Refresh failed: {e}")
        raise typer.Exit(code=1)


class ExtractSource(str, Enum):
    litellm = "litellm"
    mlflow = "mlflow"


def _get_llmaven_secrets(env_file: Optional[Path]) -> dict:
    """Wrapper to keep secrets import local and easy to mock in tests."""
    from llmaven.infrastructure.utils.secrets import get_llmaven_secrets

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
    use_zip: bool = True,
) -> Path:
    use_default_path = output_file is None
    filename_prefix = "llmaven_"
    base_suffix = f"_{from_date}_to_{to_date}"
    filename_suffix = f"{base_suffix}.zip" if use_zip else base_suffix

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

    # Ensure the output path's type matches the chosen mode (zip vs directory).
    if path.exists():
        if use_zip and path.is_dir():
            _fail_extract(
                f"Output path is a directory but zip mode is enabled: {path}. "
                "Pass --no-zip to write JSONL files into a directory."
            )
        if not use_zip and path.is_file():
            _fail_extract(
                f"Output path is a file but --no-zip writes to a directory: {path}"
            )

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


class _ExtractWriter:
    """Write per-day JSONL entries to either a zip archive or a directory.

    Why: lets the extract pipeline stay shape-identical whether `--no-zip` is
    used or not, instead of branching on every writestr call.
    """

    def __init__(self, output_path: Path, *, use_zip: bool, file_prefix: str) -> None:
        self._output_path = output_path
        self._use_zip = use_zip
        # Only files named `<file_prefix>*.jsonl` are treated as previous extract
        # output; everything else in a reused directory belongs to the user.
        self._file_prefix = file_prefix
        self._zipf_ctx = None
        self._zipf = None

    def __enter__(self) -> "_ExtractWriter":
        if self._use_zip:
            import zipfile

            self._zipf_ctx = zipfile.ZipFile(
                self._output_path, mode="w", compression=zipfile.ZIP_DEFLATED
            )
            # Use the __enter__ return value so callers (and test mocks) see the
            # post-__enter__ object, matching a plain `with zipfile.ZipFile(...)`.
            self._zipf = self._zipf_ctx.__enter__()
        else:
            # If the directory previously existed and the user confirmed overwrite,
            # remove stale output from a previous extract of the same source so it
            # doesn't linger alongside new output. Unrelated files are left alone.
            if self._output_path.is_dir():
                for child in self._output_path.glob(f"{self._file_prefix}*.jsonl"):
                    if child.is_file():
                        child.unlink()
            self._output_path.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._zipf_ctx is not None:
            self._zipf_ctx.__exit__(exc_type, exc, tb)
            self._zipf_ctx = None
            self._zipf = None

    def writestr(self, name: str, data: str) -> None:
        if self._zipf is not None:
            self._zipf.writestr(name, data)
        else:
            (self._output_path / name).write_text(data, encoding="utf-8")


class _TransientHTTPError(Exception):
    """Marker raised internally so the retry helper knows a response should be retried."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


# Retry config for transient HTTP failures (5xx + 429) and connection errors.
# Exposed at module scope so tests can monkey-patch a no-wait variant.
_RETRY_MAX_ATTEMPTS = 5
_RETRY_WAIT_MULTIPLIER = 1.0
_RETRY_WAIT_MIN_SECONDS = 1.0
_RETRY_WAIT_MAX_SECONDS = 10.0


def _is_transient_http_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _http_get_with_retry(
    client,
    *,
    url: str,
    params: dict,
    headers: dict,
):
    """Issue an HTTP GET, retrying on transient HTTP failures and connection errors.

    Retries on:
      - httpx.RequestError (connect timeouts, DNS failures, etc.)
      - HTTP 429 (rate limited)
      - HTTP 5xx (server errors)

    Non-retryable HTTP errors (e.g. 4xx other than 429) surface immediately
    via raise_for_status().
    """
    import httpx

    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            resp = client.get(url, params=params, headers=headers)
            if _is_transient_http_status(resp.status_code):
                raise _TransientHTTPError(
                    f"transient HTTP {resp.status_code} from {url}",
                    status_code=resp.status_code,
                )
            resp.raise_for_status()
            return resp
        except (_TransientHTTPError, httpx.RequestError):
            if attempt == _RETRY_MAX_ATTEMPTS:
                raise
            # Exponential backoff: multiplier * 2**(attempt-1), clamped to [min, max].
            wait = _RETRY_WAIT_MULTIPLIER * 2 ** (attempt - 1)
            sleep(max(_RETRY_WAIT_MIN_SECONDS, min(wait, _RETRY_WAIT_MAX_SECONDS)))


def _extract_litellm_logs(
    start_date_obj: "date",
    end_date_obj: "date",
    output_file: Path,
    env_file: Optional[Path],
    use_zip: bool = True,
) -> None:
    import httpx

    litellm_base_url, litellm_master_key = _get_litellm_credentials(env_file)

    endpoint = f"{litellm_base_url.rstrip('/')}/spend/logs"
    headers = {"Authorization": f"Bearer {litellm_master_key}"}

    console.print(
        f"[blue]→[/blue] Extracting LiteLLM logs "
        f"{start_date_obj.isoformat()} → {end_date_obj.isoformat()} (inclusive UTC dates)"
    )

    total_records = 0

    with _ExtractWriter(
        output_file, use_zip=use_zip, file_prefix="litellm_spend_logs_"
    ) as zipf:
        with httpx.Client(timeout=30.0) as http_client:
            current_date = start_date_obj
            while current_date <= end_date_obj:
                date_str = current_date.isoformat()
                day_records: list[object] = []
                # failed_hours: list[int] = []

                # /spend/logs only accepts YYYY-MM-DD (no time component).
                # summarize=false returns individual records instead of daily aggregates.
                next_date_str = (current_date + timedelta(days=1)).isoformat()
                params = {
                    "start_date": date_str,
                    "end_date": next_date_str,
                    "summarize": "false",
                }

                try:
                    resp = _http_get_with_retry(
                        http_client,
                        url=endpoint,
                        params=params,
                        headers=headers,
                    )
                except (_TransientHTTPError, httpx.HTTPError) as exc:
                    # Retries are exhausted or the error is not transient; fail
                    # rather than fall through to a stale or unbound `resp`.
                    _fail_extract(f"LiteLLM /spend/logs failed for {date_str}: {exc}")

                try:
                    body = resp.json()
                    if not isinstance(body, list):
                        raise ValueError(f"expected list, got {type(body).__name__}")
                    day_records.extend(body)
                except Exception as exc:
                    console_err.print(
                        f"[yellow]![/yellow] {date_str}: skipping ({exc})"
                    )

                total_records += len(day_records)

                try:
                    jsonl_payload = _serialize_to_jsonl(day_records)
                except Exception as exc:
                    _fail_extract(f"Failed to serialize records for {date_str}: {exc}")

                if day_records:
                    zipf.writestr(
                        f"litellm_spend_logs_{date_str}.jsonl",
                        jsonl_payload,
                    )

                console.print(
                    f"[green]✓[/green] {date_str}: {len(day_records)} records"
                )
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
    use_zip: bool = True,
) -> None:
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

    with _ExtractWriter(
        output_file, use_zip=use_zip, file_prefix="mlflow_traces_"
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
        help="Output path (zip file, or directory when --no-zip is used)",
        dir_okay=True,
        file_okay=True,
        writable=True,
        resolve_path=True,
        path_type=Path,
    ),
    no_zip: bool = typer.Option(
        False,
        "--no-zip",
        help=(
            "Write raw JSONL files into a directory instead of bundling them "
            "into a zip archive. Useful for small date ranges where unzipping "
            "is just an extra step."
        ),
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

    use_zip = not no_zip

    # Validate output file
    output_file = _prepare_extract_output_file(
        output_file,
        source,
        from_date,
        to_date,
        use_zip=use_zip,
    )

    if source == ExtractSource.litellm:
        _extract_litellm_logs(
            start_date_obj,
            end_date_obj,
            output_file,
            env_file,
            use_zip=use_zip,
        )
    elif source == ExtractSource.mlflow:
        _extract_mlflow_logs(
            start_date_obj,
            end_date_obj,
            output_file,
            env_file,
            use_zip=use_zip,
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
        console_err.print(f"[red]✗[/red] Cancel failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Cancel failed: {e}")
        raise typer.Exit(code=1)


def _print_loadtest_results(results: "LoadTestResults") -> None:
    from rich.table import Table

    table = Table(title="Load Test Results", show_header=True, header_style="bold")
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    rows = [
        ("Workers", str(results.workers)),
        ("Dataset size", f"{results.dataset_size:,} request(s)"),
        ("Total requests sent", f"{results.total_requests:,}"),
        ("Requests not sent", f"{results.unsent_requests:,}"),
        ("Failed requests", f"{results.failed_requests:,}"),
        ("  Content policy (400)", f"{results.content_policy_errors:,}"),
        ("Fallback requests", f"{results.fallback_requests:,}"),
        (
            "Fallback rate",
            "unknown"
            if results.fallback_rate_pct is None
            else f"{results.fallback_rate_pct:.2f}%",
        ),
        ("  Unclassified", f"{results.fallback_unclassified_requests:,}"),
        ("Served model counts", results.served_model_counts_json),
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
    model: str = typer.Option(
        ...,
        "--model",
        "-m",
        help="Anthropic model name to test (e.g. claude-haiku-4-5-20251001). Must match a model configured on the proxy.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save results to a file (.json or .csv)",
        dir_okay=False,
        resolve_path=True,
    ),
    env_file: Optional[Path] = ENV_FILE_OPTION,
) -> None:
    """Load test the LiteLLM proxy using historical requests.

    Reads LLMAVEN_SECRETS_LITELLM_BASE_URL and LLMAVEN_SECRETS_LITELLM_MASTER_KEY
    from the environment (or --env-file).  Only Anthropic Messages entries
    (call_type 'anthropic_messages') are replayed, each exactly once, to the
    proxy's /v1/messages endpoint with --model substituted.  Failed responses,
    including request previews, are logged to errors-<model>-<workers>-<ts>.log
    in the current directory.

    Examples:
        Quick smoke test with 10 workers:
            llmaven infra loadtest requests.jsonl --model claude-haiku-4-5-20251001 --workers 10

        Higher concurrency with results appended to a CSV:
            llmaven infra loadtest requests.jsonl \\
                --model claude-haiku-4-5-20251001 \\
                --workers 150 --output results.csv --env-file .env
    """
    from llmaven.deployment.loadtest import (
        LoadTestError,
        _ANTHROPIC_API_PATH,
        _load_requests,
        preflight_check,
        run_load_test,
        save_results,
    )

    base_url, api_key = _get_litellm_credentials(env_file)

    # ── Preflight: fire one request so failures are immediately visible ──────
    try:
        sample_dataset = _load_requests(requests_file, model=model)
    except LoadTestError as e:
        console_err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Failed to load requests file: {e}")
        raise typer.Exit(code=1)
    console.print(
        f"[blue]→[/blue] Loaded {len(sample_dataset):,} request(s) from {requests_file.name}"
    )

    if not sample_dataset:
        console_err.print("[red]✗[/red] No valid requests found in JSONL file")
        raise typer.Exit(code=1)

    first_req = sample_dataset[0]
    console.print(
        f"[blue]→[/blue] Preflight check against {base_url.rstrip('/')}{_ANTHROPIC_API_PATH}"
    )
    pf = preflight_check(base_url, api_key, _ANTHROPIC_API_PATH, first_req)
    if pf.error:
        console_err.print(f"[red]✗[/red] Preflight failed — {pf.error}")
        console_err.print(f"  URL: {pf.url}")
        if pf.response_body:
            console_err.print(f"  Response: {pf.response_body}")
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

    console.print(f"[blue]→[/blue] Starting load test: {workers} workers")

    _ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    _safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", model)
    error_log = Path(f"errors-{_safe_model}-{workers}-{_ts}.log")

    try:
        results = run_load_test(
            requests_file=requests_file,
            base_url=base_url,
            api_key=api_key,
            model=model,
            workers=workers,
            error_log=error_log,
        )
    except LoadTestError as e:
        console_err.print(f"[red]✗[/red] Load test failed: {e}")
        raise typer.Exit(code=1)

    _print_loadtest_results(results)

    if output:
        save_results(results, output)
        console.print(f"[green]✓[/green] Results saved to {output}")

    if error_log.exists():
        n = sum(1 for _ in error_log.open(encoding="utf-8"))
        console.print(f"[yellow]![/yellow] {n} error(s) logged to {error_log}")

    if results.unsent_requests:
        console_err.print(
            f"[red]✗[/red] Load test stopped at its deadline with "
            f"{results.unsent_requests:,} request(s) not sent; results are partial"
        )
        raise typer.Exit(code=1)


@backup_infra_app.command(name="deploy")
def backup_infra_deploy(
    config: Optional[str] = typer.Option(
        "llmaven-backup-config.yaml",
        "--config",
        "-c",
        help="Path to backup configuration file",
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
) -> None:
    """Deploy the backup storage infrastructure to Azure.

    Creates the resource group, storage account, and pg-backups container
    in an isolated stack. This stack is intentionally separate from the main
    stack so that backups survive a main-stack destroy.

    Examples:
        Preview deployment:
            llmaven backup-infra deploy --preview

        Deploy with auto-approval:
            llmaven backup-infra deploy --yes

        Deploy with explicit config path:
            llmaven backup-infra deploy --config llmaven-backup-config.yaml
    """
    from pathlib import Path

    from llmaven.deployment.deploy_backup import DeploymentError, deploy_backup_storage

    config_path = Path(config)

    try:
        deploy_backup_storage(
            config_path=config_path,
            preview=preview,
            auto_approve=auto_approve,
        )
    except DeploymentError as e:
        console_err.print(f"[red]✗[/red] Backup deployment failed: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Backup deployment failed: {e}")
        raise typer.Exit(code=1)


@backup_infra_app.command(name="output")
def backup_infra_output(
    config: Optional[str] = typer.Option(
        "llmaven-backup-config.yaml",
        "--config",
        "-c",
        help="Path to backup configuration file",
    ),
    secret: Optional[str] = typer.Option(
        None,
        "--secret",
        help="Name of a secret output to retrieve (revealed in plaintext)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Name of a non-secret output to retrieve",
    ),
) -> None:
    """Print a backup stack output value to stdout.

    Use --secret to retrieve and reveal secret outputs (e.g. connection strings).
    Use --name for non-secret outputs. Exactly one of --secret or --name is required.

    The value is printed to stdout so it can be captured by a subshell.

    Examples:
        Retrieve the storage connection string:
            llmaven backup-infra output \\
              --config llmaven-backup-config.yaml \\
              --secret backup_storage_connection_string

        Capture into an environment variable:
            export BACKUP_STORAGE_CONNECTION_STRING=$(llmaven backup-infra output \\
              --config llmaven-backup-config.yaml \\
              --secret backup_storage_connection_string)
    """
    from pathlib import Path

    from llmaven.deployment.deploy_backup import (
        DeploymentError,
        get_backup_stack_output,
    )

    if secret is None and name is None:
        console_err.print(
            "[red]✗[/red] Provide --secret <output-name> or --name <output-name>."
        )
        raise typer.Exit(code=1)
    if secret is not None and name is not None:
        console_err.print("[red]✗[/red] --secret and --name are mutually exclusive.")
        raise typer.Exit(code=1)

    config_path = Path(config)
    output_name = secret if secret is not None else name
    reveal = secret is not None

    try:
        value = get_backup_stack_output(
            config_path=config_path,
            output_name=output_name,
            reveal_secret=reveal,
        )
        # Shell-captured values must bypass Rich's wrapping and tab expansion.
        typer.echo(value)
    except DeploymentError as e:
        console_err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        console_err.print(f"[red]✗[/red] Failed to retrieve output: {e}")
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Display the LLMaven version."""
    from llmaven import __version__

    console.print(f"LLMaven version {__version__}")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
