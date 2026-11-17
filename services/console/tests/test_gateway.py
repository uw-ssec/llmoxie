"""The public gateway forwards LiteLLM's AI paths and nothing else."""

import http.client
import os
from urllib.parse import urlsplit

import httpx
import pytest

GATEWAY = urlsplit(os.environ["GATEWAY_URL"])
LITELLM = os.environ["LITELLM_URL"]

PUBLIC = ["/v1/chat/completions", "/chat/completions", "/v1/completions", "/completions", "/v1/embeddings",
          "/embeddings", "/v1/messages", "/v1/messages/count_tokens", "/v1/responses", "/responses",
          "/openai/v1/responses", "/v1/rerank", "/v2/rerank", "/rerank", "/v1/models", "/models"]

REFUSED = [
    "/", "/ui", "/ui/", "/sso/key/generate", "/login", "/fallback/login",
    "/key/generate", "/key/info", "/key/delete", "/team/new", "/team/info", "/team/block", "/model/new",
    "/model/info", "/v1/model/info", "/user/new", "/user/list", "/spend/logs", "/global/spend/logs",
    "/config/update", "/health", "/health/readiness", "/metrics", "/routes", "/openapi.json", "/docs",
    # MCP: only /mcp itself is public. Not LiteLLM's other MCP routes, nor the OAuth ones it serves for MCP.
    "/mcp/sse", "/mcp/enabled", "/mcp/proxy", "/mcp/knowledge_x", "/knowledge_x/mcp", "/mcp-rest/tools/list",
    "/mcp-rest/tools/call", "/v1/mcp/server", "/v1/mcp/server/register", "/toolset/x/mcp", "/authorize", "/token",
    "/register", "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration", "/MCP", "/mcp%2Fsse", "/mcp/../key/generate",
    # aliases, case and encoding variants of real paths
    "/V1/chat/completions", "/v1/Chat/Completions", "/v1/chat/completions/",
    "/v1/chat/completions/../../key/generate", "/v1/chat/completions%2F..%2F..%2Fkey%2Fgenerate",
    "/v1/chat%2Fcompletions", "/%6Bey/generate", "/v1/chat/completions;x", "/v1/models/../key/info",
    "//key/generate", "/v1/chat/completions%00", "/litellm/key/generate",
]


def raw(method: str, path: str) -> int:
    """Send `path` exactly as written; ordinary clients tidy paths up before sending them."""
    conn = http.client.HTTPConnection(GATEWAY.hostname, GATEWAY.port, timeout=30)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", GATEWAY.netloc)
    conn.putheader("Content-Length", "0")
    conn.endheaders()
    status = conn.getresponse().status
    conn.close()
    return status


@pytest.mark.parametrize("path", PUBLIC)
def test_ai_path_reaches_litellm(path):
    # No key is sent, so LiteLLM itself answers 401. A 404 would mean the gateway refused it.
    assert raw("POST" if "models" not in path else "GET", path) == 401


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mcp_reaches_litellm(path):
    # As above: LiteLLM answers 401 without a key.
    assert raw("POST", path) == 401


@pytest.mark.parametrize("path", ["/health/liveliness", "/health/liveness"])
def test_liveness_is_public(path):
    assert raw("GET", path) == 200


@pytest.mark.parametrize("path", REFUSED)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_everything_else_is_refused(method, path):
    assert raw(method, path) in (400, 404)


def test_tidied_spellings_only_ever_mean_the_same_ai_path():
    # Traefik tidies a path before matching it: `//` becomes `/`, and letters written as %xx are decoded.
    # So these are /v1/chat/completions and nothing more (LiteLLM answers 401 without a key),
    # and no management path can be reached by spelling it this way.
    assert raw("POST", "/v1//chat/completions") == 401
    assert raw("POST", "/%76%31/chat/completions") == 401
    assert raw("POST", "/v1/chat/completions//../key/generate") in (400, 404)
    assert raw("POST", "//v1/chat/completions/..//..//key/generate") in (400, 404)
    assert raw("POST", "/%76%31/chat/completions/%2E%2E/%2E%2E/key/generate") in (400, 404)


def test_management_route_refused_even_with_the_master_key():
    response = httpx.post(f"{GATEWAY.geturl()}/key/generate", json={},
                          headers={"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"})
    assert response.status_code == 404


def test_master_key_cannot_log_in_to_the_litellm_ui():
    # Checked from inside the network: LiteLLM's UI login accepts Keycloak only, even for the master key.
    login = httpx.post(f"{LITELLM}/v2/login", json={"username": "admin", "password": os.environ["LITELLM_MASTER_KEY"]})
    assert login.status_code >= 400
