import type { ComponentProps, ReactNode } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import type { ActionResult } from '@/lib/api'
import { useAction } from '@/lib/use-action'

type Props = Omit<ComponentProps<typeof Button>, 'onClick'> & {
  /** The call this button makes. */
  call: () => Promise<ActionResult>
  /** Ask first, for an action that cannot be undone. */
  confirm?: { title: string; description: ReactNode }
}

/** A button that is a whole action by itself: Remove, Revoke, Approve. */
export function ActionButton({ call, confirm, children, variant = 'ghost', size = 'sm', ...props }: Props) {
  const action = useAction()
  const button = (onClick?: () => void) => (
    <Button type="button" variant={variant} size={size} disabled={action.pending} aria-busy={action.pending} onClick={onClick} {...props}>
      {children}
    </Button>
  )
  if (!confirm) return button(() => void action.run(call))
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{button()}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirm.title}</AlertDialogTitle>
          <AlertDialogDescription>{confirm.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => void action.run(call)}>
            {children}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
