import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react'
import { Link, NavLink, useMatches, useNavigation } from 'react-router'
import {
  Building2Icon,
  ChevronRightIcon,
  ExternalLinkIcon,
  LandmarkIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MenuIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  UsersIcon,
  XIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { showsOverview } from '@/lib/overview'
import type { SignedIn } from '@/lib/types'
import { cn } from '@/lib/utils'

/** One step of the trail in the top bar. The last has no address: it is the page you are on. */
export type Crumb = { label: string; to?: string }
/** What a route may carry (router.tsx): how to name the page from its data. */
export type RouteHandle = { crumbs?: (data: unknown) => Crumb[] }

const row =
  'flex min-h-10 items-center gap-3 rounded-md px-3 py-2 font-ui text-base font-semibold tracking-wide text-nav-foreground no-underline outline-none hover:bg-white/10 hover:text-white hover:no-underline focus-visible:ring-2 focus-visible:ring-signature'

type Icon = ComponentType<{ className?: string; 'aria-hidden'?: boolean }>

function Item({ to, icon: Icon, label, within = false, children }: { to: string; icon?: Icon; label?: string; within?: boolean; children: ReactNode }) {
  return (
    <NavLink to={to} end aria-label={label} className={({ isActive }) => cn(row, !Icon && 'ml-7 min-h-9 py-1.5', (isActive || within) && 'bg-white/10 text-white')}>
      {({ isActive }) => (
        <>
          {Icon && <Icon aria-hidden className="size-4 shrink-0" />}
          {/* The 2px teal underline on the page you are on is the design system's signature. */}
          <span className={cn('truncate border-b-2 border-transparent', (isActive || within) && 'border-signature')}>{children}</span>
        </>
      )}
    </NavLink>
  )
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li>
      <p className="px-3 pb-2 font-ui text-xs font-semibold tracking-widest text-nav-muted uppercase">{label}</p>
      <ul className="flex flex-col gap-1">{children}</ul>
    </li>
  )
}

/** Everywhere this person can go. `orgId` is the organization the page on screen belongs to, if any. */
function MainNav({ session: { me, config }, orgId, onKnowledge }: { session: SignedIn; orgId?: string; onKnowledge: boolean }) {
  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-6 px-3 pb-6">
        {showsOverview(me) && (
          <li>
            <Item to="/" icon={LayoutDashboardIcon}>
              Overview
            </Item>
          </li>
        )}
        {me.lead_orgs.length > 0 && (
          <Group label="Your organizations">
            {me.lead_orgs.map((org) => (
              <li key={org.id} className="flex flex-col gap-1">
                <Item to={`/orgs/${org.id}`} icon={Building2Icon} within={orgId === org.id && !onKnowledge}>
                  {org.name}
                </Item>
                <Item to={`/orgs/${org.id}/knowledge`} label={`${org.name}: Knowledge`}>
                  Knowledge
                </Item>
              </li>
            ))}
          </Group>
        )}
        {me.teams.length > 0 && (
          <Group label="Your teams">
            {me.teams.map((team) => (
              <li key={team.id}>
                <Item to={`/teams/${team.id}`} icon={UsersIcon}>
                  {team.name}
                </Item>
              </li>
            ))}
          </Group>
        )}
        {me.is_admin && (
          <Group label="Administration">
            <li>
              <Item to="/admin" icon={LandmarkIcon}>
                Organizations
              </Item>
            </li>
            <li>
              <Item to="/admin/audit" icon={ScrollTextIcon}>
                Audit log
              </Item>
            </li>
            <li>
              <Item to="/admin/dlp" icon={ShieldCheckIcon}>
                Data protection
              </Item>
            </li>
            {config.litellm_admin_url && (
              <li>
                <a href={`${config.litellm_admin_url}/ui/`} rel="noopener" className={row}>
                  <ExternalLinkIcon aria-hidden className="size-4 shrink-0" />
                  LiteLLM UI
                </a>
              </li>
            )}
          </Group>
        )}
      </ul>
    </nav>
  )
}

function Wordmark() {
  return (
    <Link to="/" className="font-heading text-lg font-bold text-white no-underline outline-none hover:text-white hover:no-underline focus-visible:ring-2 focus-visible:ring-signature">
      LLMoxie <span className="font-normal text-nav-foreground">console</span>
    </Link>
  )
}

/** The same navigation on a narrow screen: a full-screen sheet, on the browser's own <dialog> (see ui/dialog.tsx for why). */
function Menu({ email, children }: { email: string | null; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    if (open && !element.open) element.showModal()
    if (!open && element.open) element.close()
    if (!open) return
    document.documentElement.classList.add('overflow-hidden')
    return () => document.documentElement.classList.remove('overflow-hidden')
  }, [open])
  return (
    <>
      <Button type="button" variant="ghost" size="icon" className="-ml-2 lg:hidden" aria-label="Open menu" onClick={() => setOpen(true)}>
        <MenuIcon />
      </Button>
      <dialog
        ref={ref}
        hidden={!open}
        aria-label="Menu"
        className="on-nav m-0 h-dvh max-h-none w-full max-w-none overflow-y-auto bg-terminal p-0"
        onClose={() => setOpen(false)}
        // Following a link closes the sheet; the page it leads to is behind it.
        onClick={(event) => {
          if ((event.target as Element).closest('a')) setOpen(false)
        }}
      >
        {open && (
          <>
            <div className="flex h-14 items-center justify-between px-6">
              <Wordmark />
              <Button type="button" variant="ghost" size="icon" className="-mr-2 text-white hover:bg-white/10" aria-label="Close menu" onClick={() => setOpen(false)}>
                <XIcon />
              </Button>
            </div>
            <div className="pt-4">{children}</div>
            {email && <p className="border-t border-white/10 px-6 py-4 text-sm text-nav-foreground">Signed in as {email}</p>}
          </>
        )}
      </dialog>
    </>
  )
}

function Trail({ crumbs }: { crumbs: Crumb[] }) {
  if (crumbs.length < 2) return null // one step would only repeat the page's own title
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex items-center gap-1.5 text-sm">
        {crumbs.map((crumb, index) => (
          <li key={index} className={cn('flex min-w-0 items-center gap-1.5', crumb.to && 'max-sm:hidden')}>
            {index > 0 && <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-muted-foreground max-sm:hidden" />}
            {crumb.to ? (
              <Link to={crumb.to} className="truncate text-muted-foreground">
                {crumb.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate font-semibold">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}

/** The purple sidebar, the bar across the top, and the page beside and beneath them. */
export function AppShell({ session, children }: { session: SignedIn; children: ReactNode }) {
  const { me, csrf } = session
  const matches = useMatches()
  const loading = useNavigation().state === 'loading'
  const page = matches.at(-1)
  const data = page?.loaderData as { org?: { id?: string }; team?: { org_id?: string } } | null | undefined
  const here = (page?.handle as RouteHandle | undefined)?.crumbs?.(page?.loaderData) ?? []
  // Every trail starts at the overview, for those who have one.
  const crumbs = showsOverview(me) && page?.pathname !== '/' && here.length > 0 ? [{ label: 'Overview', to: '/' }, ...here] : here
  const nav = <MainNav session={session} orgId={data?.org?.id ?? data?.team?.org_id} onKnowledge={page?.pathname.endsWith('/knowledge') === true} />
  return (
    <div className="min-h-svh bg-page lg:pl-64">
      <aside className="on-nav fixed inset-y-0 left-0 z-30 hidden w-64 flex-col overflow-y-auto bg-nav lg:flex">
        <div className="flex h-14 shrink-0 items-center px-6">
          <Wordmark />
        </div>
        <div className="pt-4">{nav}</div>
      </aside>
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background px-4 sm:px-6 lg:px-8">
        <Menu email={me.email}>{nav}</Menu>
        <Trail crumbs={crumbs} />
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <span className="text-sm text-muted-foreground max-md:hidden">{me.email ?? 'signed in'}</span>
          {/* A plain form, not a call: signing out ends at the identity provider's page. */}
          <form method="post" action="/logout">
            <input type="hidden" name="csrf" value={csrf} />
            <Button type="submit" variant="ghost" size="sm">
              <LogOutIcon aria-hidden />
              Sign out
            </Button>
          </form>
        </div>
        {loading && <div role="progressbar" aria-label="Loading the page" className="loading-line" />}
      </header>
      <main className="mx-auto flex w-full max-w-350 flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  )
}
