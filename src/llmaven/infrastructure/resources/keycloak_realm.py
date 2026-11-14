"""The Keycloak realm document keycloak-config-cli imports on every deploy.

Pure rendering: no Pulumi imports. Client secrets are never written here; each
is a keycloak-config-cli ``$(env:NAME)`` placeholder (variable substitution is
on in the realm job) that the job resolves from its environment.
"""

import copy
import json
from typing import Any

from llmaven.infrastructure.config.schema import LLMavenConfig

# Client id -> the realm job's env var holding that client's secret.
CLIENT_SECRET_ENV: dict[str, str] = {
    "mlflow-gate": "KC_CLIENT_SECRET_MLFLOW_GATE",
    "litellm-gate": "KC_CLIENT_SECRET_LITELLM_GATE",
    "litellm": "KC_CLIENT_SECRET_LITELLM",
    "llmaven-cli": "KC_CLIENT_SECRET_LLMAVEN_CLI",
}

# Where the access token carries the user's realm roles.
ROLES_CLAIM = "realm_access.roles"

# List key per path of dict keys; any other list is replaced.
_LIST_KEYS: dict[tuple[str, ...], str] = {
    ("clients",): "clientId",
    ("roles", "realm"): "name",
    ("identityProviders",): "alias",
    ("users",): "username",
    ("groups",): "name",
    ("clientScopes",): "name",
    ("identityProviderMappers",): "name",
}


def _list_key(path: tuple[str, ...]) -> str | None:
    if len(path) == 3 and path[:2] == ("roles", "client"):
        return "name"
    return _LIST_KEYS.get(path)


def _merge(base: Any, over: Any, path: tuple[str, ...]) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            if key not in base:
                out[key] = value
                continue
            current = base[key]
            if isinstance(current, (dict, list)) and type(value) is not type(current):
                where = ".".join(("realm", "overrides", *path, key))
                raise ValueError(
                    f"{where} must be a {type(current).__name__}, "
                    f"not {type(value).__name__}"
                )
            out[key] = _merge(current, value, (*path, key))
        return out
    key = _list_key(path)
    if key and isinstance(base, list) and isinstance(over, list):
        out = list(base)
        for item in over:
            ident = item.get(key) if isinstance(item, dict) else None
            idx = next(
                (
                    i
                    for i, cur in enumerate(out)
                    if ident is not None
                    and isinstance(cur, dict)
                    and cur.get(key) == ident
                ),
                None,
            )
            if idx is None:
                out.append(item)
            else:
                out[idx] = _merge(out[idx], item, path)
        return out
    return over


def merge_overrides(base: dict, overrides: dict) -> dict:
    """Deep-merge ``overrides`` over ``base``, returning a new dict.

    Dicts merge recursively. Lists in the realm's keyed collections merge by
    key (a match is deep-merged, a new item appended); other lists replace.
    """
    return _merge(copy.deepcopy(base), copy.deepcopy(overrides), ())


def _secret(client_id: str) -> str:
    return f"$(env:{CLIENT_SECRET_ENV[client_id]})"


def _realm_role_mapper() -> dict:
    return {
        "name": "realm roles",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-realm-role-mapper",
        "config": {
            "claim.name": ROLES_CLAIM,
            "multivalued": "true",
            "jsonType.label": "String",
            "access.token.claim": "true",
            "id.token.claim": "true",
            "userinfo.token.claim": "true",
        },
    }


def _audience_mapper(audience: str) -> dict:
    return {
        "name": f"{audience} audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": audience,
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    }


def _web_client(
    client_id: str, redirect_uri: str, name: str, pkce: bool = True
) -> dict:
    client = {
        "clientId": client_id,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "secret": _secret(client_id),
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": [redirect_uri],
        "attributes": {},
        "protocolMappers": [_realm_role_mapper()],
    }
    if pkce:
        client["attributes"]["pkce.code.challenge.method"] = "S256"
    return client


def build_realm_document(config: LLMavenConfig) -> dict:
    """The realm for ``config``: basics plus the roles and clients of each
    enabled login, with ``keycloak.realm.overrides`` merged over it."""
    realm = config.keycloak.realm
    doc: dict[str, Any] = {
        "realm": realm.name,
        "enabled": True,
        "displayName": realm.display_name,
        "registrationAllowed": False,
        "verifyEmail": True,
        "bruteForceProtected": True,
    }
    roles: list[dict] = []
    clients: list[dict] = []
    users: list[dict] = []

    mlflow, litellm = config.mlflow, config.litellm
    if mlflow.login.enabled:
        roles.append({"name": mlflow.login.role, "description": "Use MLflow"})
        clients.append(
            _web_client(
                "mlflow-gate",
                f"https://{mlflow.hostname}/oauth2/callback",
                "MLflow sign-in",
            )
        )
        cli = {
            "clientId": "llmaven-cli",
            "name": "LLMoxie CLI",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "secret": _secret("llmaven-cli"),
            "standardFlowEnabled": False,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "protocolMappers": [_realm_role_mapper(), _audience_mapper("mlflow-gate")],
        }
        clients.append(cli)
        users.append(
            {
                "username": "service-account-llmaven-cli",
                "enabled": True,
                "serviceAccountClientId": "llmaven-cli",
                "realmRoles": [mlflow.login.role],
            }
        )
    if litellm.login.enabled:
        roles.append({"name": litellm.login.role, "description": "Administer LiteLLM"})
        clients.append(
            _web_client(
                "litellm-gate",
                f"https://{litellm.hostname}/oauth2/callback",
                "LiteLLM sign-in",
            )
        )
        clients.append(
            _web_client(
                "litellm",
                f"https://{litellm.hostname}/sso/callback",
                "LiteLLM SSO",
                # LiteLLM's generic SSO sends no PKCE; it is a confidential client.
                pkce=False,
            )
        )
    roles = list({r["name"]: r for r in reversed(roles)}.values())[::-1]
    if roles:
        doc["roles"] = {"realm": roles}
    if clients:
        doc["clients"] = clients
    if users:
        doc["users"] = users
    return merge_overrides(doc, realm.overrides)


def render_realm_document(config: LLMavenConfig) -> str:
    """The realm document as deterministic JSON."""
    return json.dumps(build_realm_document(config), sort_keys=True, indent=2)
