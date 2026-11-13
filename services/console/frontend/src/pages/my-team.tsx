import { useId, useState } from 'react'
import { useLoaderData } from 'react-router'
import { ActionButton } from '@/components/action-button'
import { CodeBlock } from '@/components/code-block'
import { Field, FormError } from '@/components/form-field'
import { Muted, PageHeader, Section } from '@/components/page'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table'
import { post, type ActionResult } from '@/lib/api'
import { day, usd } from '@/lib/format'
import { useSignedIn } from '@/lib/session'
import type { MyTeamPage } from '@/lib/types'
import { useAction } from '@/lib/use-action'

/** A key just made or replaced. It exists here, in this screen's memory, and nowhere else. */
type Shown = { name: string; key: string; rotated: boolean }

/**
 * A team, for someone who is in it: the terms, their keys, how to connect, their usage.
 *
 * A new key arrives in the answer to the call that made it and is kept only in this component's
 * state: not in storage, not in the address, not in the page's loaded data. Leave the screen or
 * reload it and the key is gone, which is the point.
 */
export function MyTeamPageView() {
  const view = useLoaderData() as MyTeamPage
  const { team, consent } = view
  const { gateway_url } = useSignedIn().config
  const [shown, setShown] = useState<Shown | null>(null)
  const live = team.status === 'active' && team.org_status === 'active'
  const agreed = consent?.terms_accepted === true
  const show = (result: ActionResult | undefined) => {
    if (result?.key) setShown({ ...result.key, rotated: result.rotated === true })
  }
  return (
    <>
      <PageHeader title={team.name} lede={team.org_name} />
      {!live && (
        <Alert className="mb-6">
          <AlertDescription>This team is closed. Its keys no longer work.</AlertDescription>
        </Alert>
      )}
      {shown && (
        <Section title={`${shown.rotated ? 'Your replacement key' : 'Your new key'}: ${shown.name}`}>
          <p>
            Copy it now. It will not be shown again.{shown.rotated && ' The key it replaces no longer works.'}
          </p>
          <CodeBlock value={shown.key} copy label={shown.rotated ? 'Your replacement key' : 'Your new key'} />
        </Section>
      )}
      <Terms view={view} live={live} />
      {agreed && (
        <>
          <Keys view={view} live={live} show={show} />
          <Section title="How to connect">
            <Labelled label="Base URL">
              <CodeBlock value={`${gateway_url}/v1`} />
            </Labelled>
            <Labelled label="Models">
              {view.models.length === 0 ? (
                <Muted>none yet</Muted>
              ) : (
                <p className="flex flex-wrap gap-x-4 gap-y-1">
                  {view.models.map((model) => (
                    <code key={model}>{model}</code>
                  ))}
                </p>
              )}
            </Labelled>
            <h3>Shared knowledge</h3>
            <p className="max-w-[75ch]">
              {team.org_name} has one knowledge base, shared by all its teams. Add it to an MCP client as a streamable HTTP server and
              send your key as the bearer token. Its tools are named <code>{view.knowledge_tools}-okf_search</code>,{' '}
              <code>{view.knowledge_tools}-okf_create</code> and so on.
            </p>
            <Labelled label="MCP URL">
              <CodeBlock value={`${gateway_url}/mcp`} />
            </Labelled>
          </Section>
          <Section title="Your usage">
            <dl className="grid grid-cols-3 gap-4">
              <Figure label="Requests" value={view.usage.requests} />
              <Figure label="Tokens" value={view.usage.tokens} />
              <Figure label="Spend" value={usd(view.usage.spend, 4)} />
            </dl>
          </Section>
        </>
      )}
    </>
  )
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-ui text-sm font-semibold tracking-wider uppercase">{label}</span>
      {children}
    </div>
  )
}

function Figure({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="font-ui text-xs font-semibold tracking-wider text-muted-foreground uppercase">{label}</dt>
      <dd className="font-heading text-2xl font-bold text-primary tabular-nums">{value}</dd>
    </div>
  )
}

/** The team's terms. Without accepting them there is no key; research use is a separate, optional yes. */
function Terms({ view: { team, consent }, live }: { view: MyTeamPage; live: boolean }) {
  const id = useId()
  const action = useAction()
  const [terms, setTerms] = useState(consent?.terms_accepted === true)
  const [research, setResearch] = useState(consent?.research_use === true)
  return (
    <Section title="Terms and research use">
      <div className="max-w-[75ch] rounded-md bg-muted p-4 whitespace-pre-wrap">{team.consent_text}</div>
      {live && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void action.run(() => post(`/teams/${team.id}/my/consent`, { terms_accepted: terms, research_use: research }), { inline: true })
          }}
        >
          <div className="flex items-center gap-3">
            <Checkbox id={`${id}-terms`} checked={terms} onCheckedChange={(ticked) => setTerms(ticked === true)} />
            <Label htmlFor={`${id}-terms`}>I accept these terms. Without this you cannot have a key.</Label>
          </div>
          <div className="flex items-center gap-3">
            <Checkbox id={`${id}-research`} checked={research} onCheckedChange={(ticked) => setResearch(ticked === true)} />
            <Label htmlFor={`${id}-research`}>My usage may also be used for research. This is optional.</Label>
          </div>
          <FormError message={action.error} />
          <div>
            <Button type="submit" disabled={action.pending} aria-busy={action.pending}>
              Save my choices
            </Button>
          </div>
        </form>
      )}
    </Section>
  )
}

function Keys({ view: { team, keys }, live, show }: { view: MyTeamPage; live: boolean; show: (result: ActionResult | undefined) => void }) {
  const create = useAction()
  const replace = useAction()
  return (
    <Section
      title="API keys"
      description={`${keys.length} of ${team.key_limit} · ${usd(team.key_budget)} per key · expire after ${team.key_expiry_days} days`}
    >
      {keys.length > 0 && (
        <Table>
          <TableBody>
            {keys.map((key) => (
              <TableRow key={key.id}>
                <TableCell>{key.name}</TableCell>
                <TableCell className="text-muted-foreground">
                  {key.waiting ? 'rotated by your lead; the old key no longer works' : `created ${day(key.created_at)}`}
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {live && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={replace.pending}
                      onClick={async () => show(await replace.run(() => post(`/teams/${team.id}/my/keys/${key.id}/rotate`)))}
                    >
                      {key.waiting ? 'Get replacement key' : 'Rotate'}
                    </Button>
                  )}
                  <ActionButton call={() => post(`/teams/${team.id}/my/keys/${key.id}/delete`)}>Delete</ActionButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {live && keys.length < team.key_limit && (
        <form
          className="flex flex-col gap-4"
          onSubmit={async (event) => {
            event.preventDefault()
            const form = event.currentTarget
            const name = String(new FormData(form).get('name') ?? '').trim()
            const made = await create.run(() => post(`/teams/${team.id}/my/keys`, { name }), { inline: true })
            if (made) form.reset()
            show(made)
          }}
        >
          <Field label="Name for a new key">
            <Input name="name" required maxLength={60} placeholder="e.g. laptop" className="max-w-md" />
          </Field>
          <FormError message={create.error} />
          <div>
            <Button type="submit" disabled={create.pending} aria-busy={create.pending}>
              Create key
            </Button>
          </div>
        </form>
      )}
    </Section>
  )
}
