import { Outlet, redirect, type LoaderFunctionArgs, type RouteObject, type ShouldRevalidateFunction } from 'react-router'
import type { Crumb, RouteHandle } from '@/components/app-shell'
import { ApiError, get, loadSession } from '@/lib/api'
import { loadOverview } from '@/lib/overview'
import { pageData } from '@/lib/page-data'
import type { KnowledgePage, MyTeamPage, OrgPage, TeamManagePage } from '@/lib/types'
import { AdminOrgsPage } from '@/pages/admin-orgs'
import { AuditPage } from '@/pages/audit'
import { DataProtectionPage } from '@/pages/dlp'
import { Frame, Landing } from '@/pages/frame'
import { KnowledgePageView } from '@/pages/knowledge'
import { ErrorScreen, InvitationPage, InvitationResult } from '@/pages/messages'
import { MyTeamPageView } from '@/pages/my-team'
import { OrgPageView } from '@/pages/org'
import { TeamManagePageView } from '@/pages/team-manage'

type Args = LoaderFunctionArgs

/** A page's data. Signed out, go and sign in first, and come back to this address. */
function page(path: (args: Args) => string) {
  return async (args: Args) => {
    const session = await loadSession()
    if (!session.signed_in) throw redirect('/?next=' + encodeURIComponent(new URL(args.request.url).pathname))
    return pageData(path(args))
  }
}

/** The trail in the top bar, from the page's own data. A page that failed to load has none. */
function trail<Data>(crumbs: (data: Data) => Crumb[]): RouteHandle {
  return { crumbs: (data) => (data ? crumbs(data as Data) : []) }
}
const named = (label: string): RouteHandle => ({ crumbs: () => [{ label }] })

/** Changing which tab is open changes the address and nothing else, so the page's data is not asked for again. */
const keepForTabs: ShouldRevalidateFunction = ({ currentUrl, nextUrl, defaultShouldRevalidate }) =>
  currentUrl.pathname === nextUrl.pathname && currentUrl.search !== nextUrl.search ? false : defaultShouldRevalidate

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
          { index: true, loader: loadOverview, handle: named('Overview'), element: <Landing /> },
          { path: 'invite/:token', loader: ({ params }) => get(`/invites/${params.token}`), element: <InvitationPage /> },
          { path: 'invite-result/:outcome', element: <InvitationResult /> },
          { path: 'admin', loader: page(() => '/admin/orgs'), handle: named('Organizations'), element: <AdminOrgsPage /> },
          { path: 'admin/audit', loader: page(() => '/admin/audit'), handle: named('Audit log'), element: <AuditPage /> },
          { path: 'admin/dlp', loader: page(() => '/admin/dlp'), handle: named('Data protection'), element: <DataProtectionPage /> },
          {
            path: 'orgs/:orgId',
            loader: page(({ params }) => `/orgs/${params.orgId}`),
            shouldRevalidate: keepForTabs,
            // An admin who does not lead it came from the list of every organization.
            handle: trail<OrgPage>(({ org, is_lead }) => [...(is_lead ? [] : [{ label: 'Organizations', to: '/admin' }]), { label: org.name }]),
            element: <OrgPageView />,
          },
          {
            path: 'orgs/:orgId/knowledge',
            handle: trail<KnowledgePage>(({ org }) => [{ label: org.name, to: `/orgs/${org.id}` }, { label: 'Knowledge' }]),
            // Which concept is open is part of the address, so a link to it and a reload both work.
            loader: page(({ params, request }) => {
              const concept = new URL(request.url).searchParams.get('concept')
              return `/orgs/${params.orgId}/knowledge` + (concept ? `?concept=${encodeURIComponent(concept)}` : '')
            }),
            element: <KnowledgePageView />,
          },
          {
            path: 'teams/:teamId',
            loader: page(({ params }) => `/teams/${params.teamId}`),
            handle: trail<MyTeamPage>(({ team }) => [{ label: team.name }]),
            element: <MyTeamPageView />,
          },
          {
            path: 'teams/:teamId/manage',
            loader: page(({ params }) => `/teams/${params.teamId}/manage`),
            shouldRevalidate: keepForTabs,
            handle: trail<TeamManagePage>(({ team }) => [{ label: team.org_name, to: `/orgs/${team.org_id}` }, { label: team.name }]),
            element: <TeamManagePageView />,
          },
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
