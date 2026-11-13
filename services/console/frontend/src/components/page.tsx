import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/** The top of a page: where it sits, its name, and a line about it. */
export function PageHeader({ title, tag, lede, back }: { title: ReactNode; tag?: ReactNode; lede?: ReactNode; back?: { to: string; label: string } }) {
  return (
    <div className="mb-8">
      {back && (
        <p className="mb-2 text-sm">
          <Link to={back.to}>← {back.label}</Link>
        </p>
      )}
      <h1 className="flex flex-wrap items-center gap-3">
        {title}
        {tag}
      </h1>
      {lede && <p className="mt-2 max-w-[75ch] text-lg text-muted-foreground">{lede}</p>}
    </div>
  )
}

/** One part of a page, as a card with a heading. */
export function Section({ title, description, children, className }: { title?: ReactNode; description?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={cn('mb-6', className)}>
      {(title || description) && (
        <CardHeader>
          {title && (
            <CardTitle>
              <h2>{title}</h2>
            </CardTitle>
          )}
          {description && <CardDescription className="max-w-[75ch]">{description}</CardDescription>}
        </CardHeader>
      )}
      <CardContent className="flex flex-col gap-6">{children}</CardContent>
    </Card>
  )
}

/** A heading under a section's main part, for the form that adds to the list above it. */
export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="border-t pt-6">{children}</h3>
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

/** A page that is one message: sign in, an invitation, an error. */
export function Centered({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-6 py-24 text-center">
      <h1>{title}</h1>
      {children}
    </div>
  )
}
