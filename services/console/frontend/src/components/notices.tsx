import { CircleAlertIcon, CircleCheckIcon, XIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { notices, useNotices } from '@/lib/notices'

/** Where the answer to an action is said: bottom right, read out by screen readers. A failure interrupts and stays. */
export function Notices() {
  const items = useNotices()
  return (
    <div role="status" aria-live="polite" className="fixed right-4 bottom-4 z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {items.map((notice) => (
        <div
          key={notice.id}
          role={notice.kind === 'bad' ? 'alert' : undefined}
          className={cn('flex items-start gap-3 rounded-md border bg-card p-4 text-sm shadow-lg', notice.kind === 'bad' && 'border-destructive/40')}
        >
          {notice.kind === 'good' ? (
            <CircleCheckIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-good" />
          ) : (
            <CircleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
          )}
          <p className="flex-1">{notice.message}</p>
          <button type="button" aria-label="Dismiss" className="text-muted-foreground hover:text-foreground" onClick={() => notices.dismiss(notice.id)}>
            <XIcon className="size-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
