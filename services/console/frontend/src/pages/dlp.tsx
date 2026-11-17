import { Fragment } from 'react'
import { useLoaderData } from 'react-router'
import { Muted, PageHeader, Section, Stat, Stats } from '@/components/page'
import { Tag } from '@/components/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { minute } from '@/lib/format'
import { num, th } from '@/lib/styles'
import type { DataProtection } from '@/lib/types'

export function DataProtectionPage() {
  const view = useLoaderData() as DataProtection
  return (
    <>
      <PageHeader
        title="Data protection"
        lede="Sensitive data found in requests to models, and what was done about it. Values are never recorded, here or anywhere else; a request id leads to the request in the logs."
      />
      {view.enabled ? <Found view={view} /> : (
        <Section>
          <Muted>This console is not connected to the data-protection log.</Muted>
        </Section>
      )}
    </>
  )
}

function Found({ view }: { view: Extract<DataProtection, { enabled: true }> }) {
  const said = (action: string) => view.actions[action] ?? action
  return (
    <>
      <Stats label="Totals">
        <Stat label="Events read" value={view.read} />
        <Stat label="Times found" value={view.totals.reduce((total, row) => total + row.count, 0)} detail="sensitive data, in those events" />
        <Stat label="Kinds of data" value={new Set(view.totals.map((row) => row.kind)).size} />
      </Stats>
      <Section title="Totals">
        {view.totals.length === 0 ? (
          <Muted>Nothing has been found yet.</Muted>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={th}>Kind of data</TableHead>
                  <TableHead className={th}>What was done</TableHead>
                  <TableHead className={`${th} ${num}`}>Times</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.totals.map((total) => (
                  <TableRow key={`${total.kind} ${total.action}`}>
                    <TableCell>
                      <code>{total.kind}</code>
                    </TableCell>
                    <TableCell>{said(total.action)}</TableCell>
                    <TableCell className={num}>{total.count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Muted>Over the latest {view.read} events.</Muted>
          </>
        )}
      </Section>
      <Section
        title="Latest events"
        description={`Up to ${view.shown}, newest first. A refused request is one line, naming each kind of data that caused it.`}
      >
        <Table stack="medium">
          <TableHeader>
            <TableRow>
              <TableHead className={th}>When (UTC)</TableHead>
              <TableHead className={th}>Kind of data</TableHead>
              <TableHead className={th}>What was done</TableHead>
              <TableHead className={`${th} ${num}`}>Found</TableHead>
              <TableHead className={th}>Who</TableHead>
              <TableHead className={th}>Request</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.events.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  Nothing has been found yet.
                </TableCell>
              </TableRow>
            )}
            {view.events.map((event, index) => (
              <TableRow key={index}>
                <TableCell className="tabular-nums">{minute(event.at)}</TableCell>
                <TableCell>
                  {event.kinds.map((kind, at) => (
                    <Fragment key={kind}>
                      {at > 0 && ', '}
                      <code>{kind}</code>
                    </Fragment>
                  ))}
                </TableCell>
                <TableCell>
                  {event.blocked ? <Tag bad>request refused</Tag> : said(event.action)}
                  {event.source === 'response' && <span className="text-muted-foreground"> in the reply</span>}
                  {event.mode === 'observe' && <span className="text-muted-foreground"> (observe mode)</span>}
                </TableCell>
                <TableCell className={num}>{event.count || ''}</TableCell>
                <TableCell className="whitespace-normal">{event.email || event.user_id || 'a service'}</TableCell>
                <TableCell>
                  <code>{event.request}</code>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>
    </>
  )
}
