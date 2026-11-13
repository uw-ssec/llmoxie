// The lower half of the team screen: keys, usage, connected services, and removing the team.
import { ActionButton } from '@/components/action-button'
import { ActionForm } from '@/components/action-form'
import { Field, Row } from '@/components/form-field'
import { Muted, Section, SubHeading } from '@/components/page'
import { Tag } from '@/components/status-badge'
import { TypeToConfirmDialog } from '@/components/type-to-confirm-dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { post } from '@/lib/api'
import { text } from '@/lib/forms'
import { day, usd } from '@/lib/format'
import { num, th } from '@/lib/styles'
import type { TeamManagePage } from '@/lib/types'
import { useAction } from '@/lib/use-action'

/** Whose keys exist, and what they have spent. Never a key: only its owner sees one, once. */
export function KeysSection({ view: { team, keys }, live }: { view: TeamManagePage; live: boolean }) {
  return (
    <Section
      title="Keys"
      description="Each person's keys. Only the owner ever sees a key itself, once, when they create it. Rotate stops a key at once and lets its owner collect a replacement; Revoke removes it."
    >
      <Table>
        <TableHeader>
          <TableRow>
            {['Email', 'Name', 'Key', 'Created', 'Expires', 'Last used'].map((heading) => (
              <TableHead key={heading} className={th}>
                {heading}
              </TableHead>
            ))}
            <TableHead className={`${th} ${num}`}>Spend</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="text-muted-foreground">
                {team.status === 'archived' ? 'Archived teams have no keys.' : 'Nobody has created a key yet.'}
              </TableCell>
            </TableRow>
          )}
          {keys.map((key) => (
            <TableRow key={key.id}>
              <TableCell>{key.email}</TableCell>
              <TableCell>{key.name}</TableCell>
              <TableCell>{key.waiting ? <Tag>rotated, not collected yet</Tag> : <code>{key.hint ?? '—'}</code>}</TableCell>
              <TableCell className="tabular-nums">{day(key.created_at)}</TableCell>
              <TableCell className="tabular-nums">{key.expires ? day(key.expires) : '—'}</TableCell>
              <TableCell className="tabular-nums">{key.last_used ? day(key.last_used) : 'never'}</TableCell>
              <TableCell className={num}>
                {usd(key.spend, 4)} of {usd(team.key_budget)}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap">
                {live && !key.waiting && <ActionButton call={() => post(`/teams/${team.id}/keys/${key.id}/rotate`)}>Rotate</ActionButton>}
                {live && <ActionButton call={() => post(`/teams/${team.id}/keys/${key.id}/revoke`)}>Revoke</ActionButton>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  )
}

export function UsageSection({ view: { usage } }: { view: TeamManagePage }) {
  return (
    <Section title="Usage" description="Totals per person. Prompts and responses are never shown here.">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className={th}>Email</TableHead>
            {['Requests', 'Failed', 'Tokens', 'Spend'].map((heading) => (
              <TableHead key={heading} className={`${th} ${num}`}>
                {heading}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {usage.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                No members yet.
              </TableCell>
            </TableRow>
          )}
          {usage.map((row) => (
            <TableRow key={row.email}>
              <TableCell>{row.email}</TableCell>
              <TableCell className={num}>{row.requests}</TableCell>
              <TableCell className={num}>{row.failed}</TableCell>
              <TableCell className={num}>{row.tokens}</TableCell>
              <TableCell className={num}>{usd(row.spend, 4)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  )
}

/** Outside services that may fetch a key for a member signed in to them. Only an admin connects one. */
export function ConnectedServices({ view: { team, integrations }, isAdmin }: { view: TeamManagePage; isAdmin: boolean }) {
  return (
    <Section
      title="Connected services"
      description="Outside services, such as a JupyterHub, that may fetch a key for a member who is signed in to them. Only an SSEC admin can connect or disconnect one."
    >
      {integrations.length === 0 ? (
        <Muted>None.</Muted>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Name</TableHead>
              <TableHead className={th}>Client</TableHead>
              <TableHead className={th}>May add members</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {integrations.map((service) => (
              <TableRow key={service.id}>
                <TableCell>{service.name}</TableCell>
                <TableCell>
                  <code>{service.client_id}</code>
                </TableCell>
                <TableCell>{service.can_enroll ? 'yes' : 'no'}</TableCell>
                <TableCell className="text-right">
                  {isAdmin && <ActionButton call={() => post(`/admin/integrations/${service.id}/remove`)}>Disconnect</ActionButton>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {isAdmin && team.status === 'active' && (
        <>
          <SubHeading>Connect a service</SubHeading>
          <ActionForm
            submit="Connect service"
            call={(fields) =>
              post(`/admin/teams/${team.id}/integrations`, {
                client_id: text(fields, 'client_id'),
                name: text(fields, 'name'),
                can_enroll: fields.get('can_enroll') === 'on',
              })
            }
          >
            <Row>
              <Field label="Its client ID in Keycloak">
                <Input name="client_id" required maxLength={80} placeholder="e.g. jupyterhub" />
              </Field>
              <Field label="Name, also used for the keys it issues">
                <Input name="name" required maxLength={40} placeholder="e.g. JupyterHub" />
              </Field>
            </Row>
            <div className="flex items-center gap-3">
              <Checkbox id="can-enroll" name="can_enroll" />
              <Label htmlFor="can-enroll">It may add its signed-in users to this team without an invitation</Label>
            </div>
          </ActionForm>
        </>
      )}
    </Section>
  )
}

export function RemoveTeam({ view: { team } }: { view: TeamManagePage }) {
  const removal = useAction()
  return (
    <Section
      title="Remove team"
      description="For SSEC admins. Deletes every key in this team, removes its members and takes the team off the console. Records and logs are kept; the organization's models are not touched. This cannot be undone."
    >
      <div>
        <TypeToConfirmDialog
          trigger="Remove team"
          title={`Remove ${team.name}`}
          description="Every key in this team is deleted and its members removed. This cannot be undone."
          prompt={
            <>
              Type the team's name <code>{team.name}</code> to confirm
            </>
          }
          expected={team.name}
          confirmLabel="Remove team"
          onConfirm={(typed) => removal.run(() => post(`/admin/teams/${team.id}/remove`, { confirm_name: typed }))}
        />
      </div>
    </Section>
  )
}
