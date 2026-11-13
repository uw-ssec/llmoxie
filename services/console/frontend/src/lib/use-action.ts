import { useCallback, useRef, useState } from 'react'
import { useNavigate, useRevalidator } from 'react-router'
import { ApiError, type ActionResult } from './api'
import { notices } from './notices'

type Options = {
  /** Keep a refusal the user can fix (a taken name, a value out of range) in `error`, for the form to show. */
  inline?: boolean
}

/**
 * Runs one action at a time. Afterwards it shows the answer's message and either goes where the
 * answer says or reloads this page's data, which is what the old pages' redirect did.
 */
export function useAction() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const busy = useRef(false)
  const navigate = useNavigate()
  const { revalidate } = useRevalidator()

  const run = useCallback(
    async (call: () => Promise<ActionResult>, options: Options = {}): Promise<ActionResult | undefined> => {
      if (busy.current) return undefined // a second click while the first is on its way
      busy.current = true
      setPending(true)
      setError(null)
      try {
        const result = await call()
        if (result.message) notices.add('good', result.message)
        if (result.goto) await navigate(result.goto)
        else await revalidate()
        return result
      } catch (failure) {
        const message = failure instanceof ApiError ? failure.message : 'The console could not complete that. Nothing was changed.'
        const fixable = failure instanceof ApiError && (failure.status === 409 || failure.status === 422)
        if (options.inline && fixable) setError(message)
        else if (!(failure instanceof ApiError && failure.status === 401)) notices.add('bad', message)
        return undefined
      } finally {
        busy.current = false
        setPending(false)
      }
    },
    [navigate, revalidate],
  )

  return { run, pending, error }
}
