import { useState } from 'react'

/**
 * A choice about how the page is laid out, remembered in this browser: whether the sidebar is
 * narrow, which of its groups are folded. Never a key, and never anything a page loaded.
 */
export function useStored<Value>(name: string, initial: Value): [Value, (next: Value) => void] {
  const [value, setValue] = useState<Value>(() => {
    try {
      const kept = window.localStorage.getItem(name)
      return kept === null ? initial : (JSON.parse(kept) as Value)
    } catch {
      return initial // storage is off, or holds something else: start from the default
    }
  })
  const keep = (next: Value) => {
    setValue(next)
    try {
      window.localStorage.setItem(name, JSON.stringify(next))
    } catch {
      // storage is off: the choice lasts until the page is reloaded
    }
  }
  return [value, keep]
}
