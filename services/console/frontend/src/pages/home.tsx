import { Link, useLoaderData } from 'react-router'
import { Muted, PageHeader, Section, Stat, Stats } from '@/components/page'
import { StatusTag, Tag } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { minute, notActive, usd } from '@/lib/format'
import type { Overview } from '@/lib/overview'
import { useSignedIn } from '@/lib/session'
import { num, th } from '@/lib/styles'
import type { AdminOrgs, AuditLog, Me, OrgPage } from '@/lib/types'

const UNREAD = 'This could not be loaded just now. Reload the page to try again.'
const sum = (values: number[]) => values.reduce((total, value) => total + value, 0)

/** What each role runs, at a glance: a lead's organizations and teams first, then one's own teams, then the admin's view. */
export function Home() {
  const { me } = useSignedIn()
  const { orgs, admin } = useLoaderData() as Overview
  return (
    <>
      <PageHeader title="Overview" lede={me.email} />
      <Figures me={me} orgs={orgs} all={admin?.orgs ?? null} />
      {/* Side by side once there is more than one, so each team's figures stay near its name. */}
      <div className={me.lead_orgs.length + Math.min(me.teams.length, 1) > 1 ? 'grid items-start gap-6 xl:grid-cols-2' : 'contents'}>
        {me.lead_orgs.map((org, index) => (
          <LedOrg key={org.id} org={org} view={orgs[index] ?? null} />
        ))}
        {me.teams.length > 0 && <MyTeams teams={me.teams} />}
      </div>
      {admin && (
        <div className="grid items-start gap-6 xl:grid-cols-2">
          <Everyone orgs={admin.orgs} />
          <Latest audit={admin.audit} />
        </div>
      )}
    </>
  )
}

/** A lead's own figures when they lead something; otherwise the admin's, across every organization. */
function Figures({ me, orgs, all }: { me: Me; orgs: (OrgPage | null)[]; all: AdminOrgs | null }) {
  const led = orgs.filter((org) => org !== null)
  if (led.length > 0) {
    const teams = led.flatMap((org) => org.teams)
    return (
      <Stats label="What you lead">
        <Stat label="Organizations you lead" value={me.lead_orgs.length} />
        <Stat label="Teams" value={teams.length} detail={notActive(teams)} />
        <Stat label="Members" value={sum(teams.map((team) => team.members))} detail="across those teams" />
        <Stat label="Models" value={sum(led.map((org) => org.models.length))} />
      </Stats>
    )
  }
  if (all) {
    return (
      <Stats label="Every organization">
        <Stat label="Organizations" value={all.orgs.length} detail={notActive(all.orgs)} />
        <Stat label="Teams" value={sum(all.orgs.map((org) => org.teams))} />
        <Stat label="Leads" value={sum(all.orgs.map((org) => org.leads))} />
      </Stats>
    )
  }
  return null
}

function LedOrg({ org, view }: { org: Me['lead_orgs'][number]; view: OrgPage | null }) {
  return (
    <Section
      title={
        <span className="flex flex-wrap items-center gap-3">
          <Link to={`/orgs/${org.id}`}>{org.name}</Link>
          <StatusTag status={org.status} />
        </span>
      }
      description={view && `Budget ceiling ${usd(view.org.budget_ceiling)} · ${view.models.length} ${view.models.length === 1 ? 'model' : 'models'}`}
      action={
        <Button asChild variant="outline" size="sm" className="no-underline hover:no-underline">
          <Link to={`/orgs/${org.id}/knowledge`}>Knowledge base</Link>
        </Button>
      }
    >
      {!view ? (
        <Muted>{UNREAD}</Muted>
      ) : view.teams.length === 0 ? (
        <Muted>
          No teams yet. <Link to={`/orgs/${org.id}`}>Create the first one</Link>.
        </Muted>
      ) : (
        // Fixed columns, so the same figure sits in the same place in every organization's card.
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Team</TableHead>
              <TableHead className={`${th} ${num} w-24`}>Members</TableHead>
              <TableHead className={`${th} ${num} w-28`}>Budget</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.teams.map((team) => (
              <TableRow key={team.id}>
                <TableCell className="whitespace-normal">
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Link to={`/teams/${team.id}/manage`}>{team.name}</Link>
                    <StatusTag status={team.status} />
                  </span>
                </TableCell>
                <TableCell className={num}>{team.members}</TableCell>
                <TableCell className={num}>{usd(team.team_budget)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  )
}

function MyTeams({ teams }: { teams: Me['teams'] }) {
  return (
    <Section title="Your teams" description="Teams you are a member of. Open one for your keys and how to connect.">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={th}>Team</TableHead>
            <TableHead className={th}>Organization</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {teams.map((team) => (
            <TableRow key={team.id}>
              <TableCell>
                <Link to={`/teams/${team.id}`}>{team.name}</Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{team.org_name}</TableCell>
              <TableCell className="text-right">
                <StatusTag status={team.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  )
}

/** How many rows the admin's two cards show; the full lists are a link away. */
const SHOWN = 8

function Everyone({ orgs }: { orgs: AdminOrgs | null }) {
  // Whatever is not active comes first: it is what an admin may need to act on.
  const all = orgs?.orgs ?? []
  const shown = [...all.filter((org) => org.status !== 'active'), ...all.filter((org) => org.status === 'active')].slice(0, SHOWN)
  return (
    <Section title="Organizations" action={<More to="/admin">Manage organizations</More>}>
      {!orgs ? (
        <Muted>{UNREAD}</Muted>
      ) : orgs.orgs.length === 0 ? (
        <Muted>
          No organizations yet. <Link to="/admin">Create the first one</Link>.
        </Muted>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Organization</TableHead>
              <TableHead className={`${th} ${num}`}>Teams</TableHead>
              <TableHead className={`${th} ${num}`}>Budget ceiling</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((org) => (
              <TableRow key={org.id}>
                <TableCell className="whitespace-normal">
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Link to={`/orgs/${org.id}`}>{org.name}</Link>
                    <StatusTag status={org.status} />
                  </span>
                </TableCell>
                <TableCell className={num}>{org.teams}</TableCell>
                <TableCell className={num}>{usd(org.budget_ceiling)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {all.length > shown.length && (
        <Muted>
          Showing {shown.length} of {all.length}. <Link to="/admin">See them all</Link>.
        </Muted>
      )}
    </Section>
  )
}

function Latest({ audit }: { audit: AuditLog | null }) {
  const events = audit?.events.slice(0, SHOWN) ?? []
  return (
    <Section title="Latest actions" description="The newest entries in the audit log." action={<More to="/admin/audit">Audit log</More>}>
      {!audit ? (
        <Muted>{UNREAD}</Muted>
      ) : events.length === 0 ? (
        <Muted>Nothing has been recorded yet.</Muted>
      ) : (
        <ul className="flex flex-col divide-y">
          {events.map((event, index) => (
            <li key={index} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2.5 first:pt-0 last:pb-0">
              <code>{event.action}</code>
              {event.result !== 'ok' && <Tag bad>{event.result}</Tag>}
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">{minute(event.at)}</span>
              <span className="w-full truncate text-muted-foreground">
                {event.actor_email ?? event.actor_role ?? '—'}
                {event.org_name && ` · ${event.org_name}`}
                {event.team_name && ` · ${event.team_name}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function More({ to, children }: { to: string; children: string }) {
  return (
    <Button asChild variant="ghost" size="sm" className="no-underline hover:no-underline">
      <Link to={to}>{children}</Link>
    </Button>
  )
}
