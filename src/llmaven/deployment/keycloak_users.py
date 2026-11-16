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
    if response.status_code == 401:
        return KeycloakUsersError(
            f"{what} failed with HTTP 401: the admin token was refused, even after "
            "a refresh. Check the keycloak-admin-password secret."
        )
    return KeycloakUsersError(f"{what} failed with HTTP {response.status_code}")


def plan_users(client: httpx.Client, realm: str, emails: list[str]) -> UserPlan:
    plan = UserPlan(create=[], existing=[])
    for email in emails:
        try:
            r = client.get(
                f"/admin/realms/{realm}/users",
                params={"email": email, "exact": "true"},
            )
        except httpx.HTTPError as e:
            raise KeycloakUsersError(
                f"Looking up {email} failed: {type(e).__name__}. Nothing was created."
            )
        if r.status_code != 200:
            raise _fail(r, f"Looking up {email}")
        (plan.existing if r.json() else plan.create).append(email)
    return plan


def create_users(
    client: httpx.Client,
    realm: str,
    emails: list[str],
    out: Path,
    existed: list[str] | None = None,
) -> int:
    """Create each user with a temporary password written to ``out``.

    ``out`` is created 0600 and refused if it exists, before any user is created.
    Returns the number created. A 409 is appended to ``existed`` (if given). An
    ``out`` that would hold no passwords is removed. On failure the error says
    how many were created (their passwords stay in ``out``) and what was not
    attempted.
    """
    try:
        fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise KeycloakUsersError(f"{out} already exists; refusing to overwrite it")
    except OSError as e:
        raise KeycloakUsersError(f"Cannot create {out}: {e.strerror}")
    if existed is None:
        existed = []
    created = 0
    failure: str | None = None
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "temporary_password"])
        f.flush()
        for i, email in enumerate(emails):
            password = secrets.token_urlsafe(18)
            try:
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
            except KeycloakUsersError as e:
                failure = f"failed at {email}: {e}"
            except httpx.HTTPError as e:
                failure = (
                    f"failed at {email}: {type(e).__name__}; that account's state "
                    "is unknown (no password was recorded for it). Check it in the "
                    "Keycloak admin console, or rerun with --dry-run to see whether "
                    "it exists, and reset its password there if it does"
                )
            else:
                if r.status_code == 409:
                    existed.append(email)
                    continue
                if r.status_code != 201:
                    failure = f"failed at {email}: {_fail(r, 'Creating').args[0]}"
                else:
                    writer.writerow([email, password])
                    f.flush()
                    created += 1
                    continue
            rest = ", ".join(emails[i + 1 :]) or "none"
            kept = f"passwords in {out}" if created else "no password file kept"
            failure = f"{created} created ({kept}); {failure}; not attempted: {rest}"
            if existed:
                failure += f"; already existed: {', '.join(existed)}"
            break
    if created == 0:
        out.unlink(missing_ok=True)
    if failure:
        raise KeycloakUsersError(failure)
    return created


class _AdminAuth(httpx.Auth):
    """Bearer token fetched on first use and once more after a 401.

    Keycloak's admin tokens last about a minute, so fetching one up front would
    expire while an operator reads the confirmation prompt.
    """

    def __init__(self, fetch):
        self._fetch = fetch
        self._token: str | None = None

    def auth_flow(self, request):
        if self._token is None:
            self._token = self._fetch()
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == 401:
            self._token = self._fetch()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request


def open_admin_client(
    config_path: Path, transport: httpx.BaseTransport | None = None
) -> tuple[httpx.Client, str]:
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

    def fetch_token() -> str:
        try:
            r = _post_token(base, admin_password, transport)
        except httpx.HTTPError as e:
            raise KeycloakUsersError(f"Could not reach {base}: {type(e).__name__}")
        if r.status_code != 200:
            raise _fail(r, "Getting the admin token")
        try:
            return r.json()["access_token"]
        except (ValueError, KeyError, TypeError):
            raise KeycloakUsersError(
                f"{base} did not return an access token (HTTP 200 but not a token "
                "response); check keycloak.hostname and the edge routing"
            )

    client = httpx.Client(
        base_url=base, auth=_AdminAuth(fetch_token), timeout=30, transport=transport
    )
    return client, config.keycloak.realm.name


def _post_token(
    base: str, password: str, transport: httpx.BaseTransport | None
) -> httpx.Response:
    with httpx.Client(transport=transport, timeout=30) as c:
        return c.post(
            f"{base}/realms/master/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": "admin",
                "password": password,
            },
        )
