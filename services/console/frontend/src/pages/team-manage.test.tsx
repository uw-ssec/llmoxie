import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { openApp } from '@/test/open'
import { serve, signedIn } from '@/test/server'

afterEach(() => vi.unstubAllGlobals())

const TEAM = {
  team: { id: 't1', name: 'Workshop', status: 'active', org_id: 'o1', org_name: 'Astro Lab', org_status: 'active',
          org_budget_ceiling: '100.00', team_budget: '50.00', key_limit: 2, key_budget: '5.00', key_expiry_days: 30 },
  is_lead: true,
  models: [{ id: 'm1', public_name: 'astro/gpt', allowed: true }, { id: 'm2', public_name: 'astro/claude', allowed: false }],
  members: [{ id: 'p1', email: 'p1@uw.edu', terms_accepted: true, keys: 1 }, { id: 'p2', email: 'p2@uw.edu', terms_accepted: null, keys: 0 }],
  invites: [
    { id: 'i1', email: 'new@uw.edu', status: 'pending', signin_email: null },
    { id: 'i2', email: 'asked@uw.edu', status: 'needs_approval', signin_email: 'other@x.org' },
  ],
  keys: [
    { id: 'k1', email: 'p1@uw.edu', name: 'laptop', waiting: false, hint: 'sk-...abcd', created_at: '2026-11-02T10:00:00Z', expires: '2026-12-02T10:00:00Z', last_used: null, spend: 0.0125 },
    { id: 'k2', email: 'p1@uw.edu', name: 'desk', waiting: true, hint: null, created_at: '2026-11-03T10:00:00Z', expires: null, last_used: null, spend: 0 },
  ],
  usage: [{ email: 'p1@uw.edu', requests: 12, failed: 1, tokens: 3400, spend: 0.0125 }],
  integrations: [{ id: 'g1', name: 'JupyterHub', client_id: 'jupyterhub', can_enroll: true }],
}
const page = (view: unknown) => ({ 'GET /web-api/teams/t1/manage': { json: view } })
const ok = { json: { message: 'Done.' } }
const LEAD_ONLY = ['Save budget', 'Save models', 'Send invitations', 'Rotate', 'Revoke', 'Cancel invitation', 'Archive team']

it('gives the lead every control, and shows who holds which key but never a key', async () => {
  serve({ ...signedIn(), ...page(TEAM) })
  await openApp('/teams/t1/manage')
  expect(await screen.findByRole('heading', { name: 'Workshop', level: 1 })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '← Astro Lab' })).toHaveAttribute('href', '/orgs/o1')
  expect(screen.getByText('Up to 2 keys per person · $5.00 per key · keys expire after 30 days')).toBeInTheDocument()
  expect(screen.queryByText(/viewing this team as an SSEC admin/)).toBeNull()
  for (const name of LEAD_ONLY) expect(screen.getAllByRole('button', { name }).length).toBeGreaterThan(0)
  for (const name of ['Remove team', 'Connect service', 'Disconnect']) expect(screen.queryByRole('button', { name })).toBeNull()
  expect(screen.getByText('JupyterHub')).toBeInTheDocument() // a lead can see what is connected

  const laptop = screen.getByText('laptop').closest('tr')!
  expect(within(laptop).getByText('sk-...abcd')).toBeInTheDocument()
  expect(within(laptop).getByText('$0.0125 of $5.00')).toBeInTheDocument()
  expect(within(laptop).getByText('never')).toBeInTheDocument()
  const desk = screen.getByText('desk').closest('tr')!
  expect(within(desk).getByText('rotated, not collected yet')).toBeInTheDocument()
  expect(within(desk).queryByRole('button', { name: 'Rotate' })).toBeNull() // nothing to rotate until it is collected
  expect(within(desk).getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
  expect(within(screen.getByText('p2@uw.edu').closest('tr')!).getByText('not accepted')).toBeInTheDocument()
})

it('gives an admin who is not the lead only the remove-member, service and remove-team controls', async () => {
  serve({ ...signedIn({ is_admin: true }), ...page({ ...TEAM, is_lead: false }) })
  await openApp('/teams/t1/manage')
  expect(await screen.findByText(/You are viewing this team as an SSEC admin/)).toBeInTheDocument()
  for (const name of LEAD_ONLY) expect(screen.queryByRole('button', { name })).toBeNull()
  expect(screen.getByLabelText(/Team budget/)).toBeDisabled()
  for (const box of screen.getAllByRole('checkbox', { name: /^astro\// })) expect(box).toBeDisabled()
  expect(within(screen.getAllByText('p1@uw.edu')[0].closest('tr')!).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  for (const name of ['Remove team', 'Connect service', 'Disconnect']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
  // A request waiting for a decision is still shown with its buttons; the server decides whose it is to answer.
  expect(within(screen.getByText('asked@uw.edu').closest('li')!).getByRole('button', { name: 'Approve' })).toBeInTheDocument()
})

it('freezes every control on an archived team', async () => {
  const archived = { ...TEAM, team: { ...TEAM.team, status: 'archived' }, keys: [], invites: [] }
  serve({ ...signedIn(), ...page(archived) })
  await openApp('/teams/t1/manage')
  expect(await screen.findByText('This team is archived. Its keys are deleted and nothing here can be changed.')).toBeInTheDocument()
  expect(screen.getByText('Archived teams have no keys.')).toBeInTheDocument()
  expect(screen.getByLabelText(/Team budget/)).toBeDisabled()
  expect(screen.queryAllByRole('button').map((b) => b.textContent)).toEqual(['Sign out'])
})

it('saves the budget as a number and the ticked models as ids', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...signedIn(), ...page(TEAM), 'POST /web-api/teams/t1/budget': ok, 'POST /web-api/teams/t1/models': ok })
  await openApp('/teams/t1/manage')
  const budget = await screen.findByLabelText(/Team budget/)
  expect(budget).toHaveValue(50)
  await user.clear(budget)
  await user.type(budget, '75.5')
  await user.click(screen.getByRole('button', { name: 'Save budget' }))
  await user.click(screen.getByRole('checkbox', { name: 'astro/claude' }))
  await user.click(screen.getByRole('checkbox', { name: 'astro/gpt' }))
  await user.click(screen.getByRole('button', { name: 'Save models' }))
  await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(2))
  const posts = Object.fromEntries(calls.filter((call) => call.method === 'POST').map((call) => [call.path, call.body]))
  expect(posts['/web-api/teams/t1/budget']).toEqual({ team_budget: 75.5 })
  expect(posts['/web-api/teams/t1/models']).toEqual({ model_ids: ['m2'] })
})

it('sends typed addresses and a CSV file as multipart', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...signedIn(), ...page(TEAM), 'POST /web-api/teams/t1/invites': { json: { message: 'Sent 3 invitation(s).' } } })
  await openApp('/teams/t1/manage')
  await user.type(await screen.findByLabelText(/Email addresses/), 'a@uw.edu\nb@uw.edu')
  const file = new File(['name,email\nSee,c@uw.edu\n'], 'people.csv', { type: 'text/csv' })
  await user.upload(screen.getByLabelText(/CSV file/), file)
  await user.click(screen.getByRole('button', { name: 'Send invitations' }))
  expect(await screen.findByText('Sent 3 invitation(s).')).toBeInTheDocument()
  const sent = calls.find((call) => call.method === 'POST')!
  expect(sent.body).toBeInstanceOf(FormData)
  const form = sent.body as FormData
  expect(form.get('emails')).toBe('a@uw.edu\nb@uw.edu')
  // The file travels as the form's `csv_file` part. jsdom builds that part without the chosen file's
  // name or content, so those are checked in a real browser, not here.
  expect(form.get('csv_file')).toBeInstanceOf(File)
  expect((screen.getByLabelText(/CSV file/) as HTMLInputElement).accept).toBe('.csv,text/csv')
  expect(sent.headers.get('x-csrf-token')).toBe('csrf-token')
  expect(sent.headers.get('content-type')).toBeNull()
})

it('lets the lead decide requests, cancel invitations, rotate and revoke keys, and remove a member', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn(), ...page(TEAM),
    'POST /web-api/teams/t1/requests/i2': ok, 'POST /web-api/teams/t1/invites/i1/revoke': ok,
    'POST /web-api/teams/t1/keys/k1/rotate': ok, 'POST /web-api/teams/t1/keys/k2/revoke': ok,
    'POST /web-api/teams/t1/members/p2/remove': ok,
  })
  await openApp('/teams/t1/manage')
  await user.click(within((await screen.findByText('asked@uw.edu')).closest('li')!).getByRole('button', { name: 'Approve' }))
  await user.click(within(screen.getByText('new@uw.edu').closest('li')!).getByRole('button', { name: 'Cancel invitation' }))
  await user.click(within(screen.getByText('laptop').closest('tr')!).getByRole('button', { name: 'Rotate' }))
  await user.click(within(screen.getByText('desk').closest('tr')!).getByRole('button', { name: 'Revoke' }))
  await user.click(within(screen.getByText('p2@uw.edu').closest('tr')!).getByRole('button', { name: 'Remove' }))
  await vi.waitFor(() => expect(calls.filter((call) => call.method === 'POST')).toHaveLength(5))
  const posts = Object.fromEntries(calls.filter((call) => call.method === 'POST').map((call) => [call.path, call.body]))
  expect(posts['/web-api/teams/t1/requests/i2']).toEqual({ approve: true })
  expect(Object.keys(posts).sort()).toEqual([
    '/web-api/teams/t1/invites/i1/revoke', '/web-api/teams/t1/keys/k1/rotate', '/web-api/teams/t1/keys/k2/revoke',
    '/web-api/teams/t1/members/p2/remove', '/web-api/teams/t1/requests/i2',
  ])
})

it('archives only after the question is answered', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...signedIn(), ...page(TEAM), 'POST /web-api/teams/t1/archive': { json: { message: 'Team archived. 2 key(s) deleted.' } } })
  await openApp('/teams/t1/manage')
  await user.click(await screen.findByRole('button', { name: 'Archive team' }))
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
  await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Archive team' }))
  expect(await screen.findByText('Team archived. 2 key(s) deleted.')).toBeInTheDocument()
})

it('lets an admin connect and disconnect a service, and remove the team by typing its name', async () => {
  const user = userEvent.setup()
  const { calls } = serve({
    ...signedIn({ is_admin: true }), ...page({ ...TEAM, is_lead: false }),
    'POST /web-api/admin/teams/t1/integrations': { json: { message: 'Connected Lab.' } },
    'POST /web-api/admin/integrations/g1/remove': { json: { message: 'Integration disconnected. 1 key(s) deleted.', goto: '/teams/t1/manage' } },
    'POST /web-api/admin/teams/t1/remove': { json: { message: 'Team removed: 2 member(s) removed, 1 key(s) deleted.', goto: '/orgs/o1' } },
    'GET /web-api/orgs/o1': { status: 403, json: { error: { status: 403, message: 'You do not have access to that.' } } },
  })
  const router = await openApp('/teams/t1/manage')
  await user.type(await screen.findByLabelText(/client ID/), ' lab ')
  await user.type(screen.getByLabelText(/Name, also used/), 'Lab')
  await user.click(screen.getByRole('checkbox', { name: /may add its signed-in users/ }))
  await user.click(screen.getByRole('button', { name: 'Connect service' }))
  expect(await screen.findByText('Connected Lab.')).toBeInTheDocument()
  expect(calls.find((call) => call.path.endsWith('/integrations'))!.body).toEqual({ client_id: 'lab', name: 'Lab', can_enroll: true })
  await user.click(screen.getByRole('button', { name: 'Disconnect' }))
  await user.click(screen.getByRole('button', { name: 'Remove team' }))
  const dialog = screen.getByRole('dialog')
  await user.type(within(dialog).getByRole('textbox'), 'Workshop')
  await user.click(within(dialog).getByRole('button', { name: 'Remove team' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/orgs/o1'))
  expect(calls.find((call) => call.path === '/web-api/admin/teams/t1/remove')!.body).toEqual({ confirm_name: 'Workshop' })
  expect(calls.some((call) => call.path === '/web-api/admin/integrations/g1/remove')).toBe(true)
})
