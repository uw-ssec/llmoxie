import { useSearchParams } from 'react-router'

/** One part of a long screen (components/page.tsx draws the row of them). */
export type Tab<Id extends string = string> = { id: Id; label: string; count?: number }

/** Which part is open. It is in the address, so a link to it and a reload both work. */
export function useTab<Id extends string>(tabs: Tab<Id>[]): Id {
  const [query] = useSearchParams()
  const asked = query.get('tab')
  return (tabs.find((tab) => tab.id === asked) ?? tabs[0]).id
}
