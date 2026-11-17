import type { ComponentProps, ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import type { ActionResult } from '@/lib/api'
import { useAction } from '@/lib/use-action'
import { FormError } from './form-field'

/**
 * A form that is one action. The server decides what is valid; when it refuses something the user
 * can fix, its reason appears here and what was typed stays put.
 */
export function ActionForm({
  call,
  submit,
  variant,
  children,
  keep = false,
  ...props
}: Omit<ComponentProps<'form'>, 'onSubmit'> & {
  /** The call to make with the form's fields. */
  call: (fields: FormData) => Promise<ActionResult>
  /** The button's words. Leave out for a form whose controls are shown but cannot be used. */
  submit?: ReactNode
  variant?: ComponentProps<typeof Button>['variant']
  /** Keep the values after a success, for a form that shows what is saved. */
  keep?: boolean
}) {
  const action = useAction()
  return (
    <form
      className="flex flex-col gap-4"
      {...props}
      onSubmit={async (event) => {
        event.preventDefault()
        const form = event.currentTarget
        const done = await action.run(() => call(new FormData(form)), { inline: true })
        if (done && !keep) form.reset()
      }}
    >
      {children}
      <FormError message={action.error} />
      {submit && (
        <div>
          <Button type="submit" variant={variant} disabled={action.pending} aria-busy={action.pending}>
            {submit}
          </Button>
        </div>
      )}
    </form>
  )
}
