import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'

/** A small uppercase tag: "suspended", "archived", a concept's type. */
export function Tag({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="rounded-full border-border font-ui text-xs font-semibold tracking-widest text-muted-foreground uppercase">
      {children}
    </Badge>
  )
}

/** Shown only when something is not in its ordinary state. */
export function StatusTag({ status }: { status: string }) {
  return status === 'active' ? null : <Tag>{status}</Tag>
}
