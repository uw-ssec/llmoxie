# Console React Front End Design

- **Date:** 2026-11-12
- **Status:** Approved by the owner, 2026-11-12
- **Scope:** `services/console/`, the `console-web` service only

## Goal

`console-web` keeps doing everything it does on the server, and its pages are
drawn by a React application built from [shadcn/ui](https://ui.shadcn.com/)
components and styled to the
[SSEC design system](https://github.com/uw-ssec/uw-ssec.github.io/blob/staging/design-system/DESIGN.md).
The owner asked for this stack and this look. No further reason was given, so
this document does not claim one.

## Context

- `console-web` (`console_app/web/app.py`, 678 lines of FastAPI) is more than
  pages. It holds the OIDC client secret, runs sign-in (authorization code with
  PKCE), keeps sessions in Postgres so tokens never reach the browser, checks a
  per-session CSRF token and the `Origin` header on every post, applies
  `console_app/policy.py` before calling the broker, and serves `/api/v1/*` for
  connected services such as JupyterHub.
- The pages are 15 Jinja templates and one stylesheet (about 780 lines). Every
  action is a form post that ends in a redirect with a flash message.
- The pages run no script. The content security policy is
  `default-src 'none'; style-src 'self'; img-src 'self'; ...`, and the README
  lists "the console's pages run no script" as a design point. This change
  reverses that point on purpose.
- A new or rotated API key is rendered straight into the response to the post
  that made it and is never stored. That property must survive.
- The knowledge page renders Markdown that members wrote. `web/markdown.py`
  sanitizes it on the server, and `web/graph.py` computes the graph layout on
  the server and hands the template coordinates to draw.
- The end-to-end suite in `tests/` (about 1,900 lines) signs in through Keycloak
  and drives the console by posting forms and reading the returned HTML.
- The SSEC website that owns the design system is Vite, React 19, React Router 7
  and Tailwind 4. The design system ships its tokens as `01-tokens.css` beside
  `DESIGN.md`. It defines seven components for a marketing site (button, card,
  input, navigation bar, section divider, code block, stat counter). It has no
  table, dialog, badge, alert, checkbox, select or toast.
- The root `.pre-commit-config.yaml` excludes `services/console/`, and no
  workflow in this repository builds or tests the console.
- A local stack that runs the console with Keycloak, LiteLLM, Mailpit and the
  knowledge hub exists at `~/Agent-Workspace/litellm-keycloak` (docker-compose,
  Traefik on `*.localhost:8000`). It builds its own older copy of the console
  from `./console`, which still has the agents feature this repository removed.
  The owner offered it for testing this work.

## Goals

- Every screen and every action the console has today exists in the React
  application, at the same URL.
- The look follows the SSEC design system: its colours, its three font families,
  sharp-cornered buttons, its navigation bar and its code block.
- The security properties in [Security](#security) hold.
- The end-to-end suite covers the same behaviour as today and passes against the
  local stack.

## Non-goals

- Redesigning any flow. This is a port of the existing screens.
- Changing the broker, `policy.py`, the database schema, or `/api/v1/*`.
- Porting the policy module to TypeScript.
- A dark theme.
- Server-side rendering of React.
- An automated browser test suite (Playwright or similar).
- A CI workflow for the console, or bringing the console's Python under the root
  pre-commit hooks.

## Anti-goals

These would make the result a failure even if it works:

- A token, the OIDC client secret or the broker caller secret reaching the
  browser.
- An API key that can be read again after it was first shown, including from
  `localStorage`, `sessionStorage`, a cache, or the session row.
- `'unsafe-inline'`, `'unsafe-eval'` or any third-party origin in the content
  security policy. If a component cannot work without one, use a different
  component.
- The interface being the only thing that stops an action. Hiding a button is a
  courtesy. The server checks stay.
- Breaking UW brand rules the design system states: rounded buttons, or teal,
  green, pink or spirit-gold as text on white.

## Approaches

**A. Single-page application with a JSON API (chosen).** Each page route returns
JSON, each form post becomes a JSON call, and a React application built to
static files is served by FastAPI. Cost: every route in `app.py` changes its
response shape and the end-to-end tests are rewritten against JSON.

**B. Server-driven pages.** The Python routes stay as they are. A GET returns a
shell with that page's data embedded, forms still post and redirect, and React
renders from the embedded data. Cost: a full page load on every navigation,
plain browser form posts so shadcn's form handling adds little, and the tests
still break because the text they look for moves into embedded data.

**C. React components mounted inside the Jinja pages.** Dropped: it keeps the
templates the owner asked to replace.

**D. Replace the whole service in TypeScript.** Ruled out by the owner, who
chose to keep the Python service.

The owner chose A. It gives an ordinary React application on the same stack as
the SSEC site, keeps every secret on the server, and leaves the tests simpler
than scraping HTML.

## Design

### What the server keeps

Unchanged in behaviour: `GET /healthz`, `POST /api/v1/enroll`,
`POST /api/v1/key`, `POST /api/v1/key/revoke`, the session store, the cookies
(`__Host-Http-console`, Secure, HttpOnly, SameSite=Strict), the `Origin` check
on posts, token refresh, the policy check before each broker call, and the
broker client.

Four routes stay as plain browser navigations, not `fetch` calls, because each
ends in a redirect to Keycloak on another origin:

| Route                 | Stays as                                                                                    |
| --------------------- | ------------------------------------------------------------------------------------------- |
| `POST /login`         | A form post from the sign-in screen, carrying `next`                                        |
| `GET /auth/callback`  | Sets the session cookie and returns the small "Signed in" page that forwards to the target  |
| `POST /logout`        | A form post carrying the CSRF token                                                         |
| `POST /invite/{token}`| A form post from the invitation screen; signs in first when there is no session            |

The "Signed in" page stays a server-built page with a `meta refresh`, for the
reason the code already gives: the Strict session cookie is only sent once a
navigation starts from this site. It is the only HTML the server still writes.
A failed sign-in redirects to `/?signin=failed` and the application shows the
message.

### The browser API

A new JSON API for the application lives under `/web-api/`. It is for the
console's own pages only and reads the session cookie. `/api/v1/` stays the API
for connected services and reads no cookie.

`GET /web-api/session` never answers 401, so the application can decide between
the sign-in screen and the rest:

```json
{ "signed_in": false }
```

```json
{
  "signed_in": true,
  "csrf": "<per-session token>",
  "me": { "...": "what the broker's /me returns" },
  "config": { "gateway_url": "...", "litellm_admin_url": "..." }
}
```

Page data, one GET per screen:

| Call                                           | Screen                    |
| ---------------------------------------------- | ------------------------- |
| `GET /web-api/admin/orgs`                      | Organizations             |
| `GET /web-api/admin/audit`                     | Audit log                 |
| `GET /web-api/admin/dlp`                       | Data protection           |
| `GET /web-api/orgs/{org_id}`                   | Organization              |
| `GET /web-api/orgs/{org_id}/knowledge`         | Knowledge                 |
| `GET /web-api/teams/{team_id}/manage`          | Team, as lead or admin (includes usage) |
| `GET /web-api/teams/{team_id}`                 | Team, as participant      |
| `GET /web-api/invites/{token}`                 | Invitation (no session needed) |

**Each response carries only the fields its page shows today.** The broker's
replies hold more than the templates render, and passing them through would send
that data to the browser for the first time. So every page call and every action
has an explicit response shape, built in `console-web` from the broker's reply.
Known fields that must stay on the server:

- `participant_id`, anywhere. Today a lead sees people by email only. The
  console's design makes `participant_id` the only identity LiteLLM and the
  request logs see, so a lead must not get the mapping from email to it.
- `person_id` and the `team_orgs` map from `/me`, except where an action's URL
  already needs a person's id (removing a member or a lead).
- `org.mcp_server_id` and any other column the organization page does not show.
- The raw Markdown of concepts and the raw change log.

The knowledge call is shaped around the selected concept, as the page is today:
`GET /web-api/orgs/{org_id}/knowledge?concept=<id>` returns the concept list
without bodies, the sanitized HTML of the selected concept only, its links in
and out, the graph coordinates, and the sanitized change log.

Actions mirror today's post routes one for one under `/web-api/`, with a JSON
body instead of form fields and the CSRF token in an `X-CSRF-Token` header. Each
returns the message the flash would have carried, the broker's result, and a
`goto` path when today's handler redirects somewhere other than back:

```json
{ "message": "Created Astro Lab.", "goto": "/orgs/3f2a" }
```

Two exceptions to "JSON body":

- Inviting people stays `multipart/form-data`, because it takes a CSV upload
  that the server parses (`_emails_from`) and caps at 200 KB.
- Creating or rotating a key returns the key in the response body. That response
  is the only place it ever appears.

Errors share one shape and keep today's status codes and wording:

```json
{ "error": { "status": 409, "message": "That short name is taken." } }
```

| Status      | Meaning today                                       | What the application does            |
| ----------- | --------------------------------------------------- | ------------------------------------ |
| 401         | No session, or it could not be refreshed            | Goes to `/` with `next` set          |
| 403         | Policy or CSRF refusal                              | Shows the message                    |
| 404         | Not found                                           | Shows the not-found screen           |
| 409, 422    | A refusal the user can fix; the broker's `detail`   | Shows the message next to the form   |
| 502         | The broker failed                                   | Shows "Nothing was changed."         |

Server-side flash storage in the session goes away, since messages now come back
in the response.

### The application shell

Every page URL that exists today (`/`, `/admin`, `/admin/audit`, `/admin/dlp`,
`/orgs/{id}`, `/orgs/{id}/knowledge`, `/teams/{id}`, `/teams/{id}/manage`,
`/invite/{token}`, `/invite-result/{outcome}`) returns the same built
`index.html`. The application's router decides what to show. Built assets are
served from a static path with hashed file names.

The rule in today's `GET /` moves to the application: no session shows the
sign-in screen; no roles shows "You are not invited yet"; a participant with
exactly one team goes straight to it; everyone else sees the home screen.

### Security

- **Content security policy:**
  `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self' <identity provider origin>`.
  The other response headers stay as they are.
- **CSRF:** the token comes from `/web-api/session`, is held in memory, and goes
  in a header on every post. The server compares it in constant time, as now.
- **Keys:** a created or rotated key is held in React state for the screen that
  shows it and nowhere else. Navigating away or reloading loses it. Responses
  keep `Cache-Control: no-store`.
- **Knowledge page:** Python still sanitizes the Markdown and returns HTML, which
  the page inserts as is. The graph endpoint returns the node and line
  coordinates `graph.py` computes, and React draws the SVG. The policy above is
  the second line of defence if sanitizing ever fails.
- **Fonts:** bundled with the application. The SSEC site loads them from Google
  Fonts; the console must keep talking to no other site.
- **No new data in the browser:** responses are built field by field, as
  described under [The browser API](#the-browser-api). The port must not widen
  what any role can read.
- **Visibility:** the API returns the flags the templates already used
  (`is_admin`, `is_lead`, team and organization status). React uses them to hide
  controls. The server still refuses what the policy refuses.

### Front end

Location: `services/console/frontend/`. Stack: Vite, React 19, TypeScript,
React Router 7 and Tailwind 4, matching the SSEC site, with shadcn/ui components
copied into the source tree as shadcn intends.

Design system mapping:

- Vendor `01-tokens.css` from `uw-ssec.github.io` at `staging` commit `d3f017b`
  (2026-09-11), with the source and commit noted in the file. The design system
  is marked `version: alpha`, so the copy is pinned on purpose.
- Point shadcn's theme variables at those tokens: primary is purple-700, hover
  purple-900, destructive is the `error` red, borders and focus ring as
  `DESIGN.md` gives them.
- Buttons have no corner radius, uppercase Encode Sans Compressed text and the
  UW focus ring. Cards, inputs and code blocks use the 8px radius.
- Headings use Encode Sans, reading text Open Sans at 16px minimum, labels and
  navigation Encode Sans Compressed, code JetBrains Mono.
- The navigation bar follows the design system's own: purple-900, gold-200
  links, a 2px teal underline on the active link.
- API keys, the base URL and the MCP URL are shown in the design system's code
  block (purple-950 with teal mono text).
- Teal appears only in the active navigation underline and in code blocks, which
  keeps accents under the 15% cap.
- The hero, stat counter, angled section dividers and signature animations are
  not used. They belong to the marketing site.
- Components the design system lacks (table, dialog, badge, alert, checkbox,
  select, textarea, tabs if used) are shadcn's, themed from the same tokens.

Screens, each a port of one template:

| Screen                  | Today's template     | Notable parts                                                                 |
| ----------------------- | -------------------- | ----------------------------------------------------------------------------- |
| Sign in                 | `login.html`         | One button; a plain form post                                                 |
| Home                    | `home.html`          | Organizations you lead, your teams, admin links                               |
| Not invited             | `not_invited.html`   | Message only                                                                  |
| Invitation              | `invite.html`        | Public; one button; a plain form post                                         |
| Invitation result       | `invite_result.html` | Waiting for approval, or cannot be used                                       |
| Organizations (admin)   | `admin.html`         | Table, new organization form                                                  |
| Audit log (admin)       | `audit.html`         | Table                                                                         |
| Data protection (admin) | `dlp.html`           | Totals table, latest events table                                             |
| Organization            | `org.html`           | Admin controls, leads, models, teams, add-model and new-team forms            |
| Knowledge               | `knowledge.html`     | Concept text, graph, concept table, change log                                |
| Team (lead or admin)    | `team_manage.html`   | Budget, models, people, invitations with CSV, keys, usage, archive, connected services, remove team |
| Team (participant)      | `my_team.html`       | Terms and consent, keys, how to connect, usage                                |
| Error and not found     | `error.html`         | Message and a way back                                                        |

Behaviour that changes shape:

- Flash messages become toasts, or an inline alert next to the form for a 409 or
  422.
- After an action succeeds, the screen reloads its data, which is what the
  redirect did.
- Removing an organization or a team keeps its type-the-name confirmation, now
  in a dialog. Other destructive actions (revoke, remove, archive, delete) get a
  confirm dialog where today's form had none only if the builder judges it
  needed; the server behaviour does not change either way.
- A new key is shown in a panel at the top of the participant's team screen with
  a copy button, and the text "Copy it now. It will not be shown again."

### Packaging

- The Dockerfile gains a Node build stage, pinned by digest like the Python base
  image, that runs `npm ci` and the build. The `app` stage copies the built
  files in. The image still runs all three services.
- The console's `pixi.toml` gains `nodejs` and tasks to install, run, check and
  build the front end, so the toolchain still comes from Pixi. JavaScript
  packages come from npm with a committed `package-lock.json`.
- `Jinja2` leaves `requirements.txt` if nothing uses it afterwards.
  `python-multipart` stays for the CSV upload.
- `.dockerignore` and `.gitignore` learn about `node_modules` and the build
  output. The build output is not committed.

### Testing and verification

1. **Baseline first.** Before changing anything, run the current suite from this
   repository against the local stack, so what passes today is known.
2. **End-to-end suite.** `tests/helpers.py` keeps its Keycloak sign-in walk and
   gains JSON calls; the CSRF token comes from `/web-api/session`. Each test
   keeps what it proves and moves its assertions from HTML text to JSON fields.
   Assertions of the form "this button is not on the page" become "this flag is
   false and the post is refused". The assertions that a lead's data never
   contains a key stay. New assertions check that the fields listed under
   [The browser API](#the-browser-api) are absent from the responses, and that a
   concept's text appears only once it is selected.
3. **Front-end tests.** Vitest and Testing Library for the parts with logic: the
   API client's error mapping, the key shown once and lost on leaving, the
   type-the-name dialogs, and role-based visibility.
4. **In a browser.** Before the work is called done, each role's main flow is
   driven in a real browser against the stack, with the console open, to confirm
   nothing is blocked by the content security policy.
5. **Repository gate.** `pixi run -e llmaven verify` stays green. The front end
   has its own lint, type-check, test and build commands.

Using the local stack:

- Point it at this repository's console with a compose override file passed on
  the command line. Do not edit or commit in that repository.
- Its schema file (`postgres/20-console-db.sql`) is this repository's
  `db/console-db.sql` plus one `agent` table with its index, grant and row-level
  security entry. Every table this console uses is the same, so run against the
  stack's existing database as it is; the extra table goes unused. The suite
  creates organizations, teams and accounts with a random suffix and leaves them
  there, as that stack's own suite does.
- Check the live database against the schema file once the stack is up, since
  the volume may differ from the file.
- Stop and ask the owner before anything that changes that stack beyond test
  data: recreating a volume (`docker-compose down -v` deletes its data),
  creating a second database in its Postgres, or editing its files.

### Documentation

- `services/console/README.md`: the service table, the design point about pages
  running no script, the getting-started steps, and the tests section.
- Root `knowledge/`: record through `okf` that the console's pages are now a
  React application, what the content security policy allows, and why the key
  is held in memory only.

## Left to the builder

- The exact path prefix, if `/web-api/` collides with anything.
- How the application fetches and reloads data: React Router's loaders and
  actions, or a small fetch layer. Prefer not adding a data library.
- Whether shadcn's toast (sonner) works under `style-src 'self'`. If it injects
  styles at run time, use an inline alert.
- Which font packages to bundle, provided all four families are self-hosted.
- Table density: whether dense tables use the 14px `body-small` size.
- How the Vite dev server reaches a running `console-web`, given the `Origin`
  check and the Secure cookie.
- Where the build output lands inside the image and how FastAPI serves it.
- File and component structure inside `frontend/`.

## Calls made in this document

These were decided while writing, not by the owner. Each is easy to reverse.

- The browser API returns only the fields each page shows today, not the
  broker's full replies. This adds an explicit response shape for about 8 page
  calls and 25 actions, and is the larger of the two ways to build it.
- The local stack's existing database is used as it is, extra `agent` table and
  all.
- The screens are ported one for one, with no flow changes.
- Light theme only.
- Fonts are bundled, not loaded from Google Fonts.
- The marketing-site parts of the design system are left out.
- The design tokens are vendored as a pinned copy.
- No automated browser suite in this round.
- npm is used for JavaScript packages, with Node itself from Pixi. `AGENTS.md`
  bans `pip`, `conda` and `venv` by name and says nothing about npm.
- The work happens on a new branch stacked on `llmoxie-console`.
