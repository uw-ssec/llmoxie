---
type: Decision
title: "The console's design direction, what the design review settled, and what it left open"
description: "The direction the dashboard was built to, the eight findings and two regressions an independent review raised and how each was settled, the gaps knowingly left, and why .impeccable/ is ignored."
tags: [console, frontend, design]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T19:31:09Z" }
status: stable
code_refs: [DESIGN.md, PRODUCT.md, .gitignore]
sources:
  - resource: owner decisions in the 2026-11-13 session
  - resource: DESIGN.md
  - resource: PRODUCT.md
---

The dashboard (see the related concept) was designed on 2026-11-13 with the Impeccable design skill. The skill keeps its working files in `.impeccable/`: the brief the build was held to, a token file that goes with `DESIGN.md`, and review screenshots. On 2026-11-13 the owner decided to ignore that directory in git and keep what mattered here. `DESIGN.md` is the authority for the look and `PRODUCT.md` for who the console is for; this concept holds the rest.

## The direction the build was held to

- **A working tool, tuned for organization leads.** Admins and participants use the same shell and patterns.
- **One shell for three roles, in which every figure is one the server sent.** It refuses the dashboard kit's habits: sample charts, trend chips, four identical tiles. Figures sit in one divided strip, and a lead's teams are the first thing on the overview.
- **The SSEC system as shipped**: purple sidebar, warm gold ground under white cards, square buttons, Encode Sans headings, the compressed uppercase label style, JetBrains Mono for anything typed.
- **The signature is the 2px teal line that marks where you are**: under the current sidebar item, under the open tab, and as the loading line under the top bar. Teal on white is 1.88:1, too faint to see alone, so the loading line runs along a purple track and a tab also changes its text colour.
- **Order on a screen**: title, then the strip of figures, then tabs, then cards.
- **The form that adds to a list sits in its own card beside that list; nothing is hidden behind a button.** One exception: naming a new key is a single field and stays under the participant's list of keys.
- **The layout reference the owner named** (dashboard.shadcnspace.com) pins the idiom: sidebar, top bar, figures, cards in a grid. It does not pin the look. Because the owner pinned the composition, the skill's randomised concept roll was not run, so no seed reference exists; the skill's reviewer keeps that listed as an open process item.

## What the independent review found (three passes, 2026-11-13)

All of these are resolved in the code; they are kept because each is easy to reintroduce.

1. On a phone, tables clipped inside their cards with no cue: columns and row buttons were off screen. Tables now become labelled records by container width.
2. The open tab's teal line rendered at 1px, not 2px: the tab row scrolls sideways, and its overflow clipped a line drawn 1px below it. The row's baseline is now an inset shadow and the 2px line sits inside the box.
3. The lead's overview was a stack of full-width cards, with figures 500 to 800px from the names they belong to. The cards now sit in a grid and the team tables share fixed columns.
4. On a phone the knowledge graph showed its left part and hid the open concept's dot. Its scroller now centres on that dot.
5. Two add-forms sat inside their list's card. "Connect a service" moved to its own card; the new-key field became the named exception.
6. A breadcrumb of one step only repeated the page's title, and a lead's trail had no root. Every trail starts at Overview and a one-step trail is not shown.
7. One figure had two names ("1 archived" on one screen, "1 not active" on another). One helper now writes the status word itself.
8. The first fix for item 1 set the thresholds too high: at 1280 wide the keys and organizations tables fell to the record form, losing row-to-row comparison at the width people work at. Check 1280 whenever a table or its threshold changes.
9. As records, the audit log on a phone ran 213px an entry and broke addresses mid-word. A long log now uses a compact form: its time on one line, the rest running on with no headings.

The reviewer could not see hover, empty, error and loading states: no screenshot showed them.

## Knowingly left open

- Row buttons (Remove, Rotate, Revoke, Delete) are under the SSEC 44px touch size on a phone.
- The file picker for a CSV of invitations is the browser's default control.
- Text in tables and cards is 14 to 15px; the SSEC body minimum is 16px.
- Spend and budget are shown as two figures and never as "left" or "over": the period a budget covers is not in the browser API.
- No dark theme, by decision.
- Card, notice and dialog shadows compile to Tailwind's built-in scale, not the SSEC `--shadow-*` tokens; the values are close.
- The textarea and the input differ in padding and ground. The theme maps `good-surface`, `caution` and `caution-surface`, and the button has `secondary` and `link` variants, that no screen uses.
- The name "The Working Ledger" in `DESIGN.md` was proposed by the agent that wrote the file. The owner has not confirmed it.

## Open requests from the owner

- **Analytics**: where time series and charts go once the browser API has them.
- Done since: on 2026-11-14 the owner asked for the sidebar to collapse and for the pages under an organization to fold. Both are built; `DESIGN.md` describes them.
- **A boxed login** in the manner of dashboard.shadcnspace.com/auth/auth2/login, "using Keycloak under the hood" (asked 2026-11-13, not started). The undecided point: whether the username and password fields live on Keycloak's own page, restyled with a login theme, or on the console's page. The second means console-web handles passwords through the password grant, which reverses the rule that it holds no credential and loses MFA, single sign-on and federated sign-in. I recommended the theme; the owner has not answered.

## About `.impeccable/`

- It is ignored, so a fresh clone has no brief and no token file. The skill writes a new brief on the next design task and regenerates the token file from `DESIGN.md` with its `document` command.
- While it was tracked, the repository's prettier hook reflowed the brief's frontmatter and the skill could no longer read its list of related files. Ignoring the directory ends that.
- The screens were captured from a stand-in server that sent sample data under the console's real policy header, at 1440, 1280, 1024 and 390 wide. Neither that server nor the capture script is in the repository.

# Related Concepts
- [The console is a sidebar dashboard that shows only figures the server sent, with no charts until analytics exist](console-dashboard-layout.md): The direction and review behind the dashboard layout that concept describes
