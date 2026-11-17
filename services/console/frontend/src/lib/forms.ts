/** A form field's text, trimmed. */
export function text(fields: FormData, name: string): string {
  return String(fields.get(name) ?? '').trim()
}

/** A form field as a number. */
export function number(fields: FormData, name: string): number {
  return Number(fields.get(name))
}
