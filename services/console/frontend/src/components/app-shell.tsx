import { useEffect, useId, useRef, useState, type ComponentType, type ReactNode } from 'react'
import { Link, NavLink, useMatches, useNavigation } from 'react-router'
import {
  ChevronRightIcon,
  ExternalLinkIcon,
  LandmarkIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MenuIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  XIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { showsOverview } from '@/lib/overview'
import { useStored } from '@/lib/stored'
import type { SignedIn } from '@/lib/types'
import { cn } from '@/lib/utils'

/** One step of the trail in the top bar. The last has no address: it is the page you are on. */
export type Crumb = { label: string; to?: string }
/** What a route may carry (router.tsx): how to name the page from its data. */
export type RouteHandle = { crumbs?: (data: unknown) => Crumb[] }

const row =
  'flex min-h-10 items-center gap-3 rounded-md px-3 py-2 font-ui text-base font-semibold tracking-wide text-nav-foreground no-underline outline-none hover:bg-white/10 hover:text-white hover:no-underline focus-visible:ring-2 focus-visible:ring-signature'

type Icon = ComponentType<{ className?: string; 'aria-hidden'?: boolean }>

/**
 * One place to go. In front of its name is an icon, or for an organization or a team the first
 * letter of its name, so that several of them can be told apart when the sidebar is narrow (`rail`)
 * and shows nothing else. A page under an organization has neither and is set in from the edge.
 */
function Item({
  to,
  icon: Icon,
  letter = false,
  label,
  within = false,
  rail = false,
  className,
  children,
}: {
  to: string
  icon?: Icon
  letter?: boolean
  label?: string
  within?: boolean
  rail?: boolean
  className?: string
  children: string
}) {
  const sub = !Icon && !letter
  return (
    <NavLink
      to={to}
      end
      aria-label={label}
      title={rail ? children : undefined}
      className={({ isActive }) => cn(row, sub && 'ml-8 min-h-9 py-1.5', rail && 'size-10 justify-center p-0', (isActive || within) && 'bg-white/10 text-white', className)}
    >
      {({ isActive }) => (
        <>
          {!sub && (
            // Narrow, the teal line sits under the icon, since the name it usually sits under is not shown.
            <span className={cn('flex size-5 shrink-0 items-center justify-center', rail && 'box-content border-b-2 border-transparent py-1', rail && (isActive || within) && 'border-signature')}>
              {Icon ? (
                <Icon aria-hidden className="size-4" />
              ) : (
                <span aria-hidden className="flex size-5 items-center justify-center rounded-sm bg-white/15 text-xs leading-none font-bold text-white uppercase">
                  {children.trim().charAt(0)}
                </span>
              )}
            </span>
          )}
          {/* The 2px teal underline on the page you are on is the design system's signature. */}
          <span className={cn('truncate border-b-2 border-transparent', (isActive || within) && 'border-signature', rail && 'sr-only')}>{children}</span>
        </>
      )}
    </NavLink>
  )
}

function Group({ label, rail, children }: { label: string; rail: boolean; children: ReactNode }) {
  return (
    <li>
      <p className={cn('px-3 pb-2 font-ui text-xs font-semibold tracking-widest text-nav-muted uppercase', rail && 'sr-only')}>{label}</p>
      {rail && <div aria-hidden className="mx-2 mb-3 border-t border-white/15" />}
      <ul className="flex flex-col gap-1">{children}</ul>
    </li>
  )
}

/** Which organizations' pages are folded away in the sidebar, by organization. Unfolded until someone folds them. */
type Folded = Record<string, boolean>

/**
 * Everywhere this person can go. `orgId` is the organization the page on screen belongs to, if any.
 * `rail` is the sidebar at its narrow width: icons only, each named when pointed at.
 */
function MainNav({
  session: { me, config },
  orgId,
  onKnowledge,
  rail = false,
  folded,
  fold,
}: {
  session: SignedIn
  orgId?: string
  onKnowledge: boolean
  rail?: boolean
  folded: Folded
  fold: (next: Folded) => void
}) {
  const id = useId()
  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-6 px-3 pb-6">
        {showsOverview(me) && (
          <li>
            <Item to="/" icon={LayoutDashboardIcon} rail={rail}>
              Overview
            </Item>
          </li>
        )}
        {me.lead_orgs.length > 0 && (
          <Group label="Your organizations" rail={rail}>
            {me.lead_orgs.map((org) => {
              const open = !folded[org.id]
              return (
                <li key={org.id} className="flex flex-col gap-1">
                  <div className="flex items-center gap-1">
                    <Item to={`/orgs/${org.id}`} letter rail={rail} within={orgId === org.id && !onKnowledge} className={rail ? undefined : 'min-w-0 flex-1'}>
                      {org.name}
                    </Item>
                    {!rail && (
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-controls={`${id}-${org.id}`}
                        aria-label={`Pages of ${org.name}`}
                        className="flex size-8 shrink-0 items-center justify-center rounded-md text-nav-foreground outline-none hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-signature"
                        onClick={() => fold({ ...folded, [org.id]: open })}
                      >
                        <ChevronRightIcon aria-hidden className={cn('size-4 transition-transform duration-200', open && 'rotate-90')} />
                      </button>
                    )}
                  </div>
                  {/* The narrow sidebar shows no pages under an organization: its icon leads to the organization. */}
                  <ul id={`${id}-${org.id}`} hidden={rail || !open} className="flex flex-col gap-1">
                    <li>
                      <Item to={`/orgs/${org.id}/knowledge`} label={`${org.name}: Knowledge`}>
                        Knowledge
                      </Item>
                    </li>
                  </ul>
                </li>
              )
            })}
          </Group>
        )}
        {me.teams.length > 0 && (
          <Group label="Your teams" rail={rail}>
            {me.teams.map((team) => (
              <li key={team.id}>
                <Item to={`/teams/${team.id}`} letter rail={rail}>
                  {team.name}
                </Item>
              </li>
            ))}
          </Group>
        )}
        {me.is_admin && (
          <Group label="Administration" rail={rail}>
            <li>
              <Item to="/admin" icon={LandmarkIcon} rail={rail}>
                Organizations
              </Item>
            </li>
            <li>
              <Item to="/admin/audit" icon={ScrollTextIcon} rail={rail}>
                Audit log
              </Item>
            </li>
            <li>
              <Item to="/admin/dlp" icon={ShieldCheckIcon} rail={rail}>
                Data protection
              </Item>
            </li>
            {config.litellm_admin_url && (
              <li>
                <a href={`${config.litellm_admin_url}/ui/`} rel="noopener" title={rail ? 'LiteLLM UI' : undefined} className={cn(row, rail && 'size-10 justify-center p-0')}>
                  <span className="flex size-5 shrink-0 items-center justify-center">
                    <ExternalLinkIcon aria-hidden className="size-4" />
                  </span>
                  <span className={cn(rail && 'sr-only')}>LiteLLM UI</span>
                </a>
              </li>
            )}
          </Group>
        )}
      </ul>
    </nav>
  )
}

/** The console's mark and name. Narrow, the mark alone. */
function Wordmark({ rail = false }: { rail?: boolean }) {
  return (
    <Link
      to="/"
      className="flex items-center gap-3 font-heading text-lg font-bold whitespace-nowrap text-white no-underline outline-none hover:text-white hover:no-underline focus-visible:ring-2 focus-visible:ring-signature"
    >
      <svg viewBox="0 0 32 32" aria-hidden className="size-7 shrink-0 rounded-sm">
        <rect width="32" height="32" className="fill-primary" />
        <path d="M9 7h4v14h10v4H9z" className="fill-white" />
        <rect x="9" y="27" width="14" height="2" className="fill-signature" />
      </svg>
      <span className={cn(rail && 'sr-only')}>
        LLMoxie <span className="font-normal text-nav-foreground">console</span>
      </span>
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
            <div className="flex h-14 items-center justify-between px-5">
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
  const [rail, setRail] = useStored('console.sidebar.narrow', false)
  const [folded, fold] = useStored<Folded>('console.sidebar.folded', {})
  const page = matches.at(-1)
  const data = page?.loaderData as { org?: { id?: string }; team?: { org_id?: string } } | null | undefined
  const here = (page?.handle as RouteHandle | undefined)?.crumbs?.(page?.loaderData) ?? []
  // Every trail starts at the overview, for those who have one.
  const crumbs = showsOverview(me) && page?.pathname !== '/' && here.length > 0 ? [{ label: 'Overview', to: '/' }, ...here] : here
  const nav = (narrow: boolean) => (
    <MainNav session={session} orgId={data?.org?.id ?? data?.team?.org_id} onKnowledge={page?.pathname.endsWith('/knowledge') === true} rail={narrow} folded={folded} fold={fold} />
  )
  return (
    <div className={cn('min-h-svh bg-page transition-[padding] duration-200', rail ? 'lg:pl-16' : 'lg:pl-64')}>
      <aside id="sidebar" className={cn('on-nav fixed inset-y-0 left-0 z-30 hidden flex-col overflow-x-hidden overflow-y-auto bg-nav transition-[width] duration-200 lg:flex', rail ? 'w-16' : 'w-64')}>
        <div className={cn('flex h-14 shrink-0 items-center', rail ? 'justify-center' : 'px-5')}>
          <Wordmark rail={rail} />
        </div>
        <div className="pt-4">{nav(rail)}</div>
      </aside>
      <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background px-4 sm:px-6 lg:px-8">
        <Menu email={me.email}>{nav(false)}</Menu>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-ml-2 max-lg:hidden"
          aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!rail}
          aria-controls="sidebar"
          onClick={() => setRail(!rail)}
        >
          {rail ? <PanelLeftOpenIcon aria-hidden /> : <PanelLeftCloseIcon aria-hidden />}
        </Button>
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
