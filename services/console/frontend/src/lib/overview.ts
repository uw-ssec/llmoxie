// What the overview is made of. No call of its own: it asks for pages the person can already open.
import { get, loadSession } from './api'
import type { AdminOrgs, AuditLog, Me, OrgPage } from './types'

/** Whether "/" is an overview for this person. Someone with one team and nothing else goes straight to it. */
export function showsOverview(me: Me): boolean {
  return me.is_admin || me.lead_orgs.length > 0 || me.teams.length > 1
}

export type Overview = {
  /** One per organization this person leads, in the session's order; null when it could not be read. */
  orgs: (OrgPage | null)[]
  /** For an SSEC admin: every organization, and the audit log. */
  admin: { orgs: AdminOrgs | null; audit: AuditLog | null } | null
}

/** A part that fails leaves a gap the screen says so about; the rest of the overview still shows. */
const part = <T>(path: string) => get<T>(path).catch(() => null)

export async function loadOverview(): Promise<Overview | null> {
  const session = await loadSession()
  if (!session.signed_in || !showsOverview(session.me)) return null
  const { me } = session
  const [orgs, admin] = await Promise.all([
    Promise.all(me.lead_orgs.map((org) => part<OrgPage>(`/orgs/${org.id}`))),
    me.is_admin ? Promise.all([part<AdminOrgs>('/admin/orgs'), part<AuditLog>('/admin/audit')]) : null,
  ])
  return { orgs, admin: admin && { orgs: admin[0], audit: admin[1] } }
}
