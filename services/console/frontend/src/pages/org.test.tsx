import { cleanup, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { openApp } from '@/test/open'
import { serve, signedIn } from '@/test/server'

afterEach(() => vi.unstubAllGlobals())

const ORG = {
  org: { id: 'o1', name: 'Astro Lab', slug: 'astro', status: 'active', budget_ceiling: '100.00' },
  is_lead: true,
  is_admin: false,
  leads: [{ email: 'lead@uw.edu' }],
  lead_invites: [],
  models: [{ id: 'm1', public_name: 'astro/gpt', provider: 'openai' }],
  providers: ['openai', 'azure', 'mock'],
  teams: [{ id: 't1', name: 'Workshop', members: 4, team_budget: '50.00', status: 'archived' }],
}
const AS_ADMIN = {
  ...ORG,
  is_lead: false,
  is_admin: true,
  leads: [{ id: 'p2', email: 'lead@uw.edu' }],
  lead_invites: [
    { id: 'i1', email: 'new@uw.edu', status: 'pending', signin_email: null },
    { id: 'i2', email: 'other@uw.edu', status: 'needs_approval', signin_email: 'someone@else.org' },
  ],
}
const ok = { json: { message: 'Done.' } }
/** Opens one of the organization's tabs, as following its link does. */
async function tab(user: ReturnType<typeof userEvent.setup>, name: string) {
  const tabs = within(screen.getByRole('navigation', { name: 'Parts of Astro Lab' }))
  await user.click(tabs.getByRole('link', { name: new RegExp(`^${name}`) }))
  await tabs.findByRole('link', { name: new RegExp(`^${name}`), current: 'page' })
}

it('shows a lead the organization, with no admin controls and no lead invitations', async () => {
  const user = userEvent.setup()
  serve({ ...signedIn(), 'GET /web-api/orgs/o1': { json: ORG } })
  await openApp('/orgs/o1')
  expect(await screen.findByRole('heading', { name: 'Astro Lab', level: 1 })).toBeInTheDocument()
  expect(screen.getByText('Budget ceiling').parentElement).toHaveTextContent('$100.00')
  expect(screen.getByRole('link', { name: 'Knowledge base' })).toHaveAttribute('href', '/orgs/o1/knowledge')
  expect(screen.queryByRole('link', { name: /^Admin/ })).toBeNull() // no admin tab for a lead
  // Teams is the tab that opens first.
  expect(screen.getByRole('link', { name: 'Workshop' })).toHaveAttribute('href', '/teams/t1/manage')
  expect(within(screen.getByRole('link', { name: 'Workshop' }).closest('tr')!).getByText('archived')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create team' })).toBeInTheDocument()
  // A lead may remove a model, but not another lead.
  await tab(user, 'Models')
  expect(screen.getByRole('button', { name: 'Add model' })).toBeInTheDocument()
  expect(within(screen.getByText('astro/gpt').closest('tr')!).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  await tab(user, 'Leads')
  expect(within(screen.getByText('lead@uw.edu').closest('tr')!).queryByRole('button')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Send invitation' })).toBeNull()
})

it('shows an admin who is not a lead the admin controls, and no add-model or new-team form', async () => {
  const user = userEvent.setup()
  serve({ ...signedIn({ is_admin: true }), 'GET /web-api/orgs/o1': { json: AS_ADMIN } })
  await openApp('/orgs/o1')
  await screen.findByRole('heading', { name: 'Astro Lab', level: 1 })
  expect(screen.queryByRole('button', { name: 'Create team' })).toBeNull()
  expect(screen.queryByRole('link', { name: /knowledge base/i })).toBeNull()
  await tab(user, 'Admin')
  expect(screen.getByRole('button', { name: 'Save ceiling' })).toBeInTheDocument()
  expect(screen.getByLabelText(/Budget ceiling/)).toHaveValue(100)
  expect(screen.getByRole('button', { name: 'Suspend organization' })).toBeInTheDocument()
  await tab(user, 'Models')
  expect(screen.queryByRole('button', { name: 'Add model' })).toBeNull()
  expect(within(screen.getByText('astro/gpt').closest('tr')!).queryByRole('button')).toBeNull()
  await tab(user, 'Leads')
  expect(screen.getByRole('button', { name: 'Send invitation' })).toBeInTheDocument()
  expect(within(screen.getByText('lead@uw.edu').closest('tr')!).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  const pending = screen.getByText('new@uw.edu').closest('li')!
  expect(within(pending).getByText('invited, not yet accepted')).toBeInTheDocument()
  expect(within(pending).getByRole('button', { name: 'Cancel invitation' })).toBeInTheDocument()
  const waiting = screen.getByText('other@uw.edu').closest('li')!
  expect(within(waiting).getByText('someone@else.org')).toBeInTheDocument()
  expect(within(waiting).getByRole('button', { name: 'Approve' })).toBeInTheDocument()
})

it('hides add-model and new-team when the organization is suspended, and offers the admin Resume', async () => {
  const suspended = { ...ORG.org, status: 'suspended' }
  serve({ ...signedIn(), 'GET /web-api/orgs/o1': { json: { ...ORG, org: suspended } } })
  const user = userEvent.setup()
  await openApp('/orgs/o1')
  expect(await screen.findByText('suspended')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Create team' })).toBeNull()
  await tab(user, 'Models')
  expect(screen.queryByRole('button', { name: 'Add model' })).toBeNull()
  cleanup()

  serve({ ...signedIn({ is_admin: true }), 'GET /web-api/orgs/o1': { json: { ...AS_ADMIN, org: suspended } } })
  await openApp('/orgs/o1?tab=admin')
  expect(await screen.findByRole('button', { name: 'Resume organization' })).toBeInTheDocument()
})

it('sends the typed short name when removing and follows goto to /admin', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn({ is_admin: true }),
    'GET /web-api/orgs/o1': { json: AS_ADMIN },
    'POST /web-api/admin/orgs/o1/remove': { json: { message: 'Organization removed: 1 team(s) archived, 2 key(s) deleted, 1 model(s) removed.', goto: '/admin' } },
    'GET /web-api/admin/orgs': { json: { orgs: [] } },
  })
  const router = await openApp('/orgs/o1?tab=admin')
  await user.click(await screen.findByRole('button', { name: 'Remove organization' }))
  const dialog = screen.getByRole('dialog')
  await user.type(within(dialog).getByRole('textbox'), 'astro')
  await user.click(within(dialog).getByRole('button', { name: 'Remove organization' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
  expect(calls.find((call) => call.path.endsWith('/remove'))!.body).toEqual({ confirm_slug: 'astro' })
  expect(await screen.findByText(/Organization removed: 1 team\(s\) archived/)).toBeInTheDocument()
})

it('adds a model with the first provider chosen, and clears the provider key afterwards', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn(),
    'GET /web-api/orgs/o1': { json: ORG },
    'POST /web-api/orgs/o1/models': { json: { message: 'Added astro/gpt-5-mini. The key cannot be viewed again.' } },
  })
  await openApp('/orgs/o1?tab=models')
  const key = await screen.findByLabelText(/Provider API key/)
  expect(key).toHaveAttribute('type', 'password')
  expect(key).toHaveAttribute('autocomplete', 'off')
  await user.type(screen.getByLabelText('Model'), 'gpt-5-mini')
  await user.type(key, 'sk-provider-secret')
  await user.click(screen.getByRole('button', { name: 'Add model' }))
  expect(await screen.findByText('Added astro/gpt-5-mini. The key cannot be viewed again.')).toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST')!.body).toEqual({
    provider: 'openai', model: 'gpt-5-mini', api_key: 'sk-provider-secret', api_base: '', api_version: '',
  })
  expect(screen.getByLabelText(/Provider API key/)).toHaveValue('')
  expect(document.body.innerHTML).not.toContain('sk-provider-secret')
})

it('creates a team with numbers as numbers and follows goto', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn(),
    'GET /web-api/orgs/o1': { json: ORG },
    'POST /web-api/orgs/o1/teams': { json: { message: 'Created Notebooks.', goto: '/teams/t9/manage' } },
    'GET /web-api/teams/t9/manage': { status: 403, json: { error: { status: 403, message: 'You do not have access to that.' } } },
  })
  const router = await openApp('/orgs/o1')
  await user.type(await screen.findByLabelText('Name'), 'Notebooks')
  await user.type(screen.getByLabelText(/Team budget/), '40')
  await user.type(screen.getByLabelText(/Budget per key/), '2.5')
  await user.type(screen.getByLabelText(/Consent form/), 'Leads can see how much each person uses.')
  await user.click(screen.getByRole('button', { name: 'Create team' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/teams/t9/manage'))
  expect(calls.find((call) => call.method === 'POST')!.body).toEqual({
    name: 'Notebooks', team_budget: 40, key_budget: 2.5, key_limit: 3, key_expiry_days: 30,
    consent_text: 'Leads can see how much each person uses.',
  })
})

it('lets an admin decide a lead request, cancel an invitation, and remove a lead', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn({ is_admin: true }),
    'GET /web-api/orgs/o1': { json: AS_ADMIN },
    'POST /web-api/admin/orgs/o1/lead-requests/i2': ok,
    'POST /web-api/admin/orgs/o1/lead-invites/i1/revoke': ok,
    'POST /web-api/admin/orgs/o1/leads/p2/remove': ok,
    'POST /web-api/admin/orgs/o1/suspend': ok,
    'POST /web-api/admin/orgs/o1/leads': ok,
  })
  await openApp('/orgs/o1?tab=leads')
  await user.click(within((await screen.findByText('other@uw.edu')).closest('li')!).getByRole('button', { name: 'Reject' }))
  await user.click(within(screen.getByText('new@uw.edu').closest('li')!).getByRole('button', { name: 'Cancel invitation' }))
  await user.click(within(screen.getByText('lead@uw.edu').closest('tr')!).getByRole('button', { name: 'Remove' }))
  await user.type(screen.getByLabelText('Invite a lead by email'), 'fresh@uw.edu')
  await user.click(screen.getByRole('button', { name: 'Send invitation' }))
  await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(4))
  const posts = Object.fromEntries(calls.filter((call) => call.method === 'POST').map((call) => [call.path, call.body]))
  expect(posts['/web-api/admin/orgs/o1/lead-requests/i2']).toEqual({ approve: false })
  expect(posts).toHaveProperty(['/web-api/admin/orgs/o1/lead-invites/i1/revoke'])
  expect(posts).toHaveProperty(['/web-api/admin/orgs/o1/leads/p2/remove'])
  expect(posts['/web-api/admin/orgs/o1/leads']).toEqual({ email: 'fresh@uw.edu' })
})
