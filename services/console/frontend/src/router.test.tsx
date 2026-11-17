import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { serve, signedIn, signedOut } from '@/test/server'

async function open(path: string) {
  vi.resetModules()
  const { createMemoryRouter, RouterProvider } = await import('react-router')
  const { routes } = await import('./router')
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}

beforeEach(() => window.history.pushState({}, '', '/'))
afterEach(() => vi.unstubAllGlobals())

it('shows sign-in when signed out and keeps next in the form', async () => {
  serve(signedOut)
  await open('/?next=%2Fteams%2Fabc')
  const button = await screen.findByRole('button', { name: 'Sign in' })
  const form = button.closest('form')!
  expect(form).toHaveAttribute('method', 'post')
  expect(form).toHaveAttribute('action', '/login')
  expect(form.querySelector('input[name="next"]')).toHaveValue('/teams/abc')
  expect(screen.queryByRole('navigation')).toBeNull()
})

it('says so when a sign-in could not be completed', async () => {
  serve(signedOut)
  await open('/?signin=failed')
  expect(await screen.findByText('That sign-in could not be completed. Please start again.')).toBeInTheDocument()
})

it('sends a signed-out visitor from a page to sign-in, remembering the page', async () => {
  serve(signedOut)
  const router = await open('/teams/abc/manage')
  await screen.findByRole('button', { name: 'Sign in' })
  expect(router.state.location.pathname + router.state.location.search).toBe('/?next=%2Fteams%2Fabc%2Fmanage')
})

it('tells someone with no role that they are not invited yet', async () => {
  serve(signedIn({ email: 'new@uw.edu' }))
  await open('/')
  expect(await screen.findByRole('heading', { name: 'You are not invited yet' })).toBeInTheDocument()
  expect(screen.getByText(/as new@uw\.edu/)).toBeInTheDocument()
})

it('sends a lone participant straight to their team', async () => {
  serve({
    ...signedIn({ teams: [{ id: 't1', name: 'Workshop', org_name: 'Astro', status: 'active' }] }),
    'GET /web-api/teams/t1': { status: 403, json: { error: { status: 403, message: 'You do not have access to that.' } } },
  })
  const router = await open('/')
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/teams/t1'))
})

it('shows an admin the overview with the admin menu', async () => {
  serve(signedIn({ is_admin: true, lead_orgs: [{ id: 'o1', name: 'Astro', status: 'suspended' }] }))
  await open('/')
  expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  const nav = screen.getByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  for (const name of ['Organizations', 'Audit log', 'Data protection']) expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
  expect(within(nav).getByRole('link', { name: 'Astro' })).toHaveAttribute('href', '/orgs/o1')
  expect(within(nav).getByRole('link', { name: 'Astro: Knowledge' })).toHaveAttribute('href', '/orgs/o1/knowledge')
  const main = screen.getByRole('main')
  expect(within(main).getByRole('link', { name: 'Astro' })).toHaveAttribute('href', '/orgs/o1')
  expect(within(main).getByText('suspended')).toBeInTheDocument()
  // A part of the overview that cannot be read leaves a gap that says so; the rest still shows.
  expect(within(main).getAllByText(/could not be loaded just now/).length).toBeGreaterThan(0)
  const signOut = screen.getByRole('button', { name: 'Sign out' }).closest('form')!
  expect(signOut).toHaveAttribute('action', '/logout')
  expect(signOut.querySelector('input[name="csrf"]')).toHaveValue('csrf-token')
})

it('shows a lead what they run, from the pages they can already open', async () => {
  const { calls } = serve({
    ...signedIn({ lead_orgs: [{ id: 'o1', name: 'Astro', status: 'active' }], teams: [{ id: 't7', name: 'Reading group', org_name: 'Bio', status: 'active' }] }),
    'GET /web-api/orgs/o1': {
      json: {
        org: { id: 'o1', name: 'Astro', slug: 'astro', status: 'active', budget_ceiling: '100.00' },
        is_lead: true, is_admin: false, leads: [], lead_invites: [], providers: [],
        models: [{ id: 'm1', public_name: 'astro/gpt', provider: 'openai' }],
        teams: [
          { id: 't1', name: 'Workshop', members: 4, team_budget: '50.00', status: 'active' },
          { id: 't2', name: 'Course', members: 3, team_budget: '20.00', status: 'archived' },
        ],
      },
    },
  })
  await open('/')
  const main = await screen.findByRole('main')
  expect(within(main).getByRole('link', { name: 'Workshop' })).toHaveAttribute('href', '/teams/t1/manage')
  const figures = within(screen.getByRole('region', { name: 'What you lead' }))
  expect(figures.getByText('Members').parentElement).toHaveTextContent('7')
  expect(figures.getByText('Teams').parentElement).toHaveTextContent('1 archived')
  expect(within(main).getByRole('link', { name: 'Reading group' })).toHaveAttribute('href', '/teams/t7')
  expect(screen.queryByRole('link', { name: 'Audit log' })).toBeNull()
  expect(calls.map((call) => call.path).sort()).toEqual(['/web-api/orgs/o1', '/web-api/session'])
})

it('shows an admin a few organizations, those not active first, and says how many there are', async () => {
  const orgs = Array.from({ length: 11 }, (_, n) => ({ id: `o${n}`, name: `Org ${n}`, slug: `org-${n}`, budget_ceiling: '10.00', leads: 1, teams: 1, status: n === 10 ? 'suspended' : 'active' }))
  serve({ ...signedIn({ is_admin: true }), 'GET /web-api/admin/orgs': { json: { orgs } }, 'GET /web-api/admin/audit': { json: { events: [] } } })
  await open('/')
  const main = await screen.findByRole('main')
  expect(within(main).getAllByRole('row')).toHaveLength(1 + 8) // the headings and eight organizations
  expect(within(within(main).getAllByRole('row')[1]).getByRole('link', { name: 'Org 10' })).toBeInTheDocument()
  expect(within(main).getByText(/Showing 8 of 11\./)).toBeInTheDocument()
  expect(within(main).getByText('Nothing has been recorded yet.')).toBeInTheDocument()
})

it('collapses the sidebar to its icons and remembers that', async () => {
  const user = userEvent.setup()
  serve(signedIn({ is_admin: true, lead_orgs: [{ id: 'o1', name: 'Astro', status: 'active' }] }))
  await open('/')
  const toggle = await screen.findByRole('button', { name: 'Collapse sidebar' })
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(toggle).toHaveAttribute('aria-controls', 'sidebar')
  await user.click(toggle)
  expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false')
  // Every place is still a link with its name; pointing at an icon says where it leads.
  const nav = screen.getByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Audit log' })).toHaveAttribute('title', 'Audit log')
  expect(within(nav).getByRole('link', { name: 'Astro' })).toHaveAttribute('href', '/orgs/o1')
  // The pages under an organization are not shown at this width, nor the control that folds them.
  expect(within(nav).queryByRole('link', { name: 'Astro: Knowledge' })).toBeNull()
  expect(within(nav).queryByRole('button', { name: 'Pages of Astro' })).toBeNull()
  cleanup()
  await open('/') // a reload: the choice was kept in this browser
  expect(await screen.findByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
})

it('folds away the pages under an organization and remembers that', async () => {
  const user = userEvent.setup()
  serve(signedIn({ lead_orgs: [{ id: 'o1', name: 'Astro', status: 'active' }, { id: 'o2', name: 'Bio', status: 'active' }] }))
  await open('/')
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  const fold = within(nav).getByRole('button', { name: 'Pages of Astro' })
  expect(fold).toHaveAttribute('aria-expanded', 'true')
  expect(within(nav).getByRole('link', { name: 'Astro: Knowledge' })).toBeInTheDocument()
  await user.click(fold)
  expect(fold).toHaveAttribute('aria-expanded', 'false')
  expect(within(nav).queryByRole('link', { name: 'Astro: Knowledge' })).toBeNull()
  expect(within(nav).getByRole('link', { name: 'Bio: Knowledge' })).toBeInTheDocument() // the other organization is untouched
  cleanup()
  await open('/')
  const again = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(again).getByRole('button', { name: 'Pages of Astro' })).toHaveAttribute('aria-expanded', 'false')
  expect(within(again).queryByRole('link', { name: 'Astro: Knowledge' })).toBeNull()
})

it('names the page and the way back to it in the top bar', async () => {
  serve({
    ...signedIn(),
    'GET /web-api/teams/t1/manage': {
      json: {
        team: { id: 't1', name: 'Workshop', status: 'active', org_id: 'o1', org_name: 'Astro Lab', org_status: 'active', org_budget_ceiling: '100.00', team_budget: '50.00', key_limit: 2, key_budget: '5.00', key_expiry_days: 30 },
        is_lead: true, models: [], members: [], invites: [], keys: [], usage: [], integrations: [],
      },
    },
  })
  await open('/teams/t1/manage')
  const trail = within(await screen.findByRole('navigation', { name: 'Breadcrumb' }))
  expect(trail.getByRole('link', { name: 'Astro Lab' })).toHaveAttribute('href', '/orgs/o1')
  expect(trail.getByText('Workshop')).toHaveAttribute('aria-current', 'page')
})

it('shows the error screen with a way back when the page loader fails', async () => {
  serve({
    ...signedIn({ is_admin: true }),
    'GET /web-api/admin/orgs': { status: 502, text: 'upstream connect error' },
  })
  await open('/admin')
  expect(await screen.findByRole('heading', { name: 'The console could not complete that. Nothing was changed.' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to the console' })).toHaveAttribute('href', '/')
})

it('shows the not-found screen for an address that is no page', async () => {
  serve(signedIn({ is_admin: true }))
  await open('/nope/nothing')
  expect(await screen.findByRole('heading', { name: 'That does not exist.' })).toBeInTheDocument()
})

it('shows an invitation to someone who is signed out, with a plain form to accept it', async () => {
  serve({
    ...signedOut,
    'GET /web-api/invites/tok123': { json: { valid: true, kind: 'participant', org_name: 'Astro', team_name: 'Workshop' } },
  })
  await open('/invite/tok123')
  expect(await screen.findByRole('heading', { name: 'Join Workshop' })).toBeInTheDocument()
  const form = screen.getByRole('button', { name: 'Accept and sign in' }).closest('form')!
  expect(form).toHaveAttribute('method', 'post')
  expect(form).toHaveAttribute('action', '/invite/tok123')
})

it('says an invitation cannot be used when it is spent', async () => {
  serve({ ...signedOut, 'GET /web-api/invites/tok123': { json: { valid: false } } })
  await open('/invite/tok123')
  expect(await screen.findByRole('heading', { name: 'This invitation cannot be used' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accept and sign in' })).toBeNull()
})

it('tells someone who signed in with another address that they are waiting for approval', async () => {
  serve(signedIn())
  await open('/invite-result/waiting')
  expect(await screen.findByRole('heading', { name: 'Waiting for approval' })).toBeInTheDocument()
})
