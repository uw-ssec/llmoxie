import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/** A small uppercase tag: "suspended", "archived", a concept's type. `bad` is for something refused. */
export function Tag({ children, bad = false }: { children: ReactNode; bad?: boolean }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        // May wrap where a table column is tight, so a long tag never pushes a row's buttons out of view.
        'h-auto min-h-5 rounded-xl text-left font-ui text-xs font-semibold tracking-widest whitespace-normal uppercase',
        bad ? 'border-destructive/30 bg-bad-surface text-destructive' : 'border-border text-muted-foreground',
      )}
    >
      {children}
    </Badge>
  )
}

/** Shown only when something is not in its ordinary state. */
export function StatusTag({ status }: { status: string }) {
  return status === 'active' ? null : <Tag>{status}</Tag>
}
