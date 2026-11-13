import { useId, useState } from 'react'
import { Link, useLoaderData } from 'react-router'
import { ActionButton } from '@/components/action-button'
import { ActionForm } from '@/components/action-form'
import { Field } from '@/components/form-field'
import { Muted, PageHeader, Section, SubHeading } from '@/components/page'
import { PendingInvites } from '@/components/pending-invites'
import { StatusTag } from '@/components/status-badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { post, postForm } from '@/lib/api'
import { number } from '@/lib/forms'
import { usd } from '@/lib/format'
import { useSignedIn } from '@/lib/session'
import { num, th } from '@/lib/styles'
import type { TeamManagePage } from '@/lib/types'
import { useAction } from '@/lib/use-action'
import { ConnectedServices, KeysSection, RemoveTeam, UsageSection } from './team-manage-sections'

/**
 * A team, for its organization's lead and for SSEC admins. `live` is the lead's controls being
 * shown: a lead, on a team that is active, in an organization that is active. An admin who is not
 * the lead can only remove people and remove the team. As everywhere, these flags decide what is
 * shown and the server decides what is allowed.
 */
export function TeamManagePageView() {
  const view = useLoaderData() as TeamManagePage
  const { team, is_lead } = view
  const { is_admin } = useSignedIn().me
  const live = is_lead && team.status === 'active' && team.org_status === 'active'
  return (
    <>
      <PageHeader
        back={{ to: `/orgs/${team.org_id}`, label: team.org_name }}
        title={team.name}
        tag={<StatusTag status={team.status} />}
        lede={`Up to ${team.key_limit} keys per person · ${usd(team.key_budget)} per key · keys expire after ${team.key_expiry_days} days`}
      />
      {!is_lead && (
        <Note>
          You are viewing this team as an SSEC admin. You can remove people from it; everything else here is for the organization's
          lead.
        </Note>
      )}
      {team.status === 'archived' && <Note>This team is archived. Its keys are deleted and nothing here can be changed.</Note>}

      <Section title="Budget">
        <ActionForm
          keep
          submit={live ? 'Save budget' : undefined}
          call={(fields) => post(`/teams/${team.id}/budget`, { team_budget: number(fields, 'team_budget') })}
        >
          <Field label={`Team budget (USD), up to the organization's ceiling of ${usd(team.org_budget_ceiling)}`}>
            <Input name="team_budget" type="number" min={0} step={0.01} required defaultValue={Number(team.team_budget)} disabled={!live} className="max-w-60" />
          </Field>
        </ActionForm>
      </Section>

      <Section title="Models this team may use">
        {view.models.length === 0 ? (
          <Muted>
            The organization has no models yet. <Link to={`/orgs/${team.org_id}`}>Add one</Link>.
          </Muted>
        ) : (
          <ModelChoice view={view} live={live} />
        )}
      </Section>

      <People view={view} live={live} isAdmin={is_admin} />
      <KeysSection view={view} live={live} />
      <UsageSection view={view} />

      {live && (
        <Section title="Archive" description="Deletes every key in this team and makes it read-only. Records are kept. This cannot be undone.">
          <div>
            <ActionButton
              variant="destructive"
              size="default"
              call={() => post(`/teams/${team.id}/archive`)}
              confirm={{ title: `Archive ${team.name}?`, description: 'Every key in this team is deleted and the team becomes read-only. This cannot be undone.' }}
            >
              Archive team
            </ActionButton>
          </div>
        </Section>
      )}
      {(view.integrations.length > 0 || is_admin) && <ConnectedServices view={view} isAdmin={is_admin} />}
      {is_admin && <RemoveTeam view={view} />}
    </>
  )
}

function Note({ children }: { children: string }) {
  return (
    <Alert className="mb-6">
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  )
}

/** The organization's models, ticked for the ones this team may call. */
function ModelChoice({ view: { team, models }, live }: { view: TeamManagePage; live: boolean }) {
  const id = useId()
  const action = useAction()
  const [chosen, setChosen] = useState(() => new Set(models.filter((model) => model.allowed).map((model) => model.id)))
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        void action.run(() => post(`/teams/${team.id}/models`, { model_ids: models.filter((model) => chosen.has(model.id)).map((model) => model.id) }))
      }}
    >
      {models.map((model) => (
        <div key={model.id} className="flex items-center gap-3">
          <Checkbox
            id={`${id}-${model.id}`}
            checked={chosen.has(model.id)}
            disabled={!live}
            onCheckedChange={(ticked) => {
              const next = new Set(chosen)
              if (ticked === true) next.add(model.id)
              else next.delete(model.id)
              setChosen(next)
            }}
          />
          <Label htmlFor={`${id}-${model.id}`}>
            <code>{model.public_name}</code>
          </Label>
        </div>
      ))}
      {live && (
        <div>
          <Button type="submit" disabled={action.pending} aria-busy={action.pending}>
            Save models
          </Button>
        </div>
      )}
    </form>
  )
}

function People({ view: { team, members, invites }, live, isAdmin }: { view: TeamManagePage; live: boolean; isAdmin: boolean }) {
  const mayRemove = live || (isAdmin && team.status === 'active')
  return (
    <Section title="People">
      {members.length === 0 ? (
        <Muted>Nobody has joined yet.</Muted>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Email</TableHead>
              <TableHead className={th}>Terms</TableHead>
              <TableHead className={`${th} ${num}`}>Keys</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => (
              <TableRow key={member.id}>
                <TableCell>{member.email}</TableCell>
                <TableCell>{member.terms_accepted ? 'accepted' : 'not accepted'}</TableCell>
                <TableCell className={num}>{member.keys}</TableCell>
                <TableCell className="text-right">
                  {mayRemove && <ActionButton call={() => post(`/teams/${team.id}/members/${member.id}/remove`)}>Remove</ActionButton>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <PendingInvites
        invites={invites}
        decide={(invite, approve) => post(`/teams/${team.id}/requests/${invite.id}`, { approve })}
        cancel={live ? (invite) => post(`/teams/${team.id}/invites/${invite.id}/revoke`) : undefined}
      />
      {live && (
        <>
          <SubHeading>Invite people</SubHeading>
          {/* The one form sent as a form: it can carry a file, which the server reads. */}
          <ActionForm submit="Send invitations" call={(fields) => postForm(`/teams/${team.id}/invites`, fields)}>
            <Field label="Email addresses, one per line">
              <Textarea name="emails" rows={4} />
            </Field>
            <Field
              label={
                <>
                  Or a CSV file with an <code className="normal-case">email</code> column
                </>
              }
            >
              <Input name="csv_file" type="file" accept=".csv,text/csv" />
            </Field>
          </ActionForm>
        </>
      )}
    </Section>
  )
}
