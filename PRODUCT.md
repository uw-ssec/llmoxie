# Product

<!-- impeccable:product-schema 1 -->

This record covers the repository's one user interface, the LLMoxie console
(`services/console/`). The rest of the repository is a command-line tool and
infrastructure code with no interface of its own.

## Platform

web

## Users

Three roles use the console, each signed in through the identity provider:

- **Organization leads** are the primary users, confirmed by the owner on
  2026-11-13. A lead runs one or more organizations day to day: adds models and
  their provider keys, creates teams, sets team budgets, invites participants,
  approves requests, rotates or revokes keys, and reads per-person usage totals
  and the organization's knowledge base.
- **SSEC admins** govern every organization: create them, set budget ceilings,
  appoint and remove leads, suspend or remove an organization, connect outside
  services to a team, and read the audit log and the data-protection log.
- **Participants** are the largest group and visit least: accept a team's terms,
  create and rotate their own API keys, copy the connection details, and see
  their own usage.

## Product Purpose

The console lets organizations run their own use of a shared LiteLLM gateway so
that LiteLLM itself stays internal. Nobody outside the admins touches LiteLLM's
own interface or management API. Success is a lead who can set up a team, keep
its spending inside a budget and hand out keys without asking an admin, and a
participant who gets from an invitation email to a working key in one visit.

## Positioning

Delegated administration with the least disclosure that still works: each role
sees and changes only its own scope, a key is shown once to its owner and to
nobody else, and prompts and responses are never shown anywhere in the console.

## Operating Context

- A desktop browser, at a desk, between other work. Leads come to do one thing
  (invite people, raise a budget, rotate a key) and leave.
- Organizations are research groups and courses. Budgets are in US dollars.
- Participants connect coding tools and MCP clients with a base URL, a model
  name and a key copied from the console.
- The console is one of several services; LiteLLM, the identity provider,
  Postgres, mail and the knowledge hub are deployed separately.

## Capabilities and Constraints

- Screens: sign-in, invitation, overview, organizations (admin), an
  organization, its knowledge base and graph, a team for its lead, a team for a
  participant, the audit log, the data-protection log.
- The browser is given only what a page shows. Every `/web-api/` response is
  built field by field on the server; a participant's gateway identity never
  reaches a lead's browser.
- The content security policy allows nothing inline and nothing from another
  origin. A component that inserts a `<style>` element at run time is refused,
  which rules out Radix dialogs, selects, sheets and most toast and chart
  libraries as shipped. Fonts are bundled.
- A new or replacement key lives in one screen's memory only: not in storage,
  the address, or loaded page data.
- Hiding a control is a courtesy; the server checks every call.
- Light theme only, by decision.
- **Undecided:** analytics. Time series, charts and trends do not exist yet in
  the browser API. Until they do, screens show only figures the console already
  has, and no chart or chart placeholder is drawn (owner, 2026-11-13).

## Brand Commitments

- The name is "LLMoxie console".
- The console is styled to the SSEC design system (University of Washington
  Scientific Software Engineering Center), from a pinned copy of its tokens at
  `services/console/frontend/src/styles/ssec-tokens.css`. That system is
  UW-brand compliant and is marked alpha upstream.
- Binding reference for layout, given by the owner on 2026-11-13: a dashboard in
  the manner of <https://dashboard.shadcnspace.com/> (sidebar, top bar, stat
  cards, cards in a grid), inside the SSEC design, with every current function
  kept.
- Voice: plain sentences that say what happens and what cannot be undone. No
  marketing language.

## Evidence on Hand

- Real data per screen from the browser API: organizations with ceilings and
  counts, teams with budgets and member counts, models, keys with spend, usage
  totals per person (requests, failed, tokens, spend), audit events,
  data-protection totals and events, knowledge concepts and their graph.
- No time series, no rates of change, no comparisons with an earlier period.
  Future work must not invent them.

## Product Principles

1. **Show only what is true now.** A figure on screen is one the server sent. No
   sample data, no trend arrows without a trend.
2. **The lead's task first.** Layout choices favour the person running a team;
   admins and participants use the same patterns.
3. **Say what an action does before it does it.** Anything that deletes keys or
   cannot be undone says so, in the place the button is.
4. **Least disclosure.** A redesign never moves a figure or a name to a screen
   whose role could not already see it.
5. **One system.** The same shell, the same card, the same table on every
   screen, so the second screen costs nothing to learn.

## Accessibility & Inclusion

WCAG 2.2 AA, as the SSEC design system requires: its verified colour pairs,
sequential headings, visible focus (the UW focus ring), and reduced motion
honoured.
