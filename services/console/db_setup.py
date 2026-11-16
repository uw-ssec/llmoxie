"""Set up the console's database on a server where nobody is a superuser.

On Azure, a Container Apps Job runs this on every deploy as the Flexible Server's admin login. That
login has CREATEROLE and CREATEDB but is not a superuser, and the databases already exist (ARM made
them). It does what the local stack's superuser script (`db/console-db.sql`) does in one go:

  1. create the roles `console_web` and `console_broker` if missing, and set their passwords every
     run, so a rotated secret takes effect (the admin created the roles, so it holds ADMIN OPTION on
     them, which PostgreSQL 16 requires to alter them)
  2. close `console_db` to everyone but those two roles
  3. close the other databases on the server (`CONSOLE_OTHER_DATABASES`) to PUBLIC, keeping CONNECT
     for the admin login, so the console roles cannot reach them
  4. apply the schema, once: the text of `console-db.sql` after its `\\c console_db` line. Everything
     before that line is a superuser's setup, replaced by steps 1 to 3. The schema ran unchanged under
     a non-superuser admin; nothing had to be adapted.

Passwords reach the server only as SCRAM verifiers and are never printed. Failures name the step, never a value.
"""

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

DB = "console_db"
ROLES = {"console_web": "CONSOLE_WEB_DB_PASSWORD", "console_broker": "CONSOLE_BROKER_DB_PASSWORD"}
META_LINE = "\\c console_db"


def schema_statements(text: str) -> str:
    """The part of console-db.sql that follows the `\\c console_db` line."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == META_LINE:
            return "".join(lines[i + 1 :])
    raise ValueError(f"no {META_LINE} line in the schema file")


def _connect(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["PGHOST"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=dbname,
        sslmode=os.environ.get("PGSSLMODE", "require"),
        autocommit=True,
        connect_timeout=30,
    )


def create_roles(conn: psycopg.Connection) -> None:
    for role, env in ROLES.items():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
        # Send a SCRAM verifier, as psql's \password does, so the cleartext never appears in a statement
        # the server may log or keep (log_min_error_statement, pg_stat_statements, pgaudit).
        verifier = conn.pgconn.encrypt_password(os.environ[env].encode(), role.encode(), b"scram-sha-256").decode()
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(verifier)))


def lock_down_console_db(conn: psycopg.Connection) -> None:
    db = sql.Identifier(DB)
    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            db, sql.SQL(", ").join(sql.Identifier(r) for r in ROLES)
        )
    )


def close_other_databases(conn: psycopg.Connection, names: list[str]) -> None:
    admin = sql.Identifier(os.environ["PGUSER"])
    for name in names:
        db = sql.Identifier(name)
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, admin))
        conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(db))


def apply_schema(schema_text: str) -> None:
    with _connect(DB) as conn:
        if conn.execute("SELECT to_regclass('public.person')").fetchone()[0] is not None:
            print("schema already in place")
            return
        conn.autocommit = False  # one transaction: no half-built schema to trip the next run
        conn.execute(schema_text)
        conn.commit()
        print("schema applied")


def main() -> int:
    step = "start"
    try:
        step = "read the schema file"
        schema_text = schema_statements(Path(os.environ.get("CONSOLE_SCHEMA_FILE", "db/console-db.sql")).read_text())
        others = [n.strip() for n in os.environ.get("CONSOLE_OTHER_DATABASES", "").split(",") if n.strip()]
        step = "connect to the server"
        with _connect("postgres") as conn:
            step = "create the console roles and set their passwords"
            create_roles(conn)
            step = f"restrict connections to {DB}"
            lock_down_console_db(conn)
            step = "close the other databases to the console roles"
            close_other_databases(conn, others)
        step = f"apply the schema in {DB}"
        apply_schema(schema_text)
    except Exception as exc:  # never str(exc): a driver message could carry a value
        print(f"db_setup failed at: {step} ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("database ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
