import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { openApp } from '@/test/open'
import { serve, signedIn } from '@/test/server'

afterEach(() => vi.unstubAllGlobals())

const admin = signedIn({ is_admin: true })
const ORGS = { orgs: [
  { id: 'o1', name: 'Astro Lab', slug: 'astro', budget_ceiling: '100.00', leads: 2, teams: 3, status: 'active' },
  { id: 'o2', name: 'Bio Lab', slug: 'bio', budget_ceiling: 50, leads: 0, teams: 0, status: 'suspended' },
] }

it('lists organizations with their ceiling, counts and status', async () => {
  serve({ ...admin, 'GET /web-api/admin/orgs': { json: ORGS } })
  await openApp('/admin')
  const row = (await screen.findByRole('link', { name: 'Astro Lab' })).closest('tr')!
  expect(screen.getByRole('link', { name: 'Astro Lab' })).toHaveAttribute('href', '/orgs/o1')
  expect(within(row).getByText('astro')).toBeInTheDocument()
  expect(within(row).getByText('$100.00')).toBeInTheDocument()
  expect(within(screen.getByRole('link', { name: 'Bio Lab' }).closest('tr')!).getByText('suspended')).toBeInTheDocument()
  expect(within(row).queryByText('active')).toBeNull()
  expect(screen.getByRole('link', { name: 'Organizations' })).toHaveAttribute('aria-current', 'page')
})

it('says so when there are no organizations', async () => {
  serve({ ...admin, 'GET /web-api/admin/orgs': { json: { orgs: [] } } })
  await openApp('/admin')
  expect(await screen.findByText('No organizations yet.')).toBeInTheDocument()
})

it('posts the new organization and follows goto', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...admin,
    'GET /web-api/admin/orgs': { json: { orgs: [] } },
    'POST /web-api/admin/orgs': { json: { message: 'Created Chem Lab.', goto: '/orgs/o9' } },
    'GET /web-api/orgs/o9': { status: 403, json: { error: { status: 403, message: 'You do not have access to that.' } } },
  })
  const router = await openApp('/admin')
  await user.type(await screen.findByLabelText('Name'), 'Chem Lab')
  await user.type(screen.getByLabelText(/Short name/), 'chem')
  await user.type(screen.getByLabelText(/Budget ceiling/), '25.5')
  await user.click(screen.getByRole('button', { name: 'Create organization' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/orgs/o9'))
  const sent = calls.find((call) => call.method === 'POST')!
  expect(sent.body).toEqual({ name: 'Chem Lab', slug: 'chem', budget_ceiling: 25.5 })
  expect(sent.headers.get('x-csrf-token')).toBe('csrf-token')
  expect(await screen.findByText('Created Chem Lab.')).toBeInTheDocument()
})

it("shows the server's message beside the form when the short name is taken", async () => {
  const user = userEvent.setup()
  serve({
    ...admin,
    'GET /web-api/admin/orgs': { json: { orgs: [] } },
    'POST /web-api/admin/orgs': { status: 409, json: { error: { status: 409, message: 'That short name is taken.' } } },
  })
  const router = await openApp('/admin')
  await user.type(await screen.findByLabelText('Name'), 'Chem Lab')
  await user.type(screen.getByLabelText(/Short name/), 'chem')
  await user.type(screen.getByLabelText(/Budget ceiling/), '25')
  await user.click(screen.getByRole('button', { name: 'Create organization' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That short name is taken.')
  expect(router.state.location.pathname).toBe('/admin')
  expect(screen.getByLabelText('Name')).toHaveValue('Chem Lab') // what was typed is still there to correct
})

it('shows the audit log, with a dash where nobody or nothing applies', async () => {
  serve({ ...admin, 'GET /web-api/admin/audit': { json: { events: [
    { at: '2026-11-12T08:15:02.123456+00:00', actor_email: 'a@uw.edu', actor_role: 'admin', action: 'org.create', result: 'ok', org_name: 'Astro Lab', team_name: null },
    { at: '2026-11-12T08:14:00+00:00', actor_email: null, actor_role: 'integration:hub', action: 'integration.enroll', result: 'denied', org_name: null, team_name: null },
  ] } } })
  await openApp('/admin/audit')
  const row = (await screen.findByText('org.create')).closest('tr')!
  expect(within(row).getByText('2026-11-12 08:15:02')).toBeInTheDocument()
  expect(within(row).getByText('a@uw.edu')).toBeInTheDocument()
  expect(within(row).getByText('Astro Lab')).toBeInTheDocument()
  const other = screen.getByText('integration.enroll').closest('tr')!
  expect(within(other).getByText('integration:hub')).toBeInTheDocument()
  expect(within(other).getAllByText('—')).toHaveLength(3)
  expect(within(other).getByText('denied')).toBeInTheDocument()
})

const event = { at: '2026-11-12T09:00:00+00:00', kinds: ['credit_card'], blocked: false, action: 'mask', source: 'request', mode: 'enforce', count: 2, email: 'p@uw.edu', user_id: 'u-1', request: '0123abcd' }

it("labels a blocked event 'request refused' and maps other actions through the server's labels", async () => {
  serve({ ...admin, 'GET /web-api/admin/dlp': { json: {
    enabled: true, read: 12, shown: 100, actions: { mask: 'hidden from the model', observe: 'only noted' },
    totals: [{ kind: 'credit_card', action: 'mask', count: 3 }, { kind: 'ssn', action: 'unheard-of', count: 1 }],
    events: [
      { ...event, blocked: true, kinds: ['credit_card', 'ssn'], count: null },
      { ...event, source: 'response', request: 'aaaa1111' },
      { ...event, action: 'observe', mode: 'observe', email: null, request: 'bbbb2222' },
      { ...event, email: null, user_id: null, request: 'cccc3333' },
    ],
  } } })
  await openApp('/admin/dlp')
  const refused = (await screen.findByText('request refused')).closest('tr')!
  expect(within(refused).getByText('credit_card')).toBeInTheDocument()
  expect(within(refused).getByText('ssn')).toBeInTheDocument()
  expect(within(refused).getByText('0123abcd')).toBeInTheDocument()
  const reply = screen.getByText('aaaa1111').closest('tr')!
  expect(within(reply).getByText('hidden from the model')).toBeInTheDocument()
  expect(within(reply).getByText('in the reply')).toBeInTheDocument()
  const observed = screen.getByText('bbbb2222').closest('tr')!
  expect(within(observed).getByText('only noted')).toBeInTheDocument()
  expect(within(observed).getByText('(observe mode)')).toBeInTheDocument()
  expect(within(observed).getByText('u-1')).toBeInTheDocument() // no email on record: the id the request carried
  expect(within(screen.getByText('cccc3333').closest('tr')!).getByText('a service')).toBeInTheDocument()
  expect(screen.getByText('unheard-of')).toBeInTheDocument() // an action with no label is shown as it is
  expect(screen.getByText('Over the latest 12 events.')).toBeInTheDocument()
})

it('says the console is not connected when enabled is false', async () => {
  serve({ ...admin, 'GET /web-api/admin/dlp': { json: { enabled: false } } })
  await openApp('/admin/dlp')
  expect(await screen.findByText('This console is not connected to the data-protection log.')).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
})

it('says nothing has been found when the log is empty', async () => {
  serve({ ...admin, 'GET /web-api/admin/dlp': { json: { enabled: true, read: 0, shown: 100, actions: {}, totals: [], events: [] } } })
  await openApp('/admin/dlp')
  expect(await screen.findAllByText('Nothing has been found yet.')).toHaveLength(2)
})

it('gives the short name a pattern browsers can apply', async () => {
  serve({ ...admin, 'GET /web-api/admin/orgs': { json: { orgs: [] } } })
  await openApp('/admin')
  const pattern = (await screen.findByLabelText(/Short name/)).getAttribute('pattern')!
  // Browsers compile `pattern` with the v flag, under which an unescaped "-" in a class is an error
  // and the whole pattern is silently ignored.
  const rule = new RegExp(`^(?:${pattern})$`, 'v')
  expect(rule.test('uw-ess')).toBe(true)
  expect(rule.test('Not A Slug')).toBe(false)
  expect(rule.test('-leading')).toBe(false)
})
