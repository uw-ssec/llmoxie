/** "$12.00", or "$0.0031" for the spend columns. */
export function usd(value: number | string, digits: 2 | 4 = 2): string {
  return '$' + Number(value).toFixed(digits)
}

/** "2026-11-12" */
export function day(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : ''
}

/** "2026-11-12 08:15:02", in UTC as the server gives it. */
export function minute(iso: string): string {
  return iso.slice(0, 19).replace('T', ' ')
}
