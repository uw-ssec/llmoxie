import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { serve, signedIn } from '@/test/server'

let api: typeof import('./api')

beforeEach(async () => {
  vi.resetModules()
  api = await import('./api')
})
afterEach(() => vi.unstubAllGlobals())

describe('the API client', () => {
  it("throws ApiError with the server's message", async () => {
    serve({ 'POST /web-api/admin/orgs': { status: 409, json: { error: { status: 409, message: 'Taken.' } } } })
    await expect(api.post('/admin/orgs', { slug: 'x' })).rejects.toMatchObject({ status: 409, message: 'Taken.' })
  })

  it('treats a non-JSON reply as a 502', async () => {
    serve({ 'GET /web-api/admin/orgs': { status: 502, text: '<html>bad gateway' } })
    await expect(api.get('/admin/orgs')).rejects.toMatchObject({
      status: 502,
      message: 'The console could not complete that. Nothing was changed.',
    })
  })

  it('treats a network failure as a 502', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.get('/admin/orgs')).rejects.toMatchObject({ status: 502 })
  })

  it('sends the CSRF token on posts and not on gets', async () => {
    const { calls } = serve({
      ...signedIn(),
      'GET /web-api/admin/orgs': { json: { orgs: [] } },
      'POST /web-api/admin/orgs': { json: { message: 'Created.' } },
    })
    await api.loadSession()
    await api.get('/admin/orgs')
    await api.post('/admin/orgs', { name: 'N' })
    const [, read, write] = calls
    expect(read.headers.get('x-csrf-token')).toBeNull()
    expect(write.headers.get('x-csrf-token')).toBe('csrf-token')
    expect(write.headers.get('content-type')).toBe('application/json')
    expect(write.body).toEqual({ name: 'N' })
  })

  it('sends a form as it is, with the token and no JSON content type', async () => {
    const { calls } = serve({ ...signedIn(), 'POST /web-api/teams/t/invites': { json: { message: 'Sent 1 invitation(s).' } } })
    await api.loadSession()
    const form = new FormData()
    form.set('emails', 'a@uw.edu')
    await api.postForm('/teams/t/invites', form)
    expect(calls[1].headers.get('x-csrf-token')).toBe('csrf-token')
    expect(calls[1].headers.get('content-type')).toBeNull()
    expect(calls[1].body).toBe(form)
  })

  it('goes to sign-in with next when an action answers 401', async () => {
    serve({ 'POST /web-api/teams/abc/archive': { status: 401, json: { error: { status: 401, message: 'You are signed out.' } } } })
    const go = vi.spyOn(api.browser, 'go').mockImplementation(() => {})
    window.history.pushState({}, '', '/teams/abc')
    await expect(api.post('/teams/abc/archive')).rejects.toMatchObject({ status: 401 })
    expect(go).toHaveBeenCalledWith('/?next=%2Fteams%2Fabc')
  })

  it('asks for the session once and remembers it', async () => {
    const { fetchMock } = serve(signedIn({ is_admin: true }))
    const [first, second] = await Promise.all([api.loadSession(), api.loadSession()])
    expect(first).toBe(second)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(api.currentSession().me.is_admin).toBe(true)
  })
})
