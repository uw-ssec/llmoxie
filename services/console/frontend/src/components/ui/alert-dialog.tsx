// A question before something that cannot be undone. The same native dialog as ./dialog, announced
// as an alert and closed only by one of its two buttons or Escape. See ./dialog for why it is not Radix's.
import * as React from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger, useDialog } from './dialog'

const AlertDialog = Dialog
const AlertDialogTrigger = DialogTrigger
const AlertDialogHeader = DialogHeader
const AlertDialogFooter = DialogFooter
const AlertDialogTitle = DialogTitle
const AlertDialogDescription = DialogDescription

function AlertDialogContent({ className, ...props }: React.ComponentProps<typeof DialogContent>) {
  return <DialogContent alert className={cn('flex flex-col gap-4', className)} {...props} />
}

function AlertDialogCancel(props: React.ComponentProps<typeof Button>) {
  const { setOpen } = useDialog()
  return <Button type="button" variant="outline" {...props} onClick={() => setOpen(false)} />
}

/** Does the thing, and closes the question. */
function AlertDialogAction({ onClick, ...props }: React.ComponentProps<typeof Button>) {
  const { setOpen } = useDialog()
  return (
    <Button
      type="button"
      {...props}
      onClick={(event) => {
        onClick?.(event)
        setOpen(false)
      }}
    />
  )
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
}
