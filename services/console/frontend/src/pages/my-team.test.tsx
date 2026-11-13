import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { openApp } from '@/test/open'
import { serve, signedIn } from '@/test/server'

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

const KEY = 'sk-live-0123456789abcdef'
const TEAM = {
  team: { id: 't1', name: 'Workshop', status: 'active', org_name: 'Astro Lab', org_status: 'active',
          consent_text: 'Leads can see how many requests you make.', key_limit: 2, key_budget: '5.00', key_expiry_days: 30 },
  consent: { terms_accepted: true, research_use: false },
  keys: [{ id: 'k1', name: 'laptop', waiting: false, created_at: '2026-11-02T10:00:00Z' }],
  models: ['astro/gpt', 'astro/claude'],
  knowledge_tools: 'knowledge_astro',
  usage: { requests: 12, tokens: 3400, spend: 0.0125 },
}
const me = signedIn({ teams: [{ id: 't1', name: 'Workshop', org_name: 'Astro Lab', status: 'active' }] })
const page = (view: unknown) => ({ 'GET /web-api/teams/t1': { json: view } })

it('shows the terms first, and no keys section until they are accepted', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...me, ...page({ ...TEAM, consent: null, keys: [] }), 'POST /web-api/teams/t1/my/consent': { json: { message: 'Your choices are saved.' } } })
  await openApp('/teams/t1')
  expect(await screen.findByText('Leads can see how many requests you make.')).toBeInTheDocument()
  for (const name of ['API keys', 'How to connect', 'Your usage']) expect(screen.queryByRole('heading', { name })).toBeNull()
  const terms = screen.getByRole('checkbox', { name: /I accept these terms/ })
  expect(terms).not.toBeChecked()
  await user.click(terms)
  await user.click(screen.getByRole('button', { name: 'Save my choices' }))
  expect(await screen.findByText('Your choices are saved.')).toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST')!.body).toEqual({ terms_accepted: true, research_use: false })
})

it('shows keys, how to connect and usage once the terms are accepted', async () => {
  serve({ ...me, ...page(TEAM) })
  await openApp('/teams/t1')
  expect(await screen.findByRole('heading', { name: 'API keys' })).toBeInTheDocument()
  expect(screen.getByText('1 of 2 · $5.00 per key · expire after 30 days')).toBeInTheDocument()
  expect(within(screen.getByText('laptop').closest('tr')!).getByText('created 2026-11-02')).toBeInTheDocument()
  expect(screen.getByText('http://gateway.test/v1')).toBeInTheDocument()
  expect(screen.getByText('http://gateway.test/mcp')).toBeInTheDocument()
  expect(screen.getByText('astro/gpt')).toBeInTheDocument()
  expect(screen.getByText('knowledge_astro-okf_search')).toBeInTheDocument()
  expect(screen.getByText('$0.0125')).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: /I accept these terms/ })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: /used for research/ })).not.toBeChecked()
})

it('shows the new key once, in a code block, with the copy-now warning', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...me, ...page(TEAM), 'POST /web-api/teams/t1/my/keys': { json: { key: { name: 'desk', key: KEY }, rotated: false } } })
  await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), ' desk ')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  expect(await screen.findByRole('heading', { name: 'Your new key: desk' })).toBeInTheDocument()
  expect(screen.getByText('Copy it now. It will not be shown again.')).toBeInTheDocument()
  expect(screen.getByLabelText('Your new key')).toHaveTextContent(KEY)
  expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST')!.body).toEqual({ name: 'desk' })
  expect(screen.queryByRole('status')?.textContent ?? '').not.toContain(KEY) // not repeated in a notice
})

it('writes the key to no storage', async () => {
  const user = userEvent.setup()
  serve({ ...me, ...page(TEAM), 'POST /web-api/teams/t1/my/keys': { json: { key: { name: 'desk', key: KEY }, rotated: false } } })
  const router = await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), 'desk')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  await screen.findByLabelText('Your new key')
  const kept = JSON.stringify([
    Object.entries(window.localStorage), Object.entries(window.sessionStorage), window.history.state,
    router.state.location.state, router.state.loaderData, document.cookie,
  ])
  expect(kept).not.toContain(KEY)
})

it('loses the key when the screen is left and opened again', async () => {
  const user = userEvent.setup()
  serve({ ...me, ...page(TEAM), 'POST /web-api/teams/t1/my/keys': { json: { key: { name: 'desk', key: KEY }, rotated: false } } })
  const router = await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), 'desk')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  await screen.findByLabelText('Your new key')
  await router.navigate('/invite-result/waiting')
  await screen.findByRole('heading', { name: 'Waiting for approval' })
  await router.navigate(-1)
  await screen.findByRole('heading', { name: 'API keys' })
  expect(screen.queryByLabelText('Your new key')).toBeNull()
  expect(document.body.innerHTML).not.toContain(KEY)
})

it("offers 'Get replacement key' for a key a lead rotated, and says it replaces the old one", async () => {
  const user = userEvent.setup()
  const waiting = { ...TEAM, keys: [{ id: 'k1', name: 'laptop', waiting: true, created_at: '2026-11-02T10:00:00Z' }] }
  serve({ ...me, ...page(waiting), 'POST /web-api/teams/t1/my/keys/k1/rotate': { json: { key: { name: 'laptop', key: KEY }, rotated: true } } })
  await openApp('/teams/t1')
  const row = (await screen.findByText('laptop')).closest('tr')!
  expect(within(row).getByText('rotated by your lead; the old key no longer works')).toBeInTheDocument()
  expect(within(row).queryByRole('button', { name: 'Rotate' })).toBeNull()
  await user.click(within(row).getByRole('button', { name: 'Get replacement key' }))
  expect(await screen.findByRole('heading', { name: 'Your replacement key: laptop' })).toBeInTheDocument()
  expect(screen.getByText(/The key it replaces no longer works\./)).toBeInTheDocument()
})

it('hides Create key at the key limit', async () => {
  const full = { ...TEAM, keys: [...TEAM.keys, { id: 'k2', name: 'desk', waiting: false, created_at: '2026-11-03T10:00:00Z' }] }
  serve({ ...me, ...page(full) })
  await openApp('/teams/t1')
  expect(await screen.findByText('2 of 2 · $5.00 per key · expire after 30 days')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Create key' })).toBeNull()
  expect(screen.getAllByRole('button', { name: 'Rotate' })).toHaveLength(2)
})

it('on a closed team offers nothing but deleting a key', async () => {
  const user = userEvent.setup()
  const { calls } = serve({ ...me, ...page({ ...TEAM, team: { ...TEAM.team, status: 'archived' } }), 'POST /web-api/teams/t1/my/keys/k1/delete': { json: { message: 'Key deleted.' } } })
  await openApp('/teams/t1')
  expect(await screen.findByText('This team is closed. Its keys no longer work.')).toBeInTheDocument()
  for (const name of ['Create key', 'Rotate', 'Save my choices']) expect(screen.queryByRole('button', { name })).toBeNull()
  await user.click(within(screen.getByText('laptop').closest('tr')!).getByRole('button', { name: 'Delete' }))
  await vi.waitFor(() => expect(calls.some((call) => call.path === '/web-api/teams/t1/my/keys/k1/delete')).toBe(true))
})

it('says in place why a key could not be made', async () => {
  const user = userEvent.setup()
  serve({ ...me, ...page(TEAM), 'POST /web-api/teams/t1/my/keys': { status: 409, json: { error: { status: 409, message: 'you already have 2 keys' } } } })
  await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), 'third')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('you already have 2 keys')
})

it('keeps the page, and a key just made, when the reload after an action fails', async () => {
  const user = userEvent.setup()
  let loads = 0
  serve({
    ...me,
    'GET /web-api/teams/t1': () => (++loads === 1 ? { json: TEAM } : { status: 502, text: 'upstream connect error' }),
    'POST /web-api/teams/t1/my/keys': { json: { key: { name: 'desk', key: KEY }, rotated: false } },
  })
  await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), 'desk')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  // The key was made. Losing it to an error screen that says "Nothing was changed" would be wrong twice.
  expect(await screen.findByLabelText('Your new key')).toHaveTextContent(KEY)
  expect(await screen.findByText('That was done, but this page could not be refreshed. Reload it to see it as it is now.')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'API keys' })).toBeInTheDocument()
  expect(loads).toBe(2)
})

it('still shows the error screen when the page cannot be loaded in the first place', async () => {
  serve({ ...me, 'GET /web-api/teams/t1': { status: 502, text: 'upstream connect error' } })
  await openApp('/teams/t1')
  expect(await screen.findByRole('heading', { name: 'The console could not complete that. Nothing was changed.' })).toBeInTheDocument()
})

it('drops the key when the browser puts the page away, so Back cannot bring it out of a cache', async () => {
  const user = userEvent.setup()
  serve({ ...me, ...page(TEAM), 'POST /web-api/teams/t1/my/keys': { json: { key: { name: 'desk', key: KEY }, rotated: false } } })
  await openApp('/teams/t1')
  await user.type(await screen.findByLabelText('Name for a new key'), 'desk')
  await user.click(screen.getByRole('button', { name: 'Create key' }))
  await screen.findByLabelText('Your new key')
  // What a browser fires when it leaves a page, including when it keeps the page to restore on Back.
  act(() => { window.dispatchEvent(new Event('pagehide')) })
  expect(screen.queryByLabelText('Your new key')).toBeNull()
  expect(document.body.innerHTML).not.toContain(KEY)
})
