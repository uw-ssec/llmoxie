"""Server-side sessions. The browser holds only a random id; tokens never leave the server."""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

pool = ConnectionPool(os.environ["CONSOLE_WEB_DATABASE_URL"], min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row})

# `__Host-` makes the browser insist on Secure, Path=/ and no Domain; `Http-` adds "set by a server, HttpOnly".
SESSION_COOKIE = "__Host-Http-console"
LOGIN_COOKIE = "__Host-Http-console-login"  # lives only across the trip to the sign-in page
SESSION_TTL = timedelta(hours=8)
LOGIN_TTL = timedelta(minutes=10)


def _hash(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


def create(data: dict, ttl: timedelta) -> str:
    sid = secrets.token_urlsafe(32)
    with pool.connection() as conn:
        conn.execute("DELETE FROM web_session WHERE expires_at < now()")
        conn.execute("INSERT INTO web_session (sid_hash, data, expires_at) VALUES (%s, %s::jsonb, %s)",
                     (_hash(sid), json.dumps(data), datetime.now(timezone.utc) + ttl))
    return sid


def load(sid: str | None) -> dict | None:
    if not sid:
        return None
    with pool.connection() as conn:
        row = conn.execute("SELECT data FROM web_session WHERE sid_hash = %s AND expires_at > now()",
                           (_hash(sid),)).fetchone()
    return row["data"] if row else None


def save(sid: str, data: dict) -> None:
    with pool.connection() as conn:
        conn.execute("UPDATE web_session SET data = %s::jsonb WHERE sid_hash = %s", (json.dumps(data), _hash(sid)))


def delete(sid: str | None) -> None:
    if sid:
        with pool.connection() as conn:
            conn.execute("DELETE FROM web_session WHERE sid_hash = %s", (_hash(sid),))


def set_cookie(response, name: str, sid: str, ttl: timedelta, samesite: str) -> None:
    response.set_cookie(name, sid, max_age=int(ttl.total_seconds()), path="/", secure=True, httponly=True,
                        samesite=samesite)


def clear_cookie(response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True)
