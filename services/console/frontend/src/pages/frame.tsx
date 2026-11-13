import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { AppShell } from '@/components/app-shell'
import { Notices } from '@/components/notices'
import { showsOverview } from '@/lib/overview'
import { useSession } from '@/lib/session'
import { Home } from './home'
import { NotInvited } from './messages'
import { SignIn } from './sign-in'

/** Around every page: the sidebar and top bar once someone is signed in, and where messages appear. */
export function Frame({ children }: { children: ReactNode }) {
  const session = useSession()
  return (
    <>
      {session?.signed_in ? <AppShell session={session}>{children}</AppShell> : <SignedOut>{children}</SignedOut>}
      <Notices />
    </>
  )
}

/**
 * Before anyone is signed in there is one message on the page. It sits on a card over the edge of a
 * purple field cut at the design system's 15 degrees.
 */
function SignedOut({ children }: { children: ReactNode }) {
  return (
    <main className="relative flex min-h-svh flex-col items-center bg-page px-4 pt-[18svh] pb-12">
      <div aria-hidden className="absolute inset-x-0 top-0 h-[62svh] bg-nav [clip-path:polygon(0_0,100%_0,100%_max(0%,calc(100%-26.8vw)),0_100%)]" />
      <div className="relative w-full max-w-xl rounded-lg border bg-card shadow-lg">{children}</div>
    </main>
  )
}

/** The rule the server's home page used to apply: what "/" shows depends on who you are. */
export function Landing() {
  const session = useSession()
  if (!session.signed_in) return <SignIn />
  const { me } = session
  if (!showsOverview(me)) {
    if (me.teams.length === 0) return <NotInvited me={me} />
    return <Navigate to={`/teams/${me.teams[0].id}`} replace />
  }
  return <Home />
}
