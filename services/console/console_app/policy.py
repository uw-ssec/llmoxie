"""Who may do what. The one place authorization is decided.

console-web and console-broker both call `allowed` before acting, with an Actor
built from the database (never from the request). Anything not listed is denied.
"""

from dataclasses import dataclass, field

ADMIN = "admin"
LEAD = "lead"
PARTICIPANT = "participant"

# action -> the role that may perform it
ACTIONS: dict[str, str] = {
    # SSEC admin
    "org.list": ADMIN,
    "org.create": ADMIN,
    "org.suspend": ADMIN,
    "org.resume": ADMIN,
    "org.set_ceiling": ADMIN,
    "org.appoint_lead": ADMIN,
    "org.decide_lead_exception": ADMIN,
    "org.remove_lead": ADMIN,
    "org.remove": ADMIN,
    "team.remove": ADMIN,
    "integration.register": ADMIN,
    "integration.remove": ADMIN,
    "audit.read": ADMIN,
    "dlp.read": ADMIN,
    # Org lead, inside their own org
    "org.view": LEAD,  # admins too (see ADMIN_ALSO)
    "model.add": LEAD,
    "model.remove": LEAD,
    "team.create": LEAD,
    "team.view": LEAD,
    "team.set_budget": LEAD,
    "team.set_models": LEAD,
    "team.invite": LEAD,
    "team.cancel_invite": LEAD,
    "team.decide_exception": LEAD,
    "team.remove_member": LEAD,
    "team.revoke_key": LEAD,
    "team.rotate_key": LEAD,
    "team.usage": LEAD,
    "team.archive": LEAD,
    "org.knowledge": LEAD,  # read everything in the org's knowledge base; leads only, not SSEC admins
    # Participant, inside their own teams
    "my.team": PARTICIPANT,
    "my.consent": PARTICIPANT,
    "my.key.create": PARTICIPANT,
    "my.key.delete": PARTICIPANT,
    "my.key.rotate": PARTICIPANT,
    "my.usage": PARTICIPANT,
}

# Lead actions an SSEC admin may also take, in any org: look at an org and its teams, and remove
# someone from a team. Running a team (budgets, models, invitations, keys, archiving) stays with its lead.
ADMIN_ALSO = {"org.view", "team.view", "team.usage", "team.remove_member"}

# Lead actions that still work when the org is suspended or the team archived.
READ_ONLY = {"org.view", "org.knowledge", "team.view", "team.usage", "my.team", "my.usage", "my.key.delete"}


@dataclass(frozen=True)
class Actor:
    person_id: str
    is_admin: bool = False
    lead_orgs: frozenset[str] = frozenset()
    # team id -> org id, for teams this person is an active member of
    member_teams: dict[str, str] = field(default_factory=dict)

    @property
    def role(self) -> str:
        if self.is_admin:
            return ADMIN
        if self.lead_orgs:
            return LEAD
        if self.member_teams:
            return PARTICIPANT
        return "none"


def allowed(actor: Actor, action: str, *, org_id: str | None = None, team_id: str | None = None) -> bool:
    """`org_id` is the org the target belongs to, as the caller looked it up itself."""
    needs = ACTIONS.get(action)
    if needs is None:
        return False
    if needs == ADMIN:
        return actor.is_admin
    if needs == LEAD:
        if org_id is None:
            return False
        if org_id in actor.lead_orgs:
            return True
        return action in ADMIN_ALSO and actor.is_admin
    if needs == PARTICIPANT:
        return team_id is not None and org_id is not None and actor.member_teams.get(team_id) == org_id
    return False


# ── Integrations ────────────────────────────────────────────────────────────
# An integration is an outside service connected to exactly one team. It never acts on its own:
# every call is for one signed-in user, whose own token it must present.

@dataclass(frozen=True)
class Integration:
    id: str
    team_id: str
    org_id: str
    can_enroll: bool


INTEGRATION_ACTIONS = {"integration.enroll", "integration.issue_key", "integration.revoke_key"}


def integration_allowed(integration: Integration, action: str, *, org_id: str, team_id: str) -> bool:
    """Whether the integration may do this for a user, in the team the caller looked up for it."""
    if action not in INTEGRATION_ACTIONS:
        return False
    if integration.team_id != team_id or integration.org_id != org_id:
        return False
    if action == "integration.enroll":
        return integration.can_enroll
    return True
