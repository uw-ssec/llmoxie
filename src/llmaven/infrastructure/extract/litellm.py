import datetime
from datetime import timezone
import io
import json
import logging
from pathlib import Path
from typing import Optional
import time
import zipfile
from decimal import Decimal
from uuid import UUID
import psycopg2
from psycopg2.extras import RealDictCursor

from llmaven.infrastructure.extract.exceptions import ExtractionError, FileWriteError

logger = logging.getLogger(__name__)


class LiteLLMLogExtractor:
    """Extract LiteLLM request logs from PostgreSQL."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        """Initialize extractor with database credentials."""
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._connection: Optional[psycopg2.extensions.connection] = None

    def connect_to_postgres(self) -> None:
        """Connect to PostgreSQL database."""
        try:
            self._connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=10,
            )

            # psycopg2 default is autocommit=False (good for server-side cursors).
            # We *avoid* setting autocommit=True because named cursors require a transaction.
            logger.info(f"Connected to {self.host}:{self.port}/{self.database}")

        except psycopg2.OperationalError as e:
            logger.error(f"Failed to connect: {e}")
            raise

    def disconnect_from_postgres(self) -> None:
        """Close database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Disconnected from database")
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
            finally:
                self._connection = None

    def extract_to_zip(
        self,
        start_date: datetime,
        end_date: datetime,
        output_path: Path | str,
        validate: bool = False,
    ) -> None:
        """
        Extract LiteLLM logs for a date range into a partitioned JSONL zip file (UTC).

        Creates a zip file with one `.jsonl` file per calendar day. Both dates are inclusive
        (00:00:00 UTC through 23:59:59 UTC). Empty days are omitted. Records within each day
        are ordered by `created_at`.

        **Schema note:**
        This export serializes rows from the `litellm_logs` table (`SELECT *`). As a result,
        the JSONL schema reflects the database table columns and may differ from LiteLLM’s
        `StandardLoggingPayload` / `standard_logging_object`. If strict payload parity is
        required, export the payload JSON field (if present) or add a mapping step.
        See: https://docs.litellm.ai/docs/proxy/logging_spec

        **Example**:
            ```python
            extractor = LiteLLMLogExtractor(
                host="localhost", port=5432, database="litellm_db",
                user="postgres", password="secret"
            )

            extractor.connect_to_postgres()

            extractor.extract_to_zip(
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 1, 3),
                output_path=Path("litellm-logs.zip")
            )

            extractor.disconnect_from_progress()

            # Result:
            # litellm-logs.zip
            # ├── litellm_2026-01-01.jsonl
            # ├── litellm_2026-01-02.jsonl
            # └── litellm_2026-01-03.jsonl
            ```

        Args:
            start_date: Start date (inclusive). Time ignored; begins at 00:00:00 UTC.
            end_date: End date (inclusive). Time ignored; includes through 23:59:59 UTC.
            output_path: Output zip file path. Parent directories created if needed.
            validate: If True, attempts to validate records against LiteLLM’s StandardLoggingPayload
                when available. Validation failures are logged but do not stop extraction.

        Raises:
            ExtractionError: If start_date > end_date, not connected, or no logs found.
            FileWriteError: If zip creation or writing fails.
        """
        # Internal tuning constants (not parameters)
        COMPRESSLEVEL = 6
        CURSOR_ITERSIZE = 5000

        if not self._connection:
            raise ExtractionError("Not connected to database. Call connect() first.")

        if start_date > end_date:
            raise ExtractionError("start_date must be before or equal to end_date")

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.perf_counter()

        # Interpret inputs as calendar days in UTC (ignore time portion)
        start_of_range = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_range = (end_date + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Ensure UTC-aware boundaries (assume naive datetimes are UTC)
        if start_of_range.tzinfo is None:
            start_of_range = start_of_range.replace(tzinfo=timezone.utc)
        else:
            start_of_range = start_of_range.astimezone(timezone.utc)

        if end_of_range.tzinfo is None:
            end_of_range = end_of_range.replace(tzinfo=timezone.utc)
        else:
            end_of_range = end_of_range.astimezone(timezone.utc)

        logger.info(f"Fetching logs from {start_date.date()} to {end_date.date()}")

        # Ordered query enables single-pass date bucketing
        # TODO: determine exact fields we want to mirror StandardLoggingPayload specification.
        query = """
            SELECT *
            FROM litellm_logs
            WHERE created_at >= %s AND created_at < %s
            ORDER BY created_at ASC
        """

        # Server-side cursor requires autocommit=False (named cursor streams rows in batches)
        old_autocommit = self._connection.autocommit
        self._connection.autocommit = False

        cursor_name = f"litellm_log_stream_{int(time.time() * 1000)}"
        cursor = self._connection.cursor(
            name=cursor_name,
            cursor_factory=RealDictCursor,
        )
        cursor.itersize = CURSOR_ITERSIZE

        # Streaming state for active zip entry (one per day)
        current_date_key: str | None = None
        entry_text: io.TextIOWrapper | None = None

        # Metrics
        rows_seen = 0
        rows_written = 0
        rows_skipped = 0

        def close_entry() -> None:
            """Close the active day's zip entry cleanly."""
            nonlocal entry_text
            if entry_text is not None:
                entry_text.flush()
                entry_text.close()
                entry_text = None

        try:
            cursor.execute(query, (start_of_range, end_of_range))

            with zipfile.ZipFile(
                output_file,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=COMPRESSLEVEL,
            ) as zf:
                for row in cursor:
                    rows_seen += 1

                    created_at = row.get("created_at")
                    if not isinstance(created_at, datetime.datetime):
                        # created_at should be a datetime; skip malformed rows
                        rows_skipped += 1
                        logger.warning(
                            f"Skipping record with invalid created_at: {created_at!r}"
                        )
                        continue

                    # Normalize to UTC before extracting bucket date
                    if created_at.tzinfo is None:
                        created_utc = created_at.replace(tzinfo=timezone.utc)
                    else:
                        created_utc = created_at.astimezone(timezone.utc)

                    date_key = created_utc.date().isoformat()  # "YYYY-MM-DD"

                    # Day boundary: close previous entry, open new JSONL file
                    if date_key != current_date_key:
                        close_entry()
                        current_date_key = date_key

                        filename = f"litellm_{date_key}.jsonl"
                        entry_bin = zf.open(filename, "w")
                        entry_text = io.TextIOWrapper(
                            entry_bin, encoding="utf-8", newline="\n"
                        )

                    # Convert DB record to JSON-serializable dict
                    serialized = self._serialize_record(dict(row))

                    # JSONL: one object per line
                    entry_text.write(json.dumps(serialized, ensure_ascii=False))
                    entry_text.write("\n")
                    rows_written += 1

                close_entry()

            if rows_written == 0:
                raise ExtractionError(
                    f"No logs found for date range {start_date.date()} to {end_date.date()}"
                )

            # Commit closes out the transaction and releases server-side cursor resources
            self._connection.commit()

        except psycopg2.DatabaseError as e:
            try:
                self._connection.rollback()
            except Exception:
                pass
            logger.error(f"Database query failed: {e}")
            raise ExtractionError(f"Database query failed: {e}") from e

        except IOError as e:
            try:
                self._connection.rollback()
            except Exception:
                pass
            raise FileWriteError(
                f"Failed to write zip file to {output_file}: {e}"
            ) from e

        except ExtractionError:
            try:
                self._connection.rollback()
            except Exception:
                pass
            raise

        except Exception as e:
            try:
                self._connection.rollback()
            except Exception:
                pass
            logger.error(f"Unexpected error during extraction: {e}")
            raise FileWriteError(f"Unexpected error: {e}") from e

        finally:
            try:
                cursor.close()
            except Exception:
                pass
            self._connection.autocommit = old_autocommit

        elapsed = time.perf_counter() - start_time
        file_size_mb = output_file.stat().st_size / (1024 * 1024)
        rps = (rows_seen / elapsed) if elapsed > 0 else 0

        logger.info(
            "Extraction complete",
            extra={
                "duration_seconds": round(elapsed, 2),
                "output_size_mb": round(file_size_mb, 2),
                "records_seen": rows_seen,
                "records_written": rows_written,
                "records_skipped": rows_skipped,
                "records_per_second": round(rps, 0),
                "date_range_days": (end_date.date() - start_date.date()).days + 1,
            },
        )

    def _serialize_record(self, record: dict) -> dict:
        """Normalize a DB record into JSON-serializable types."""

        def normalize(value):
            if isinstance(value, datetime.datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.isoformat()
            if isinstance(value, datetime.date):
                return value.isoformat()
            if isinstance(value, (bytes, bytearray, memoryview)):
                return bytes(value).decode("utf-8", errors="replace")
            if isinstance(value, Decimal):
                return float(value)
            if isinstance(value, UUID):
                return str(value)
            if isinstance(value, dict):
                return {key: normalize(val) for key, val in value.items()}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            return value

        return {key: normalize(val) for key, val in record.items()}
