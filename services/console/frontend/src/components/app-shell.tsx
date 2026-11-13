import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router'
import { cn } from '@/lib/utils'
import type { SignedIn } from '@/lib/types'

const item = 'border-b-2 border-transparent py-1 font-ui text-sm font-semibold tracking-wider text-nav-foreground uppercase no-underline hover:text-white hover:no-underline'

function Item({ to, children }: { to: string; children: ReactNode }) {
  return (
    // The 2px teal underline on the page you are on is the design system's signature.
    <NavLink to={to} end className={({ isActive }) => cn(item, isActive && 'border-signature text-white')}>
      {children}
    </NavLink>
  )
}

/** The purple bar across the top, and the page beneath it. */
export function AppShell({ session, children }: { session: SignedIn; children: ReactNode }) {
  const { me, config, csrf } = session
  return (
    <>
      <header className="sticky top-0 z-20 bg-nav">
        <nav aria-label="Main" className="mx-auto flex max-w-285 flex-wrap items-center gap-x-8 gap-y-2 px-6 py-4">
          <Link to="/" className="font-heading text-lg font-bold text-white no-underline hover:text-white hover:no-underline">
            LLMoxie console
          </Link>
          {me.is_admin && (
            <>
              <Item to="/admin">Organizations</Item>
              <Item to="/admin/audit">Audit log</Item>
              <Item to="/admin/dlp">Data protection</Item>
              {config.litellm_admin_url && (
                <a href={`${config.litellm_admin_url}/ui/`} rel="noopener" className={item}>
                  LiteLLM UI
                </a>
              )}
            </>
          )}
          <span className="ml-auto text-sm text-nav-foreground">{me.email ?? 'signed in'}</span>
          {/* A plain form, not a call: signing out ends at the identity provider's page. */}
          <form method="post" action="/logout">
            <input type="hidden" name="csrf" value={csrf} />
            <button type="submit" className={cn(item, 'cursor-pointer')}>
              Sign out
            </button>
          </form>
        </nav>
      </header>
      <main className="mx-auto max-w-285 px-6 py-10">{children}</main>
    </>
  )
}
