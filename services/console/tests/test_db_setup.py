"""db_setup.py against a real PostgreSQL 16 where the admin login is not a superuser (as on Azure).

The server is a throwaway `postgres:16` container started through Docker. When the tests run inside
the test image, start the server yourself on a shared network and point DB_SETUP_TEST_PG at it:
`DB_SETUP_TEST_PG=host:port` (superuser `postgres`, password `DB_SETUP_TEST_PG_PASSWORD`). The
Docker container gets a random password. With neither Docker nor that variable, the database
tests skip.
"""

import os
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

import db_setup
from db_setup import main, schema_statements

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "console-db.sql"
# Throwaway role passwords, made per run so no password literal sits in the source.
PW = {
    name: secrets.token_urlsafe(16) for name in ("super", "admin", "web-1", "web-2", "broker-1", "wrong", "hub")
}
SUPER_PW = os.environ.get("DB_SETUP_TEST_PG_PASSWORD") or PW["super"]
ADMIN_PW = PW["admin"]
OTHERS = ("litellm_db", "mlflow_db")


def test_schema_statements_drop_psql_meta_commands():
    text = schema_statements(SCHEMA.read_text())
    assert "\\c" not in text
    assert "CREATE ROLE" not in text and "CREATE DATABASE" not in text
    assert text.lstrip().startswith("REVOKE ALL ON SCHEMA public")
    assert "CREATE TABLE web_session" in text
    with pytest.raises(ValueError):
        schema_statements("SELECT 1;")


@pytest.fixture(scope="module")
def server():
    external = os.environ.get("DB_SETUP_TEST_PG")
    name = None
    if external:
        host, port = external.rsplit(":", 1)
    elif shutil.which("docker"):
        name = f"db-setup-test-{uuid.uuid4().hex[:8]}"
        run = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={SUPER_PW}",
             "-p", "127.0.0.1::5432", "postgres:16"],
            capture_output=True, text=True)
        if run.returncode:
            pytest.skip(f"cannot start postgres:16: {run.stderr.strip()[-200:]}")
        host = "127.0.0.1"
    else:
        pytest.skip("Docker is not available")
    try:
        if name:
            port = subprocess.run(["docker", "port", name, "5432/tcp"], capture_output=True, text=True,
                                  check=True).stdout.split(":")[-1].strip()
        for _ in range(60):
            try:
                psycopg.connect(host=host, port=port, user="postgres", password=SUPER_PW, dbname="postgres",
                                connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                time.sleep(1)
        else:
            pytest.skip("postgres did not come up")
        yield host, port
    finally:
        if name:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def superuser(server, dbname="postgres"):
    host, port = server
    return psycopg.connect(host=host, port=port, user="postgres", password=SUPER_PW, dbname=dbname,
                           autocommit=True)


@pytest.fixture
def pg(server, monkeypatch):
    """A clean server per test: azadmin (CREATEROLE CREATEDB, no superuser) owns the databases."""
    host, port = server
    with superuser(server) as conn:
        for db in ("console_db", "okf_hub", *OTHERS):
            conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        for role in ("console_web", "console_broker", "okf_hub", "azadmin", "pgadmin_group"):
            conn.execute(f"DROP ROLE IF EXISTS {role}")
        conn.execute(f"CREATE ROLE azadmin LOGIN CREATEROLE CREATEDB PASSWORD '{ADMIN_PW}'")
        conn.execute("GRANT azadmin TO postgres")
        # On Azure the other databases may belong to azure_pg_admin, of which the admin login is a member.
        conn.execute("DROP ROLE IF EXISTS pgadmin_group")
        conn.execute("CREATE ROLE pgadmin_group NOLOGIN")
        conn.execute("GRANT pgadmin_group TO azadmin")
        conn.execute("CREATE DATABASE console_db OWNER azadmin")
        for db in OTHERS:
            conn.execute(f"CREATE DATABASE {db} OWNER pgadmin_group")
        conn.execute("CREATE DATABASE okf_hub OWNER azadmin")
    for key, value in {
        "PGHOST": host, "PGPORT": port, "PGUSER": "azadmin", "PGPASSWORD": ADMIN_PW,
        "PGSSLMODE": "disable",  # the throwaway server has no TLS; main() defaults to verify-full
        "CONSOLE_WEB_DB_PASSWORD": PW["web-1"], "CONSOLE_BROKER_DB_PASSWORD": PW["broker-1"],
        "CONSOLE_OTHER_DATABASES": ",".join(OTHERS), "CONSOLE_SCHEMA_FILE": str(SCHEMA),
    }.items():
        monkeypatch.setenv(key, value)
    return server


def connect_as(server, role, password, dbname):
    host, port = server
    return psycopg.connect(host=host, port=port, user=role, password=password, dbname=dbname,
                           connect_timeout=5)


def test_runs_twice_without_error(pg):
    assert main() == 0 and main() == 0


def test_second_run_does_not_reapply_schema(pg, capsys):
    assert main() == 0
    with superuser(pg, "console_db") as conn:
        conn.execute("INSERT INTO person (issuer, subject, participant_id) VALUES ('i', 's', 'p1')")
    capsys.readouterr()
    assert main() == 0
    assert "schema already in place" in capsys.readouterr().out
    with superuser(pg, "console_db") as conn:
        assert conn.execute("SELECT count(*) FROM person").fetchone()[0] == 1


def test_changed_password_takes(pg, monkeypatch):
    assert main() == 0
    connect_as(pg, "console_web", PW["web-1"], "console_db").close()
    monkeypatch.setenv("CONSOLE_WEB_DB_PASSWORD", PW["web-2"])
    assert main() == 0
    connect_as(pg, "console_web", PW["web-2"], "console_db").close()
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        connect_as(pg, "console_web", PW["web-1"], "console_db")


def test_passwords_are_stored_as_scram_verifiers(pg):
    assert main() == 0
    with superuser(pg) as conn:
        rows = conn.execute("SELECT rolpassword FROM pg_authid WHERE rolname LIKE 'console_%'").fetchall()
    assert len(rows) == 2 and all(r[0].startswith("SCRAM-SHA-256$") for r in rows)


def test_console_roles_cannot_connect_elsewhere(pg):
    assert main() == 0
    for role, password in (("console_web", PW["web-1"]), ("console_broker", PW["broker-1"])):
        for db in OTHERS:
            # a refused login surfaces as OperationalError carrying the server's "permission denied"
            with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
                connect_as(pg, role, password, db)


def test_admin_keeps_connect_on_other_databases(pg):
    assert main() == 0
    for db in OTHERS:
        connect_as(pg, "azadmin", ADMIN_PW, db).close()
    # Membership in the owning role would let azadmin in anyway, so also check the explicit grant:
    # it is what keeps the access if the databases' ownership differs from this mimic.
    with superuser(pg) as conn:
        for db in OTHERS:
            granted = conn.execute(
                "SELECT count(*) FROM pg_database d, aclexplode(d.datacl) a "
                "WHERE d.datname = %s AND a.grantee = 'azadmin'::regrole AND a.privilege_type = 'CONNECT'",
                (db,)).fetchone()[0]
            assert granted == 1, db


def test_admin_keeps_connect_on_console_db_it_does_not_own(pg):
    # ARM may make console_db owned by azure_pg_admin, not the admin login. Revoking PUBLIC must not
    # leave the admin relying on that membership: it needs its own grant to apply the schema.
    with superuser(pg) as conn:
        conn.execute("ALTER DATABASE console_db OWNER TO pgadmin_group")
    assert main() == 0
    with superuser(pg) as conn:
        granted = conn.execute(
            "SELECT count(*) FROM pg_database d, aclexplode(d.datacl) a "
            "WHERE d.datname = 'console_db' AND a.grantee = 'azadmin'::regrole AND a.privilege_type = 'CONNECT'"
        ).fetchone()[0]
    assert granted == 1


def test_without_the_hub_password_no_okf_hub_role_is_made(pg):
    assert main() == 0
    with superuser(pg) as conn:
        assert conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'okf_hub'").fetchone() is None


def test_okf_hub_role_owns_its_database_and_others_cannot_connect(pg, monkeypatch):
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["hub"])
    assert main() == 0
    with connect_as(pg, "okf_hub", PW["hub"], "okf_hub") as conn:
        conn.execute("CREATE TABLE t (x int)")
        conn.execute("INSERT INTO t VALUES (1)")
    for role, password in (("console_web", PW["web-1"]), ("console_broker", PW["broker-1"])):
        with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
            connect_as(pg, role, password, db_setup.HUB_DB)
    with superuser(pg) as conn:
        owner = conn.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'okf_hub'"
        ).fetchone()[0]
    assert owner == "okf_hub"


def test_okf_hub_role_cannot_connect_to_the_console_database(pg, monkeypatch):
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["hub"])
    assert main() == 0
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        connect_as(pg, "okf_hub", PW["hub"], "console_db")


def test_okf_hub_setup_runs_twice_and_a_changed_password_takes(pg, monkeypatch):
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["hub"])
    assert main() == 0 and main() == 0
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["wrong"])
    assert main() == 0
    connect_as(pg, "okf_hub", PW["wrong"], "okf_hub").close()
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        connect_as(pg, "okf_hub", PW["hub"], "okf_hub")


def test_okf_hub_password_is_a_scram_verifier(pg, monkeypatch):
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["hub"])
    assert main() == 0
    with superuser(pg) as conn:
        (verifier,) = conn.execute("SELECT rolpassword FROM pg_authid WHERE rolname = 'okf_hub'").fetchone()
    assert verifier.startswith("SCRAM-SHA-256$")


def test_a_failed_hub_step_still_leaves_the_console_schema_applied(pg, monkeypatch, capsys):
    # Without its database the hub step fails; it runs after the schema, so the console is unaffected.
    with superuser(pg) as conn:
        conn.execute("DROP DATABASE okf_hub")
    monkeypatch.setenv("OKF_HUB_DB_PASSWORD", PW["hub"])
    assert main() == 1
    err = capsys.readouterr().err
    assert "db_setup failed at: create the okf_hub role and give it okf_hub" in err
    assert PW["hub"] not in err
    with superuser(pg, "console_db") as conn:
        assert conn.execute("SELECT to_regclass('public.person')").fetchone()[0] is not None


def test_broker_sees_rls(pg):
    assert main() == 0
    with superuser(pg, "console_db") as conn:
        conn.execute("INSERT INTO person (issuer, subject, participant_id) VALUES ('i', 's', 'p1')")
        conn.execute("INSERT INTO org (slug, name, budget_ceiling) VALUES ('acme', 'Acme', 10)")
    with connect_as(pg, "console_broker", PW["broker-1"], "console_db") as conn:
        assert conn.execute("SELECT count(*) FROM person").fetchone()[0] == 1  # no RLS on person
        assert conn.execute("SELECT count(*) FROM org").fetchone()[0] == 0  # RLS: no org set


def test_failure_names_the_step_and_not_the_password(pg, monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", PW["wrong"])
    assert main() == 1
    err = capsys.readouterr().err
    assert "db_setup failed at: connect to the server" in err
    assert PW["wrong"] not in err and PW["web-1"] not in err


def test_default_sslmode_verifies_the_server_against_the_system_roots(monkeypatch):
    seen = {}
    monkeypatch.delenv("PGSSLMODE", raising=False)
    monkeypatch.delenv("PGSSLROOTCERT", raising=False)
    monkeypatch.setattr(db_setup.psycopg, "connect", lambda **kw: seen.update(kw) or (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setenv("PGHOST", "h"); monkeypatch.setenv("PGUSER", "u"); monkeypatch.setenv("PGPASSWORD", "p")
    monkeypatch.setenv("CONSOLE_SCHEMA_FILE", str(SCHEMA))
    assert main() == 1
    assert seen["sslmode"] == "verify-full" and seen["sslrootcert"] == "system"


def test_a_weaker_sslmode_is_passed_without_the_system_roots(monkeypatch):
    seen = {}
    monkeypatch.setenv("PGSSLMODE", "disable")  # libpq refuses sslrootcert=system with any mode but verify-full
    monkeypatch.setattr(db_setup.psycopg, "connect", lambda **kw: seen.update(kw) or (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setenv("PGHOST", "h"); monkeypatch.setenv("PGUSER", "u"); monkeypatch.setenv("PGPASSWORD", "p")
    monkeypatch.setenv("CONSOLE_SCHEMA_FILE", str(SCHEMA))
    assert main() == 1
    assert seen["sslmode"] == "disable" and "sslrootcert" not in seen


@pytest.mark.skipif(not Path("/app/console_app").is_dir(), reason="checks the console image")
def test_the_image_points_libpq_at_the_system_roots():
    # psycopg's bundled OpenSSL looks for roots in a directory the image does not have, so `system` would
    # trust nothing without this.
    assert Path(os.environ.get("SSL_CERT_FILE", "")).is_file()
