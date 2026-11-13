"""LiteLLM callback that writes one spend line per successful request.

Each line is ``LLMOXIE_SPEND {json}`` on stdout, which Azure Container Apps
forwards to ``ContainerAppConsoleLogs_CL``. Prompts, responses, and raw API
keys are never written.
"""

import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

SPEND_LINE_PREFIX = "LLMOXIE_SPEND "
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

logger = logging.getLogger("SpendLogger")
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[SpendLogger] %(levelname)s - %(message)s"))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def _key_hash(value: Any) -> str | None:
    """Return the hash only when it is a SHA-256 hex digest, else None."""
    if isinstance(value, str) and _SHA256_HEX.fullmatch(value):
        return value
    return None


def _finite_cost(value: Any) -> float:
    """Return the cost as a float, or 0.0 when it is not a finite number."""
    cost = float(value or 0.0)
    return cost if math.isfinite(cost) else 0.0


def spend_record(payload: dict) -> dict:
    """Build the spend record for one standard logging payload."""
    metadata = payload.get("metadata") or {}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": payload.get("id"),
        "key_alias": metadata.get("user_api_key_alias"),
        "key_hash": _key_hash(metadata.get("user_api_key_hash")),
        "user_id": metadata.get("user_api_key_user_id"),
        "team_alias": metadata.get("user_api_key_team_alias"),
        "model": payload.get("model"),
        "spend": _finite_cost(payload.get("response_cost")),
        "total_tokens": int(payload.get("total_tokens") or 0),
    }


class SpendLogger(CustomLogger):
    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        try:
            payload = kwargs.get("standard_logging_object")
            if not payload:
                return
            record = spend_record(payload)
            line = json.dumps(record, separators=(",", ":"), allow_nan=False)
            sys.stdout.write(SPEND_LINE_PREFIX + line + "\n")
            sys.stdout.flush()
        except Exception:  # never fail the request over logging
            logger.exception("failed to write spend record")


proxy_handler_instance = SpendLogger()
