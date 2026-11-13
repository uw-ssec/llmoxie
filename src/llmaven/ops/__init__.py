"""Operator tooling for an already-deployed LLMaven platform.

This package imports nothing from ``llmaven.cli`` or ``llmaven.data`` so that it
can move out of this repository unchanged. LiteLLM credentials arrive through a
callback passed to :func:`build_ops_app` at registration time.
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape

from llmaven.ops.spend import (
    GroupBy,
    SpendFetchError,
    aggregate,
    baseline_window,
    compare,
    fetch_spend_records,
    iter_extract_records,
    render_table,
    write_csv,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

__all__ = ["build_ops_app"]

# Everything a bad --from-zip path can raise on read. ``iter_extract_records``
# is a generator, so these surface when the records are materialised, not when
# it is called: OSError covers FileNotFoundError and IsADirectoryError.
EXTRACT_READ_ERRORS = (ValueError, zipfile.BadZipFile, UnicodeDecodeError, OSError)


def build_ops_app(
    get_credentials: Callable[[Path | None], tuple[str, str]],
) -> typer.Typer:
    """Return the ``ops`` Typer group, reading credentials via ``get_credentials``.

    The callback keeps this package free of any import from ``llmaven.cli``.
    """
    ops_app = typer.Typer(
        name="ops",
        help="Operator reports for a deployed LLMaven platform",
        add_completion=False,
    )
    console = Console()
    console_err = Console(stderr=True)

    @ops_app.callback()
    def _ops() -> None:
        """Keep ``spend-report`` an explicit subcommand.

        Typer collapses a group that holds exactly one command and no callback,
        which would make the command reachable as plain ``ops``.
        """

    def _fail(message: str) -> typer.Exit:
        # ``message`` carries paths and exception text, so it is escaped before
        # it reaches rich: a bare "[x]" in a path would otherwise be swallowed
        # as markup and "[/x]" would raise MarkupError.
        console_err.print(f"[red]✗[/red] {escape(message)}")
        return typer.Exit(code=1)

    @ops_app.command("spend-report")
    def spend_report(
        start: datetime = typer.Option(
            ...,
            "--start",
            help="First day of the report window (inclusive, UTC)",
            formats=["%Y-%m-%d"],
        ),
        end: datetime = typer.Option(
            ...,
            "--end",
            help="Last day of the report window (inclusive, UTC)",
            formats=["%Y-%m-%d"],
        ),
        by: GroupBy = typer.Option(
            GroupBy.key,
            "--by",
            help="Grouping dimension",
        ),
        threshold: float = typer.Option(
            2.0,
            "--threshold",
            help="Flag a row as a spike at this multiple of its baseline spend",
        ),
        top: int | None = typer.Option(
            None,
            "--top",
            help="Show only the N highest-spend rows (the CSV always has every row)",
            min=1,
        ),
        from_zip: Path | None = typer.Option(
            None,
            "--from-zip",
            help="Read records from `llmaven infra extract` output instead of LiteLLM",
            exists=True,
            readable=True,
            resolve_path=True,
            path_type=Path,
        ),
        csv_path: Path | None = typer.Option(
            None,
            "--csv",
            help="Also write every row to this CSV file",
            dir_okay=False,
            resolve_path=True,
            path_type=Path,
        ),
        env_file: Path | None = typer.Option(
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
        ),
    ) -> None:
        """Report spend by key, user, model or team against the prior window."""
        report_start: date = start.date()
        report_end: date = end.date()
        if report_start > report_end:
            raise typer.BadParameter(
                f"--start ({report_start}) is after --end ({report_end}).",
                param_hint="--start",
            )

        base_start, base_end = baseline_window(report_start, report_end)

        # Both windows come from one pass so the live path fetches each day
        # once and the zip path reads the archive once.
        if from_zip is not None:
            source = f"extract {from_zip.name}"
            try:
                records = list(iter_extract_records(from_zip))
            except EXTRACT_READ_ERRORS as exc:
                raise _fail(f"Could not read {from_zip}: {exc}") from exc
        else:
            source = "LiteLLM"
            base_url, api_key = get_credentials(env_file)
            try:
                records = list(
                    fetch_spend_records(base_url, api_key, base_start, report_end)
                )
            except SpendFetchError as exc:
                raise _fail(str(exc)) from exc

        current = aggregate(records, by, report_start, report_end)
        baseline = aggregate(records, by, base_start, base_end)
        if not baseline:
            console_err.print(
                f"[yellow]![/yellow] No spend in the baseline window "
                f"{base_start}..{base_end}; comparison columns are blank."
            )
            baseline = None

        rows = compare(current, baseline, threshold)
        title = (
            f"Spend by {by.value} — {report_start}..{report_end} "
            f"vs {base_start}..{base_end} (source: {source})"
        )
        console.print(render_table(rows, title=title, top=top))

        if csv_path is not None:
            try:
                write_csv(rows, csv_path)
            except OSError as exc:
                raise _fail(f"Could not write {csv_path}: {exc}") from exc
            # soft_wrap keeps a long path on one line so it stays greppable.
            console_err.print(
                f"Wrote {len(rows)} row(s) to {csv_path}",
                soft_wrap=True,
                markup=False,
            )

    return ops_app
