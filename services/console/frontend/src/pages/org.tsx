import { Link, useLoaderData } from 'react-router'
import { ActionButton } from '@/components/action-button'
import { ActionForm } from '@/components/action-form'
import { Field, Row } from '@/components/form-field'
import { Muted, PageHeader, Section, SubHeading } from '@/components/page'
import { PendingInvites } from '@/components/pending-invites'
import { StatusTag } from '@/components/status-badge'
import { TypeToConfirmDialog } from '@/components/type-to-confirm-dialog'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { post } from '@/lib/api'
import { number, text } from '@/lib/forms'
import { usd } from '@/lib/format'
import { num, th } from '@/lib/styles'
import type { OrgPage } from '@/lib/types'
import { useAction } from '@/lib/use-action'

/**
 * An organization, for its leads and for SSEC admins. What each may do differs: a lead runs it
 * (models, teams), an admin governs it (ceiling, suspension, who leads). The flags only decide
 * what is shown; the server refuses the rest whatever the page shows.
 */
export function OrgPageView() {
  const view = useLoaderData() as OrgPage
  const { org, is_lead, is_admin } = view
  const live = is_lead && org.status === 'active'
  return (
    <>
      <PageHeader
        title={org.name}
        tag={<StatusTag status={org.status} />}
        lede={
          <>
            Short name <code>{org.slug}</code> · budget ceiling {usd(org.budget_ceiling)}
          </>
        }
      />
      {is_admin && <AdminSection view={view} />}
      {is_lead && (
        <Section title="Knowledge">
          <p>
            One knowledge base, shared by all of {org.name}'s teams and written through their MCP clients. Only leads can read all of it
            here.
          </p>
          <p>
            <Link to={`/orgs/${org.id}/knowledge`}>Browse the knowledge base and its graph</Link>
          </p>
        </Section>
      )}
      <Leads view={view} />
      <Models view={view} live={live} />
      <Teams view={view} live={live} />
    </>
  )
}

function AdminSection({ view: { org } }: { view: OrgPage }) {
  const removal = useAction()
  const suspended = org.status !== 'active'
  return (
    <Section title="Admin">
      <ActionForm
        keep
        submit="Save ceiling"
        call={(fields) => post(`/admin/orgs/${org.id}/ceiling`, { budget_ceiling: number(fields, 'budget_ceiling') })}
      >
        <Field label="Budget ceiling (USD)">
          <Input name="budget_ceiling" type="number" min={0} step={0.01} required defaultValue={Number(org.budget_ceiling)} className="max-w-60" />
        </Field>
      </ActionForm>
      <div>
        {suspended ? (
          <ActionButton variant="default" size="default" call={() => post(`/admin/orgs/${org.id}/resume`)}>
            Resume organization
          </ActionButton>
        ) : (
          <ActionButton variant="destructive" size="default" call={() => post(`/admin/orgs/${org.id}/suspend`)}>
            Suspend organization
          </ActionButton>
        )}
      </div>
      <SubHeading>Remove organization</SubHeading>
      <Muted>
        Deletes every key, archives every team, removes the organization's models and provider keys, and ends access for its leads and
        members. Records and logs are kept. This cannot be undone.
      </Muted>
      <div>
        <TypeToConfirmDialog
          trigger="Remove organization"
          title={`Remove ${org.name}`}
          description="Every key is deleted, every team archived, and its models and provider keys removed. This cannot be undone."
          prompt={
            <>
              Type the short name <code>{org.slug}</code> to confirm
            </>
          }
          expected={org.slug}
          confirmLabel="Remove organization"
          onConfirm={(typed) => removal.run(() => post(`/admin/orgs/${org.id}/remove`, { confirm_slug: typed }))}
        />
      </div>
    </Section>
  )
}

function Leads({ view: { org, leads, lead_invites, is_admin } }: { view: OrgPage }) {
  return (
    <Section title="Leads">
      {leads.length === 0 ? (
        <Muted>No lead has accepted an invitation yet.</Muted>
      ) : (
        <Table>
          <TableBody>
            {leads.map((lead) => (
              <TableRow key={lead.email}>
                <TableCell>{lead.email}</TableCell>
                <TableCell className="text-right">
                  {is_admin && lead.id && (
                    <ActionButton call={() => post(`/admin/orgs/${org.id}/leads/${lead.id}/remove`)}>Remove</ActionButton>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {is_admin && (
        <>
          <PendingInvites
            invites={lead_invites}
            decide={(invite, approve) => post(`/admin/orgs/${org.id}/lead-requests/${invite.id}`, { approve })}
            cancel={(invite) => post(`/admin/orgs/${org.id}/lead-invites/${invite.id}/revoke`)}
          />
          <ActionForm submit="Send invitation" call={(fields) => post(`/admin/orgs/${org.id}/leads`, { email: text(fields, 'email') })}>
            <Field label="Invite a lead by email">
              <Input name="email" type="email" required className="max-w-md" />
            </Field>
          </ActionForm>
        </>
      )}
    </Section>
  )
}

function Models({ view: { org, models, providers, is_lead }, live }: { view: OrgPage; live: boolean }) {
  return (
    <Section title="Models">
      {models.length === 0 ? (
        <Muted>No models yet.</Muted>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Name clients use</TableHead>
              <TableHead className={th}>Provider</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => (
              <TableRow key={model.id}>
                <TableCell>
                  <code>{model.public_name}</code>
                </TableCell>
                <TableCell>{model.provider}</TableCell>
                <TableCell className="text-right">
                  {is_lead && <ActionButton call={() => post(`/orgs/${org.id}/models/${model.id}/remove`)}>Remove</ActionButton>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {live && (
        <>
          <SubHeading>Add a model</SubHeading>
          {/* The provider key is sent once and never comes back; the form empties itself afterwards. */}
          <ActionForm
            autoComplete="off"
            submit="Add model"
            call={(fields) =>
              post(`/orgs/${org.id}/models`, {
                provider: text(fields, 'provider'),
                model: text(fields, 'model'),
                api_key: text(fields, 'api_key'),
                api_base: text(fields, 'api_base'),
                api_version: text(fields, 'api_version'),
              })
            }
          >
            <Row>
              <Field label="Provider">
                <NativeSelect name="provider" defaultValue={providers[0]}>
                  {providers.map((provider) => (
                    <NativeSelectOption key={provider} value={provider}>
                      {provider}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Model">
                <Input name="model" required maxLength={80} placeholder="e.g. gpt-5-mini" />
              </Field>
            </Row>
            <Field label="Provider API key" hint="Stored encrypted; it cannot be viewed again.">
              <Input name="api_key" type="password" required autoComplete="off" />
            </Field>
            <Row>
              <Field label="Azure endpoint (Azure only)">
                <Input name="api_base" placeholder="https://<resource>.openai.azure.com" />
              </Field>
              <Field label="Azure API version (Azure only)">
                <Input name="api_version" placeholder="2024-12-01-preview" />
              </Field>
            </Row>
          </ActionForm>
        </>
      )}
    </Section>
  )
}

function Teams({ view: { org, teams }, live }: { view: OrgPage; live: boolean }) {
  return (
    <Section title="Teams">
      {teams.length === 0 ? (
        <Muted>No teams yet.</Muted>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={th}>Team</TableHead>
              <TableHead className={`${th} ${num}`}>Members</TableHead>
              <TableHead className={`${th} ${num}`}>Budget</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {teams.map((team) => (
              <TableRow key={team.id}>
                <TableCell>
                  <Link to={`/teams/${team.id}/manage`}>{team.name}</Link>
                </TableCell>
                <TableCell className={num}>{team.members}</TableCell>
                <TableCell className={num}>{usd(team.team_budget)}</TableCell>
                <TableCell className="text-right">
                  <StatusTag status={team.status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {live && (
        <>
          <SubHeading>New team</SubHeading>
          <ActionForm
            submit="Create team"
            call={(fields) =>
              post(`/orgs/${org.id}/teams`, {
                name: text(fields, 'name'),
                team_budget: number(fields, 'team_budget'),
                key_budget: number(fields, 'key_budget'),
                key_limit: number(fields, 'key_limit'),
                key_expiry_days: number(fields, 'key_expiry_days'),
                consent_text: text(fields, 'consent_text'),
              })
            }
          >
            <Field label="Name">
              <Input name="name" required minLength={2} maxLength={60} />
            </Field>
            <Row>
              <Field label="Team budget (USD)">
                <Input name="team_budget" type="number" min={0} step={0.01} required />
              </Field>
              <Field label="Budget per key (USD)">
                <Input name="key_budget" type="number" min={0} step={0.01} required />
              </Field>
            </Row>
            <Row>
              <Field label="Keys per person">
                <Input name="key_limit" type="number" min={1} max={20} defaultValue={3} required />
              </Field>
              <Field label="Keys expire after (days)">
                <Input name="key_expiry_days" type="number" min={1} max={365} defaultValue={30} required />
              </Field>
            </Row>
            <Field label="Consent form shown to participants" hint="Say that leads can see each person's usage totals.">
              <Textarea name="consent_text" required minLength={20} rows={5} />
            </Field>
          </ActionForm>
        </>
      )}
    </Section>
  )
}
