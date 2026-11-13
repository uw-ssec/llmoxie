"""Test helpers: a tiny browser, Keycloak sign-in, Mailpit, and direct broker calls."""

import base64
import hashlib
import json
import os
import re
import secrets
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row

CONSOLE = os.environ["CONSOLE_URL"]
GATEWAY = os.environ["GATEWAY_URL"]
KEYCLOAK = os.environ["KEYCLOAK_URL"]
BROKER = os.environ["BROKER_URL"]
MAILPIT = os.environ["MAILPIT_URL"]
CALLER_SECRET = os.environ["CONSOLE_BROKER_CALLER_SECRET"]
CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
CLIENT_SECRET = os.environ["OIDC_CLIENT_SECRET"]
REALM = f"{KEYCLOAK}/realms/litellm"


class Browser:
    """Follows redirects and keeps cookies per host, like a browser on *.localhost would.

    Cookies are kept by hand because they are marked Secure and this stack is plain http;
    real browsers make an exception for *.localhost, http clients do not.
    """

    def __init__(self):
        self.cookies: dict[str, dict[str, str]] = {}
        self.http = httpx.Client(follow_redirects=False, timeout=60)
        self.set_cookie_headers: list[str] = []

    def request(self, method, url, *, data=None, files=None, headers=None, follow=True):
        for _ in range(12):
            host = urlsplit(url).netloc
            sent = dict(headers or {})
            if self.cookies.get(host):
                sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies[host].items())
            if method == "POST" and url.startswith(CONSOLE):
                sent.setdefault("Origin", CONSOLE)
            response = self.http.request(method, url, data=data, files=files, headers=sent)
            for header in response.headers.get_list("set-cookie"):
                self.set_cookie_headers.append(header)
                name, _, rest = header.partition("=")
                value = rest.split(";")[0]
                jar = self.cookies.setdefault(host, {})
                if not value or "max-age=0" in header.lower():
                    jar.pop(name, None)
                else:
                    jar[name] = value
            if follow and response.status_code in (301, 302, 303, 307):
                url = urljoin(url, response.headers["location"])
                if response.status_code != 307:
                    method, data, files = "GET", None, None
                continue
            return response
        raise AssertionError("too many redirects")

    def get(self, path, **kwargs):
        return self.request("GET", path if path.startswith("http") else CONSOLE + path, **kwargs)

    def post(self, path, data=None, **kwargs):
        """Post a console form, adding the page's CSRF token the way the real form would."""
        data = dict(data or {})
        if "csrf" not in data and getattr(self, "csrf", None):
            data["csrf"] = self.csrf
        return self.request("POST", path if path.startswith("http") else CONSOLE + path, data=data, **kwargs)

    def remember_csrf(self, response):
        found = re.search(r'name="csrf" value="([^"]+)"', response.text)
        if found:
            self.csrf = found.group(1)
        return response

    def page(self, path):
        return self.remember_csrf(self.get(path))


def _submit_keycloak_login(browser: Browser, response, email, password, follow=True):
    action = re.search(r'id="kc-form-login"[^>]*action="([^"]+)"', response.text)
    assert action, f"no Keycloak login form: {response.status_code} {response.text[:300]}"
    return browser.request("POST", action.group(1).replace("&amp;", "&"),
                           data={"username": email, "password": password}, follow=follow)


def sign_in(email: str, password: str, start=None) -> Browser:
    """A browser signed in to the console. `start` is (path, data) for a POST that begins sign-in, e.g. an invite."""
    browser = Browser()
    path, data = start or ("/login", {})
    response = browser.post(path, data)
    response = _submit_keycloak_login(browser, response, email, password)
    assert response.status_code == 200 and "Signed in" in response.text, response.text[:300]
    target = re.search(r'http-equiv="refresh" content="0; url=([^"]+)"', response.text).group(1)
    browser.landed = browser.page(target)
    browser.landed_path = target
    return browser


def access_token(email: str, password: str, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET,
                 redirect: str = f"{CONSOLE}/auth/callback") -> str:
    """A user's access token as a client gets it when that user signs in through it.
    By default the console's own client, i.e. the token console-web forwards to the broker."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    browser = Browser()
    response = browser.request("GET", f"{REALM}/protocol/openid-connect/auth?" + urlencode({
        "client_id": client_id, "response_type": "code", "scope": "openid email profile", "redirect_uri": redirect,
        "state": "s", "code_challenge": challenge, "code_challenge_method": "S256"}))
    response = _submit_keycloak_login(browser, response, email, password, follow=False)
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    token = httpx.post(f"{REALM}/protocol/openid-connect/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "code_verifier": verifier,
        "client_id": client_id, "client_secret": client_secret})
    token.raise_for_status()
    return token.json()["access_token"]


def broker(method: str, path: str, token: str | None, json=None, caller: str | None = CALLER_SECRET):
    headers = {}
    if caller:
        headers["X-Console-Caller"] = caller
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.request(method, BROKER + path, json=json, headers=headers, timeout=60)


def _keycloak_admin() -> dict:
    admin = httpx.post(f"{KEYCLOAK}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"})
    admin.raise_for_status()
    return {"Authorization": f"Bearer {admin.json()['access_token']}"}


SERVICE_REDIRECT = "http://hub.example/oauth_callback"


def create_service_client(client_id: str, secret: str, audience: bool = True) -> None:
    """What an operator sets up in Keycloak for a service such as a JupyterHub: a confidential client its
    users sign in through, with a service account, whose tokens are addressed to the console broker."""
    mappers = [{"name": "console-broker-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                "config": {"included.custom.audience": "console-broker", "access.token.claim": "true",
                           "id.token.claim": "false"}}] if audience else []
    created = httpx.post(f"{KEYCLOAK}/admin/realms/litellm/clients", headers=_keycloak_admin(), json={
        "clientId": client_id, "enabled": True, "protocol": "openid-connect", "publicClient": False,
        "clientAuthenticatorType": "client-secret", "secret": secret, "standardFlowEnabled": True,
        "serviceAccountsEnabled": True, "directAccessGrantsEnabled": False, "redirectUris": [SERVICE_REDIRECT],
        "protocolMappers": mappers})
    assert created.status_code in (201, 409), created.text


def service_token(client_id: str, secret: str) -> str:
    """The service's own token (client credentials)."""
    token = httpx.post(f"{REALM}/protocol/openid-connect/token", data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": secret})
    token.raise_for_status()
    return token.json()["access_token"]


def api(operation: str, user_token: str | None, service: str | None, **kwargs):
    """Call the console's API for connected services."""
    headers = dict(kwargs.pop("headers", {}))
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    if service:
        headers["X-Service-Authorization"] = f"Bearer {service}"
    return httpx.post(f"{CONSOLE}/api/v1/{operation}", headers=headers, timeout=60, **kwargs)


def create_user(email: str, password: str) -> None:
    """A Keycloak account with a verified email, as if the person had signed up and clicked the email link."""
    created = httpx.post(f"{KEYCLOAK}/admin/realms/litellm/users",
                         headers=_keycloak_admin(),
                         json={"username": email, "email": email, "firstName": "Test", "lastName": "User",
                               "enabled": True, "emailVerified": True,
                               "credentials": [{"type": "password", "value": password, "temporary": False}]})
    assert created.status_code in (201, 409), created.text


def invite_token(email: str) -> str:
    """The token from the newest invitation email sent to `email`."""
    listing = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{email}"}).json()["messages"]
    assert listing, f"no email for {email}"
    text = httpx.get(f"{MAILPIT}/api/v1/message/{listing[0]['ID']}").json()["Text"]
    return re.search(rf"{re.escape(CONSOLE)}/invite/([A-Za-z0-9_-]+)", text).group(1)


def sql(url_env: str, query: str, params=()):
    with psycopg.connect(os.environ[url_env], row_factory=dict_row, autocommit=True) as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else []


def chat(key: str, model: str, content: str = "hello"):
    return httpx.post(f"{GATEWAY}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "messages": [{"role": "user", "content": content}]}, timeout=60)


def mcp(key: str | None, method: str, params: dict | None = None, url: str = f"{GATEWAY}/mcp", headers=None):
    """One MCP request (streamable HTTP) with a LiteLLM key. Returns (status, the JSON-RPC reply or None)."""
    sent = {"Accept": "application/json, text/event-stream", **(headers or {})}
    if key:
        sent["Authorization"] = f"Bearer {key}"
    response = httpx.post(url, headers=sent, timeout=60,
                          json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    reply = None
    for line in response.text.splitlines():  # the reply comes as one server-sent event
        if line.startswith("data:"):
            reply = json.loads(line[5:])
    if reply is None and response.headers.get("content-type", "").startswith("application/json"):
        reply = response.json()
    return response.status_code, reply


def mcp_tool(key: str, name: str, **arguments) -> tuple[bool, str]:
    """Call one tool. Returns (it worked, the text it answered)."""
    status, reply = mcp(key, "tools/call", {"name": name, "arguments": arguments})
    assert status == 200 and reply and "result" in reply, (status, reply)
    result = reply["result"]
    return not result.get("isError"), " ".join(part.get("text", "") for part in result.get("content", []))
