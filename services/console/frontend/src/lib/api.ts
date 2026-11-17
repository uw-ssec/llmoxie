// The one way the application talks to console-web: its browser API under /web-api/.
import type { ActionResult, Session, SignedIn } from './types'

export type { ActionResult } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const FAILED = 'The console could not complete that. Nothing was changed.'

/** Leaving the application for another page. Its own object so tests can watch it. */
export const browser = {
  go(url: string) {
    window.location.assign(url)
  },
}

let session: Promise<Session> | null = null
let known: Session | null = null

async function call<T>(method: string, path: string, init: RequestInit = {}, signInOn401 = true): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/web-api${path}`, { ...init, method, credentials: 'same-origin' })
  } catch {
    throw new ApiError(502, FAILED)
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError(response.ok ? 502 : response.status >= 500 ? response.status : 502, FAILED)
  }
  if (response.ok) return body as T
  const refusal = (body as { error?: { status?: number; message?: string } }).error
  const error = new ApiError(refusal?.status ?? response.status, refusal?.message ?? FAILED)
  if (error.status === 401 && signInOn401) {
    // The session ended while the application was open. Sign in again, and come back to this page.
    browser.go('/?next=' + encodeURIComponent(window.location.pathname))
  }
  throw error
}

/** Who is signed in. Asked once; the answer also carries the token every post must send. */
export function loadSession(): Promise<Session> {
  session ??= call<Session>('GET', '/session', {}, false).then((answer) => (known = answer))
  return session
}

/** The signed-in session, for code that only runs once someone is signed in. */
export function currentSession(): SignedIn {
  if (!known?.signed_in) throw new Error('nobody is signed in')
  return known
}

function csrf(): Record<string, string> {
  return known?.signed_in ? { 'X-CSRF-Token': known.csrf } : {}
}

export function get<T>(path: string): Promise<T> {
  return call<T>('GET', path)
}

export function post<T = ActionResult>(path: string, body?: unknown): Promise<T> {
  const json = body === undefined ? {} : { body: JSON.stringify(body) }
  return call<T>('POST', path, { ...json, headers: { 'Content-Type': 'application/json', ...csrf() } })
}

/** For the one action that carries a file. The browser sets the form's content type itself. */
export function postForm<T = ActionResult>(path: string, form: FormData): Promise<T> {
  return call<T>('POST', path, { body: form, headers: csrf() })
}
