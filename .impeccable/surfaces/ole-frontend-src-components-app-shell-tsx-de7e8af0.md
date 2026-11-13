---
version: 1
slug: "ole-frontend-src-components-app-shell-tsx-de7e8af0"
primary_target: "services/console/frontend/src/components/app-shell.tsx"
related_targets: []
---

# Console dashboard

- Scope: every signed-in screen of the LLMoxie console, plus sign-in and the
  one-message pages.
- Mode: Operate. Primary user: organization leads; admins and participants use
  the same patterns.
- Reference pinned by the owner: the sidebar dashboard at
  dashboard.shadcnspace.com, inside the SSEC design system.
- Constraints: front-end only, same `/web-api/` calls and actions, strict
  content security policy (no run-time style elements), light theme, no charts
  or chart placeholders until analytics exist.

## Direction contract

THESIS: One working shell for three roles, in which every figure is one the
server sent. It refuses the dashboard kit's habits of sample charts, trend chips
and four identical tiles: figures sit in one divided strip, and the lead's teams
are the first thing on the overview.

OWN-WORLD: The SSEC system as shipped. Husky Purple (purple-900) sidebar with
Light Gold labels; a warm gold-50 ground under white 8px cards with a hairline
border and a small shadow; Encode Sans headings in Spirit Purple, Encode Sans at
75% width in uppercase for labels, buttons and table heads; Open Sans body;
JetBrains Mono for names clients type. Square buttons. Signature move: the 2px
teal underline marks where you are, in the sidebar, in the tabs and as the
loading line under the top bar.

STORY: The lead sees which organizations and teams they run and how big each is,
opens a team, and does one job (invite, budget, rotate a key) in the tab named
for it.

FIRST VIEWPORT: 256px purple sidebar at the left edge, full height: wordmark,
Overview, "Your organizations", "Your teams", "Administration". A 56px white top
bar: breadcrumb at the left, email and Sign out at the right. Below, on gold-50:
the page title, then one stat strip of four figures across the full width, then
cards. On an organization or team: title, stat strip, tab row, the active tab's
cards. The form that adds to a list sits in its own card beside that list;
nothing is hidden behind a button. One exception: naming a new key is a single
field, and stays under the participant's list of keys.

FORM: Side-rail dashboard, pinned by the owner's reference. No concept roll was
run, so there is no seed reference to record: seed: none (roll skipped;
composition pinned by the brief)

FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its
provenance

## Unresolved

- Analytics (time series, charts) and where they go once the browser API has
  them.
- A collapsed icon-rail state for the sidebar on desktop was left out.
