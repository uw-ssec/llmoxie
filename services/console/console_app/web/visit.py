"""One signed-in request: the session, the user's roles, and a way to call the broker as them.

Used two ways. The browser API (`api=True`) answers every refusal as JSON through `ApiError`. The few
routes a browser navigates to directly (sign-out, accepting an invitation) get a redirect or a short
plain-text answer through `Stop`.
"""

import hmac
import os
import time
from urllib.parse import quote

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from .. import policy
from . import oidc, sessions

BROKER_URL = os.environ["CONSOLE_BROKER_URL"]
CALLER_SECRET = os.environ["CONSOLE_BROKER_CALLER_SECRET"]

SIGNED_OUT = "You are signed out."
NO_ACCESS = "You do not have access to that."
NOT_FOUND = "That does not exist."
NOT_VALID = "Some of those values are not valid."
FAILED = "The console could not complete that. Nothing was changed."
EXPIRED_FORM = "This form has expired. Go back, reload the page and try again."


class Stop(Exception):
    """Ends the request with a ready response (a redirect or an error page)."""

    def __init__(self, response: Response):
        self.response = response


class ApiError(Exception):
    """Ends a browser API request. Answered as {"error": {"status": ..., "message": ...}}."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


def see_other(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def broker_plain(path: str, json: dict, access_token: str | None = None) -> dict:
    """A broker call that needs no session: looking at an invitation, or using one right after sign-in."""
    headers = {"X-Console-Caller": CALLER_SECRET}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    with httpx.Client(base_url=BROKER_URL, timeout=20) as client:
        response = client.post(path, json=json, headers=headers)
    return response.json() if response.status_code < 300 else {"valid": False, "outcome": "invalid"}


class Visit:
    def __init__(self, request: Request, *, api: bool = False):
        self.request = request
        self.api = api
        self.sid = request.cookies.get(sessions.SESSION_COOKIE)
        self.data = sessions.load(self.sid)
        if not self.data:
            raise self.signed_out()
        if self.data["expires_at"] - time.time() < 30:  # access tokens live a few minutes
            try:
                self.data.update(oidc.refresh(self.data["refresh_token"]))
                sessions.save(self.sid, self.data)
            except Exception:
                sessions.delete(self.sid)
                raise self.signed_out(back=False) from None
        self.me = self.broker("GET", "/me")
        self.actor = policy.Actor(
            person_id=self.me["person_id"], is_admin=self.me["is_admin"],
            lead_orgs=frozenset(o["id"] for o in self.me["lead_orgs"]),
            member_teams={t["id"]: t["org_id"] for t in self.me["teams"]})

    def signed_out(self, back: bool = True) -> Exception:
        if self.api:
            return ApiError(401, SIGNED_OUT)
        # Go to the sign-in page, and come back here afterwards if this was a page view.
        here = self.request.url.path
        return Stop(see_other(f"/?next={quote(here, safe='')}" if back and self.request.method == "GET" else "/"))

    def refuse(self, status: int, message: str) -> Exception:
        return ApiError(status, message) if self.api else Stop(Response(message, status_code=status))

    def fixable(self, status: int, message: str, back: str | None) -> Exception:
        """A refusal the user can put right, such as a name that is taken."""
        return self.refuse(status, message)

    def broker(self, method: str, path: str, json: dict | None = None, back: str | None = None):
        """Call a broker operation as the signed-in user. `back` is where a form's page is, for `fixable`."""
        headers = {"X-Console-Caller": CALLER_SECRET, "Authorization": f"Bearer {self.data['access_token']}"}
        with httpx.Client(base_url=BROKER_URL, timeout=40) as client:
            response = client.request(method, path, json=json, headers=headers)
        if response.status_code < 300:
            return response.json()
        if response.status_code == 401:
            sessions.delete(self.sid)
            raise self.signed_out(back=False)
        if response.status_code == 403:
            raise self.refuse(403, NO_ACCESS)
        if response.status_code == 404 or (response.status_code == 422 and method == "GET"):
            raise self.refuse(404, NOT_FOUND)  # an id in the address that is not an id is a page that is not there
        if response.status_code in (409, 422) and (back or self.api):
            detail = response.json().get("detail")
            raise self.fixable(response.status_code, detail if isinstance(detail, str) else NOT_VALID, back)
        raise self.refuse(502, FAILED)

    def require(self, action: str, *, org_id: str | None = None, team_id: str | None = None) -> None:
        """The same policy the broker applies, checked here first. The org always comes from /me, not the URL."""
        if team_id is not None:
            org_id = self.me["team_orgs"].get(team_id)
        if not policy.allowed(self.actor, action, org_id=org_id, team_id=team_id):
            raise self.refuse(403, NO_ACCESS)

    def check_csrf(self, token: str) -> None:
        if not hmac.compare_digest(token.encode(), self.data["csrf"].encode()):
            raise self.refuse(403, EXPIRED_FORM)
