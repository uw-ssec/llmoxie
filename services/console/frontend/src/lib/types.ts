// What console-web's browser API answers with. These mirror console_app/web/shapes.py field for field;
// a field that is not there was left out on purpose.

export type Status = 'active' | 'suspended' | 'archived' | 'removed' | string

export type Me = {
  email: string | null
  is_admin: boolean
  lead_orgs: { id: string; name: string; status: Status }[]
  teams: { id: string; name: string; org_name: string; status: Status }[]
}
export type SignedIn = {
  signed_in: true
  csrf: string
  me: Me
  config: { gateway_url: string; litellm_admin_url: string }
}
export type Session = SignedIn | { signed_in: false }

/** What an action answers with: a sentence to show, somewhere to go next, or a key shown this once. */
export type ActionResult = {
  message?: string
  goto?: string
  key?: { name: string; key: string }
  rotated?: boolean
}

export type Invitation = { valid: false } | { valid: true; kind: 'lead' | 'participant'; org_name: string; team_name: string | null }

export type AdminOrgs = {
  orgs: { id: string; name: string; slug: string; budget_ceiling: string | number; leads: number; teams: number; status: Status }[]
}

export type AuditLog = {
  events: {
    at: string
    actor_email: string | null
    actor_role: string | null
    action: string
    result: string
    org_name: string | null
    team_name: string | null
  }[]
}

export type DataProtection =
  | { enabled: false }
  | {
      enabled: true
      read: number
      shown: number
      actions: Record<string, string>
      totals: { kind: string; action: string; count: number }[]
      events: {
        at: string
        kinds: string[]
        blocked: boolean
        action: string
        source: string | null
        mode: string | null
        count: number | null
        email: string | null
        user_id: string | null
        request: string
      }[]
    }

export type PendingInvite = { id: string; email: string; status: 'pending' | 'needs_approval'; signin_email: string | null }

export type OrgPage = {
  org: { id: string; name: string; slug: string; status: Status; budget_ceiling: string | number }
  is_lead: boolean
  is_admin: boolean
  leads: { id?: string; email: string }[]
  lead_invites: PendingInvite[]
  models: { id: string; public_name: string; provider: string }[]
  providers: string[]
  teams: { id: string; name: string; members: number; team_budget: string | number; status: Status }[]
}

export type TeamManagePage = {
  team: {
    id: string
    name: string
    status: Status
    org_id: string
    org_name: string
    org_status: Status
    org_budget_ceiling: string | number
    team_budget: string | number
    key_limit: number
    key_budget: string | number
    key_expiry_days: number
  }
  is_lead: boolean
  models: { id: string; public_name: string; allowed: boolean }[]
  members: { id: string; email: string; terms_accepted: boolean | null; keys: number }[]
  invites: PendingInvite[]
  keys: {
    id: string
    email: string
    name: string
    waiting: boolean
    hint: string | null
    created_at: string
    expires: string | null
    last_used: string | null
    spend: number
  }[]
  usage: { email: string; requests: number; failed: number; tokens: number; spend: number }[]
  integrations: { id: string; name: string; client_id: string; can_enroll: boolean }[]
}

export type MyTeamPage = {
  team: {
    id: string
    name: string
    status: Status
    org_name: string
    org_status: Status
    consent_text: string
    key_limit: number
    key_budget: string | number
    key_expiry_days: number
  }
  consent: { terms_accepted: boolean; research_use: boolean } | null
  keys: { id: string; name: string; waiting: boolean; created_at: string }[]
  models: string[]
  knowledge_tools: string
  usage: { requests: number; tokens: number; spend: number }
}

export type ConceptLink = { id: string; title: string; note: string | null }
export type KnowledgePage = {
  org: { id: string; name: string }
  tools: string
  edge_count: number
  concepts: { id: string; title: string; type: string; description: string | null; tags: string[] | null; links: number; written_at: string | null }[]
  concept: {
    id: string
    title: string
    type: string
    status: string | null
    written_at: string | null
    tags: string[] | null
    description: string | null
    html: string
    links_out: ConceptLink[]
    links_in: ConceptLink[]
  } | null
  graph: {
    width: number
    height: number
    hidden: number
    nodes: { id: string; title: string; label: string; type: string; colour: string; x: number; y: number; selected: boolean; faded: boolean }[]
    lines: { x1: number; y1: number; x2: number; y2: number; note: string | null; selected: boolean }[]
    legend: { type: string; colour: string }[]
  }
  log_html: string
}
