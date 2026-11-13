"""LiteLLM's own UI and management API, on their own hostname, for SSEC admins only.

Runs after test_console.py on purpose: by then the console has issued keys to several
participants, and the admin's Keycloak sign-in to LiteLLM must still work.
"""

import base64
import json
import os
import re

import httpx

from .helpers import Browser, _submit_keycloak_login, create_user

ADMIN_URL = os.environ["LITELLM_ADMIN_URL"]
MASTER = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}


def through_keycloak(browser: Browser, url: str, username: str, password: str):
    response = browser.request("GET", url)
    if 'id="kc-form-login"' in response.text:
        response = _submit_keycloak_login(browser, response, username, password)
    return response


def test_nothing_on_the_admin_hostname_is_open():
    for path in ("/ui/", "/key/generate", "/team/list", "/v1/chat/completions", "/health/liveliness", "/"):
        for headers in ({}, MASTER):  # not even the master key gets past the gate without a Keycloak session
            response = httpx.request("POST" if "generate" in path else "GET", ADMIN_URL + path, headers=headers)
            assert response.status_code == 302, (path, response.status_code)
            assert response.headers["location"].startswith(f"{os.environ['KEYCLOAK_URL']}/realms/litellm/")


def test_admin_reaches_the_litellm_ui_as_proxy_admin():
    browser = Browser()
    # LiteLLM's sign-in entry point: the gate asks Keycloak first, then LiteLLM does, with no second prompt.
    landed = through_keycloak(browser, f"{ADMIN_URL}/sso/key/generate", "alice", "alice123")
    assert landed.status_code == 200 and "<html" in landed.text.lower(), (landed.status_code, landed.text[:200])
    token = browser.cookies["litellm.localhost:8000"]["token"]
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["user_id"] == "alice" and claims["user_role"] == "proxy_admin" and claims["login_method"] == "sso"

    # With the gate passed, the management API answers on this hostname.
    teams = browser.request("GET", f"{ADMIN_URL}/team/list", headers=MASTER)
    assert teams.status_code == 200 and isinstance(teams.json(), list)
    assert browser.request("GET", f"{ADMIN_URL}/ui/").status_code == 200


def test_other_keycloak_users_are_turned_away():
    create_user("operator-outsider@example.com", "Correct-horse-9")
    browser = Browser()
    refused = through_keycloak(browser, f"{ADMIN_URL}/ui/", "operator-outsider@example.com", "Correct-horse-9")
    assert refused.status_code == 403
    assert browser.request("GET", f"{ADMIN_URL}/team/list", headers=MASTER, follow=False).status_code in (302, 403)
    assert "token" not in browser.cookies.get("litellm.localhost:8000", {})


def test_console_links_admins_to_the_litellm_ui():
    from .helpers import sign_in
    assert f'href="{ADMIN_URL}/ui/"' in sign_in("alice", "alice123").landed.text
    assert not re.search(r"LiteLLM UI", sign_in("operator-outsider@example.com", "Correct-horse-9").landed.text)
