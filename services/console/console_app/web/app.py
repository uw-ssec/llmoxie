"""console-web: the public pages.

It signs people in, keeps their session, and turns form posts into calls to
console-broker. It holds no LiteLLM credential and cannot read org data: all of
that comes from the broker, which checks the signed-in user's token itself.
"""

import csv
import hmac
import io
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import api, oidc, sessions
from .api import DLP_ACTIONS
from .visit import BROKER_URL, CALLER_SECRET, NOT_VALID, ApiError, Stop, see_other
from .visit import Visit as BaseVisit
from .visit import broker_plain as _broker_plain

PUBLIC_URL = os.environ["CONSOLE_PUBLIC_URL"]
GATEWAY_URL = os.environ["GATEWAY_PUBLIC_URL"]
LITELLM_ADMIN_URL = os.environ.get("LITELLM_ADMIN_URL", "")
HERE = Path(__file__).parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    sessions.pool.open(wait=True)
    yield
    sessions.pool.close()


app = FastAPI(title="console-web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals["litellm_admin_url"] = LITELLM_ADMIN_URL

CSP = ("default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
       f"form-action 'self' {oidc.ISSUER.split('/realms/')[0]}")


@app.middleware("http")
async def harden(request: Request, call_next):
    # Cross-site form posts are refused outright; the per-session token below is the second check.
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


# ── Plumbing ────────────────────────────────────────────────────────────────

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


def page(request: Request, name: str, status: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status)


def error(request: Request, status: int, message: str) -> Stop:
    return Stop(page(request, "error.html", status, message=message, me=None))


class Visit(BaseVisit):
    """A signed-in request for an HTML page: refusals are error pages, and messages wait in the session."""

    def refuse(self, status: int, message: str) -> Exception:
        return error(self.request, status, message)

    def fixable(self, status: int, message: str, back: str | None) -> Exception:
        self.flash(message, "bad")
        return Stop(see_other(back))

    def flash(self, message: str, kind: str = "good") -> None:
        self.data["flash"] = {"message": message, "kind": kind}
        sessions.save(self.sid, self.data)

    def render(self, name: str, **context) -> HTMLResponse:
        flash = self.data.pop("flash", None)
        if flash:
            sessions.save(self.sid, self.data)
        return page(self.request, name, me=self.me, csrf=self.data["csrf"], flash=flash, **context)


def start_login(next_path: str = "/", invite: str | None = None) -> RedirectResponse:
    url, pending = oidc.begin()
    sid = sessions.create({**pending, "next": next_path, "invite": invite}, sessions.LOGIN_TTL)
    response = RedirectResponse(url, status_code=303)
    # Lax, not Strict: this cookie must come back on the redirect from the sign-in page.
    sessions.set_cookie(response, sessions.LOGIN_COOKIE, sid, sessions.LOGIN_TTL, "lax")
    return response


# ── Sign-in ─────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def home(request: Request, next: str = ""):
    if not sessions.load(request.cookies.get(sessions.SESSION_COOKIE)):
        return page(request, "login.html", me=None, next=local_path(next))
    visit = Visit(request)
    me = visit.me
    if not (me["is_admin"] or me["lead_orgs"] or me["teams"]):
        return visit.render("not_invited.html")
    if not me["is_admin"] and not me["lead_orgs"] and len(me["teams"]) == 1:
        return see_other(f"/teams/{me['teams'][0]['id']}")
    return visit.render("home.html")


def local_path(value: str) -> str:
    """`value` if it is a plain path on this site, else the home page. Never somewhere else."""
    plain = value.startswith("/") and not value.startswith("//") and "\\" not in value and ":" not in value
    return value if plain and len(value) < 200 else "/"


@app.post("/login")
def login(next: str = Form("/")):
    return start_login(local_path(next))


@app.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = ""):
    login_sid = request.cookies.get(sessions.LOGIN_COOKIE)
    pending = sessions.load(login_sid)
    sessions.delete(login_sid)
    if not pending or not code or not hmac.compare_digest(state.encode(), pending["state"].encode()):
        raise error(request, 400, "That sign-in could not be completed. Please start again.")
    try:
        tokens = oidc.finish(code, pending)
    except Exception:
        raise error(request, 400, "That sign-in could not be completed. Please start again.") from None

    data = {**tokens, "csrf": secrets.token_urlsafe(24)}
    sid = sessions.create(data, sessions.SESSION_TTL)  # a fresh id: nothing from before sign-in carries over
    target = pending.get("next") or "/"
    if pending.get("invite"):
        target = accept_invite(request, data, pending["invite"])
    # A page, not a redirect: the Strict session cookie is only sent once navigation starts from this site.
    response = page(request, "signed_in.html", me=None, target=target)
    sessions.set_cookie(response, sessions.SESSION_COOKIE, sid, sessions.SESSION_TTL, "strict")
    sessions.clear_cookie(response, sessions.LOGIN_COOKIE)
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    sessions.delete(visit.sid)
    response = see_other(oidc.logout_url(visit.data.get("id_token")))
    sessions.clear_cookie(response, sessions.SESSION_COOKIE)
    return response


# ── Invites ─────────────────────────────────────────────────────────────────

def accept_invite(request: Request, data: dict, token: str) -> str:
    """Use the invite as the signed-in user and return where to send them."""
    result = _broker_plain("/invites/accept", {"token": token}, data["access_token"])
    if result.get("outcome") == "joined":
        return f"/teams/{result['team_id']}" if result["kind"] == "participant" else f"/orgs/{result['org_id']}"
    return "/invite-result/" + ("waiting" if result.get("outcome") == "needs_approval" else "invalid")


@app.get("/invite/{token}")
def invite_page(request: Request, token: str):
    """Shows what the invite is for. Opening the link uses nothing up; only the button below does."""
    info = _broker_plain("/invites/inspect", {"token": token}) if 20 <= len(token) <= 200 else {"valid": False}
    return page(request, "invite.html", me=None, info=info, token=token)


@app.post("/invite/{token}")
def invite_use(request: Request, token: str):
    data = sessions.load(request.cookies.get(sessions.SESSION_COOKIE))
    if not data:
        return start_login(invite=token)
    Visit(request)  # refreshes the access token if it is about to expire
    return see_other(accept_invite(request, sessions.load(request.cookies.get(sessions.SESSION_COOKIE)), token))


@app.get("/invite-result/{outcome}")
def invite_result(request: Request, outcome: str):
    return page(request, "invite_result.html", me=None, waiting=outcome == "waiting")


# ── SSEC admin ──────────────────────────────────────────────────────────────

@app.get("/admin")
def admin(request: Request):
    visit = Visit(request)
    visit.require("org.list")
    return visit.render("admin.html", orgs=visit.broker("GET", "/admin/orgs"))


@app.post("/admin/orgs")
def admin_org_create(request: Request, csrf: str = Form(), name: str = Form(), slug: str = Form(),
                     budget_ceiling: float = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("org.create")
    org = visit.broker("POST", "/admin/orgs", {"name": name, "slug": slug, "budget_ceiling": budget_ceiling},
                       back="/admin")
    visit.flash(f"Created {name}.")
    return see_other(f"/orgs/{org['id']}")


@app.post("/admin/orgs/{org_id}/{operation}")
def admin_org_operation(request: Request, org_id: str, operation: str, csrf: str = Form(),
                        budget_ceiling: float | None = Form(None), email: str | None = Form(None),
                        confirm_slug: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    back = f"/orgs/{org_id}"
    if operation in ("suspend", "resume"):
        visit.require(f"org.{operation}")
        visit.broker("POST", f"/admin/orgs/{quote(org_id)}/{operation}", back=back)
        visit.flash("Organization suspended." if operation == "suspend" else "Organization resumed.")
    elif operation == "ceiling":
        visit.require("org.set_ceiling")
        visit.broker("POST", f"/admin/orgs/{quote(org_id)}/ceiling", {"budget_ceiling": budget_ceiling}, back=back)
        visit.flash("Budget ceiling updated.")
    elif operation == "remove":
        visit.require("org.remove")
        result = visit.broker("POST", f"/admin/orgs/{quote(org_id)}/remove", {"confirm_slug": confirm_slug.strip()},
                              back=back)
        visit.flash(f"Organization removed: {result['teams_archived']} team(s) archived, {result['keys_deleted']} key(s) "
                    f"deleted, {result['models_removed']} model(s) removed.")
        return see_other("/admin")
    elif operation == "leads":
        visit.require("org.appoint_lead")
        visit.broker("POST", f"/admin/orgs/{quote(org_id)}/leads", {"email": email}, back=back)
        visit.flash(f"Invitation sent to {email}.")
    else:
        raise error(request, 404, "That does not exist.")
    return see_other(back)


@app.post("/admin/orgs/{org_id}/lead-requests/{invite_id}")
def admin_lead_request(request: Request, org_id: str, invite_id: str, csrf: str = Form(), decision: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("org.decide_lead_exception")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/lead-requests/{quote(invite_id)}",
                 {"approve": decision == "approve"}, back=f"/orgs/{org_id}")
    visit.flash("Request approved." if decision == "approve" else "Request rejected.")
    return see_other(f"/orgs/{org_id}")


@app.post("/admin/orgs/{org_id}/leads/{person_id}/remove")
def admin_lead_remove(request: Request, org_id: str, person_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("org.remove_lead")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/leads/{quote(person_id)}/remove", back=f"/orgs/{org_id}")
    visit.flash("Lead removed.")
    return see_other(f"/orgs/{org_id}")


@app.post("/admin/orgs/{org_id}/lead-invites/{invite_id}/revoke")
def admin_lead_invite_revoke(request: Request, org_id: str, invite_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("org.remove_lead")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/lead-invites/{quote(invite_id)}/revoke", back=f"/orgs/{org_id}")
    visit.flash("Invitation cancelled.")
    return see_other(f"/orgs/{org_id}")


@app.post("/admin/teams/{team_id}/remove")
def admin_team_remove(request: Request, team_id: str, csrf: str = Form(), confirm_name: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.remove")
    result = visit.broker("POST", f"/admin/teams/{quote(team_id)}/remove", {"confirm_name": confirm_name.strip()},
                          back=f"/teams/{team_id}/manage")
    visit.flash(f"Team removed: {result['members_removed']} member(s) removed, {result['keys_deleted']} key(s) deleted.")
    return see_other(f"/orgs/{result['org_id']}")


@app.post("/admin/teams/{team_id}/integrations")
def admin_integration_register(request: Request, team_id: str, csrf: str = Form(), client_id: str = Form(),
                               name: str = Form(), can_enroll: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("integration.register")
    visit.broker("POST", f"/admin/teams/{quote(team_id)}/integrations",
                 {"client_id": client_id.strip(), "name": name.strip(), "can_enroll": can_enroll == "yes"},
                 back=f"/teams/{team_id}/manage")
    visit.flash(f"Connected {name.strip()}.")
    return see_other(f"/teams/{team_id}/manage")


@app.post("/admin/integrations/{integration_id}/remove")
def admin_integration_remove(request: Request, integration_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("integration.remove")
    result = visit.broker("POST", f"/admin/integrations/{quote(integration_id)}/remove", back="/admin")
    visit.flash(f"Integration disconnected. {result['keys_deleted']} key(s) deleted.")
    return see_other(f"/teams/{result['team_id']}/manage")


@app.get("/admin/audit")
def admin_audit(request: Request):
    visit = Visit(request)
    visit.require("audit.read")
    return visit.render("audit.html", events=visit.broker("GET", "/admin/audit"))


@app.get("/admin/dlp")
def admin_dlp(request: Request):
    visit = Visit(request)
    visit.require("dlp.read")
    return visit.render("dlp.html", actions=DLP_ACTIONS, **visit.broker("GET", "/admin/dlp"))


# ── Org lead ────────────────────────────────────────────────────────────────

@app.get("/orgs/{org_id}")
def org_page(request: Request, org_id: str):
    visit = Visit(request)
    visit.require("org.view", org_id=org_id)
    view = visit.broker("GET", f"/orgs/{quote(org_id)}")
    return visit.render("org.html", is_lead=org_id in visit.actor.lead_orgs, **view)


@app.get("/orgs/{org_id}/knowledge")
def org_knowledge(request: Request, org_id: str, concept: str = ""):
    visit = Visit(request)
    visit.require("org.knowledge", org_id=org_id)
    view = visit.broker("GET", f"/orgs/{quote(org_id)}/knowledge")
    parts = api.knowledge_parts(view, concept)
    return visit.render("knowledge.html", concept=parts["concept"], links_out=parts["links_out"],
                        links_in=parts["links_in"], body=parts["body_html"], log_text=parts["log_html"],
                        graph=parts["graph"], **view)


@app.post("/orgs/{org_id}/models")
def org_model_add(request: Request, org_id: str, csrf: str = Form(), provider: str = Form(), model: str = Form(),
                  api_key: str = Form(), api_base: str = Form(""), api_version: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("model.add", org_id=org_id)
    added = visit.broker("POST", f"/orgs/{quote(org_id)}/models", {
        "provider": provider, "model": model.strip(), "api_key": api_key.strip(),
        "api_base": api_base.strip() or None, "api_version": api_version.strip() or None}, back=f"/orgs/{org_id}")
    visit.flash(f"Added {added['public_name']}. The key cannot be viewed again.")
    return see_other(f"/orgs/{org_id}")


@app.post("/orgs/{org_id}/models/{model_id}/remove")
def org_model_remove(request: Request, org_id: str, model_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("model.remove", org_id=org_id)
    removed = visit.broker("POST", f"/orgs/{quote(org_id)}/models/{quote(model_id)}/remove", back=f"/orgs/{org_id}")
    visit.flash(f"Removed {removed['removed']}.")
    return see_other(f"/orgs/{org_id}")


@app.post("/orgs/{org_id}/teams")
def org_team_create(request: Request, org_id: str, csrf: str = Form(), name: str = Form(), key_limit: int = Form(),
                    key_budget: float = Form(), key_expiry_days: int = Form(), team_budget: float = Form(),
                    consent_text: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.create", org_id=org_id)
    team = visit.broker("POST", f"/orgs/{quote(org_id)}/teams", {
        "name": name.strip(), "key_limit": key_limit, "key_budget": key_budget, "key_expiry_days": key_expiry_days,
        "team_budget": team_budget, "consent_text": consent_text.strip()}, back=f"/orgs/{org_id}")
    visit.flash(f"Created {name}.")
    return see_other(f"/teams/{team['id']}/manage")


@app.get("/teams/{team_id}/manage")
def team_manage(request: Request, team_id: str):
    visit = Visit(request)
    visit.require("team.view", team_id=team_id)
    view = visit.broker("GET", f"/teams/{quote(team_id)}/manage")
    usage = visit.broker("GET", f"/teams/{quote(team_id)}/usage")
    is_lead = visit.me["team_orgs"].get(team_id) in visit.actor.lead_orgs
    return visit.render("team_manage.html", usage=usage, is_lead=is_lead, **view)


def _emails_from(text: str, upload: bytes) -> list[str]:
    """Addresses typed into the box plus any in an uploaded CSV (an `email` column, or the first column)."""
    found = [part.strip() for part in text.replace(",", "\n").replace(";", "\n").splitlines()]
    rows = list(csv.reader(io.StringIO(upload.decode("utf-8-sig", errors="replace"))))
    if rows:
        header = [c.strip().lower() for c in rows[0]]
        column = header.index("email") if "email" in header else 0
        found += [row[column].strip() for row in rows if len(row) > column]
    return [e for e in found if "@" in e]


@app.post("/teams/{team_id}/invites")
async def team_invites(request: Request, team_id: str, csrf: str = Form(), emails: str = Form(""),
                       csv_file: UploadFile | None = None):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.invite", team_id=team_id)
    back = f"/teams/{team_id}/manage"
    upload = await csv_file.read(200_001) if csv_file and csv_file.filename else b""
    if len(upload) > 200_000:
        visit.flash("That file is too large (200 KB at most).", "bad")
        return see_other(back)
    addresses = _emails_from(emails, upload)
    if not addresses:
        visit.flash("No email addresses found.", "bad")
        return see_other(back)
    sent = visit.broker("POST", f"/teams/{quote(team_id)}/invites", {"emails": addresses}, back=back)
    visit.flash(f"Sent {sent['invited']} invitation(s).")
    return see_other(back)


@app.post("/teams/{team_id}/{operation}")
def team_operation(request: Request, team_id: str, operation: str, csrf: str = Form(),
                   team_budget: float | None = Form(None), model_ids: list[str] = Form([])):
    visit = Visit(request)
    visit.check_csrf(csrf)
    back = f"/teams/{team_id}/manage"
    if operation == "budget":
        visit.require("team.set_budget", team_id=team_id)
        visit.broker("POST", f"/teams/{quote(team_id)}/budget", {"team_budget": team_budget}, back=back)
        visit.flash("Team budget updated.")
    elif operation == "models":
        visit.require("team.set_models", team_id=team_id)
        visit.broker("POST", f"/teams/{quote(team_id)}/models", {"model_ids": model_ids}, back=back)
        visit.flash("Models updated.")
    elif operation == "archive":
        visit.require("team.archive", team_id=team_id)
        result = visit.broker("POST", f"/teams/{quote(team_id)}/archive", back=back)
        visit.flash(f"Team archived. {result['keys_deleted']} key(s) deleted.")
    else:
        raise error(request, 404, "That does not exist.")
    return see_other(back)


@app.post("/teams/{team_id}/invites/{invite_id}/revoke")
def team_invite_revoke(request: Request, team_id: str, invite_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.cancel_invite", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/invites/{quote(invite_id)}/revoke", back=f"/teams/{team_id}/manage")
    visit.flash("Invitation cancelled.")
    return see_other(f"/teams/{team_id}/manage")


@app.post("/teams/{team_id}/requests/{invite_id}")
def team_request(request: Request, team_id: str, invite_id: str, csrf: str = Form(), decision: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.decide_exception", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/requests/{quote(invite_id)}", {"approve": decision == "approve"},
                 back=f"/teams/{team_id}/manage")
    visit.flash("Request approved." if decision == "approve" else "Request rejected.")
    return see_other(f"/teams/{team_id}/manage")


@app.post("/teams/{team_id}/keys/{key_id}/revoke")
def team_key_revoke(request: Request, team_id: str, key_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.revoke_key", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/keys/{quote(key_id)}/revoke", back=f"/teams/{team_id}/manage")
    visit.flash("Key revoked.")
    return see_other(f"/teams/{team_id}/manage")


@app.post("/teams/{team_id}/keys/{key_id}/rotate")
def team_key_rotate(request: Request, team_id: str, key_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.rotate_key", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/keys/{quote(key_id)}/rotate", back=f"/teams/{team_id}/manage")
    visit.flash("Key rotated. It no longer works, and its owner has been emailed to collect the replacement.")
    return see_other(f"/teams/{team_id}/manage")


@app.post("/teams/{team_id}/members/{person_id}/remove")
def team_member_remove(request: Request, team_id: str, person_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("team.remove_member", team_id=team_id)
    result = visit.broker("POST", f"/teams/{quote(team_id)}/members/{quote(person_id)}/remove",
                          back=f"/teams/{team_id}/manage")
    visit.flash(f"Removed. {result['keys_deleted']} key(s) deleted.")
    return see_other(f"/teams/{team_id}/manage")


# ── Participant ─────────────────────────────────────────────────────────────

@app.get("/teams/{team_id}")
def my_team(request: Request, team_id: str):
    visit = Visit(request)
    visit.require("my.team", team_id=team_id)
    return visit.render("my_team.html", gateway_url=GATEWAY_URL, new_key=None,
                        **visit.broker("GET", f"/my/teams/{quote(team_id)}"))


@app.post("/teams/{team_id}/my/consent")
def my_consent(request: Request, team_id: str, csrf: str = Form(), terms_accepted: str = Form(""),
               research_use: str = Form("")):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("my.consent", team_id=team_id)
    visit.broker("POST", f"/my/teams/{quote(team_id)}/consent",
                 {"terms_accepted": terms_accepted == "yes", "research_use": research_use == "yes"},
                 back=f"/teams/{team_id}")
    visit.flash("Your choices are saved.")
    return see_other(f"/teams/{team_id}")


@app.post("/teams/{team_id}/my/keys")
def my_key_create(request: Request, team_id: str, csrf: str = Form(), name: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("my.key.create", team_id=team_id)
    created = visit.broker("POST", f"/my/teams/{quote(team_id)}/keys", {"name": name.strip()}, back=f"/teams/{team_id}")
    # Rendered straight into this response and never stored: this is the only time the key is shown.
    return visit.render("my_team.html", gateway_url=GATEWAY_URL, new_key=created,
                        **visit.broker("GET", f"/my/teams/{quote(team_id)}"))


@app.post("/teams/{team_id}/my/keys/{key_id}/rotate")
def my_key_rotate(request: Request, team_id: str, key_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("my.key.rotate", team_id=team_id)
    rotated = visit.broker("POST", f"/my/teams/{quote(team_id)}/keys/{quote(key_id)}/rotate", back=f"/teams/{team_id}")
    # As with a new key: rendered into this response only, never stored.
    return visit.render("my_team.html", gateway_url=GATEWAY_URL, new_key=rotated, rotated=True,
                        **visit.broker("GET", f"/my/teams/{quote(team_id)}"))


@app.post("/teams/{team_id}/my/keys/{key_id}/delete")
def my_key_delete(request: Request, team_id: str, key_id: str, csrf: str = Form()):
    visit = Visit(request)
    visit.check_csrf(csrf)
    visit.require("my.key.delete", team_id=team_id)
    visit.broker("POST", f"/my/teams/{quote(team_id)}/keys/{quote(key_id)}/delete", back=f"/teams/{team_id}")
    visit.flash("Key deleted.")
    return see_other(f"/teams/{team_id}")


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
