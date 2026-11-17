"""Keep the secrets that travel in addresses out of uvicorn's access log.

An invitation's token is part of its address (`/invite/<token>`, and `/web-api/invites/<token>` that its
screen asks), and the sign-in callback carries the identity provider's code and state in its query.
Anyone who can read the logs could use them. Each request is still logged, with those parts left out.
"""

import logging
import re

TOKEN_PATH = re.compile(r"^(/invite/|/web-api/invites/)[^/?]+", re.IGNORECASE)
SECRET_QUERY = re.compile(r"(^|&)(code|state|session_state|token|id_token|access_token|refresh_token)=",
                          re.IGNORECASE)
CALLBACK = "/auth/callback"


def redact(path: str) -> str:
    """`path` (with its query) as the log may keep it."""
    path, sep, query = path.partition("?")
    path = TOKEN_PATH.sub(r"\1<redacted>", path)
    if path == CALLBACK or SECRET_QUERY.search(query):
        return path
    return path + sep + query


class Redact(logging.Filter):
    """For uvicorn's access records, whose arguments are (client, method, path, http version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], redact(args[2]), *args[3:])
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, Redact) for f in logger.filters):
        logger.addFilter(Redact())
