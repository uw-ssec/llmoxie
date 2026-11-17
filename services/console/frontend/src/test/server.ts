// A stand-in for console-web in tests: answers fetch from a table of "METHOD /path" -> reply.
import { vi } from 'vitest'

type Reply = { status?: number; json?: unknown; text?: string }
export type Call = { method: string; path: string; headers: Headers; body: unknown }

export function serve(table: Record<string, Reply | ((call: Call) => Reply)>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const method = (init.method ?? 'GET').toUpperCase()
    const path = String(input)
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body
    const call = { method, path, headers: new Headers(init.headers), body }
    calls.push(call)
    const entry = table[`${method} ${path}`]
    if (!entry) return new Response(JSON.stringify({ error: { status: 404, message: 'That does not exist.' } }), { status: 404 })
    const reply = typeof entry === 'function' ? entry(call) : entry
    const text = reply.text ?? JSON.stringify(reply.json ?? {})
    return new Response(text, { status: reply.status ?? 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export const signedOut = { 'GET /web-api/session': { json: { signed_in: false } } }

export function signedIn(me: Partial<{ email: string; is_admin: boolean; lead_orgs: unknown[]; teams: unknown[] }> = {}) {
  return {
    'GET /web-api/session': {
      json: {
        signed_in: true,
        csrf: 'csrf-token',
        me: { email: 'a@uw.edu', is_admin: false, lead_orgs: [], teams: [], ...me },
        config: { gateway_url: 'http://gateway.test', litellm_admin_url: '' },
      },
    },
  }
}
