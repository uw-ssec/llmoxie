"""Sign-in: authorization code with PKCE against the identity provider (Keycloak here)."""

import os
import secrets
import time
from urllib.parse import urlencode

import jwt
from authlib.integrations.httpx_client import OAuth2Client

ISSUER = os.environ["OIDC_ISSUER"]
CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
CLIENT_SECRET = os.environ["OIDC_CLIENT_SECRET"]
AUTH_URL = os.environ["OIDC_AUTH_URL"]        # the browser goes here
TOKEN_URL = os.environ["OIDC_TOKEN_URL"]      # this service calls these two directly
LOGOUT_URL = os.environ["OIDC_LOGOUT_URL"]
PUBLIC_URL = os.environ["CONSOLE_PUBLIC_URL"]
REDIRECT_URI = f"{PUBLIC_URL}/auth/callback"

_jwks = jwt.PyJWKClient(os.environ["OIDC_JWKS_URL"], cache_keys=True, lifespan=300)


def _client() -> OAuth2Client:
    return OAuth2Client(CLIENT_ID, CLIENT_SECRET, scope="openid email profile", redirect_uri=REDIRECT_URI,
                        code_challenge_method="S256", timeout=15)


def begin() -> tuple[str, dict]:
    """The sign-in URL, and what to remember until the user comes back."""
    verifier, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(16)
    with _client() as client:
        url, state = client.create_authorization_url(AUTH_URL, code_verifier=verifier, nonce=nonce)
    return url, {"state": state, "verifier": verifier, "nonce": nonce}


def _tokens(token: dict) -> dict:
    return {"access_token": token["access_token"], "refresh_token": token.get("refresh_token"),
            "id_token": token.get("id_token"), "expires_at": time.time() + int(token.get("expires_in", 60))}


def finish(code: str, pending: dict) -> dict:
    """Trade the code for tokens and check the ID token really is for this sign-in."""
    with _client() as client:
        token = client.fetch_token(TOKEN_URL, code=code, code_verifier=pending["verifier"])
    key = _jwks.get_signing_key_from_jwt(token["id_token"]).key
    claims = jwt.decode(token["id_token"], key, algorithms=["RS256"], audience=CLIENT_ID, issuer=ISSUER)
    if claims.get("nonce") != pending["nonce"]:
        raise ValueError("nonce mismatch")
    return _tokens(token)


def refresh(refresh_token: str) -> dict:
    with _client() as client:
        token = client.refresh_token(TOKEN_URL, refresh_token=refresh_token)
    return _tokens({**token, "id_token": token.get("id_token")})


def logout_url(id_token: str | None) -> str:
    query = {"post_logout_redirect_uri": f"{PUBLIC_URL}/", "client_id": CLIENT_ID}
    if id_token:
        query["id_token_hint"] = id_token
    return f"{LOGOUT_URL}?{urlencode(query)}"
