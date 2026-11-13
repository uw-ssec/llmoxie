import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { AppShell } from '@/components/app-shell'
import { Notices } from '@/components/notices'
import { useSession } from '@/lib/session'
import { Home } from './home'
import { NotInvited } from './messages'
import { SignIn } from './sign-in'

/** Around every page: the bar across the top once someone is signed in, and where messages appear. */
export function Frame({ children }: { children: ReactNode }) {
  const session = useSession()
  return (
    <>
      {session?.signed_in ? <AppShell session={session}>{children}</AppShell> : <main>{children}</main>}
      <Notices />
    </>
  )
}

/** The rule the server's home page used to apply: what "/" shows depends on who you are. */
export function Landing() {
  const session = useSession()
  if (!session.signed_in) return <SignIn />
  const { me } = session
  if (!me.is_admin && me.lead_orgs.length === 0) {
    if (me.teams.length === 0) return <NotInvited me={me} />
    if (me.teams.length === 1) return <Navigate to={`/teams/${me.teams[0].id}`} replace />
  }
  return <Home session={session} />
}
