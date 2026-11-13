"""The browser API: what the console's own pages call. Not for other services; those use /api/v1.

Every route reads the session cookie, checks the policy the broker will check again, calls the broker
as the signed-in user, and answers with a shape from `shapes`, never with the broker's reply itself.
"""

import os
from urllib.parse import quote

from fastapi import APIRouter, Request

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
