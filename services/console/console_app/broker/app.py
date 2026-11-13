"""console-broker: the only service that holds the LiteLLM admin key and org data.

It offers a fixed set of operations and no passthrough. Each one:
  1. identifies the user from their signed access token (auth.py),
  2. looks the target's org up in the database, never trusting the request for it,
  3. asks policy.allowed, and
  4. writes an audit event, whatever the outcome.
"""

import hashlib
import json
import os
import secrets
import smtplib
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from .. import policy
from . import db, dlp, keycloak, knowledge, litellm
from .auth import WEB_CLIENT_ID, IntegrationSession, Session, current_session, integration_session, require_caller

PUBLIC_URL = os.environ["CONSOLE_PUBLIC_URL"]
INVITE_TTL = timedelta(hours=int(os.environ.get("CONSOLE_INVITE_TTL_HOURS", "72")))
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
MAIL_FROM = os.environ.get("MAIL_FROM", "console@llmoxie.localhost")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.pool.open(wait=True)
    yield
    db.pool.close()


app = FastAPI(title="console-broker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(litellm.LiteLLMError)
def litellm_failed(_, exc: litellm.LiteLLMError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(keycloak.KeycloakError)
def keycloak_failed(_, exc: keycloak.KeycloakError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(knowledge.HubError)
def hub_failed(_, exc: knowledge.HubError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── Helpers ─────────────────────────────────────────────────────────────────

def audit(s: Session | None, action: str, result: str, *, org_id=None, team_id=None, target=None, **detail) -> None:
    """Append one audit event, and copy it to stdout so it also lands in storage the console cannot rewrite."""
    event = {
        "actor_person_id": s.actor.person_id if s else None,
        "actor_role": (getattr(s, "role_label", None) or s.actor.role) if s else None,
        "org_id": str(org_id) if org_id else None,
        "team_id": str(team_id) if team_id else None,
        "action": action,
        "target": str(target) if target else None,
        "result": result,
        "detail": detail,
    }
    with db.system_tx() as conn:
        conn.execute(
            """INSERT INTO audit_event (actor_person_id, actor_role, org_id, team_id, action, target, result, detail)
               VALUES (%(actor_person_id)s, %(actor_role)s, %(org_id)s, %(team_id)s, %(action)s, %(target)s,
                       %(result)s, %(detail)s::jsonb)""",
            {**event, "detail": json.dumps(detail, default=str)},
        )
    print(json.dumps({"audit": event, "at": datetime.now(timezone.utc).isoformat()}, default=str), file=sys.stdout, flush=True)


def find_org(org_id: UUID) -> dict | None:
    with db.system_tx() as conn:
        # A removed org is gone as far as every operation is concerned.
        return conn.execute("SELECT * FROM org WHERE id = %s AND status <> 'removed'", (org_id,)).fetchone()


def find_team(team_id: UUID) -> dict | None:
    with db.system_tx() as conn:
        return conn.execute(
            """SELECT t.*, o.slug AS org_slug, o.name AS org_name, o.status AS org_status,
                      o.budget_ceiling AS org_budget_ceiling
               FROM team t JOIN org o ON o.id = t.org_id
               WHERE t.id = %s AND o.status <> 'removed' AND t.status <> 'removed'""",
            (team_id,)).fetchone()


def require(s: Session, action: str, *, org: dict | None = None, team: dict | None = None, target=None) -> None:
    """Deny unless the policy allows it. An unknown org or team is denied the same way, so ids cannot be probed."""
    org_id = str(team["org_id"]) if team else (str(org["id"]) if org else None)
    team_id = str(team["id"]) if team else None
    if not policy.allowed(s.actor, action, org_id=org_id, team_id=team_id):
        audit(s, action, "denied", org_id=org_id, team_id=team_id, target=target)
        raise HTTPException(403, "not allowed")
    if action not in policy.READ_ONLY and policy.ACTIONS[action] != policy.ADMIN:
        org_status = team["org_status"] if team else org["status"]
        if org_status != "active" and not s.actor.is_admin:  # an admin can still remove people while it is suspended
            raise HTTPException(409, "this organization is suspended")
        if team and team["status"] != "active":
            raise HTTPException(409, "this team is archived")


def send_invite(email: str, token: str, what: str) -> None:
    message = EmailMessage()
    message["From"], message["To"] = MAIL_FROM, email
    message["Subject"] = f"You are invited to {what}"
    message.set_content(
        f"You have been invited to {what} on the LLMoxie console.\n\n"
        f"Open this link and sign in with this email address ({email}):\n\n"
        f"{PUBLIC_URL}/invite/{token}\n\n"
        f"The link works once and expires in {int(INVITE_TTL.total_seconds() // 3600)} hours.\n")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)


def send_notice(email: str | None, subject: str, body: str) -> None:
    if not email:
        return
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = MAIL_FROM, email, subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)


def create_invite(conn, s: Session, *, org_id, team_id, kind: str, email: str) -> str:
    """Store a hashed single-use token and return the token itself, which goes only into the email."""
    token = secrets.token_urlsafe(32)
    conn.execute(
        """UPDATE invite SET status = 'revoked'
           WHERE org_id = %s AND team_id IS NOT DISTINCT FROM %s::uuid AND kind = %s AND lower(email) = %s
             AND status = 'pending'""", (org_id, team_id, kind, email))
    conn.execute(
        """INSERT INTO invite (org_id, team_id, kind, email, token_hash, expires_at, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (org_id, team_id, kind, email, hashlib.sha256(token.encode()).hexdigest(),
         datetime.now(timezone.utc) + INVITE_TTL, s.actor.person_id))
    return token


def grant_membership(conn, invite: dict) -> None:
    if invite["kind"] == "lead":
        conn.execute("INSERT INTO org_lead (org_id, person_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                     (invite["org_id"], invite["person_id"]))
    else:
        conn.execute(
            """INSERT INTO team_member (team_id, person_id, org_id) VALUES (%s, %s, %s)
               ON CONFLICT (team_id, person_id) DO UPDATE SET status = 'active'""",
            (invite["team_id"], invite["person_id"], invite["org_id"]))


def decide_invite(s: Session, invite_id: UUID, approve: bool, *, org_id, team_id) -> dict:
    """Approve or reject a sign-in whose email did not match its invite."""
    with db.org_tx(org_id) as conn:
        invite = conn.execute(
            """SELECT * FROM invite WHERE id = %s AND team_id IS NOT DISTINCT FROM %s::uuid
                 AND status = 'needs_approval' FOR UPDATE""", (invite_id, team_id)).fetchone()
        if not invite:
            raise HTTPException(404, "no such request")
        conn.execute("UPDATE invite SET status = %s, decided_by = %s, decided_at = now() WHERE id = %s",
                     ("consumed" if approve else "rejected", s.actor.person_id, invite_id))
        if approve:
            grant_membership(conn, invite)
    return invite


def delete_keys(conn, where: str, params: tuple) -> int:
    """Delete matching keys in LiteLLM, then mark them deleted here."""
    rows = conn.execute(
        f"SELECT id, key_alias, status FROM api_key WHERE status <> 'deleted' AND {where} FOR UPDATE", params).fetchall()
    litellm.key_delete([r["key_alias"] for r in rows if r["status"] == "active"])  # 'creating' has no secret yet
    conn.execute("UPDATE api_key SET status = 'deleted', deleted_at = now() WHERE id = ANY(%s)",
                 ([r["id"] for r in rows],))
    return len(rows)


def sync_team_models(conn, team_id) -> None:
    """What the team's keys may call: the models its lead ticked."""
    names = [r["public_name"] for r in conn.execute(
        """SELECT m.public_name FROM team_model tm JOIN org_model m ON m.id = tm.org_model_id
           WHERE tm.team_id = %s AND m.removed_at IS NULL
           ORDER BY public_name""", (team_id,))]
    litellm.team_set_models(str(team_id), names)


# ── Everyone ────────────────────────────────────────────────────────────────

@app.get("/me")
def me(s: Session = Depends(current_session)):
    with db.system_tx() as conn:
        lead_orgs = conn.execute(
            "SELECT id, name, slug, status FROM org WHERE id = ANY(%s) ORDER BY name",
            ([UUID(o) for o in s.actor.lead_orgs],)).fetchall()
        teams = conn.execute(
            """SELECT t.id, t.name, t.status, t.org_id, o.name AS org_name FROM team t JOIN org o ON o.id = t.org_id
               WHERE t.id = ANY(%s) ORDER BY o.name, t.name""",
            ([UUID(t) for t in s.actor.member_teams],)).fetchall()
        led_teams = conn.execute(  # an admin may look at every team
            "SELECT id, org_id FROM team WHERE status <> 'removed' AND (%s OR org_id = ANY(%s))",
            (s.actor.is_admin, [UUID(o) for o in s.actor.lead_orgs])).fetchall()
    return {
        "person_id": s.actor.person_id,
        "participant_id": s.person["participant_id"],
        "email": s.verified_email,
        "is_admin": s.actor.is_admin,
        "lead_orgs": lead_orgs,
        "teams": teams,
        # team id -> org id for every team this person may touch; console-web feeds it to the same policy
        "team_orgs": {**{str(t["id"]): str(t["org_id"]) for t in led_teams}, **s.actor.member_teams},
    }


class TokenBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)


def _invite_by_token(conn, token: str, lock: bool = False) -> dict | None:
    return conn.execute(
        f"""SELECT i.*, o.name AS org_name, o.status AS org_status, t.name AS team_name, t.status AS team_status
            FROM invite i JOIN org o ON o.id = i.org_id LEFT JOIN team t ON t.id = i.team_id
            WHERE i.token_hash = %s {'FOR UPDATE OF i' if lock else ''}""",
        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()


def _usable(invite: dict | None) -> bool:
    return bool(invite and invite["status"] == "pending" and invite["expires_at"] > datetime.now(timezone.utc)
                and invite["org_status"] == "active" and invite["team_status"] in (None, "active"))


@app.post("/invites/inspect", dependencies=[Depends(require_caller)])
def invite_inspect(body: TokenBody):
    """What an invite is for, shown before sign-in. Reading it never uses it up."""
    with db.system_tx() as conn:
        invite = _invite_by_token(conn, body.token)
    if not _usable(invite):
        return {"valid": False}
    return {"valid": True, "kind": invite["kind"], "org_name": invite["org_name"], "team_name": invite["team_name"]}


@app.post("/invites/accept")
def invite_accept(body: TokenBody, s: Session = Depends(current_session)):
    with db.system_tx() as conn:
        invite = _invite_by_token(conn, body.token, lock=True)
        if not _usable(invite):
            outcome = "invalid"
        else:
            invite["person_id"] = s.actor.person_id
            if s.verified_email and s.verified_email == invite["email"].lower():
                conn.execute("UPDATE invite SET status = 'consumed', person_id = %s WHERE id = %s",
                             (s.actor.person_id, invite["id"]))
                grant_membership(conn, invite)
                outcome = "joined"
            else:  # wrong or unproven email: no access until the lead (or an admin) approves
                conn.execute(
                    "UPDATE invite SET status = 'needs_approval', person_id = %s, signin_email = %s WHERE id = %s",
                    (s.actor.person_id, s.verified_email, invite["id"]))
                outcome = "needs_approval"
    audit(s, "invite.accept", "ok" if outcome == "joined" else outcome,
          org_id=invite["org_id"] if invite else None, team_id=invite["team_id"] if invite else None,
          target=invite["id"] if invite else None)
    return {"outcome": outcome, "kind": invite["kind"] if invite else None,
            "team_id": invite["team_id"] if invite else None, "org_id": invite["org_id"] if invite else None}


# ── SSEC admin ──────────────────────────────────────────────────────────────

class OrgBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,30}$")
    budget_ceiling: float = Field(ge=0, le=1_000_000)


class CeilingBody(BaseModel):
    budget_ceiling: float = Field(ge=0, le=1_000_000)


class EmailBody(BaseModel):
    email: EmailStr


class DecisionBody(BaseModel):
    approve: bool


@app.get("/admin/orgs")
def admin_orgs(s: Session = Depends(current_session)):
    require(s, "org.list")
    with db.system_tx() as conn:
        return conn.execute(
            """SELECT o.*, (SELECT count(*) FROM org_lead l WHERE l.org_id = o.id) AS leads,
                      (SELECT count(*) FROM team t WHERE t.org_id = o.id AND t.status <> 'removed') AS teams
               FROM org o WHERE o.status <> 'removed' ORDER BY o.name""").fetchall()


@app.post("/admin/orgs")
def admin_org_create(body: OrgBody, s: Session = Depends(current_session)):
    require(s, "org.create")
    with db.system_tx() as conn:
        if conn.execute("SELECT 1 FROM org WHERE slug = %s", (body.slug,)).fetchone():
            raise HTTPException(409, "that short name is taken")
        org = conn.execute("INSERT INTO org (name, slug, budget_ceiling) VALUES (%s, %s, %s) RETURNING *",
                           (body.name, body.slug, body.budget_ceiling)).fetchone()
        # The org's knowledge: a Keycloak client that may reach only this org's bundle in the hub, and an
        # MCP server in LiteLLM that signs in as that client. A failure here undoes the insert.
        secret = keycloak.org_client_create(body.slug)
        server_id = litellm.mcp_server_new(
            body.slug, f"{keycloak.HUB_URL}/mcp?bundle={keycloak.bundle(body.slug)}", keycloak.TOKEN_URL,
            keycloak.client_id(body.slug), secret)
        org = conn.execute("UPDATE org SET mcp_server_id = %s WHERE id = %s RETURNING *",
                           (server_id, org["id"])).fetchone()
    audit(s, "org.create", "ok", org_id=org["id"], target=body.slug)
    return org


def _set_org_status(s: Session, org_id: UUID, action: str, status: str):
    require(s, action)
    org = find_org(org_id)
    if not org:
        raise HTTPException(404, "no such organization")
    with db.org_tx(org_id) as conn:
        conn.execute("UPDATE org SET status = %s WHERE id = %s", (status, org_id))
        for team in conn.execute("SELECT id FROM team WHERE status = 'active'").fetchall():
            (litellm.team_block if status == "suspended" else litellm.team_unblock)(str(team["id"]))
            litellm.team_set_knowledge(str(team["id"]), None if status == "suspended" else org["mcp_server_id"])
    audit(s, action, "ok", org_id=org_id)
    return {"status": status}


class RemoveOrgBody(BaseModel):
    confirm_slug: str = Field(max_length=40)


@app.post("/admin/orgs/{org_id}/remove")
def admin_org_remove(org_id: UUID, body: RemoveOrgBody, s: Session = Depends(current_session)):
    """Close an organization for good.

    Every key is deleted, every team archived and blocked, the org's models and provider keys are
    removed from LiteLLM, and its leads and members lose it. Its knowledge can no longer be reached: the
    MCP server and the Keycloak client behind it are deleted, while the bundle itself stays in the hub.
    The org's rows, consent records and audit events stay, and its short name is not given out again,
    since it appears in the request logs and names the bundle.
    """
    require(s, "org.remove")
    org = find_org(org_id)
    if not org:
        raise HTTPException(404, "no such organization")
    if body.confirm_slug != org["slug"]:
        raise HTTPException(422, "type the organization's short name exactly to confirm")
    with db.org_tx(org_id) as conn:
        conn.execute("SELECT 1 FROM org WHERE id = %s FOR UPDATE", (org_id,))
        keys = delete_keys(conn, "org_id = %s", (org_id,))  # this is what stops access
        teams = conn.execute("SELECT id FROM team WHERE status = 'active'").fetchall()
        for team in teams:
            litellm.team_set_models(str(team["id"]), [])
            litellm.team_block(str(team["id"]))
        conn.execute("UPDATE team SET status = 'archived', archived_at = now() WHERE status = 'active'")
        conn.execute("DELETE FROM team_model")
        models = conn.execute("SELECT id, litellm_model_id FROM org_model WHERE removed_at IS NULL").fetchall()
        for model in models:
            litellm.model_delete(model["litellm_model_id"], missing_ok=True)  # takes the provider key with it
        conn.execute("UPDATE org_model SET removed_at = now() WHERE removed_at IS NULL")
        if org["mcp_server_id"]:
            litellm.mcp_server_delete(org["mcp_server_id"])
        keycloak.org_client_delete(org["slug"])
        conn.execute("UPDATE invite SET status = 'revoked' WHERE status IN ('pending', 'needs_approval')")
        conn.execute("UPDATE team_member SET status = 'removed' WHERE status = 'active'")
        conn.execute("DELETE FROM org_lead")
        conn.execute("UPDATE org SET status = 'removed', mcp_server_id = NULL WHERE id = %s", (org_id,))
    audit(s, "org.remove", "ok", org_id=org_id, target=org["slug"], keys_deleted=keys, teams_archived=len(teams),
          models_removed=len(models))
    return {"keys_deleted": keys, "teams_archived": len(teams), "models_removed": len(models)}


class RemoveTeamBody(BaseModel):
    confirm_name: str = Field(max_length=80)


@app.post("/admin/teams/{team_id}/remove")
def admin_team_remove(team_id: UUID, body: RemoveTeamBody, s: Session = Depends(current_session)):
    """Take a team away for good, active or archived.

    Its keys are deleted, it is blocked in LiteLLM, and its members and pending invitations lose it.
    Unlike a lead's archive, the team also disappears from the console; its records stay in the database.
    The org's models and provider keys are not touched.
    """
    require(s, "team.remove")
    team = find_team(team_id)
    if not team:
        raise HTTPException(404, "no such team")
    if body.confirm_name != team["name"]:
        raise HTTPException(422, "type the team's name exactly to confirm")
    with db.org_tx(team["org_id"]) as conn:
        conn.execute("SELECT 1 FROM team WHERE id = %s FOR UPDATE", (team_id,))
        keys = delete_keys(conn, "team_id = %s", (team_id,))
        conn.execute("DELETE FROM team_model WHERE team_id = %s", (team_id,))
        litellm.team_set_models(str(team_id), [])
        litellm.team_block(str(team_id))
        conn.execute("UPDATE invite SET status = 'revoked' WHERE team_id = %s AND status IN ('pending', 'needs_approval')",
                     (team_id,))
        members = conn.execute(
            "UPDATE team_member SET status = 'removed' WHERE team_id = %s AND status = 'active'", (team_id,)).rowcount
        conn.execute("UPDATE team SET status = 'removed', archived_at = coalesce(archived_at, now()) WHERE id = %s",
                     (team_id,))
    audit(s, "team.remove", "ok", org_id=team["org_id"], team_id=team_id, target=team["name"], keys_deleted=keys,
          members_removed=members)
    return {"org_id": team["org_id"], "keys_deleted": keys, "members_removed": members}


@app.post("/admin/orgs/{org_id}/suspend")
def admin_org_suspend(org_id: UUID, s: Session = Depends(current_session)):
    return _set_org_status(s, org_id, "org.suspend", "suspended")


@app.post("/admin/orgs/{org_id}/resume")
def admin_org_resume(org_id: UUID, s: Session = Depends(current_session)):
    return _set_org_status(s, org_id, "org.resume", "active")


@app.post("/admin/orgs/{org_id}/ceiling")
def admin_org_ceiling(org_id: UUID, body: CeilingBody, s: Session = Depends(current_session)):
    require(s, "org.set_ceiling")
    with db.org_tx(org_id) as conn:
        over = conn.execute("SELECT max(team_budget) AS top FROM team WHERE status = 'active'").fetchone()["top"]
        if over is not None and float(over) > body.budget_ceiling:
            raise HTTPException(409, f"a team in this organization has a budget of {over}; lower that first")
        if conn.execute("UPDATE org SET budget_ceiling = %s WHERE id = %s AND status <> 'removed'",
                        (body.budget_ceiling, org_id)).rowcount != 1:
            raise HTTPException(404, "no such organization")
    audit(s, "org.set_ceiling", "ok", org_id=org_id, budget_ceiling=body.budget_ceiling)
    return {"budget_ceiling": body.budget_ceiling}


@app.post("/admin/orgs/{org_id}/leads")
def admin_appoint_lead(org_id: UUID, body: EmailBody, s: Session = Depends(current_session)):
    require(s, "org.appoint_lead")
    org = find_org(org_id)
    if not org:
        raise HTTPException(404, "no such organization")
    email = body.email.lower()
    with db.org_tx(org_id) as conn:
        token = create_invite(conn, s, org_id=org_id, team_id=None, kind="lead", email=email)
    send_invite(email, token, f"lead {org['name']}")
    audit(s, "org.appoint_lead", "ok", org_id=org_id, target=email)
    return {"invited": email}


@app.post("/admin/orgs/{org_id}/lead-requests/{invite_id}")
def admin_decide_lead(org_id: UUID, invite_id: UUID, body: DecisionBody, s: Session = Depends(current_session)):
    require(s, "org.decide_lead_exception")
    decide_invite(s, invite_id, body.approve, org_id=org_id, team_id=None)
    audit(s, "org.decide_lead_exception", "ok", org_id=org_id, target=invite_id, approved=body.approve)
    return {"approved": body.approve}


@app.post("/admin/orgs/{org_id}/leads/{person_id}/remove")
def admin_remove_lead(org_id: UUID, person_id: UUID, s: Session = Depends(current_session)):
    """Take an org away from a lead. Their account, and whatever they set up in the org, stays."""
    require(s, "org.remove_lead")
    with db.org_tx(org_id) as conn:
        removed = conn.execute(
            "DELETE FROM org_lead WHERE org_id = %s AND person_id = %s", (org_id, person_id)).rowcount
    if not removed:
        raise HTTPException(404, "not a lead of this organization")
    audit(s, "org.remove_lead", "ok", org_id=org_id, target=person_id)
    return {"removed": True}


@app.post("/admin/orgs/{org_id}/lead-invites/{invite_id}/revoke")
def admin_revoke_lead_invite(org_id: UUID, invite_id: UUID, s: Session = Depends(current_session)):
    """Cancel a lead invitation that has not been accepted, or is waiting for approval."""
    require(s, "org.remove_lead")
    with db.org_tx(org_id) as conn:
        revoked = conn.execute(
            """UPDATE invite SET status = 'revoked', decided_by = %s, decided_at = now()
               WHERE id = %s AND kind = 'lead' AND status IN ('pending', 'needs_approval')""",
            (s.actor.person_id, invite_id)).rowcount
    if not revoked:
        raise HTTPException(404, "no such invitation")
    audit(s, "org.remove_lead", "ok", org_id=org_id, target=invite_id, invitation=True)
    return {"revoked": True}


@app.get("/admin/audit")
def admin_audit(s: Session = Depends(current_session)):
    require(s, "audit.read")
    with db.system_tx() as conn:
        return conn.execute(
            """SELECT a.*, p.email AS actor_email, o.name AS org_name, t.name AS team_name
               FROM audit_event a LEFT JOIN person p ON p.id = a.actor_person_id
               LEFT JOIN org o ON o.id = a.org_id LEFT JOIN team t ON t.id = a.team_id
               ORDER BY a.id DESC LIMIT 300""").fetchall()


@app.get("/admin/dlp")
def admin_dlp(s: Session = Depends(current_session)):
    """What ceil-dlp found in requests to models. Kinds, actions and counts; never a value."""
    require(s, "dlp.read")
    view = dlp.recent()
    with db.system_tx() as conn:
        people = {r["participant_id"]: r["email"] for r in conn.execute(
            "SELECT participant_id, email FROM person WHERE participant_id = ANY(%s)",
            ([e["user_id"] for e in view["events"] if e["user_id"]],))}
    for event in view["events"]:
        event["email"] = people.get(event["user_id"])
    return {"enabled": dlp.enabled(), "shown": dlp.SHOWN, **view}


# ── Org lead ────────────────────────────────────────────────────────────────

MODEL_NAME = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$"


class ModelBody(BaseModel):
    provider: str
    model: str = Field(pattern=MODEL_NAME)
    api_key: str = Field(min_length=1, max_length=500)
    api_base: str | None = Field(default=None, max_length=200)
    api_version: str | None = Field(default=None, max_length=30)


class TeamBody(BaseModel):
    name: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    key_limit: int = Field(ge=1, le=20)
    key_budget: float = Field(ge=0, le=1_000_000)
    key_expiry_days: int = Field(ge=1, le=365)
    team_budget: float = Field(ge=0, le=1_000_000)
    consent_text: str = Field(min_length=20, max_length=20_000)


class BudgetBody(BaseModel):
    team_budget: float = Field(ge=0, le=1_000_000)


class TeamModelsBody(BaseModel):
    model_ids: list[UUID] = Field(max_length=200)


class InvitesBody(BaseModel):
    emails: list[EmailStr] = Field(min_length=1, max_length=500)


@app.get("/orgs/{org_id}")
def org_view(org_id: UUID, s: Session = Depends(current_session)):
    org = find_org(org_id)
    require(s, "org.view", org=org, target=org_id)
    with db.org_tx(org_id) as conn:
        return {
            "org": org,
            "providers": litellm.provider_names(),
            "leads": conn.execute(
                "SELECT p.id, p.email FROM org_lead l JOIN person p ON p.id = l.person_id ORDER BY p.email").fetchall(),
            "lead_invites": conn.execute(
                """SELECT i.id, i.email, i.status, i.signin_email, i.expires_at FROM invite i
                   WHERE i.kind = 'lead' AND i.status IN ('pending', 'needs_approval') ORDER BY i.created_at""").fetchall(),
            "models": conn.execute(
                "SELECT id, provider, model, public_name, created_at FROM org_model WHERE removed_at IS NULL "
                "ORDER BY public_name").fetchall(),
            "teams": conn.execute(
                """SELECT t.id, t.name, t.status, t.team_budget,
                          (SELECT count(*) FROM team_member m WHERE m.team_id = t.id AND m.status = 'active') AS members
                   FROM team t WHERE t.status <> 'removed' ORDER BY t.status, t.name""").fetchall(),
        }


@app.get("/orgs/{org_id}/knowledge")
def org_knowledge(org_id: UUID, s: Session = Depends(current_session)):
    """Everything in the org's knowledge base, for its leads. Members reach the same content through MCP."""
    org = find_org(org_id)
    require(s, "org.knowledge", org=org, target=org_id)
    view = knowledge.bundle_view(org["slug"])
    audit(s, "org.knowledge", "ok", org_id=org_id, concepts=len(view["concepts"]))
    return {"org": {k: org[k] for k in ("id", "name", "slug", "status")}, "tools": litellm.mcp_server_name(org["slug"]),
            **view}


@app.post("/orgs/{org_id}/models")
def model_add(org_id: UUID, body: ModelBody, s: Session = Depends(current_session)):
    org = find_org(org_id)
    require(s, "model.add", org=org, target=org_id)
    try:
        params = litellm.model_params(body.provider, body.model, body.api_key, body.api_base, body.api_version)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    public_name = f"{org['slug']}/{body.model}"
    with db.org_tx(org_id) as conn:
        if conn.execute("SELECT 1 FROM org_model WHERE public_name = %s AND removed_at IS NULL", (public_name,)).fetchone():
            raise HTTPException(409, "this organization already has that model")
        model_id = litellm.model_new(public_name, params)
        row = conn.execute(
            """INSERT INTO org_model (org_id, provider, model, public_name, litellm_model_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING id, public_name""",
            (org_id, body.provider, body.model, public_name, model_id)).fetchone()
    audit(s, "model.add", "ok", org_id=org_id, target=public_name, provider=body.provider)  # never the key
    return row


@app.post("/orgs/{org_id}/models/{model_id}/remove")
def model_remove(org_id: UUID, model_id: UUID, s: Session = Depends(current_session)):
    org = find_org(org_id)
    require(s, "model.remove", org=org, target=model_id)
    with db.org_tx(org_id) as conn:
        model = conn.execute(
            "SELECT * FROM org_model WHERE id = %s AND removed_at IS NULL FOR UPDATE", (model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "no such model")
        teams = conn.execute("DELETE FROM team_model WHERE org_model_id = %s RETURNING team_id", (model_id,)).fetchall()
        conn.execute("UPDATE org_model SET removed_at = now() WHERE id = %s", (model_id,))
        for team in teams:
            sync_team_models(conn, team["team_id"])
        litellm.model_delete(model["litellm_model_id"])
    audit(s, "model.remove", "ok", org_id=org_id, target=model["public_name"])
    return {"removed": model["public_name"]}


@app.post("/orgs/{org_id}/teams")
def team_create(org_id: UUID, body: TeamBody, s: Session = Depends(current_session)):
    org = find_org(org_id)
    require(s, "team.create", org=org, target=org_id)
    if body.team_budget > float(org["budget_ceiling"]):
        raise HTTPException(422, f"the team budget cannot exceed the organization's ceiling of {org['budget_ceiling']}")
    if body.key_budget > body.team_budget:
        raise HTTPException(422, "the per-key budget cannot exceed the team budget")
    team_id = uuid.uuid4()
    with db.org_tx(org_id) as conn:
        if conn.execute("SELECT 1 FROM team WHERE name = %s AND status <> 'removed'", (body.name,)).fetchone():
            raise HTTPException(409, "this organization already has a team with that name")
        conn.execute(
            """INSERT INTO team (id, org_id, name, key_limit, key_budget, key_expiry_days, team_budget, consent_text)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (team_id, org_id, body.name, body.key_limit, body.key_budget, body.key_expiry_days, body.team_budget,
             body.consent_text))
        litellm.team_new(str(team_id), f"{org['slug']}/{body.name}", body.team_budget, org["mcp_server_id"])
    audit(s, "team.create", "ok", org_id=org_id, team_id=team_id, target=body.name)
    return {"id": team_id}


@app.get("/teams/{team_id}/manage")
def team_view(team_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.view", team=team, target=team_id)
    in_litellm = litellm.team_keys(str(team_id)) if team["status"] == "active" else {}
    with db.org_tx(team["org_id"]) as conn:
        keys = conn.execute(
            """SELECT k.id, k.name, k.key_alias, k.status, k.created_at, p.email FROM api_key k JOIN person p ON p.id = k.person_id
               WHERE k.team_id = %s AND k.status <> 'deleted' ORDER BY p.email, k.created_at""", (team_id,)).fetchall()
        return {
            "team": team,
            # Names, owners and totals only. The keys themselves are not stored anywhere they could be read back.
            "keys": [{"id": k["id"], "name": k["name"], "email": k["email"], "created_at": k["created_at"],
                      "waiting": k["status"] == "creating",  # rotated by a lead, not yet collected by its owner
                      **in_litellm.get(k["key_alias"], {"hint": None, "spend": 0.0, "expires": None, "last_used": None})}
                     for k in keys],
            "models": conn.execute(
                """SELECT m.id, m.public_name, m.provider,
                          EXISTS (SELECT 1 FROM team_model tm WHERE tm.team_id = %s AND tm.org_model_id = m.id) AS allowed
                   FROM org_model m WHERE m.removed_at IS NULL ORDER BY m.public_name""", (team_id,)).fetchall(),
            "members": conn.execute(
                """SELECT p.id, p.email, p.participant_id,
                          (SELECT count(*) FROM api_key k WHERE k.team_id = m.team_id AND k.person_id = p.id
                             AND k.status = 'active') AS keys,
                          (SELECT c.terms_accepted FROM consent c WHERE c.team_id = m.team_id AND c.person_id = p.id
                             ORDER BY c.id DESC LIMIT 1) AS terms_accepted
                   FROM team_member m JOIN person p ON p.id = m.person_id
                   WHERE m.team_id = %s AND m.status = 'active' ORDER BY p.email""", (team_id,)).fetchall(),
            "invites": conn.execute(
                """SELECT id, email, status, signin_email, expires_at FROM invite
                   WHERE team_id = %s AND status IN ('pending', 'needs_approval') ORDER BY created_at""",
                (team_id,)).fetchall(),
            "integrations": conn.execute(
                """SELECT id, name, client_id, can_enroll, created_at FROM integration
                   WHERE team_id = %s AND removed_at IS NULL ORDER BY name""", (team_id,)).fetchall(),
        }


@app.post("/teams/{team_id}/budget")
def team_set_budget(team_id: UUID, body: BudgetBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.set_budget", team=team, target=team_id)
    if body.team_budget > float(team["org_budget_ceiling"]):
        raise HTTPException(422, f"the organization's ceiling is {team['org_budget_ceiling']}")
    if body.team_budget < float(team["key_budget"]):
        raise HTTPException(422, f"the team budget cannot be below the per-key budget of {team['key_budget']}")
    with db.org_tx(team["org_id"]) as conn:
        conn.execute("UPDATE team SET team_budget = %s WHERE id = %s", (body.team_budget, team_id))
        litellm.team_set_budget(str(team_id), body.team_budget)
    audit(s, "team.set_budget", "ok", org_id=team["org_id"], team_id=team_id, team_budget=body.team_budget)
    return {"team_budget": body.team_budget}


@app.post("/teams/{team_id}/models")
def team_set_models(team_id: UUID, body: TeamModelsBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.set_models", team=team, target=team_id)
    with db.org_tx(team["org_id"]) as conn:
        # Row-level security limits this to the org's own models, whatever ids were sent.
        mine = conn.execute(
            "SELECT id FROM org_model WHERE id = ANY(%s) AND removed_at IS NULL", (body.model_ids,)).fetchall()
        if len(mine) != len(set(body.model_ids)):
            raise HTTPException(422, "unknown model")
        conn.execute("DELETE FROM team_model WHERE team_id = %s", (team_id,))
        for row in mine:
            conn.execute("INSERT INTO team_model (team_id, org_model_id, org_id) VALUES (%s, %s, %s)",
                         (team_id, row["id"], team["org_id"]))
        sync_team_models(conn, team_id)
    audit(s, "team.set_models", "ok", org_id=team["org_id"], team_id=team_id, count=len(mine))
    return {"models": len(mine)}


@app.post("/teams/{team_id}/invites")
def team_invite(team_id: UUID, body: InvitesBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.invite", team=team, target=team_id)
    emails = sorted({e.lower() for e in body.emails})
    with db.org_tx(team["org_id"]) as conn:
        tokens = {e: create_invite(conn, s, org_id=team["org_id"], team_id=team_id, kind="participant", email=e)
                  for e in emails}
    for email, token in tokens.items():
        send_invite(email, token, f"join {team['name']} ({team['org_name']})")
    audit(s, "team.invite", "ok", org_id=team["org_id"], team_id=team_id, count=len(emails))
    return {"invited": len(emails)}


@app.post("/teams/{team_id}/invites/{invite_id}/revoke")
def team_cancel_invite(team_id: UUID, invite_id: UUID, s: Session = Depends(current_session)):
    """Cancel an invitation to this team that has not been accepted, or is waiting for approval."""
    team = find_team(team_id)
    require(s, "team.cancel_invite", team=team, target=invite_id)
    with db.org_tx(team["org_id"]) as conn:
        revoked = conn.execute(
            """UPDATE invite SET status = 'revoked', decided_by = %s, decided_at = now()
               WHERE id = %s AND team_id = %s AND status IN ('pending', 'needs_approval')""",
            (s.actor.person_id, invite_id, team_id)).rowcount
    if not revoked:
        raise HTTPException(404, "no such invitation")
    audit(s, "team.cancel_invite", "ok", org_id=team["org_id"], team_id=team_id, target=invite_id)
    return {"revoked": True}


@app.post("/teams/{team_id}/requests/{invite_id}")
def team_decide(team_id: UUID, invite_id: UUID, body: DecisionBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.decide_exception", team=team, target=invite_id)
    decide_invite(s, invite_id, body.approve, org_id=team["org_id"], team_id=team_id)
    audit(s, "team.decide_exception", "ok", org_id=team["org_id"], team_id=team_id, target=invite_id,
          approved=body.approve)
    return {"approved": body.approve}


@app.post("/teams/{team_id}/members/{person_id}/remove")
def team_remove_member(team_id: UUID, person_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.remove_member", team=team, target=person_id)
    with db.org_tx(team["org_id"]) as conn:
        if conn.execute("UPDATE team_member SET status = 'removed' WHERE team_id = %s AND person_id = %s AND status = 'active'",
                        (team_id, person_id)).rowcount != 1:
            raise HTTPException(404, "not a member")
        deleted = delete_keys(conn, "team_id = %s AND person_id = %s", (team_id, person_id))
    audit(s, "team.remove_member", "ok", org_id=team["org_id"], team_id=team_id, target=person_id, keys_deleted=deleted)
    return {"keys_deleted": deleted}


@app.post("/teams/{team_id}/keys/{key_id}/revoke")
def team_revoke_key(team_id: UUID, key_id: UUID, s: Session = Depends(current_session)):
    """A lead deletes one of a participant's keys. The participant stays in the team and can make another."""
    team = find_team(team_id)
    require(s, "team.revoke_key", team=team, target=key_id)
    with db.org_tx(team["org_id"]) as conn:
        deleted = delete_keys(conn, "id = %s AND team_id = %s", (key_id, team_id))
    if not deleted:
        raise HTTPException(404, "no such key")
    audit(s, "team.revoke_key", "ok", org_id=team["org_id"], team_id=team_id, target=key_id)
    return {"revoked": True}


@app.post("/teams/{team_id}/keys/{key_id}/rotate")
def team_rotate_key(team_id: UUID, key_id: UUID, s: Session = Depends(current_session)):
    """A lead forces a key to be replaced. The old secret stops working now; the new one is made only
    when its owner collects it, so the lead never sees it and nothing secret is stored in between."""
    team = find_team(team_id)
    require(s, "team.rotate_key", team=team, target=key_id)
    with db.org_tx(team["org_id"]) as conn:
        key = conn.execute(
            """SELECT k.id, k.name, k.key_alias, p.email FROM api_key k JOIN person p ON p.id = k.person_id
               WHERE k.id = %s AND k.team_id = %s AND k.status = 'active' FOR UPDATE OF k""", (key_id, team_id)).fetchone()
        if not key:
            raise HTTPException(404, "no such key")
        spent = litellm.team_keys(str(team_id)).get(key["key_alias"], {}).get("spend", 0.0)
        conn.execute("UPDATE api_key SET status = 'creating', carried_spend = %s WHERE id = %s", (spent, key_id))
        litellm.key_delete([key["key_alias"]])
    send_notice(key["email"], f"Your key \"{key['name']}\" was rotated",
                f"The lead of {team['name']} ({team['org_name']}) rotated your API key \"{key['name']}\".\n"
                f"It no longer works. Sign in to collect its replacement:\n\n{PUBLIC_URL}/teams/{team_id}\n")
    audit(s, "team.rotate_key", "ok", org_id=team["org_id"], team_id=team_id, target=key_id)
    return {"rotated": True}


@app.get("/teams/{team_id}/usage")
def team_usage(team_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.usage", team=team, target=team_id)
    totals = litellm.team_usage(str(team_id))
    with db.org_tx(team["org_id"]) as conn:
        people = conn.execute(
            """SELECT p.participant_id, p.email FROM team_member m JOIN person p ON p.id = m.person_id
               WHERE m.team_id = %s ORDER BY p.email""", (team_id,)).fetchall()
    return [{"email": p["email"], "participant_id": p["participant_id"],
             **totals.get(p["participant_id"], {"requests": 0, "failed": 0, "spend": 0.0, "tokens": 0})} for p in people]


@app.post("/teams/{team_id}/archive")
def team_archive(team_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "team.archive", team=team, target=team_id)
    with db.org_tx(team["org_id"]) as conn:
        conn.execute("SELECT 1 FROM team WHERE id = %s FOR UPDATE", (team_id,))
        # Deleting the keys is what stops access; blocking alone does not (see the design's notes).
        deleted = delete_keys(conn, "team_id = %s", (team_id,))
        conn.execute("DELETE FROM team_model WHERE team_id = %s", (team_id,))
        litellm.team_set_models(str(team_id), [])
        litellm.team_block(str(team_id))
        conn.execute("UPDATE invite SET status = 'revoked' WHERE team_id = %s AND status IN ('pending', 'needs_approval')",
                     (team_id,))
        conn.execute("UPDATE team SET status = 'archived', archived_at = now() WHERE id = %s", (team_id,))
    audit(s, "team.archive", "ok", org_id=team["org_id"], team_id=team_id, keys_deleted=deleted)
    return {"keys_deleted": deleted}


# ── Participant ─────────────────────────────────────────────────────────────

class ConsentBody(BaseModel):
    terms_accepted: bool
    research_use: bool


class KeyBody(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")


def _latest_consent(conn, team_id, person_id) -> dict | None:
    return conn.execute(
        "SELECT terms_accepted, research_use, created_at FROM consent WHERE team_id = %s AND person_id = %s "
        "ORDER BY id DESC LIMIT 1", (team_id, person_id)).fetchone()


@app.get("/my/teams/{team_id}")
def my_team(team_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "my.team", team=team, target=team_id)
    with db.org_tx(team["org_id"]) as conn:
        keys = conn.execute(
            "SELECT id, name, created_at, status = 'creating' AS waiting FROM api_key "
            "WHERE team_id = %s AND person_id = %s AND status <> 'deleted' "
            "ORDER BY created_at", (team_id, s.actor.person_id)).fetchall()
        models = [r["public_name"] for r in conn.execute(
            """SELECT m.public_name FROM team_model tm JOIN org_model m ON m.id = tm.org_model_id
               WHERE tm.team_id = %s AND m.removed_at IS NULL ORDER BY m.public_name""", (team_id,))]
        consent = _latest_consent(conn, team_id, s.actor.person_id)
    usage = litellm.team_usage(str(team_id)).get(s.person["participant_id"]) if keys or consent else None
    return {
        "team": {k: team[k] for k in ("id", "name", "org_name", "status", "org_status", "key_limit", "key_budget",
                                      "key_expiry_days", "consent_text")},
        "consent": consent, "keys": keys, "models": models,
        "knowledge_tools": litellm.mcp_server_name(team["org_slug"]),
        "usage": usage or {"requests": 0, "failed": 0, "spend": 0.0, "tokens": 0},
    }


@app.post("/my/teams/{team_id}/consent")
def my_consent(team_id: UUID, body: ConsentBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "my.consent", team=team, target=team_id)
    with db.org_tx(team["org_id"]) as conn:
        conn.execute(
            "INSERT INTO consent (org_id, team_id, person_id, terms_accepted, research_use) VALUES (%s, %s, %s, %s, %s)",
            (team["org_id"], team_id, s.actor.person_id, body.terms_accepted, body.research_use))
        # Withdrawing from the terms means no key, so existing ones go too.
        deleted = 0 if body.terms_accepted else delete_keys(
            conn, "team_id = %s AND person_id = %s", (team_id, s.actor.person_id))
    audit(s, "my.consent", "ok", org_id=team["org_id"], team_id=team_id, terms_accepted=body.terms_accepted,
          research_use=body.research_use, keys_deleted=deleted)
    return {"terms_accepted": body.terms_accepted, "research_use": body.research_use}


@app.post("/my/teams/{team_id}/keys")
def my_key_create(team_id: UUID, body: KeyBody, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "my.key.create", team=team, target=team_id)
    alias = f"c-{uuid.uuid4()}"
    with db.org_tx(team["org_id"]) as conn:
        # Locking the membership row makes this person's key requests run one at a time,
        # so the limit holds however many arrive together.
        if not conn.execute(
                "SELECT 1 FROM team_member WHERE team_id = %s AND person_id = %s AND status = 'active' FOR UPDATE",
                (team_id, s.actor.person_id)).fetchone():
            raise HTTPException(403, "not allowed")
        consent = _latest_consent(conn, team_id, s.actor.person_id)
        if not consent or not consent["terms_accepted"]:
            raise HTTPException(409, "accept the workshop terms first")
        count = conn.execute(
            "SELECT count(*) AS n FROM api_key WHERE team_id = %s AND person_id = %s AND status <> 'deleted'",
            (team_id, s.actor.person_id)).fetchone()["n"]
        if count >= team["key_limit"]:
            raise HTTPException(409, f"you already have {team['key_limit']} keys, the limit for this team")
        row = conn.execute(
            """INSERT INTO api_key (org_id, team_id, person_id, name, key_alias, status)
               VALUES (%s, %s, %s, %s, %s, 'active') RETURNING id""",
            (team["org_id"], team_id, s.actor.person_id, body.name, alias)).fetchone()
        litellm.user_ensure(s.person["participant_id"])
        key = litellm.key_generate(str(team_id), s.person["participant_id"], alias, float(team["key_budget"]),
                                   team["key_expiry_days"])
    audit(s, "my.key.create", "ok", org_id=team["org_id"], team_id=team_id, target=row["id"])
    return {"id": row["id"], "name": body.name, "key": key}  # the only time the key is ever returned


@app.post("/my/teams/{team_id}/keys/{key_id}/rotate")
def my_key_rotate(team_id: UUID, key_id: UUID, s: Session = Depends(current_session)):
    """Replace one of the participant's own keys: same name, new secret, and the old one stops working."""
    team = find_team(team_id)
    require(s, "my.key.rotate", team=team, target=key_id)
    alias = f"c-{uuid.uuid4()}"
    with db.org_tx(team["org_id"]) as conn:
        if not conn.execute(
                "SELECT 1 FROM team_member WHERE team_id = %s AND person_id = %s AND status = 'active' FOR UPDATE",
                (team_id, s.actor.person_id)).fetchone():
            raise HTTPException(403, "not allowed")
        consent = _latest_consent(conn, team_id, s.actor.person_id)
        if not consent or not consent["terms_accepted"]:
            raise HTTPException(409, "accept the workshop terms first")
        old = conn.execute(
            "SELECT id, name, key_alias, status, carried_spend FROM api_key WHERE id = %s AND team_id = %s "
            "AND person_id = %s AND status <> 'deleted' FOR UPDATE", (key_id, team_id, s.actor.person_id)).fetchone()
        if not old:
            raise HTTPException(404, "no such key")
        # The new key starts from what the old one has spent, so rotating does not refill its budget.
        # After a lead's rotation the old secret is already gone and its spend was noted then.
        spent = float(old["carried_spend"]) if old["status"] == "creating" else \
            litellm.team_keys(str(team_id)).get(old["key_alias"], {}).get("spend", 0.0)
        row = conn.execute(
            """INSERT INTO api_key (org_id, team_id, person_id, name, key_alias, status)
               VALUES (%s, %s, %s, %s, %s, 'active') RETURNING id""",
            (team["org_id"], team_id, s.actor.person_id, old["name"], alias)).fetchone()
        key = litellm.key_generate(str(team_id), s.person["participant_id"], alias, float(team["key_budget"]),
                                   team["key_expiry_days"], spent=spent)
        try:
            delete_keys(conn, "id = %s", (old["id"],))
        except Exception:
            litellm.key_delete([alias])  # do not leave two working keys behind
            raise
    audit(s, "my.key.rotate", "ok", org_id=team["org_id"], team_id=team_id, target=row["id"], replaced=old["id"])
    return {"id": row["id"], "name": old["name"], "key": key}  # shown once, like a new key


@app.post("/my/teams/{team_id}/keys/{key_id}/delete")
def my_key_delete(team_id: UUID, key_id: UUID, s: Session = Depends(current_session)):
    team = find_team(team_id)
    require(s, "my.key.delete", team=team, target=key_id)
    with db.org_tx(team["org_id"]) as conn:
        deleted = delete_keys(conn, "id = %s AND team_id = %s AND person_id = %s", (key_id, team_id, s.actor.person_id))
    if not deleted:
        raise HTTPException(404, "no such key")
    audit(s, "my.key.delete", "ok", org_id=team["org_id"], team_id=team_id, target=key_id)
    return {"deleted": True}


# ── Integrations: registering them (SSEC admin) ─────────────────────────────

class IntegrationBody(BaseModel):
    client_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$")
    can_enroll: bool = False


@app.post("/admin/teams/{team_id}/integrations")
def admin_integration_register(team_id: UUID, body: IntegrationBody, s: Session = Depends(current_session)):
    """Connect an outside service to this team. The service is a client in the identity provider;
    this only records that its calls, made with its users' tokens, are accepted for this one team."""
    require(s, "integration.register")
    team = find_team(team_id)
    if not team:
        raise HTTPException(404, "no such team")
    if body.client_id == WEB_CLIENT_ID:
        raise HTTPException(422, "that client is the console itself")
    with db.system_tx() as conn:  # a client may be connected to one team only, across all orgs
        if conn.execute("SELECT 1 FROM integration WHERE client_id = %s AND removed_at IS NULL",
                        (body.client_id,)).fetchone():
            raise HTTPException(409, "that client is already connected to a team")
        row = conn.execute(
            """INSERT INTO integration (org_id, team_id, client_id, name, can_enroll, created_by)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (team["org_id"], team_id, body.client_id, body.name, body.can_enroll, s.actor.person_id)).fetchone()
    audit(s, "integration.register", "ok", org_id=team["org_id"], team_id=team_id, target=body.client_id,
          can_enroll=body.can_enroll)
    return {"id": row["id"]}


@app.post("/admin/integrations/{integration_id}/remove")
def admin_integration_remove(integration_id: UUID, s: Session = Depends(current_session)):
    """Disconnect a service. Its calls are refused from now on and the keys it issued are deleted."""
    require(s, "integration.remove")
    with db.system_tx() as conn:
        found = conn.execute(
            "SELECT * FROM integration WHERE id = %s AND removed_at IS NULL", (integration_id,)).fetchone()
    if not found:
        raise HTTPException(404, "no such integration")
    with db.org_tx(found["org_id"]) as conn:
        conn.execute("UPDATE integration SET removed_at = now() WHERE id = %s", (integration_id,))
        keys = delete_keys(conn, "integration_id = %s", (integration_id,))
    audit(s, "integration.remove", "ok", org_id=found["org_id"], team_id=found["team_id"], target=found["client_id"],
          keys_deleted=keys)
    return {"team_id": found["team_id"], "keys_deleted": keys}


# ── Integrations: what a connected service may do, always for one signed-in user ──

def refuse(status: int, code: str, message: str, **more):
    """Errors a service can act on: a stable `error` code next to the message."""
    return HTTPException(status, {"error": code, "message": message, **more})


def integration_team(i: IntegrationSession, action: str) -> dict:
    """The integration's own team, if it is open and the integration may do `action` there."""
    team = find_team(i.integration["team_id"])
    org_id, team_id = str(i.integration["org_id"]), str(i.integration["team_id"])
    if not team or not policy.integration_allowed(i.grant, action, org_id=str(team["org_id"]), team_id=str(team["id"])):
        audit(i, action, "denied", org_id=org_id, team_id=team_id)
        raise refuse(403, "not_allowed", "this integration may not do that")
    if team["org_status"] != "active" or team["status"] != "active":
        raise refuse(409, "team_closed", "this team is archived or its organization is suspended")
    return team


def consent_url(team: dict) -> str:
    return f"{PUBLIC_URL}/teams/{team['id']}"


@app.post("/integration/enroll")
def integration_enroll(i: IntegrationSession = Depends(integration_session)):
    """Make the signed-in user a member of the integration's team, as an accepted invitation would."""
    team = integration_team(i, "integration.enroll")
    if not i.verified_email:
        raise refuse(409, "email_not_verified", "the user's email address has not been verified")
    person = i.actor.person_id
    with db.org_tx(team["org_id"]) as conn:
        member = conn.execute(
            "SELECT status FROM team_member WHERE team_id = %s AND person_id = %s FOR UPDATE", (team["id"], person)).fetchone()
        if member and member["status"] != "active":
            # A lead or admin took this person out. Only a new invitation from the lead brings them back.
            raise refuse(409, "removed", "this user was removed from the team")
        if not member:
            conn.execute("INSERT INTO team_member (team_id, person_id, org_id) VALUES (%s, %s, %s)",
                         (team["id"], person, team["org_id"]))
        consent = _latest_consent(conn, team["id"], person)
    if not member:
        audit(i, "integration.enroll", "ok", org_id=team["org_id"], team_id=team["id"], target=person)
    return {"member": True, "newly_enrolled": not member, "terms_accepted": bool(consent and consent["terms_accepted"]),
            "consent_url": consent_url(team), "team": {"id": team["id"], "name": team["name"]}}


@app.post("/integration/key")
def integration_issue_key(i: IntegrationSession = Depends(integration_session)):
    """Issue the user's key for this service. There is one per user and service: asking again replaces it,
    so the previous one stops working and the new one carries on from what it had spent."""
    team = integration_team(i, "integration.issue_key")
    person, alias = i.actor.person_id, f"c-{uuid.uuid4()}"
    with db.org_tx(team["org_id"]) as conn:
        if not conn.execute(
                "SELECT 1 FROM team_member WHERE team_id = %s AND person_id = %s AND status = 'active' FOR UPDATE",
                (team["id"], person)).fetchone():
            raise refuse(409, "not_member", "this user is not a member of the team")
        consent = _latest_consent(conn, team["id"], person)
        if not consent or not consent["terms_accepted"]:  # the user's own act, in the console
            raise refuse(409, "consent_required", "the user must accept the team's terms in the console first",
                         consent_url=consent_url(team))
        old = conn.execute(
            """SELECT id, key_alias, status, carried_spend FROM api_key
               WHERE team_id = %s AND person_id = %s AND integration_id = %s AND status <> 'deleted' FOR UPDATE""",
            (team["id"], person, i.integration["id"])).fetchone()
        spent = 0.0
        if old:
            spent = float(old["carried_spend"]) if old["status"] == "creating" else \
                litellm.team_keys(str(team["id"])).get(old["key_alias"], {}).get("spend", 0.0)
        else:
            count = conn.execute(
                "SELECT count(*) AS n FROM api_key WHERE team_id = %s AND person_id = %s AND status <> 'deleted'",
                (team["id"], person)).fetchone()["n"]
            if count >= team["key_limit"]:
                raise refuse(409, "key_limit", f"the user already has {team['key_limit']} keys, the limit for this team")
        row = conn.execute(
            """INSERT INTO api_key (org_id, team_id, person_id, name, key_alias, status, integration_id)
               VALUES (%s, %s, %s, %s, %s, 'active', %s) RETURNING id""",
            (team["org_id"], team["id"], person, i.integration["name"], alias, i.integration["id"])).fetchone()
        litellm.user_ensure(i.person["participant_id"])
        key = litellm.key_generate(str(team["id"]), i.person["participant_id"], alias, float(team["key_budget"]),
                                   team["key_expiry_days"], spent=spent)
        if old:
            try:
                delete_keys(conn, "id = %s", (old["id"],))
            except Exception:
                litellm.key_delete([alias])  # do not leave two working keys behind
                raise
        models = [r["public_name"] for r in conn.execute(
            """SELECT m.public_name FROM team_model tm JOIN org_model m ON m.id = tm.org_model_id
               WHERE tm.team_id = %s AND m.removed_at IS NULL ORDER BY m.public_name""", (team["id"],))]
    audit(i, "integration.issue_key", "ok", org_id=team["org_id"], team_id=team["id"], target=row["id"],
          replaced=old["id"] if old else None)
    return {"key": key, "name": i.integration["name"], "replaced_previous": bool(old), "models": models,
            "expires_in_days": team["key_expiry_days"], "team": {"id": team["id"], "name": team["name"]}}


@app.post("/integration/key/revoke")
def integration_revoke_key(i: IntegrationSession = Depends(integration_session)):
    """Delete the user's key for this service, for example when their session ends."""
    integration = i.integration
    team = find_team(integration["team_id"])
    if not team or not policy.integration_allowed(i.grant, "integration.revoke_key", org_id=str(team["org_id"]),
                                                  team_id=str(team["id"])):
        audit(i, "integration.revoke_key", "denied", org_id=integration["org_id"], team_id=integration["team_id"])
        raise refuse(403, "not_allowed", "this integration may not do that")
    with db.org_tx(team["org_id"]) as conn:
        deleted = delete_keys(conn, "team_id = %s AND person_id = %s AND integration_id = %s",
                              (team["id"], i.actor.person_id, integration["id"]))
    if deleted:
        audit(i, "integration.revoke_key", "ok", org_id=team["org_id"], team_id=team["id"])
    return {"revoked": bool(deleted)}
