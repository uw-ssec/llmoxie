"""Database access for the broker. Every transaction declares its row-level-security scope."""

import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

pool = ConnectionPool(os.environ["CONSOLE_BROKER_DATABASE_URL"], min_size=1, max_size=10, open=False,
                      kwargs={"row_factory": dict_row})


@contextmanager
def _tx(scope: str, org_id: str):
    with pool.connection() as conn:  # commits on exit, rolls back on an exception
        conn.execute("SELECT set_config('app.scope', %s, true), set_config('app.org_id', %s, true)", (scope, org_id))
        yield conn


def org_tx(org_id):
    """A transaction that can only see and write one org's rows."""
    return _tx("org", str(org_id))


def system_tx():
    """For work not tied to one org: sign-in, invite tokens, SSEC admin screens, the audit log."""
    return _tx("system", "")
