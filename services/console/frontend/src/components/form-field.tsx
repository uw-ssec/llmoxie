import { useId, type ReactElement, type ReactNode } from 'react'
import { cloneElement } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Label } from '@/components/ui/label'

/** A labelled input. The label and the input are tied together, as the design system requires. */
export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactElement<{ id?: string; 'aria-describedby'?: string }> }) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
      <Label htmlFor={id} className="font-ui text-sm font-semibold tracking-wider uppercase">
        {label}
      </Label>
      {cloneElement(children, { id, 'aria-describedby': hintId })}
      {hint && (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}

/** Fields side by side, stacking on a narrow screen. */
export function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-4 sm:flex-row">{children}</div>
}

/** Why the server refused what was just submitted, next to the form it came from. */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <Alert variant="destructive" role="alert">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}
