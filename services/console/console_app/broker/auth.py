"""Who is calling, and as whom.

console-web must present a shared secret (it is the only expected caller) and the
signed-in user's access token. The token is signed by Keycloak and lives a few
minutes, so console-web cannot make one up: the broker verifies it here against
Keycloak's keys and builds the Actor from the database.
"""

import hmac
import os
import secrets

import jwt
from fastapi import HTTPException, Request

from ..policy import Actor, Integration
from . import db

ISSUER = os.environ["OIDC_ISSUER"]
AUDIENCE = "console-broker"
WEB_CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
CALLER_SECRET = os.environ["CONSOLE_BROKER_CALLER_SECRET"]
ADMIN_SUBJECTS = {s.strip() for s in os.environ.get("CONSOLE_ADMIN_SUBJECTS", "").split(",") if s.strip()}

_jwks = jwt.PyJWKClient(os.environ["OIDC_JWKS_URL"], cache_keys=True, lifespan=300)


def require_caller(request: Request) -> None:
    given = request.headers.get("x-console-caller", "")
    if not hmac.compare_digest(given.encode(), CALLER_SECRET.encode()):
        raise HTTPException(401, "unknown caller")


def _decode(token: str, what: str) -> dict:
    """Claims of a token Keycloak signed for this broker, or 401."""
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER,
                          options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid {what}") from exc


def _verify(token: str) -> dict:
    claims = _decode(token, "user assertion")
    if claims.get("azp") != WEB_CLIENT_ID:
        raise HTTPException(401, "invalid user assertion")
    return claims


def _bearer(request: Request, header: str, what: str) -> str:
    scheme, _, token = request.headers.get(header, "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, f"missing {what}")
    return token


def _person(conn, claims: dict, email: str | None) -> dict:
    return conn.execute(
        """INSERT INTO person (issuer, subject, participant_id, email) VALUES (%s, %s, %s, %s)
           ON CONFLICT (issuer, subject) DO UPDATE
             SET last_seen_at = now(), email = coalesce(EXCLUDED.email, person.email)
           RETURNING *""",
        (claims["iss"], claims["sub"], "p_" + secrets.token_hex(8), email),
    ).fetchone()


def _verified_email(claims: dict) -> str | None:
    email = claims.get("email") if claims.get("email_verified") is True else None
    return email.strip().lower() if email else None


class Session:
    """The verified user behind one broker call."""

    def __init__(self, person: dict, actor: Actor, verified_email: str | None):
        self.person = person
        self.actor = actor
        self.verified_email = verified_email


def current_session(request: Request) -> Session:
    require_caller(request)
    claims = _verify(_bearer(request, "authorization", "user assertion"))
    email = _verified_email(claims)

    with db.system_tx() as conn:
        person = _person(conn, claims, email)
        leads = conn.execute(
            "SELECT org_id FROM org_lead WHERE person_id = %s", (person["id"],)).fetchall()
        teams = conn.execute(
            "SELECT team_id, org_id FROM team_member WHERE person_id = %s AND status = 'active'",
            (person["id"],)).fetchall()

    actor = Actor(
        person_id=str(person["id"]),
        is_admin=claims["sub"] in ADMIN_SUBJECTS,
        lead_orgs=frozenset(str(r["org_id"]) for r in leads),
        member_teams={str(r["team_id"]): str(r["org_id"]) for r in teams},
    )
    return Session(person, actor, email)


class IntegrationSession:
    """One call from an outside service, made for one signed-in user."""

    def __init__(self, person: dict, verified_email: str | None, integration: dict):
        self.person = person
        self.verified_email = verified_email
        self.integration = integration
        self.actor = Actor(person_id=str(person["id"]))  # the user, with no console role of their own here
        self.role_label = f"integration:{integration['client_id']}"
        self.grant = Integration(id=str(integration["id"]), team_id=str(integration["team_id"]),
                                 org_id=str(integration["org_id"]), can_enroll=integration["can_enroll"])


def integration_session(request: Request) -> IntegrationSession:
    """Two tokens, both signed by Keycloak for the same registered client:

    - the user's access token, which the service got when that user signed in through it, and
    - the service's own token (client credentials), which shows the call comes from the service
      itself and not from someone who merely got hold of a user's token.
    """
    require_caller(request)
    user = _decode(_bearer(request, "authorization", "user assertion"), "user assertion")
    service = _decode(_bearer(request, "x-service-authorization", "service assertion"), "service assertion")
    client_id = user.get("azp")
    if (not client_id or client_id == WEB_CLIENT_ID or service.get("azp") != client_id
            or service.get("preferred_username") != f"service-account-{client_id}"
            or str(user.get("preferred_username", "")).startswith("service-account-")):
        raise HTTPException(401, "the user and service assertions do not belong to one integration")
    email = _verified_email(user)
    with db.system_tx() as conn:
        integration = conn.execute(
            "SELECT * FROM integration WHERE client_id = %s AND removed_at IS NULL", (client_id,)).fetchone()
        if not integration:
            raise HTTPException(403, "this service is not a registered integration")
        person = _person(conn, user, email)
    return IntegrationSession(person, email, integration)
