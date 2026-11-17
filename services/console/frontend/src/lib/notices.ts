// Short messages after an action: "Team budget updated." A store of the console's own, because the
// usual toast libraries add styles at run time, which the content security policy does not allow.
import { useSyncExternalStore } from 'react'

export type Notice = { id: number; kind: 'good' | 'bad'; message: string }

let items: Notice[] = []
let nextId = 1
const listeners = new Set<() => void>()

function set(next: Notice[]) {
  items = next
  listeners.forEach((listener) => listener())
}

export const notices = {
  list: () => items,
  clear: () => set([]),
  dismiss: (id: number) => set(items.filter((item) => item.id !== id)),
  /** A success fades after a few seconds. A failure stays until it is dismissed: it must not be missed. */
  add(kind: Notice['kind'], message: string) {
    const id = nextId++
    set([...items, { id, kind, message }])
    if (kind === 'good') setTimeout(() => notices.dismiss(id), 7000)
  },
}

export function useNotices(): Notice[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => items,
  )
}
