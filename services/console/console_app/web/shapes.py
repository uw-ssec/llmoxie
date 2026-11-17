"""What the browser is given. The broker's replies hold more than the pages show; nothing passes through.

Every function names the fields it lets out, so a field the broker adds later stays on the server
until someone lists it here. Three things never leave: `participant_id` (the only identity LiteLLM
and the request logs see, so a lead must not learn whose it is), the raw Markdown of the knowledge
base, and columns no page shows, such as an organization's MCP server id.
"""


def _pick(row: dict, *fields: str) -> dict:
    return {field: row.get(field) for field in fields}


def _each(rows: list[dict], *fields: str) -> list[dict]:
    return [_pick(row, *fields) for row in rows]


def session(me: dict, csrf: str, gateway_url: str, litellm_admin_url: str) -> dict:
    return {
        "signed_in": True,
        "csrf": csrf,
        "me": {"email": me["email"], "is_admin": me["is_admin"],
               "lead_orgs": _each(me["lead_orgs"], "id", "name", "status"),
               "teams": _each(me["teams"], "id", "name", "org_name", "status")},
        "config": {"gateway_url": gateway_url, "litellm_admin_url": litellm_admin_url},
    }


def admin_orgs(orgs: list[dict]) -> dict:
    return {"orgs": _each(orgs, "id", "name", "slug", "budget_ceiling", "leads", "teams", "status")}


def audit(events: list[dict]) -> dict:
    return {"events": _each(events, "at", "actor_email", "actor_role", "action", "result", "org_name", "team_name")}


def dlp(view: dict, actions: dict[str, str]) -> dict:
    if not view["enabled"]:
        return {"enabled": False}
    events = [{**_pick(e, "at", "kinds", "blocked", "action", "source", "mode", "count", "email", "user_id"),
               "request": (e.get("request_id") or "")[:8]} for e in view["events"]]
    return {"enabled": True, "read": view["read"], "shown": view["shown"], "actions": actions,
            "totals": _each(view["totals"], "kind", "action", "count"), "events": events}


def org(view: dict, *, is_lead: bool, is_admin: bool) -> dict:
    """A lead's id is in the address of the admin's Remove button, so only an admin is given it."""
    return {
        "org": _pick(view["org"], "id", "name", "slug", "status", "budget_ceiling"),
        "is_lead": is_lead,
        "is_admin": is_admin,
        "leads": _each(view["leads"], "id", "email") if is_admin else _each(view["leads"], "email"),
        "lead_invites": _each(view["lead_invites"], "id", "email", "status", "signin_email") if is_admin else [],
        "models": _each(view["models"], "id", "public_name", "provider"),
        "providers": list(view["providers"]),
        "teams": _each(view["teams"], "id", "name", "members", "team_budget", "status"),
    }


def knowledge(view: dict, *, concept: dict | None, body_html: str, links_out: list[dict], links_in: list[dict],
              graph: dict, log_html: str) -> dict:
    """The list of concepts without their text, and the one selected concept as sanitized HTML."""
    chosen = None
    if concept:
        chosen = {**_pick(concept, "id", "title", "type", "status", "written_at", "tags", "description"),
                  "html": body_html,
                  "links_out": _each(links_out, "id", "title", "note"),
                  "links_in": _each(links_in, "id", "title", "note")}
    return {
        "org": _pick(view["org"], "id", "name"),
        "tools": view["tools"],
        "edge_count": len(view["edges"]),
        "concepts": _each(view["concepts"], "id", "title", "type", "description", "tags", "links", "written_at"),
        "concept": chosen,
        "graph": graph,
        "log_html": log_html,
    }


def team_manage(view: dict, usage: list[dict], *, is_lead: bool) -> dict:
    return {
        "team": _pick(view["team"], "id", "name", "status", "org_id", "org_name", "org_status", "org_budget_ceiling",
                      "team_budget", "key_limit", "key_budget", "key_expiry_days"),
        "is_lead": is_lead,
        "models": _each(view["models"], "id", "public_name", "allowed"),
        "members": _each(view["members"], "id", "email", "terms_accepted", "keys"),
        "invites": _each(view["invites"], "id", "email", "status", "signin_email"),
        "keys": _each(view["keys"], "id", "email", "name", "waiting", "hint", "created_at", "expires", "last_used",
                      "spend"),
        "usage": _each(usage, "email", "requests", "failed", "tokens", "spend"),
        "integrations": _each(view["integrations"], "id", "name", "client_id", "can_enroll"),
    }


def my_team(view: dict) -> dict:
    consent = view["consent"]
    return {
        "team": _pick(view["team"], "id", "name", "status", "org_name", "org_status", "consent_text", "key_limit",
                      "key_budget", "key_expiry_days"),
        "consent": _pick(consent, "terms_accepted", "research_use") if consent else None,
        "keys": _each(view["keys"], "id", "name", "waiting", "created_at"),
        "models": list(view["models"]),
        "knowledge_tools": view["knowledge_tools"],
        "usage": _pick(view["usage"], "requests", "tokens", "spend"),
    }


def invite(info: dict) -> dict:
    if not info.get("valid"):
        return {"valid": False}
    return {"valid": True, **_pick(info, "kind", "org_name", "team_name")}


def key(created: dict) -> dict:
    """A new or replacement key, for the one response that ever carries it."""
    return _pick(created, "name", "key")
