/** "$12.00", or "$0.0031" for the spend columns. */
export function usd(value: number | string, digits: 2 | 4 = 2): string {
  return '$' + Number(value).toFixed(digits)
}

/** "2,210,400" */
export function count(value: number): string {
  return value.toLocaleString('en-US')
}

/** "2 archived, 1 suspended", or nothing when all are active. */
export function notActive(items: { status: string }[]): string | undefined {
  const counts = new Map<string, number>()
  for (const { status } of items) if (status !== 'active') counts.set(status, (counts.get(status) ?? 0) + 1)
  return [...counts].map(([status, number]) => `${number} ${status}`).join(', ') || undefined
}

/** "2026-11-12" */
export function day(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : ''
}

/** "2026-11-12 08:15:02", in UTC as the server gives it. */
export function minute(iso: string): string {
  return iso.slice(0, 19).replace('T', ' ')
}
