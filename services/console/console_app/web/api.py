"""The browser API: what the console's own pages call. Not for other services; those use /api/v1.

Every route reads the session cookie, checks the policy the broker will check again, calls the broker
as the signed-in user, and answers with a shape from `shapes`, never with the broker's reply itself.
"""

import csv
import io
import os
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, UploadFile
from pydantic import BaseModel

from . import graph, markdown, shapes
from .visit import ApiError, Visit, broker_plain

GATEWAY_URL = os.environ["GATEWAY_PUBLIC_URL"]
LITELLM_ADMIN_URL = os.environ.get("LITELLM_ADMIN_URL", "")

DLP_ACTIONS = {"block": "refused", "blocked": "refused", "mask": "hidden from the model",
               "whistledown": "swapped for a stand-in", "observe": "only noted"}

router = APIRouter(prefix="/web-api")


def knowledge_parts(view: dict, concept_id: str) -> dict:
    """What the knowledge page shows besides the list: the chosen concept as HTML, its links, the graph, the log."""
    by_id = {c["id"]: c for c in view["concepts"]}
    chosen = by_id.get(concept_id)
    for c in view["concepts"]:
        c["links"] = sum(c["id"] in (e["source"], e["target"]) for e in view["edges"])
    return {
        "concept": chosen,
        "links_out": [{**by_id[e["target"]], "note": e["note"]} for e in view["edges"]
                      if chosen and e["source"] == chosen["id"]],
        "links_in": [{**by_id[e["source"]], "note": e["note"]} for e in view["edges"]
                     if chosen and e["target"] == chosen["id"]],
        "body_html": markdown.render(chosen["body"], chosen["id"], set(by_id)) if chosen else "",
        "log_html": markdown.render(view["log"]) if view["log"] else "",
        "graph": graph.picture(view["concepts"], view["edges"], chosen["id"] if chosen else None),
    }


# ── Who is signed in ────────────────────────────────────────────────────────

@router.get("/session")
def session(request: Request):
    """Never a 401: the application asks this first, to choose between the sign-in screen and the rest."""
    try:
        visit = Visit(request, api=True)
    except ApiError as refusal:
        if refusal.status == 401:
            return {"signed_in": False}
        raise
    return shapes.session(visit.me, visit.data["csrf"], GATEWAY_URL, LITELLM_ADMIN_URL)


@router.get("/invites/{token}")
def invite(token: str):
    """What an invitation is for. Needs no session, and looking uses nothing up."""
    info = broker_plain("/invites/inspect", {"token": token}) if 20 <= len(token) <= 200 else {"valid": False}
    return shapes.invite(info)


# ── Page data ───────────────────────────────────────────────────────────────

@router.get("/admin/orgs")
def admin_orgs(request: Request):
    visit = Visit(request, api=True)
    visit.require("org.list")
    return shapes.admin_orgs(visit.broker("GET", "/admin/orgs"))


@router.get("/admin/audit")
def admin_audit(request: Request):
    visit = Visit(request, api=True)
    visit.require("audit.read")
    return shapes.audit(visit.broker("GET", "/admin/audit"))


@router.get("/admin/dlp")
def admin_dlp(request: Request):
    visit = Visit(request, api=True)
    visit.require("dlp.read")
    return shapes.dlp(visit.broker("GET", "/admin/dlp"), DLP_ACTIONS)


@router.get("/orgs/{org_id}")
def org(request: Request, org_id: str):
    visit = Visit(request, api=True)
    visit.require("org.view", org_id=org_id)
    view = visit.broker("GET", f"/orgs/{quote(org_id)}")
    return shapes.org(view, is_lead=org_id in visit.actor.lead_orgs, is_admin=visit.actor.is_admin)


@router.get("/orgs/{org_id}/knowledge")
def org_knowledge(request: Request, org_id: str, concept: str = ""):
    visit = Visit(request, api=True)
    visit.require("org.knowledge", org_id=org_id)
    view = visit.broker("GET", f"/orgs/{quote(org_id)}/knowledge")
    return shapes.knowledge(view, **knowledge_parts(view, concept))


@router.get("/teams/{team_id}/manage")
def team_manage(request: Request, team_id: str):
    visit = Visit(request, api=True)
    visit.require("team.view", team_id=team_id)
    view = visit.broker("GET", f"/teams/{quote(team_id)}/manage")
    usage = visit.broker("GET", f"/teams/{quote(team_id)}/usage")
    return shapes.team_manage(view, usage, is_lead=visit.me["team_orgs"].get(team_id) in visit.actor.lead_orgs)


@router.get("/teams/{team_id}")
def my_team(request: Request, team_id: str):
    visit = Visit(request, api=True)
    visit.require("my.team", team_id=team_id)
    return shapes.my_team(visit.broker("GET", f"/my/teams/{quote(team_id)}"))


# ── Actions ─────────────────────────────────────────────────────────────────
# One per form the pages have. Each answers with the sentence to show, `goto` when the next page is
# another one, and for a new or replacement key the key itself, in that one response only.

def acting(request: Request) -> Visit:
    """A signed-in request that changes something: the session's token must come with it, in a header."""
    visit = Visit(request, api=True)
    visit.check_csrf(request.headers.get("x-csrf-token", ""))
    return visit


def emails_from(text: str, upload: bytes) -> list[str]:
    """Addresses typed into the box plus any in an uploaded CSV (an `email` column, or the first column)."""
    found = [part.strip() for part in text.replace(",", "\n").replace(";", "\n").splitlines()]
    rows = list(csv.reader(io.StringIO(upload.decode("utf-8-sig", errors="replace"))))
    if rows:
        header = [c.strip().lower() for c in rows[0]]
        column = header.index("email") if "email" in header else 0
        found += [row[column].strip() for row in rows if len(row) > column]
    return [e for e in found if "@" in e]


class NewOrg(BaseModel):
    name: str
    slug: str
    budget_ceiling: float


class Ceiling(BaseModel):
    budget_ceiling: float


class ConfirmSlug(BaseModel):
    confirm_slug: str = ""


class ConfirmName(BaseModel):
    confirm_name: str = ""


class Email(BaseModel):
    email: str


class Decision(BaseModel):
    approve: bool


class NewIntegration(BaseModel):
    client_id: str
    name: str
    can_enroll: bool = False


class NewModel(BaseModel):
    provider: str
    model: str
    api_key: str
    api_base: str = ""
    api_version: str = ""


class NewTeam(BaseModel):
    name: str
    key_limit: int
    key_budget: float
    key_expiry_days: int
    team_budget: float
    consent_text: str


class Budget(BaseModel):
    team_budget: float


class TeamModels(BaseModel):
    model_ids: list[str] = []


class Consent(BaseModel):
    terms_accepted: bool = False
    research_use: bool = False


class NewKey(BaseModel):
    name: str


# SSEC admin

@router.post("/admin/orgs")
def admin_org_create(request: Request, body: NewOrg):
    visit = acting(request)
    visit.require("org.create")
    org = visit.broker("POST", "/admin/orgs", {"name": body.name, "slug": body.slug,
                                               "budget_ceiling": body.budget_ceiling})
    return {"message": f"Created {body.name}.", "goto": f"/orgs/{org['id']}"}


@router.post("/admin/orgs/{org_id}/suspend")
def admin_org_suspend(request: Request, org_id: str):
    visit = acting(request)
    visit.require("org.suspend")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/suspend")
    return {"message": "Organization suspended."}


@router.post("/admin/orgs/{org_id}/resume")
def admin_org_resume(request: Request, org_id: str):
    visit = acting(request)
    visit.require("org.resume")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/resume")
    return {"message": "Organization resumed."}


@router.post("/admin/orgs/{org_id}/ceiling")
def admin_org_ceiling(request: Request, org_id: str, body: Ceiling):
    visit = acting(request)
    visit.require("org.set_ceiling")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/ceiling", {"budget_ceiling": body.budget_ceiling})
    return {"message": "Budget ceiling updated."}


@router.post("/admin/orgs/{org_id}/remove")
def admin_org_remove(request: Request, org_id: str, body: ConfirmSlug):
    visit = acting(request)
    visit.require("org.remove")
    result = visit.broker("POST", f"/admin/orgs/{quote(org_id)}/remove", {"confirm_slug": body.confirm_slug.strip()})
    return {"message": f"Organization removed: {result['teams_archived']} team(s) archived, "
                       f"{result['keys_deleted']} key(s) deleted, {result['models_removed']} model(s) removed.",
            "goto": "/admin"}


@router.post("/admin/orgs/{org_id}/leads")
def admin_lead_invite(request: Request, org_id: str, body: Email):
    visit = acting(request)
    visit.require("org.appoint_lead")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/leads", {"email": body.email})
    return {"message": f"Invitation sent to {body.email}."}


@router.post("/admin/orgs/{org_id}/lead-requests/{invite_id}")
def admin_lead_request(request: Request, org_id: str, invite_id: str, body: Decision):
    visit = acting(request)
    visit.require("org.decide_lead_exception")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/lead-requests/{quote(invite_id)}", {"approve": body.approve})
    return {"message": "Request approved." if body.approve else "Request rejected."}


@router.post("/admin/orgs/{org_id}/leads/{person_id}/remove")
def admin_lead_remove(request: Request, org_id: str, person_id: str):
    visit = acting(request)
    visit.require("org.remove_lead")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/leads/{quote(person_id)}/remove")
    return {"message": "Lead removed."}


@router.post("/admin/orgs/{org_id}/lead-invites/{invite_id}/revoke")
def admin_lead_invite_revoke(request: Request, org_id: str, invite_id: str):
    visit = acting(request)
    visit.require("org.remove_lead")
    visit.broker("POST", f"/admin/orgs/{quote(org_id)}/lead-invites/{quote(invite_id)}/revoke")
    return {"message": "Invitation cancelled."}


@router.post("/admin/teams/{team_id}/remove")
def admin_team_remove(request: Request, team_id: str, body: ConfirmName):
    visit = acting(request)
    visit.require("team.remove")
    result = visit.broker("POST", f"/admin/teams/{quote(team_id)}/remove", {"confirm_name": body.confirm_name.strip()})
    return {"message": f"Team removed: {result['members_removed']} member(s) removed, "
                       f"{result['keys_deleted']} key(s) deleted.",
            "goto": f"/orgs/{result['org_id']}"}


@router.post("/admin/teams/{team_id}/integrations")
def admin_integration_register(request: Request, team_id: str, body: NewIntegration):
    visit = acting(request)
    visit.require("integration.register")
    visit.broker("POST", f"/admin/teams/{quote(team_id)}/integrations",
                 {"client_id": body.client_id.strip(), "name": body.name.strip(), "can_enroll": body.can_enroll})
    return {"message": f"Connected {body.name.strip()}."}


@router.post("/admin/integrations/{integration_id}/remove")
def admin_integration_remove(request: Request, integration_id: str):
    visit = acting(request)
    visit.require("integration.remove")
    result = visit.broker("POST", f"/admin/integrations/{quote(integration_id)}/remove")
    return {"message": f"Integration disconnected. {result['keys_deleted']} key(s) deleted.",
            "goto": f"/teams/{result['team_id']}/manage"}


# Org lead

@router.post("/orgs/{org_id}/models")
def org_model_add(request: Request, org_id: str, body: NewModel):
    visit = acting(request)
    visit.require("model.add", org_id=org_id)
    added = visit.broker("POST", f"/orgs/{quote(org_id)}/models", {
        "provider": body.provider, "model": body.model.strip(), "api_key": body.api_key.strip(),
        "api_base": body.api_base.strip() or None, "api_version": body.api_version.strip() or None})
    return {"message": f"Added {added['public_name']}. The key cannot be viewed again."}


@router.post("/orgs/{org_id}/models/{model_id}/remove")
def org_model_remove(request: Request, org_id: str, model_id: str):
    visit = acting(request)
    visit.require("model.remove", org_id=org_id)
    removed = visit.broker("POST", f"/orgs/{quote(org_id)}/models/{quote(model_id)}/remove")
    return {"message": f"Removed {removed['removed']}."}


@router.post("/orgs/{org_id}/teams")
def org_team_create(request: Request, org_id: str, body: NewTeam):
    visit = acting(request)
    visit.require("team.create", org_id=org_id)
    team = visit.broker("POST", f"/orgs/{quote(org_id)}/teams", {
        "name": body.name.strip(), "key_limit": body.key_limit, "key_budget": body.key_budget,
        "key_expiry_days": body.key_expiry_days, "team_budget": body.team_budget,
        "consent_text": body.consent_text.strip()})
    return {"message": f"Created {body.name}.", "goto": f"/teams/{team['id']}/manage"}


@router.post("/teams/{team_id}/invites")
async def team_invites(request: Request, team_id: str, emails: str = Form(""), csv_file: UploadFile | None = None):
    """The one action sent as a form, because it can carry a CSV file."""
    visit = acting(request)
    visit.require("team.invite", team_id=team_id)
    upload = await csv_file.read(200_001) if csv_file and csv_file.filename else b""
    if len(upload) > 200_000:
        raise ApiError(422, "That file is too large (200 KB at most).")
    addresses = emails_from(emails, upload)
    if not addresses:
        raise ApiError(422, "No email addresses found.")
    sent = visit.broker("POST", f"/teams/{quote(team_id)}/invites", {"emails": addresses})
    return {"message": f"Sent {sent['invited']} invitation(s)."}


@router.post("/teams/{team_id}/budget")
def team_budget(request: Request, team_id: str, body: Budget):
    visit = acting(request)
    visit.require("team.set_budget", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/budget", {"team_budget": body.team_budget})
    return {"message": "Team budget updated."}


@router.post("/teams/{team_id}/models")
def team_models(request: Request, team_id: str, body: TeamModels):
    visit = acting(request)
    visit.require("team.set_models", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/models", {"model_ids": body.model_ids})
    return {"message": "Models updated."}


@router.post("/teams/{team_id}/archive")
def team_archive(request: Request, team_id: str):
    visit = acting(request)
    visit.require("team.archive", team_id=team_id)
    result = visit.broker("POST", f"/teams/{quote(team_id)}/archive")
    return {"message": f"Team archived. {result['keys_deleted']} key(s) deleted."}


@router.post("/teams/{team_id}/invites/{invite_id}/revoke")
def team_invite_revoke(request: Request, team_id: str, invite_id: str):
    visit = acting(request)
    visit.require("team.cancel_invite", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/invites/{quote(invite_id)}/revoke")
    return {"message": "Invitation cancelled."}


@router.post("/teams/{team_id}/requests/{invite_id}")
def team_request(request: Request, team_id: str, invite_id: str, body: Decision):
    visit = acting(request)
    visit.require("team.decide_exception", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/requests/{quote(invite_id)}", {"approve": body.approve})
    return {"message": "Request approved." if body.approve else "Request rejected."}


@router.post("/teams/{team_id}/keys/{key_id}/revoke")
def team_key_revoke(request: Request, team_id: str, key_id: str):
    visit = acting(request)
    visit.require("team.revoke_key", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/keys/{quote(key_id)}/revoke")
    return {"message": "Key revoked."}


@router.post("/teams/{team_id}/keys/{key_id}/rotate")
def team_key_rotate(request: Request, team_id: str, key_id: str):
    visit = acting(request)
    visit.require("team.rotate_key", team_id=team_id)
    visit.broker("POST", f"/teams/{quote(team_id)}/keys/{quote(key_id)}/rotate")
    return {"message": "Key rotated. It no longer works, and its owner has been emailed to collect the replacement."}


@router.post("/teams/{team_id}/members/{person_id}/remove")
def team_member_remove(request: Request, team_id: str, person_id: str):
    visit = acting(request)
    visit.require("team.remove_member", team_id=team_id)
    result = visit.broker("POST", f"/teams/{quote(team_id)}/members/{quote(person_id)}/remove")
    return {"message": f"Removed. {result['keys_deleted']} key(s) deleted."}


# Participant

@router.post("/teams/{team_id}/my/consent")
def my_consent(request: Request, team_id: str, body: Consent):
    visit = acting(request)
    visit.require("my.consent", team_id=team_id)
    visit.broker("POST", f"/my/teams/{quote(team_id)}/consent",
                 {"terms_accepted": body.terms_accepted, "research_use": body.research_use})
    return {"message": "Your choices are saved."}


@router.post("/teams/{team_id}/my/keys")
def my_key_create(request: Request, team_id: str, body: NewKey):
    visit = acting(request)
    visit.require("my.key.create", team_id=team_id)
    created = visit.broker("POST", f"/my/teams/{quote(team_id)}/keys", {"name": body.name.strip()})
    # In this response and never stored: this is the only time the key leaves the broker.
    return {"key": shapes.key(created), "rotated": False}


@router.post("/teams/{team_id}/my/keys/{key_id}/rotate")
def my_key_rotate(request: Request, team_id: str, key_id: str):
    visit = acting(request)
    visit.require("my.key.rotate", team_id=team_id)
    rotated = visit.broker("POST", f"/my/teams/{quote(team_id)}/keys/{quote(key_id)}/rotate")
    return {"key": shapes.key(rotated), "rotated": True}  # as with a new key: here only, never stored


@router.post("/teams/{team_id}/my/keys/{key_id}/delete")
def my_key_delete(request: Request, team_id: str, key_id: str):
    visit = acting(request)
    visit.require("my.key.delete", team_id=team_id)
    visit.broker("POST", f"/my/teams/{quote(team_id)}/keys/{quote(key_id)}/delete")
    return {"message": "Key deleted."}
