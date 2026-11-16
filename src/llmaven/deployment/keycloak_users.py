"""Create invitee Keycloak accounts from a CSV (``llmaven infra keycloak-users``).

The realm has no self sign-up and no mail, and a console invitation needs a
verified email, so an operator creates each invitee's account first. Passwords
exist only in the ``--out`` file; nothing here prints or raises with one.
"""

import csv
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx

ADMIN_HINT = (
    "The Keycloak edge refused the request (HTTP 403). Only addresses in "
    "keycloak.admin_allowed_ips can reach /admin; run this from one of them."
)


class KeycloakUsersError(Exception):
    """Raised when the CSV, the output file or the Keycloak admin API fails."""


@dataclass
class UserPlan:
    create: list[str]
    existing: list[str]


def read_emails(csv_path: Path) -> list[str]:
    """Distinct lower-cased addresses of the CSV's ``email`` column, in order.

    Raises ValueError if the file has no ``email`` column.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        names = [h.strip().lower() for h in header]
        if "email" not in names:
            raise ValueError(
                f"{csv_path} has no 'email' column (found: "
                f"{', '.join(h.strip() for h in header) or 'no header'})"
            )
        idx = names.index("email")
        seen: dict[str, None] = {}
        for row in reader:
            if idx < len(row) and (e := row[idx].strip().lower()):
                seen.setdefault(e)
    return list(seen)


def _fail(response: httpx.Response, what: str) -> KeycloakUsersError:
    if response.status_code == 403:
        return KeycloakUsersError(ADMIN_HINT)
    return KeycloakUsersError(f"{what} failed with HTTP {response.status_code}")


def plan_users(client: httpx.Client, realm: str, emails: list[str]) -> UserPlan:
    plan = UserPlan(create=[], existing=[])
    for email in emails:
        r = client.get(
            f"/admin/realms/{realm}/users", params={"email": email, "exact": "true"}
        )
        if r.status_code != 200:
            raise _fail(r, f"Looking up {email}")
        (plan.existing if r.json() else plan.create).append(email)
    return plan


def create_users(
    client: httpx.Client, realm: str, emails: list[str], out: Path
) -> int:
    """Create each user with a temporary password written to ``out``.

    ``out`` is created 0600 and refused if it exists, before any user is created.
    Returns the number created (a 409 counts as already existing).
    """
    try:
        fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise KeycloakUsersError(f"{out} already exists; refusing to overwrite it")
    except OSError as e:
        raise KeycloakUsersError(f"Cannot create {out}: {e.strerror}")
    created = 0
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "temporary_password"])
        f.flush()
        for email in emails:
            password = secrets.token_urlsafe(18)
            r = client.post(
                f"/admin/realms/{realm}/users",
                json={
                    "username": email,
                    "email": email,
                    "emailVerified": True,
                    "enabled": True,
                    "requiredActions": ["UPDATE_PASSWORD"],
                    "credentials": [
                        {"type": "password", "value": password, "temporary": True}
                    ],
                },
            )
            if r.status_code == 409:
                continue
            if r.status_code != 201:
                raise _fail(r, f"Creating {email}")
            writer.writerow([email, password])
            f.flush()
            created += 1
    return created


def open_admin_client(config_path: Path) -> tuple[httpx.Client, str]:
    """An admin-authenticated client for the configured Keycloak, and its realm."""
    from ..infrastructure.config.loader import load_config
    from .deploy import DeploymentError, _run_az_command, get_stack

    config = load_config(config_path)
    if not config.keycloak.enabled or not config.keycloak.hostname:
        raise KeycloakUsersError("keycloak.enabled and keycloak.hostname must be set")
    if not config.project.enable_passphrase:
        os.environ.setdefault("PULUMI_CONFIG_PASSPHRASE", "")
    elif not os.environ.get("PULUMI_CONFIG_PASSPHRASE"):
        raise KeycloakUsersError(
            "Passphrase protection is enabled in config but "
            "PULUMI_CONFIG_PASSPHRASE is not set."
        )
    try:
        stack = get_stack(
            stack_name=f"{config.project.name}-{config.project.environment}",
            project_name="llmaven",
            config_path=config_path,
        )
        vault = stack.outputs().get("key_vault_name")
        if vault is None:
            raise KeycloakUsersError("The stack has no key_vault_name output.")
        result = _run_az_command(
            [
                "keyvault",
                "secret",
                "show",
                "--vault-name",
                str(vault.value),
                "--name",
                "keycloak-admin-password",
                "--query",
                "value",
                "-o",
                "tsv",
            ],
            subscription_id=config.azure.subscription_id,
        )
    except DeploymentError as e:
        raise KeycloakUsersError(str(e))
    admin_password = result.stdout.strip()
    base = f"https://{config.keycloak.hostname}"
    try:
        r = httpx.post(
            f"{base}/realms/master/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": "admin",
                "password": admin_password,
            },
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise KeycloakUsersError(f"Could not reach {base}: {type(e).__name__}")
    if r.status_code != 200:
        raise _fail(r, "Getting the admin token")
    token = r.json()["access_token"]
    client = httpx.Client(
        base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    return client, config.keycloak.realm.name
