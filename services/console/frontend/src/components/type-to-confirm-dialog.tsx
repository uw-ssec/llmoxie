import { useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** For what cannot be undone: the name has to be typed, exactly, before the button works. */
export function TypeToConfirmDialog({
  trigger,
  title,
  description,
  prompt,
  expected,
  confirmLabel,
  onConfirm,
}: {
  trigger: string
  title: string
  description: ReactNode
  prompt: ReactNode
  expected: string
  confirmLabel: string
  onConfirm: (typed: string) => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const matches = typed.trim() === expected
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        setTyped('')
      }}
    >
      <DialogTrigger asChild>
        <Button variant="destructive">{trigger}</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={async (event) => {
            event.preventDefault()
            if (!matches || busy) return
            setBusy(true)
            try {
              await onConfirm(typed.trim())
              setOpen(false)
            } finally {
              setBusy(false)
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirm-text">{prompt}</Label>
            <Input id="confirm-text" value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="destructive" disabled={!matches || busy} aria-busy={busy}>
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
