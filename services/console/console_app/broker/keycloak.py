"""Every request the broker ever sends to Keycloak's admin API.

One purpose: each organization gets a client of its own (okf-org-<short name>) that LiteLLM signs in
with when it calls the knowledge hub for that organization. The client's tokens are addressed to the
hub and carry the organization's short name, and the hub lets a token touch only the bundle it names
(the `grants` in the hub's OAuth settings). No person ever signs in through these clients.

The broker's own client, console-provisioner, may manage clients in this realm and nothing else.
As in litellm.py, each function is a fixed template.
"""

import os
import secrets

import httpx

_ADMIN = os.environ["KEYCLOAK_ADMIN_URL"]          # .../admin/realms/<realm>
TOKEN_URL = os.environ["KEYCLOAK_TOKEN_URL"]       # where LiteLLM fetches each organization's token, too
_CLIENT_ID = os.environ["KEYCLOAK_PROVISIONER_CLIENT_ID"]
_CLIENT_SECRET = os.environ["KEYCLOAK_PROVISIONER_CLIENT_SECRET"]
HUB_URL = os.environ["KNOWLEDGE_HUB_URL"].rstrip("/")  # also the audience the hub expects
ORG_CLAIM = "okf_org"                              # the hub's `actor_claim` must name the same claim


class KeycloakError(Exception):
    def __init__(self, operation: str, status: int):
        super().__init__(f"Keycloak {operation} failed with HTTP {status}")  # never the body
        self.operation, self.status = operation, status


def client_id(slug: str) -> str:
    return f"okf-org-{slug}"


def bundle(slug: str) -> str:
    """The organization's bundle in the hub. The hub writes a token's organization as oidc:<short name>."""
    return f"orgs/oidc-{slug}"


def _call(operation: str, method: str, path: str, ok: tuple[int, ...] = (), **kwargs) -> httpx.Response:
    with httpx.Client(timeout=30) as http:
        token = http.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": _CLIENT_ID,
                                           "client_secret": _CLIENT_SECRET})
        if token.status_code != 200:
            raise KeycloakError("sign-in", token.status_code)
        response = http.request(method, _ADMIN + path, **kwargs,
                                headers={"Authorization": f"Bearer {token.json()['access_token']}"})
    if response.status_code >= 400 and response.status_code not in ok:
        raise KeycloakError(operation, response.status_code)
    return response


def org_client_delete(slug: str) -> None:
    """Remove the organization's client, which ends LiteLLM's access to its bundle. Fine if it is already gone."""
    found = _call("client_find", "GET", "/clients", params={"clientId": client_id(slug)}).json()
    for client in found:
        _call("client_delete", "DELETE", f"/clients/{client['id']}", ok=(404,))


def org_client_create(slug: str) -> str:
    """Create the organization's client and return its secret, which is kept nowhere but Keycloak and LiteLLM.

    A client left behind by an interrupted attempt is replaced.
    """
    org_client_delete(slug)
    secret = secrets.token_urlsafe(32)
    _call("client_create", "POST", "/clients", json={
        "clientId": client_id(slug), "name": f"Knowledge hub access for {slug}", "enabled": True,
        "protocol": "openid-connect", "publicClient": False, "clientAuthenticatorType": "client-secret",
        "secret": secret, "serviceAccountsEnabled": True, "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "protocolMappers": [
            {"name": "knowledge-hub-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
             "config": {"included.custom.audience": HUB_URL, "access.token.claim": "true", "id.token.claim": "false"}},
            {"name": "organization", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper",
             "config": {"claim.name": ORG_CLAIM, "claim.value": slug, "jsonType.label": "String",
                        "access.token.claim": "true", "id.token.claim": "false"}},
        ]})
    return secret
