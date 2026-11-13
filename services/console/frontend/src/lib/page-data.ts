// A page's data, and what to do when reloading it fails.
import { ApiError, get } from './api'
import { notices } from './notices'

/** What each page last showed, by address. Page data only; a key is never in it. */
const shown = new Map<string, unknown>()
let afterAction = false

/**
 * Loads a page's data. When the load is the reload that follows an action, and it fails because the
 * console itself is in trouble, the page stays as it was: the action went through, and an error
 * screen saying "Nothing was changed" would be untrue, and would throw away a key just made.
 */
export async function pageData(path: string): Promise<unknown> {
  try {
    const data = await get(path)
    shown.set(path, data)
    return data
  } catch (failure) {
    if (afterAction && failure instanceof ApiError && failure.status >= 500 && shown.has(path)) {
      notices.add('bad', 'That was done, but this page could not be refreshed. Reload it to see it as it is now.')
      return shown.get(path)
    }
    throw failure
  }
}

/** Runs the reload that follows an action, so `pageData` knows which kind of load this is. */
export async function reloadAfterAction(reload: () => Promise<void>): Promise<void> {
  afterAction = true
  try {
    await reload()
  } finally {
    afterAction = false
  }
}
