"""console-web: the console's public face.

It signs people in, keeps their session, serves the application that draws the pages (built from
`frontend/` into `dist/`), and answers that application's calls (`api.py`) by calling console-broker.
It holds no LiteLLM credential and cannot read org data: all of that comes from the broker, which
checks the signed-in user's token itself.
"""

import hmac
import html
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import api, oidc, sessions
from .visit import BROKER_URL, CALLER_SECRET, NOT_VALID, ApiError, Stop, Visit, broker_plain, see_other

PUBLIC_URL = os.environ["CONSOLE_PUBLIC_URL"]
GATEWAY_URL = os.environ["GATEWAY_PUBLIC_URL"]
DIST = Path(__file__).parent / "dist"  # the built application: index.html and assets/


@asynccontextmanager
async def lifespan(_: FastAPI):
    sessions.pool.open(wait=True)
    yield
    sessions.pool.close()


app = FastAPI(title="console-web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# The pages run one script, the console's own, and load nothing from anywhere else. Nothing inline
# is allowed, so text a member wrote cannot run even if it slipped through as markup.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
       f"form-action 'self' {oidc.ISSUER.split('/realms/')[0]}")


@app.middleware("http")
async def harden(request: Request, call_next):
    # Cross-site posts are refused outright; the per-session token is the second check.
    if request.method == "POST" and request.headers.get("origin") not in (PUBLIC_URL, None):
        return Response("cross-site request refused", status_code=403)
    response = await call_next(request)
    response.headers.update({
        # same-origin, not no-referrer: both keep page addresses (invite tokens) away from other sites,
        # but under no-referrer browsers send `Origin: null` on our own forms and the check above refuses them.
        "Cache-Control": "no-store", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY", "Content-Security-Policy": CSP,
    })
    return response


@app.exception_handler(Stop)
def stop(_, exc: Stop):
    return exc.response


@app.exception_handler(ApiError)
def api_error(_, exc: ApiError):
    return JSONResponse({"error": {"status": exc.status, "message": exc.message}}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
def not_valid(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/web-api/"):
        return JSONResponse({"error": {"status": 422, "message": NOT_VALID}}, status_code=422)
    return JSONResponse({"detail": "Not valid"}, status_code=422)


app.include_router(api.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── Sign-in ─────────────────────────────────────────────────────────────────
# These are navigations, not calls from the application: each ends at the identity provider.

def start_login(next_path: str = "/", invite: str | None = None) -> RedirectResponse:
    url, pending = oidc.begin()
    sid = sessions.create({**pending, "next": next_path, "invite": invite}, sessions.LOGIN_TTL)
    response = RedirectResponse(url, status_code=303)
    # Lax, not Strict: this cookie must come back on the redirect from the sign-in page.
    sessions.set_cookie(response, sessions.LOGIN_COOKIE, sid, sessions.LOGIN_TTL, "lax")
    return response


def local_path(value: str) -> str:
    """`value` if it is a plain path on this site, else the home page. Never somewhere else."""
    plain = value.startswith("/") and not value.startswith("//") and "\\" not in value and ":" not in value
    return value if plain and len(value) < 200 else "/"


def signed_in_page(target: str) -> HTMLResponse:
    """The one page the server still writes. A page, not a redirect: the Strict session cookie is only
    sent once navigation starts from this site, which this page's refresh does."""
    to = html.escape(target, quote=True)
    return HTMLResponse(
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="refresh" content="0; url={to}"><title>Signed in · LLMoxie console</title></head>'
        f'<body><h1>Signed in</h1><p><a href="{to}">Continue</a></p></body></html>\n')


@app.post("/login")
def login(next: str = Form("/")):
    return start_login(local_path(next))


@app.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = ""):
    login_sid = request.cookies.get(sessions.LOGIN_COOKIE)
    pending = sessions.load(login_sid)
    sessions.delete(login_sid)
    tokens = None
    if pending and code and hmac.compare_digest(state.encode(), pending["state"].encode()):
        try:
            tokens = oidc.finish(code, pending)
        except Exception:
            tokens = None
    if not tokens:
        response = see_other("/?signin=failed")  # the application says so and offers to start again
        sessions.clear_cookie(response, sessions.LOGIN_COOKIE)
        return response

    data = {**tokens, "csrf": secrets.token_urlsafe(24)}
    sid = sessions.create(data, sessions.SESSION_TTL)  # a fresh id: nothing from before sign-in carries over
    target = pending.get("next") or "/"
    if pending.get("invite"):
        target = accept_invite(data, pending["invite"])
    response = signed_in_page(target)
    sessions.set_cookie(response, sessions.SESSION_COOKIE, sid, sessions.SESSION_TTL, "strict")
    sessions.clear_cookie(response, sessions.LOGIN_COOKIE)
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    sessions.delete(visit.sid)
    response = see_other(oidc.logout_url(visit.data.get("id_token")))
    sessions.clear_cookie(response, sessions.SESSION_COOKIE)
    return response


# ── Invites ─────────────────────────────────────────────────────────────────

def accept_invite(data: dict, token: str) -> str:
    """Use the invite as the signed-in user and return where to send them."""
    result = broker_plain("/invites/accept", {"token": token}, data["access_token"])
    if result.get("outcome") == "joined":
        return f"/teams/{result['team_id']}" if result["kind"] == "participant" else f"/orgs/{result['org_id']}"
    return "/invite-result/" + ("waiting" if result.get("outcome") == "needs_approval" else "invalid")


@app.post("/invite/{token}")
def invite_use(request: Request, token: str):
    """The invitation screen's button. Opening the link uses nothing up; only this does."""
    if not sessions.load(request.cookies.get(sessions.SESSION_COOKIE)):
        return start_login(invite=token)
    visit = Visit(request)  # refreshes the access token if it is about to expire
    return see_other(accept_invite(visit.data, token))


# ── API for connected services (integrations) ───────────────────────────────
# Not for browsers: no cookie is read here. A service sends two Keycloak tokens, the signed-in
# user's and its own, and console-web hands them to the broker unchanged. Three fixed operations.

def _integration_call(request: Request, operation: str) -> JSONResponse:
    headers = {"X-Console-Caller": CALLER_SECRET}
    for name in ("authorization", "x-service-authorization"):
        if name in request.headers:
            headers[name] = request.headers[name]
    with httpx.Client(base_url=BROKER_URL, timeout=40) as client:
        response = client.post(f"/integration/{operation}", headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {"detail": "the console could not complete that"}
    detail = body.get("detail") if isinstance(body, dict) else None
    if response.status_code >= 400:  # one shape for every refusal: {"error": code, "message": text, ...}
        body = detail if isinstance(detail, dict) else {"error": "refused", "message": str(detail or "refused")}
    elif operation == "key":
        body["base_url"] = f"{GATEWAY_URL}/v1"
        body["mcp_url"] = f"{GATEWAY_URL}/mcp"
    return JSONResponse(body, status_code=response.status_code)


@app.post("/api/v1/enroll")
def api_enroll(request: Request):
    return _integration_call(request, "enroll")


@app.post("/api/v1/key")
def api_key(request: Request):
    return _integration_call(request, "key")


@app.post("/api/v1/key/revoke")
def api_key_revoke(request: Request):
    return _integration_call(request, "key/revoke")


# ── The application ─────────────────────────────────────────────────────────
# Every page address gets the same built page; the application reads the address and asks the
# browser API for that page's data. Declared last, so everything above is matched first.

app.mount("/assets", StaticFiles(directory=DIST / "assets", check_dir=False), name="assets")


@app.get("/{path:path}")
def shell(path: str):
    if path.startswith(("api/", "web-api/", "assets/")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = DIST / "index.html"
    if not index.is_file():
        return Response("The console's front end has not been built.", status_code=503, media_type="text/plain")
    return FileResponse(index, media_type="text/html")
