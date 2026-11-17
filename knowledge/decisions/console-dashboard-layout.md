---
type: Decision
title: "The console is a sidebar dashboard that shows only figures the server sent, with no charts until analytics exist"
description: "Sidebar and top bar shell, a role-aware overview built from pages the person can already open, organization and team screens split into tabs kept in the address; no charts, chart placeholders or sample data until the browser API has analytics."
tags: [console, frontend, design]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T19:31:09Z" }
status: stable
governance: constraint
code_refs: [services/console/frontend/src/components/app-shell.tsx, services/console/frontend/src/components/page.tsx, services/console/frontend/src/lib/overview.ts, services/console/frontend/src/pages/home.tsx, services/console/frontend/src/router.tsx]
sources:
  - resource: owner decisions in the 2026-11-13 session
  - resource: PRODUCT.md
---

On 2026-11-13 the owner asked for the console's React pages to become a dashboard in the manner of dashboard.shadcnspace.com, inside the SSEC design and with every function kept, and said real analytics come later. Asked three questions, the owner chose: organization leads are the primary user; the overview shows real figures only until analytics exist; every screen is redesigned, front end only. The product record is `PRODUCT.md`; the look is recorded in `DESIGN.md`.

**Status (branch `console-react-ui`, 2026-11-13):** implemented and committed on that branch, not yet merged.

## What must stay true

- **A figure on screen is one the server sent, or a count or sum of what that screen lists.** No sample data, no trend arrows, no chart and no empty chart panel until `/web-api/` carries time series. The owner rejected reserved chart panels and sample charts by name.
- **The overview adds no server call of its own.** `frontend/src/lib/overview.ts` asks for pages the person can already open: `/orgs/<id>` for each organization they lead, and `/admin/orgs` and `/admin/audit` for an admin. So `shapes.py` and its rule (the browser gets only what a page shows) are untouched. A part that fails to load leaves a gap that says so; the overview still renders.
- **The overview does not load `/teams/<id>` or `/admin/dlp`.** The first makes a LiteLLM usage call per team and the second reads the data-protection log; both were left off the page everyone lands on. This is my choice, not the owner's; revisit it if the overview should show a member's usage.
- **A budget ceiling caps each team's budget; it is not a pool the teams share.** The broker refuses a team budget above the ceiling and never sums them, so no meter of teams' budgets against the ceiling is drawn. Team spend is shown beside the team budget as two separate figures because the period a budget covers is not in the browser API.
- **The open tab is in the address** (`?tab=keys`) on the organization and lead's-team screens. `keepForTabs` in `router.tsx` stops a tab change from reloading the page's data, and `use-action.ts` treats an answer that says "go to" the page already open as a reload in place, so an action on the Settings tab does not throw the user back to the first tab.

## Traps

- The shell adds landmarks. There are now up to three `navigation` regions (Main, Breadcrumb, the tab row), and an organization's or team's name appears in the sidebar, the breadcrumb and the page. Tests must name the region they mean (`getByRole('navigation', { name: 'Main' })`, `within(screen.getByRole('main'))`).
- The narrow-screen menu is the browser's `<dialog>`, for the reason the dialogs are (the content security policy). Its links are rendered only while it is open, so jsdom, which applies no CSS, does not see every link twice.
- A form's fields sit side by side by container width (`@lg:` in `form-field.tsx`, the container set in `components/page.tsx`), not by window width, because the same form appears in a wide card and in a narrow one beside a list.
- The sidebar and top bar are fixed, so a full-page screenshot paints them once at the first window height. Capture in a window as tall as the page instead.
- A table turns into a list of labelled records where its card is narrower than its columns need (`components/ui/table.tsx`, the `stacked` utility in `index.css`). The switch is a container query, so it depends on the card's width, not the window's; each table says how wide it needs to be (`stack`), and the cell labels are copied from the column headings after render. A new table with many columns needs its `stack` set, and a check at 1280 wide that it is still a table there: an independent review caught two tables falling to the record form at laptop width.
- A list and the form beside it (`Split`) go side by side by the page's own width for the same reason.
- The sidebar's width and which organizations' pages are folded are kept in the browser's `localStorage` (`lib/stored.ts`), the only thing the console keeps there. It is for layout choices only: never a key, never anything a page loaded. `test-setup.ts` clears it after every test, or one test's collapsed sidebar would hide links from the next.
- Collapsed, the sidebar shows an icon per place. Organizations and teams therefore show the first letter of their name instead of a shared icon: with one icon for all of them a lead with two organizations could not tell them apart.

## How it was checked

`npm run check` in `services/console/frontend`: lint, type-check and 74 tests pass. Every screen was opened in headless Chromium at 1440, 1280, 1024 and 390 wide against a stand-in server sending sample data under the console's real policy header: no policy violations, no page errors, no sideways scroll. It was then run on a local docker-compose stack with real data: signed in as an admin, every admin screen and one organization's and one team's tabs opened with no policy violations, page errors or failed calls. That stack held 138 organizations and the admin's overview listed all of them, which sample data had hidden; the overview now shows eight, those not active first, and says how many there are. The lead's and participant's screens were not walked on the stack, and the end-to-end suite in `tests/` was not rerun (it drives `/web-api/`, which did not change).

# Related Concepts
- [The console's pages are a React application served by console-web, under a policy that allows nothing inline](console-react-front-end.md): The dashboard layout is built on that React front end and keeps its rules: the strict content security policy, field-by-field responses, keys in memory only
