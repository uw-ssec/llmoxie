import { useLoaderData } from 'react-router'
import { PageHeader, Section } from '@/components/page'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { minute } from '@/lib/format'
import { th } from '@/lib/styles'
import type { AuditLog } from '@/lib/types'

export function AuditPage() {
  const { events } = useLoaderData() as AuditLog
  return (
    <>
      <PageHeader title="Audit log" lede="The latest 300 console actions, newest first. Entries cannot be changed or removed." />
      <Section>
        <Table>
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
                <TableCell>
                  <span>{event.actor_email ?? '—'}</span> <span className="text-muted-foreground">{event.actor_role}</span>
                </TableCell>
                <TableCell>
                  <code>{event.action}</code>
                </TableCell>
                <TableCell>{event.result}</TableCell>
                <TableCell>{event.org_name ?? '—'}</TableCell>
                <TableCell>{event.team_name ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>
    </>
  )
}
