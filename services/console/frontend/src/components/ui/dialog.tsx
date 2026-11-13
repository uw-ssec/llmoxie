// A dialog on the browser's own <dialog> element, with shadcn's part names and look.
//
// Not shadcn's Radix dialog: that one locks the page behind it by adding a <style> element at run
// time, which the console's content security policy (no inline styles) refuses. The native element
// needs no such thing. Shown with showModal(), it is modal, traps focus, closes on Escape and makes
// the rest of the page inert without help.
import * as React from 'react'
import { Slot } from 'radix-ui'
import { cn } from '@/lib/utils'

type Shared = { open: boolean; setOpen: (open: boolean) => void; titleId: string; descriptionId: string }
const DialogContext = React.createContext<Shared | null>(null)

function useDialog(): Shared {
  const shared = React.useContext(DialogContext)
  if (!shared) throw new Error('a dialog part was used outside <Dialog>')
  return shared
}

function Dialog({ open: controlled, onOpenChange, children }: { open?: boolean; onOpenChange?: (open: boolean) => void; children: React.ReactNode }) {
  const [own, setOwn] = React.useState(false)
  const id = React.useId()
  const open = controlled ?? own
  const setOpen = (next: boolean) => {
    if (controlled === undefined) setOwn(next)
    onOpenChange?.(next)
  }
  return <DialogContext value={{ open, setOpen, titleId: `${id}-title`, descriptionId: `${id}-description` }}>{children}</DialogContext>
}

function DialogTrigger({ asChild = false, ...props }: React.ComponentProps<'button'> & { asChild?: boolean }) {
  const { setOpen } = useDialog()
  const Comp = asChild ? Slot.Root : 'button'
  return <Comp data-slot="dialog-trigger" {...props} onClick={() => setOpen(true)} />
}

function DialogClose({ asChild = false, ...props }: React.ComponentProps<'button'> & { asChild?: boolean }) {
  const { setOpen } = useDialog()
  const Comp = asChild ? Slot.Root : 'button'
  return <Comp data-slot="dialog-close" type="button" {...props} onClick={() => setOpen(false)} />
}

function DialogContent({
  className,
  children,
  alert = false,
  ...props
}: Omit<React.ComponentProps<'dialog'>, 'open' | 'role'> & {
  /** A question that must be answered: no closing by clicking outside. */
  alert?: boolean
}) {
  const { open, setOpen, titleId, descriptionId } = useDialog()
  const ref = React.useRef<HTMLDialogElement>(null)

  React.useEffect(() => {
    if (!open) return
    const element = ref.current
    if (element && !element.open) element.showModal()
    // The page behind must not scroll. A class, not a style: the policy allows one and not the other.
    document.documentElement.classList.add('overflow-hidden')
    return () => document.documentElement.classList.remove('overflow-hidden')
  }, [open])

  if (!open) return null
  return (
    <dialog
      ref={ref}
      data-slot="dialog-content"
      role={alert ? 'alertdialog' : undefined}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className={cn(
        'm-auto w-[calc(100%-2rem)] max-w-lg rounded-xl border bg-popover p-6 text-popover-foreground shadow-xl backdrop:bg-black/50',
        className,
      )}
      onClose={() => setOpen(false)}
      onClick={(event) => {
        // A click on the dialog element itself, not on anything in it, is a click on the backdrop.
        if (!alert && event.target === event.currentTarget) setOpen(false)
      }}
      {...props}
    >
      {children}
    </dialog>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="dialog-header" className={cn('flex flex-col gap-2', className)} {...props} />
}

function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="dialog-footer" className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)} {...props} />
}

function DialogTitle({ className, ...props }: React.ComponentProps<'h2'>) {
  const { titleId } = useDialog()
  return <h2 id={titleId} data-slot="dialog-title" className={cn('text-xl leading-snug font-semibold', className)} {...props} />
}

function DialogDescription({ className, ...props }: React.ComponentProps<'p'>) {
  const { descriptionId } = useDialog()
  return <p id={descriptionId} data-slot="dialog-description" className={cn('text-sm text-muted-foreground', className)} {...props} />
}

export { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger, useDialog }
