import { Outlet, redirect, type LoaderFunctionArgs, type RouteObject } from 'react-router'
import { ApiError, get, loadSession } from '@/lib/api'
import { AdminOrgsPage } from '@/pages/admin-orgs'
import { AuditPage } from '@/pages/audit'
import { DataProtectionPage } from '@/pages/dlp'
import { Frame, Landing, NotBuilt } from '@/pages/frame'
import { ErrorScreen, InvitationPage, InvitationResult } from '@/pages/messages'
import { OrgPageView } from '@/pages/org'

type Args = LoaderFunctionArgs

/** A page's data. Signed out, go and sign in first, and come back to this address. */
function page(path: (args: Args) => string) {
  return async (args: Args) => {
    const session = await loadSession()
    if (!session.signed_in) throw redirect('/?next=' + encodeURIComponent(new URL(args.request.url).pathname))
    return get(path(args))
  }
}

export const routes: RouteObject[] = [
  {
    id: 'root',
    path: '/',
    loader: loadSession,
    element: (
      <Frame>
        <Outlet />
      </Frame>
    ),
    errorElement: <ErrorScreen />, // the session itself could not be read
    hydrateFallbackElement: <p className="p-10 text-muted-foreground">Loading…</p>,
    children: [
      {
        errorElement: <ErrorScreen />, // a page failed; the bar across the top stays
        children: [
          { index: true, element: <Landing /> },
          { path: 'invite/:token', loader: ({ params }) => get(`/invites/${params.token}`), element: <InvitationPage /> },
          { path: 'invite-result/:outcome', element: <InvitationResult /> },
          { path: 'admin', loader: page(() => '/admin/orgs'), element: <AdminOrgsPage /> },
          { path: 'admin/audit', loader: page(() => '/admin/audit'), element: <AuditPage /> },
          { path: 'admin/dlp', loader: page(() => '/admin/dlp'), element: <DataProtectionPage /> },
          { path: 'orgs/:orgId', loader: page(({ params }) => `/orgs/${params.orgId}`), element: <OrgPageView /> },
          { path: 'teams/:teamId', loader: page(({ params }) => `/teams/${params.teamId}`), element: <NotBuilt /> },
          { path: 'teams/:teamId/manage', loader: page(({ params }) => `/teams/${params.teamId}/manage`), element: <NotBuilt /> },
          {
            path: '*',
            loader: () => {
              throw new ApiError(404, 'That does not exist.')
            },
          },
        ],
      },
    ],
  },
]
