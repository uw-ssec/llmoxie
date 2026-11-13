import { useLoaderData } from 'react-router'
import { Muted, PageHeader, Section, Stat, Stats } from '@/components/page'
import { Tag } from '@/components/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { minute } from '@/lib/format'
import { th } from '@/lib/styles'
import type { AuditLog } from '@/lib/types'

export function AuditPage() {
  const { events } = useLoaderData() as AuditLog
  const denied = events.filter((event) => event.result === 'denied').length
  const people = new Set(events.map((event) => event.actor_email).filter(Boolean)).size
  return (
    <>
      <PageHeader title="Audit log" lede="The latest 300 console actions, newest first. Entries cannot be changed or removed." />
      <Stats label="In the entries below">
        <Stat label="Entries shown" value={events.length} />
        <Stat label="Denied" value={denied} />
        <Stat label="People" value={people} detail="named in these entries" />
      </Stats>
      <Section>
        {events.length === 0 ? (
          <Muted>Nothing has been recorded yet.</Muted>
        ) : (
          <Table stack="medium" dense>
            <TableHeader>
              <TableRow>
                {['When (UTC)', 'Who', 'Action', 'Result', 'Organization', 'Team'].map((heading) => (
                  <TableHead key={heading} className={th}>
                    {heading}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event, index) => (
                <TableRow key={index}>
                  <TableCell className="tabular-nums">{minute(event.at)}</TableCell>
                  <TableCell className="whitespace-normal">
                    <span>{event.actor_email ?? '—'}</span> <span className="text-muted-foreground">{event.actor_role}</span>
                  </TableCell>
                  <TableCell>
                    <code>{event.action}</code>
                  </TableCell>
                  <TableCell>{event.result === 'ok' ? event.result : <Tag bad>{event.result}</Tag>}</TableCell>
                  <TableCell data-empty={event.org_name ? undefined : ''} className="whitespace-normal">
                    {event.org_name ?? '—'}
                  </TableCell>
                  <TableCell data-empty={event.team_name ? undefined : ''} className="whitespace-normal">
                    {event.team_name ?? '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </>
  )
}
