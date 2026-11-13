"""Every request the broker ever sends to LiteLLM.

Each function is a fixed template: the caller supplies values, never a route, a
role or a raw body. The admin key is read from a file written by console-init.
"""

import os
import re
from pathlib import Path

import httpx

_BASE = os.environ["LITELLM_URL"]
_KEY_FILE = Path(os.environ["LITELLM_ADMIN_KEY_FILE"])
NO_MODELS = ["no-default-models"]  # LiteLLM reads an empty list as "every model"
NO_MCP_SERVER = "no-mcp-servers"   # likewise: names no server, so the team gets none

# provider -> prefix LiteLLM routes on. No custom URL is accepted for these, so a
# key can only ever be sent to the provider's own host.
PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "mistral": "mistral",
    "groq": "groq",
}
# Azure is per-account, so its endpoint must be given; only this shape is accepted.
AZURE_ENDPOINT = re.compile(r"^https://[a-z0-9][a-z0-9-]{1,62}\.openai\.azure\.com/?$")
MOCK_ENABLED = os.environ.get("CONSOLE_ENABLE_MOCK_PROVIDER", "").lower() == "true"
# Dev only: a provider called "lmstudio", for models served by LM Studio on the machine running the stack.
# The address comes from here, never from the form, so it is no way to send a key somewhere else.
LMSTUDIO_URL = os.environ.get("CONSOLE_LMSTUDIO_URL", "").rstrip("/")


class LiteLLMError(Exception):
    def __init__(self, operation: str, status: int):
        super().__init__(f"LiteLLM {operation} failed with HTTP {status}")  # never the body: it can echo a key
        self.operation, self.status = operation, status


def _call(operation: str, method: str, path: str, **kwargs) -> dict | list:
    headers = {"Authorization": f"Bearer {_KEY_FILE.read_text().strip()}"}
    with httpx.Client(base_url=_BASE, timeout=30) as client:
        response = client.request(method, path, headers=headers, **kwargs)
    if response.status_code >= 400:
        raise LiteLLMError(operation, response.status_code)
    return response.json() if response.content else {}  # deleting an MCP server answers with no body


def provider_names() -> list[str]:
    return [*PROVIDERS, "azure", *(["mock"] if MOCK_ENABLED else []), *(["lmstudio"] if LMSTUDIO_URL else [])]


def model_params(provider: str, model: str, api_key: str, api_base: str | None, api_version: str | None) -> dict:
    """LiteLLM parameters for one org model, or ValueError if the provider or endpoint is not allowed."""
    if provider in PROVIDERS:
        if api_base:
            raise ValueError("a custom endpoint is not allowed for this provider")
        return {"model": f"{PROVIDERS[provider]}/{model}", "api_key": api_key}
    if provider == "azure":
        if not api_base or not AZURE_ENDPOINT.match(api_base):
            raise ValueError("the Azure endpoint must look like https://<resource>.openai.azure.com")
        if not api_version or not re.fullmatch(r"[0-9a-z-]{8,30}", api_version):
            raise ValueError("an Azure API version is required")
        return {"model": f"azure/{model}", "api_key": api_key, "api_base": api_base, "api_version": api_version}
    if provider == "mock" and MOCK_ENABLED:
        return {"model": f"openai/{model}", "api_key": api_key, "mock_response": "Hello from a mocked model"}
    if provider == "lmstudio" and LMSTUDIO_URL:
        if api_base:
            raise ValueError("a custom endpoint is not allowed for this provider")
        return {"model": f"openai/{model}", "api_key": api_key, "api_base": LMSTUDIO_URL}  # LM Studio ignores the key
    raise ValueError("unknown provider")


def team_new(team_id: str, alias: str, max_budget: float, mcp_server_id: str | None) -> None:
    """`mcp_server_id` is the one MCP server the team's keys may use: its organization's knowledge."""
    _call("team_new", "POST", "/team/new",
          json={"team_id": team_id, "team_alias": alias, "max_budget": max_budget, "models": NO_MODELS,
                "object_permission": {"mcp_servers": [mcp_server_id or NO_MCP_SERVER]}})


def team_set_knowledge(team_id: str, mcp_server_id: str | None) -> None:
    """Give the team's keys its organization's knowledge, or with None take it away.

    Needed when an org is suspended: LiteLLM does not stop a blocked team's keys from using MCP servers.
    """
    _call("team_set_knowledge", "POST", "/team/update",
          json={"team_id": team_id, "object_permission": {"mcp_servers": [mcp_server_id or NO_MCP_SERVER]}})


def mcp_server_name(slug: str) -> str:
    """Also the prefix of the tool names clients see. LiteLLM allows no hyphen in it; a short name has no underscore."""
    return "knowledge_" + slug.replace("-", "_")


def mcp_server_delete(server_id: str) -> None:
    try:
        _call("mcp_server_delete", "DELETE", f"/v1/mcp/server/{server_id}")
    except LiteLLMError as exc:
        if exc.status != 404:  # already gone
            raise


def mcp_server_new(slug: str, url: str, token_url: str, client_id: str, client_secret: str) -> str:
    """Register an organization's knowledge as an MCP server and return its id.

    LiteLLM fetches a token as the organization's Keycloak client (client credentials) for every call it
    forwards. No key can use the server until a team is given it (team_new). A server left behind under
    the same name by an interrupted attempt is replaced.
    """
    name = mcp_server_name(slug)
    for server in _call("mcp_server_list", "GET", "/v1/mcp/server"):
        if server.get("server_name") == name or server.get("alias") == name:
            mcp_server_delete(server["server_id"])
    return _call("mcp_server_new", "POST", "/v1/mcp/server", json={
        "server_name": name, "alias": name, "transport": "http", "url": url,
        "description": f"Shared knowledge of the organization {slug}",
        "auth_type": "oauth2", "oauth2_flow": "client_credentials", "token_url": token_url,
        "credentials": {"client_id": client_id, "client_secret": client_secret},
        "allow_all_keys": False})["server_id"]


def team_set_models(team_id: str, public_names: list[str]) -> None:
    _call("team_set_models", "POST", "/team/update", json={"team_id": team_id, "models": public_names or NO_MODELS})


def team_set_budget(team_id: str, max_budget: float) -> None:
    _call("team_set_budget", "POST", "/team/update", json={"team_id": team_id, "max_budget": max_budget})


def team_block(team_id: str) -> None:
    _call("team_block", "POST", "/team/block", json={"team_id": team_id})


def team_unblock(team_id: str) -> None:
    _call("team_unblock", "POST", "/team/unblock", json={"team_id": team_id})


def model_new(public_name: str, params: dict) -> str:
    return _call("model_new", "POST", "/model/new",
                 json={"model_name": public_name, "litellm_params": params})["model_id"]


def model_delete(model_id: str, missing_ok: bool = False) -> None:
    try:
        _call("model_delete", "POST", "/model/delete", json={"id": model_id})
    except LiteLLMError as exc:
        if not (missing_ok and exc.status in (400, 404)):
            raise


def user_ensure(participant_id: str) -> None:
    """Give the participant a LiteLLM user record, so their keys and spend show under a user in the LiteLLM UI.

    Stock LiteLLM refuses every SSO login once it holds more than five users, which is why this stack
    runs the sso-unlimited-users fork.
    """
    try:
        _call("user_new", "POST", "/user/new",
              json={"user_id": participant_id, "user_role": "internal_user_viewer", "auto_create_key": False})
    except LiteLLMError as exc:
        if exc.status not in (400, 409):  # already exists
            raise


def key_generate(team_id: str, participant_id: str, alias: str, max_budget: float, days: int,
                 spent: float = 0.0) -> str:
    """`spent` starts the key part-way through its budget; a rotated key carries on from the one it replaces."""
    return _call("key_generate", "POST", "/key/generate",
                 json={"team_id": team_id, "user_id": participant_id, "key_alias": alias,
                       "max_budget": max_budget, "duration": f"{days}d", "spend": spent})["key"]


def key_delete(aliases: list[str]) -> None:
    if not aliases:
        return
    try:
        _call("key_delete", "POST", "/key/delete", json={"key_aliases": aliases})
    except LiteLLMError as exc:
        if exc.status != 404:  # 404: already gone, e.g. when an interrupted removal is run again
            raise


def team_keys(team_id: str) -> dict[str, dict]:
    """What LiteLLM knows about each of a team's keys, by alias. Never the key: LiteLLM keeps only a hash."""
    info = _call("team_keys", "GET", "/team/info", params={"team_id": team_id})
    return {key["key_alias"]: {"hint": key.get("key_name"), "spend": float(key.get("spend") or 0),
                               "expires": key.get("expires"), "last_used": key.get("last_active")}
            for key in info.get("keys", []) if key.get("key_alias")}


def team_usage(team_id: str) -> dict[str, dict]:
    """Per-participant totals for one team. Prompt and response content is dropped here."""
    rows = _call("team_usage", "GET", "/spend/logs", params={"team_id": team_id})
    totals: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        entry = totals.setdefault(row.get("user") or "", {"requests": 0, "failed": 0, "spend": 0.0, "tokens": 0})
        entry["requests"] += 1
        entry["failed"] += 1 if (row.get("metadata") or {}).get("status") == "failure" else 0
        entry["spend"] += float(row.get("spend") or 0)
        entry["tokens"] += int(row.get("total_tokens") or 0)
    return totals
