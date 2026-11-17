---
type: Decision
title: "The console's pages are a React application served by console-web, under a policy that allows nothing inline"
description: "console-web serves a React app (shadcn/ui, SSEC tokens) and a field-by-field browser API; the strict CSP rules out Radix dialogs, selects and toast libraries, and keys live in memory only."
tags: [console, frontend, security, csp]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-13T06:08:29Z" }
status: stable
governance: constraint
code_refs:
  - "services/console/console_app/web/app.py"
  - "services/console/console_app/web/api.py"
  - "services/console/console_app/web/shapes.py"
  - "services/console/frontend/src/components/ui/dialog.tsx"
  - "services/console/frontend/src/index.css"
  - "services/console/frontend/package.json"
sources:
  - resource: "owner decisions in the 2026-11-12 session"
  - resource: docs/superpowers/specs/2026-11-12-console-react-frontend-design.md
  - resource: docs/superpowers/plans/2026-11-12-console-react-frontend.md
  - resource: services/console/README.md
---

**Status at d2ac474 (branch `console-react-ui`):** implemented, not yet merged.

On 2026-11-12 the owner asked for the console's pages to be a React application built from shadcn/ui components and styled to the SSEC design system, keeping the Python service. `console-web` still signs people in, keeps sessions and calls the broker; it now serves one built page for every page address (`frontend/`, built into `console_app/web/dist`) and answers that page's calls under `/web-api/` (`console_app/web/api.py`). The Jinja templates and the form routes are gone. Design: `docs/superpowers/specs/2026-11-12-console-react-frontend-design.md`.

Rejected: server-driven pages with the data embedded (a full page load per navigation, and the tests break anyway), React components inside the Jinja pages (keeps the templates), and rewriting the service in TypeScript (the owner chose to keep Python).

## What must stay true

- **The browser gets only what a page shows.** `console_app/web/shapes.py` builds every `/web-api/` response field by field from the broker's reply. `participant_id` never leaves the server: it is the only identity LiteLLM and the request logs see, so a lead must not learn whose it is. Nor do `team_orgs`, `org.mcp_server_id`, or the raw Markdown of the knowledge base. A new broker field stays on the server until it is listed in `shapes.py`; `tests/test_shapes.py` pins the exact fields.
- **The content security policy gets nothing added.** It is `default-src 'none'` plus `'self'` for script, style, font, connect and img (and `data:` for img). No `'unsafe-inline'`, no nonce, no other origin. The reversal of "the pages run no script" was deliberate; loosening further is not.
- **A key is held in memory only.** A new or replacement key comes back in the response to the call that made it and lives in that screen's React state. Not in storage, the address, loader data or the session row.
- **The UI hiding a control is a courtesy.** `policy.py` is not ported to TypeScript; the server checks every call.

## What the policy cost

Found in a real browser, not by the unit tests:

- Radix's Dialog and Select each insert a `<style>` element at run time. Under `style-src 'self'` the browser refuses it: the dialog opened but the page behind was not locked, and a violation was logged. So `frontend/src/components/ui/dialog.tsx` and `alert-dialog.tsx` are the console's own, on the native `<dialog>` element with shadcn's part names, and the provider field is shadcn's `native-select`. `dialog.test.tsx` fails if a dialog adds a style element.
- shadcn's toast (sonner) injects styles the same way, so messages use a small store of the console's own (`lib/notices.ts`).
- Fonts are bundled from `@fontsource-variable` packages, not Google Fonts. No package exists for Encode Sans Compressed; the variable Encode Sans carries a width axis, so the compressed face is that font at 75% (`font-ui`).
- Any shadcn component added later must be opened in a browser against a running console with the developer console showing. jsdom does not enforce the policy.

## Traps

- The root `.gitignore` ignores every `lib/`. `services/console/.gitignore` re-includes `frontend/src/lib/`; a new directory named `lib` elsewhere under the console would be silently left out of commits.
- The design tokens (`frontend/src/styles/ssec-tokens.css`) are a pinned copy from `uw-ssec/uw-ssec.github.io` at `staging` commit d3f017b; the design system is marked alpha. Its `:root` variables share names with Tailwind's theme (`--radius-*`, `--text-*`, `--color-*`), so they override Tailwind's defaults at run time; shadcn's theme is mapped to them in `frontend/src/index.css` with `@theme inline`.
- Browsers compile an input's `pattern` with the `v` flag. The old template's `[a-z0-9][a-z0-9-]{1,30}` was a syntax error under it and silently ignored; the hyphen is now escaped.
- jsdom builds a form's file part without the chosen file's name or content, so the CSV upload is verified only in a browser.
- An organization that does not exist answers 403, not 404: the broker does not reveal existence, and the browser API passes that on.

## How it is checked

- `tests/` (end to end, needs a full stack) drives `/web-api/`, not HTML. It ran against a local docker-compose stack with Keycloak, LiteLLM, Mailpit and the knowledge hub: 255 passed.
- `pixi run ui-check` in `services/console` runs the front end's lint, type-check and 63 tests against a stand-in server.
- No automated browser suite. Each role's flows were walked by script in headless Chromium against that stack, with no policy violations after the dialog fix. That walk is not in the repository.
- The root `verify` gate still excludes `services/console/`, and no workflow builds or tests the console.

**Sources:** owner decisions in the 2026-11-12 session; docs/superpowers/specs/2026-11-12-console-react-frontend-design.md; docs/superpowers/plans/2026-11-12-console-react-frontend.md; services/console/README.md

# Related Concepts
- [The repo is the LiteLLM and MLflow platform and its console; RAG lives in llmoxie-rag](platform-only-scope.md): The console this front end belongs to is in the repo's scope by that decision
