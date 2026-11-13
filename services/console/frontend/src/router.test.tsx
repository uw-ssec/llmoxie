import { render, screen } from '@testing-library/react'
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

it('shows an admin the home screen with the admin menu', async () => {
  serve(signedIn({ is_admin: true, lead_orgs: [{ id: 'o1', name: 'Astro', status: 'suspended' }] }))
  await open('/')
  expect(await screen.findByRole('heading', { name: 'Welcome' })).toBeInTheDocument()
  const nav = screen.getByRole('navigation')
  for (const name of ['Organizations', 'Audit log', 'Data protection']) {
    expect(nav).toContainElement(screen.getAllByRole('link', { name }).find((link) => nav.contains(link))!)
  }
  expect(screen.getByRole('link', { name: 'Astro' })).toHaveAttribute('href', '/orgs/o1')
  expect(screen.getByText('suspended')).toBeInTheDocument()
  const signOut = screen.getByRole('button', { name: 'Sign out' }).closest('form')!
  expect(signOut).toHaveAttribute('action', '/logout')
  expect(signOut.querySelector('input[name="csrf"]')).toHaveValue('csrf-token')
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
