import type { ComponentProps, ReactNode } from 'react'
import { Link } from 'react-router'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { count } from '@/lib/format'
import { th } from '@/lib/styles'
import type { Tab } from '@/lib/tabs'
import { cn } from '@/lib/utils'

/** The top of a page: its name, a line about it, and what can be done to the whole of it. */
export function PageHeader({ title, tag, lede, actions }: { title: ReactNode; tag?: ReactNode; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="flex flex-wrap items-center gap-3 text-2xl font-bold">
          {title}
          {tag}
        </h1>
        {lede && <p className="mt-1 max-w-[75ch] text-muted-foreground">{lede}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

/** A page's figures, side by side in one strip. Each is one the server sent, or a count of what is on the page. */
export function Stats({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section aria-label={label}>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border shadow-xs xl:auto-cols-fr xl:grid-flow-col xl:grid-cols-none">{children}</dl>
    </section>
  )
}

/** The design system's stat: the number in purple, its label beneath in the label style. */
export function Stat({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 bg-card px-6 py-5 last:odd:col-span-2 xl:last:odd:col-span-1">
      <dt className={th}>{label}</dt>
      <dd className="order-first font-heading text-2xl leading-none font-extrabold tracking-tight wrap-anywhere text-primary tabular-nums">
        {typeof value === 'number' ? count(value) : value}
      </dd>
      {detail && <dd className="text-sm text-muted-foreground">{detail}</dd>}
    </div>
  )
}

/** The parts of a long screen. The teal underline marks the open one, as it marks the page in the sidebar. */
export function Tabs<Id extends string>({ label, tabs, current }: { label: string; tabs: Tab<Id>[]; current: Id }) {
  return (
    <nav aria-label={label} className="flex gap-x-8 overflow-x-auto shadow-[inset_0_-1px_0_var(--border)]">
      {tabs.map((tab) => (
        <Link
          key={tab.id}
          to={`?tab=${tab.id}`}
          preventScrollReset
          aria-current={tab.id === current ? 'page' : undefined}
          className={cn(
            'flex shrink-0 items-center gap-2 border-b-2 border-transparent py-3 font-ui text-sm font-semibold tracking-wider text-muted-foreground uppercase no-underline outline-none hover:text-primary hover:no-underline focus-visible:text-primary focus-visible:ring-2 focus-visible:ring-ring/50',
            tab.id === current && 'border-signature text-primary',
          )}
        >
          {tab.label}
          {tab.count !== undefined && <span className="rounded-full bg-secondary px-2 text-xs leading-5 tracking-normal text-secondary-foreground tabular-nums">{tab.count}</span>}
        </Link>
      ))}
    </nav>
  )
}

/** One part of a page, as a card with a heading. `action` sits at the heading's right. */
export function Section({
  title,
  description,
  action,
  children,
  className,
  ...props
}: Omit<ComponentProps<typeof Card>, 'title'> & { title?: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <Card className={cn('gap-5 rounded-lg border shadow-xs ring-0 [--card-spacing:--spacing(6)]', className)} {...props}>
      {(title || description || action) && (
        <CardHeader>
          {title && (
            <CardTitle>
              <h2 className="text-lg">{title}</h2>
            </CardTitle>
          )}
          {description && <CardDescription className="max-w-[75ch]">{description}</CardDescription>}
          {action && <CardAction>{action}</CardAction>}
        </CardHeader>
      )}
      <CardContent className="@container flex flex-col gap-5">{children}</CardContent>
    </Card>
  )
}

/** A list and, beside it, the form that adds to it. Without a form the list has the row to itself. */
export function Split({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  if (!aside) return <>{children}</>
  return (
    <div className="@container">
      <div className="grid items-start gap-6 @[68rem]:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
        <div className="flex min-w-0 flex-col gap-6">{children}</div>
        {aside}
      </div>
    </div>
  )
}

/** A heading under a section's main part. */
export function SubHeading({ children }: { children: ReactNode }) {
  return <h3 className="border-t pt-5 text-base">{children}</h3>
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

/** A page that is one message: sign in, an invitation, an error. */
export function Centered({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-6 py-16 text-center">
      <h1 className="text-2xl font-bold text-balance">{title}</h1>
      {children}
    </div>
  )
}
