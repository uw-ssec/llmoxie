# llmoxie-console

The LLMoxie console lets organizations run their own use of a shared
[LiteLLM](https://github.com/BerriAI/litellm) gateway, so that LiteLLM itself
can stay internal. An SSEC admin creates an organization and invites its leads;
a lead adds models, sets up teams and invites participants; a participant
accepts the team's terms and creates API keys. Nobody outside the admins touches
LiteLLM's own UI or management API.

It follows the
[LLMoxie console design](https://github.com/uw-ssec/llmoxie/blob/docs/azure-console-design/docs/superpowers/specs/2026-11-06-azure-console-design.md).
This repository holds the console's code, its database schema, its image and its
test suite. The services it works with (LiteLLM, an identity provider, Postgres,
a reverse proxy, mail) are deployed separately; what the console expects of them
is listed under [What the console needs](#what-the-console-needs).

## What is in the image

One image runs three services; the command picks which.

| Service          | Command                                                         | Role                                                                                                                                                                                                               |
| ---------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `console-web`    | `uvicorn console_app.web.app:app --host 0.0.0.0 --port 8200`    | Public pages. Signs people in (authorization code + PKCE), keeps sessions, turns forms into broker calls. Holds no LiteLLM credential; its database role can read only its session table.                          |
| `console-broker` | `uvicorn console_app.broker.app:app --host 0.0.0.0 --port 8100` | Internal. Holds the LiteLLM admin key and all organization data. Offers fixed operations only (`console_app/broker/app.py`), each building its LiteLLM request from a template in `console_app/broker/litellm.py`. |
| `console-init`   | `python init_admin_key.py`                                      | One-shot. Creates the broker's key as a `proxy_admin` user's key and writes it to a file the broker reads, so the broker never has the master key.                                                                 |

Each service answers `GET /healthz`.

Who may do what is decided in one module, `console_app/policy.py`, deny by
default. Three layers apply it:

- `console-web` checks before calling the broker.
- The broker checks again. It does not trust `console-web` about who is signed
  in: every call carries the user's short-lived access token, which the broker
  verifies against the identity provider's keys. The organization a team belongs
  to is always looked up in the database, never taken from the request.
- Postgres row-level security: the broker opens each transaction for one
  organization, and then sees only that organization's rows.

## Getting started

This project uses [Pixi](https://pixi.sh) for its development environment and
tasks, and the `docker` CLI to build and test the image.

```bash
pixi install            # the development environment (pre-commit, gh, okf)
pixi run image          # build llmoxie-console:dev
pixi run pre-commit-all # the checks every change must pass
```

For first-time setup, `pixi run -e onboard onboard` installs the pre-commit
hooks and runs the SSEC onboarding. The repository also ships a
[`.devcontainer/`](.devcontainer/) configuration for GitHub Codespaces and VS
Code Dev Containers.

The image installs the locked versions in `requirements.txt`; the test image
adds `requirements-test.txt`.

## What the console needs

| Piece             | What the console expects                                                                                                                                                                                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LiteLLM           | Reachable by the broker and `console-init` at `LITELLM_URL`, with `store_model_in_db: true` so that models can be added through its API. Only `console-init` is given the master key.                                                                                                                               |
| Postgres          | A database `console_db` with the roles `console_web` and `console_broker`, created by [`db/console-db.sql`](db/console-db.sql). Neither role can connect to LiteLLM's database.                                                                                                                                     |
| Identity provider | Keycloak. A confidential client for `console-web` (standard flow, PKCE `S256`, redirect URI `<console URL>/auth/callback`) with an audience mapper that adds `console-broker` to the access token. Email is used only when the provider has verified it.                                                            |
| Knowledge hub     | An [okf-hub](https://github.com/bitbarrelllc/okf-memory-rs) that checks the same provider's tokens, reads the organization from the claim `okf_org`, lets a token write only the bundle named after that organization (`orgs/oidc-<short name>`), and lets the role `knowledge-reader` read every bundle.           |
| Two more clients  | `console-provisioner`: a service account with the `manage-clients` role of `realm-management`, which the broker uses to create one client per organization. `console-knowledge`: a service account with the realm role `knowledge-reader`, the hub as audience, and a hardcoded claim `okf_org` = `console_reader`. |
| Reverse proxy     | Serves `console-web` at `CONSOLE_PUBLIC_URL` over https or on a `*.localhost` name (the session cookie is Secure), and LiteLLM's AI paths and `/mcp`, and nothing else of LiteLLM, at `GATEWAY_PUBLIC_URL`. The broker is not public.                                                                               |
| Mail              | An SMTP server for invitations and key-rotation notices.                                                                                                                                                                                                                                                            |
| Shared volume     | One volume mounted at the directory of `LITELLM_ADMIN_KEY_FILE`: writable for `console-init`, read-only for the broker. The image's user (uid 10001) owns `/run/console` for this.                                                                                                                                  |

## Configuration

Every setting is an environment variable. Those without a default are required.

### console-web

| Variable                       | Meaning                                                            |
| ------------------------------ | ------------------------------------------------------------------ |
| `CONSOLE_WEB_DATABASE_URL`     | `console_db` as the role `console_web`                             |
| `CONSOLE_BROKER_URL`           | Where the broker listens, for example `http://console-broker:8100` |
| `CONSOLE_BROKER_CALLER_SECRET` | Shared with the broker; shows a call comes from `console-web`      |
| `CONSOLE_PUBLIC_URL`           | The console's address as browsers see it                           |
| `GATEWAY_PUBLIC_URL`           | The gateway's address, shown to participants as their base URL     |
| `LITELLM_ADMIN_URL`            | Optional. LiteLLM's own UI, linked for admins when set             |
| `OIDC_ISSUER`                  | The issuer in the provider's tokens                                |
| `OIDC_CLIENT_ID`               | The console's client                                               |
| `OIDC_CLIENT_SECRET`           | Its secret                                                         |
| `OIDC_AUTH_URL`                | Authorization endpoint, as the browser reaches it                  |
| `OIDC_TOKEN_URL`               | Token endpoint, as this service reaches it                         |
| `OIDC_JWKS_URL`                | Signing keys, as this service reaches them                         |
| `OIDC_LOGOUT_URL`              | End-session endpoint, as the browser reaches it                    |

### console-broker

| Variable                                                               | Default                     | Meaning                                                                                                   |
| ---------------------------------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------------------------------- |
| `CONSOLE_BROKER_DATABASE_URL`                                          |                             | `console_db` as the role `console_broker`                                                                 |
| `CONSOLE_BROKER_CALLER_SECRET`                                         |                             | The same value as in `console-web`                                                                        |
| `CONSOLE_PUBLIC_URL`                                                   |                             | Used in the links of invitation emails                                                                    |
| `CONSOLE_ADMIN_SUBJECTS`                                               | none                        | The first SSEC admins: the provider's user ids, comma-separated                                           |
| `CONSOLE_INVITE_TTL_HOURS`                                             | `72`                        | How long an invitation works                                                                              |
| `LITELLM_URL`                                                          |                             | LiteLLM, internally                                                                                       |
| `LITELLM_ADMIN_KEY_FILE`                                               |                             | The file `console-init` wrote                                                                             |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_JWKS_URL`                       |                             | As for `console-web`; the broker verifies every user token itself                                         |
| `SMTP_HOST`                                                            |                             | The SMTP server                                                                                           |
| `SMTP_PORT`                                                            | `25`                        | Its port                                                                                                  |
| `MAIL_FROM`                                                            | `console@llmoxie.localhost` | The sender of the console's mail                                                                          |
| `KEYCLOAK_ADMIN_URL`                                                   |                             | `<keycloak>/admin/realms/<realm>`                                                                         |
| `KEYCLOAK_TOKEN_URL`                                                   |                             | The realm's token endpoint; LiteLLM fetches each organization's token here too                            |
| `KEYCLOAK_PROVISIONER_CLIENT_ID`, `KEYCLOAK_PROVISIONER_CLIENT_SECRET` |                             | The client that creates each organization's client                                                        |
| `KNOWLEDGE_HUB_URL`                                                    |                             | The hub, as LiteLLM reaches it; also the audience the hub expects                                         |
| `KNOWLEDGE_READER_CLIENT_ID`, `KNOWLEDGE_READER_CLIENT_SECRET`         |                             | The client the broker reads the hub with, for the leads' knowledge page                                   |
| `CONSOLE_DLP_AUDIT_FILE`                                               | none                        | The audit log ceil-dlp writes, mounted read-only; without it the Data protection page has nothing to show |
| `CONSOLE_ENABLE_MOCK_PROVIDER`                                         | `false`                     | Development only: a provider `mock` that answers without a real provider key                              |
| `CONSOLE_LMSTUDIO_URL`                                                 | none                        | Development only: a provider `lmstudio` for models an LM Studio server offers at this URL                 |

### console-init

| Variable                 | Meaning                                                  |
| ------------------------ | -------------------------------------------------------- |
| `LITELLM_URL`            | LiteLLM, internally                                      |
| `LITELLM_MASTER_KEY`     | Used once, to create the broker's key; never written out |
| `LITELLM_ADMIN_KEY_FILE` | Where to write the broker's key                          |

It does nothing if the file already holds a working key, so it can run on every
start.

## Using the console

1. An SSEC admin signs in, creates an organization and invites a lead by email.
2. The lead accepts the invitation, signing in or registering with the invited
   address.
3. The lead adds a model with the organization's provider key, creates a team,
   ticks the model for the team, and invites participants by typing addresses or
   uploading a CSV with an `email` column.
4. A participant accepts the invitation and the team's terms, creates a key, and
   calls `<gateway>/v1/chat/completions` with the model
   `<org short name>/<model>`.
5. The lead watches usage, removes people, and archives the team when it is
   done.

A lead can remove a member from a team, or cancel an invitation that has not
been accepted, on the team's page. The admin can open any team from its
organization's page and remove a member too, but cannot run the team. The admin
can remove a single team after typing its name: its keys are deleted, its
members lose it and it leaves the console, while the organization and its models
stay. The admin can remove a whole organization after typing its short name:
that deletes every key, archives every team, removes its models and provider
keys, and ends everyone's access to it, while records and logs are kept. The
admin can also remove a lead from an organization, or cancel a lead invitation
that has not been accepted; the lead's account and the teams they set up stay.

Signing in with a different address than the invited one grants nothing; the
lead (or, for a lead invitation, the admin) sees the request and approves or
rejects it.

## Connecting a service (JupyterHub and the like)

A service that signs its users in through the same identity provider can fetch
each user's API key and put it into that user's environment, with no copy and
paste. It uses three calls on the console's public address:

| Call                      | What it does                                                                                                                                                                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/v1/enroll`     | Makes the signed-in user a member of the service's team. Only if the service was connected with "may add members".                                                                                                                                 |
| `POST /api/v1/key`        | Returns the user's key for this service, with `base_url`, `mcp_url` (the organization's knowledge) and the team's `models`. There is one such key per user: each call replaces the last, which stops working, and the new one continues its spend. |
| `POST /api/v1/key/revoke` | Deletes that key, for example when the user's server stops.                                                                                                                                                                                        |

Every call carries two tokens, and no other body:

```sh
curl -X POST "$CONSOLE_URL/api/v1/key" \
  -H "Authorization: Bearer $USER_ACCESS_TOKEN" \
  -H "X-Service-Authorization: Bearer $SERVICE_TOKEN"
```

- `Authorization` is the access token the service received when this user signed
  in through it. It is the proof that the user is real, so a service cannot ask
  for a key for someone who has not signed in.
- `X-Service-Authorization` is the service's own token from the
  client-credentials grant. It shows the call comes from the service and not
  from someone who got hold of a user's token.

To connect one:

1. In Keycloak, create a client for the service in the console's realm: client
   authentication on, standard flow on, service accounts on, and a mapper of
   type "Audience" that adds the custom audience `console-broker` to the access
   token. Configure the service to sign users in with it.
2. As the SSEC admin, open the team's page in the console and fill in "Connect a
   service" with that client ID. A client can be connected to one team only.

What a service cannot do: choose the team (it is fixed when the admin connects
it), exceed the team's key limit, budget or expiry, issue a key before the user
has accepted the team's terms in the console (it gets `consent_required` and a
`consent_url` to send the user to), or bring back someone a lead removed.
Refusals come back as `{"error": "<code>", "message": "..."}` with codes
`not_member`, `consent_required`, `key_limit`, `removed`, `email_not_verified`,
`team_closed` and `not_allowed`. Every call is in the audit log under
`integration:<client id>`. Disconnecting a service deletes the keys it issued.

Not covered: platforms whose users do not sign in through the same identity
provider, such as GitHub Codespaces. They would need users to fetch their own
key from inside the environment (a device-login command), which is not built.

## Design points

- A person's identity is the provider's issuer and user id. Email is used only
  to match invitations, and only when the provider has verified it. Each person
  gets a console-made `participant_id`, which is the only identity LiteLLM and
  the request logs see.
- Invitation tokens are stored hashed, work once and expire after 72 hours.
  Opening the link changes nothing; only the button's POST uses it, so an email
  scanner cannot.
- Provider keys are write-only: sent to LiteLLM, never stored in the console or
  written to its logs. Only known providers are accepted, with no custom URL;
  Azure needs an `https://<resource>.openai.azure.com` endpoint.
- A team starts with no models. The lead picks from the organization's models,
  named `<org short name>/<model>`.
- No consent, no key. Consent rows and the audit log are append-only for the
  broker's database role. Every action, allowed or denied, is an audit event,
  also printed to the broker's log.
- The per-person key limit is enforced by the broker inside a transaction that
  locks the membership row.
- A participant can rotate a key: same name, new secret shown once, the old one
  stops working, and the new one starts from what the old one had spent. A lead
  can revoke any single key in their teams, or rotate it: the key stops at once,
  its owner is emailed, and the replacement is made only when the owner collects
  it, so the lead never sees it and no key is stored in between.
- Archiving deletes the team's keys, empties its model list and blocks it in
  LiteLLM.
- Leads see per-person request counts, tokens and spend, and each person's keys
  by name, with expiry, last use and spend. They never see a key itself or any
  prompt or response content.
- The session cookie is `__Host-Http-console`: Secure, HttpOnly,
  SameSite=Strict. Forms carry a per-session token and cross-site posts are
  refused. The console's pages run no script.

Left out, compared with the design: MFA and re-authentication for sensitive
actions, monitoring alerts, dormant-account cleanup, consent-filtered exports
and retention jobs.

Known limits:

- Changes made in LiteLLM's own UI bypass the console: they are not in its audit
  log, and editing a console-made team, model or key there can leave the two out
  of step.
- If LiteLLM creates a key and the console's database write then fails, the key
  exists without a console record.

## Organization knowledge

Each organization has one knowledge base, shared by all its teams. It lives in
the knowledge hub, which is internal like LiteLLM: people reach it only as MCP
tools through LiteLLM, at `<gateway>/mcp`, with the key they already have. A
participant's team page shows the URL and the tool names
(`knowledge_<short name>-okf_search`, `-okf_create`, `-okf_show` and so on).

The identity provider decides who gets in, in two steps:

1. A person signs in to the console and gets a LiteLLM key for a team. LiteLLM
   lets that team's keys use one MCP server, its organization's.
2. LiteLLM calls the hub with a token of that organization's own client,
   `okf-org-<short name>`. The hub checks the token's signature, that it is
   addressed to the hub, and which organization it names, and lets it touch only
   the bundle `orgs/oidc-<short name>`.

So organizations are kept apart twice. The hub's tools take a bundle name as an
argument, which is why the first step alone would not be enough: the hub refuses
a bundle the token does not name.

The console sets this up. Creating an organization creates its Keycloak client
and registers the MCP server in LiteLLM; the client's secret is kept only in
those two places. Creating a team gives it that server. Suspending the
organization takes the server away from its teams, because LiteLLM does not stop
a blocked team's keys from using MCP. Removing the organization deletes the MCP
server and the Keycloak client; the bundle stays in the hub, unreachable, and
the short name is never reused.

An organization's leads can read all of it in the console: the organization's
page links to a knowledge page with every concept, the text of the one selected,
and the knowledge graph (a dot per concept, an arrow per link between two). It
is read-only and for that organization's leads alone; an SSEC admin gets no such
view, and members see the knowledge through their MCP client. Each look is
written to the audit log. A concept's Markdown is shown formatted. It is
members' writing, so HTML in it stays text, images are not loaded, and only
links to http(s) addresses or to other concepts of the bundle are kept.

- `console-provisioner` may manage clients and nothing else. That is still a
  strong right: it covers every client in the realm, including the console's
  own.
- The `okf_org` value of `console-knowledge`, `console_reader`, has an
  underscore so that it can never be an organization's short name.
- A token for the hub lasts as long as any access token of the provider, so
  removing an organization can take that long to reach the hub. Its keys stop at
  once.
- Everyone in an organization can read and write its knowledge. Writes are
  recorded under the organization, not the person: the hub sees LiteLLM's token,
  not the user.

## Data protection page

When LiteLLM runs [ceil-dlp](https://github.com/uw-ssec/ceil-dlp) as a
guardrail, SSEC admins see what it found on the console's **Data protection**
page: totals by kind of data and action, and the latest events with who sent the
request and its id. ceil-dlp writes one JSON line per detection, with the kind
of data and a hash of the value and never the value; the broker reads that file
(`CONSOLE_DLP_AUDIT_FILE`) and needs no write access to it. The policy itself is
part of LiteLLM's configuration, not the console's.

## Tests

The suite in `tests/` is end to end: it signs in through Keycloak, clicks
through the console as admin, lead and participant, reads invitations from a
[Mailpit](https://mailpit.axllent.org) inbox, and sends requests through the
gateway. It covers the gateway's path list, the full organization → team →
participant → archive flow, every out-of-scope call being denied, connected
services, each organization's knowledge, data loss prevention, and the
admin-only LiteLLM UI. So it needs a complete running stack, and it runs in a
container on that stack's Docker network:

```bash
cp tests/env.example tests/.env   # then fill in the stack's addresses and secrets
pixi run test <docker network>    # builds the test image and runs pytest in it
```

`tests/.env` is ignored by git. Besides the settings in `tests/env.example`, the
suite expects of the stack under test:

- a Keycloak realm named `litellm`, the bootstrap admin `admin` / `admin`, and a
  user `alice` / `alice123` who is listed in `CONSOLE_ADMIN_SUBJECTS`
- mail delivered to Mailpit, `CONSOLE_ENABLE_MOCK_PROVIDER=true`, and a LiteLLM
  model `fake-gpt` that no team is given
- LiteLLM logging requests to MLflow and to the blob container `litellm-logs`,
  with ceil-dlp as a guardrail

It creates organizations, teams and accounts with a random suffix on every run
and leaves them in place. CI builds the image and does not run the suite.

## For AI coding agents

`AGENTS.md` is the entry point for Claude Code, Codex, Copilot, Cursor and other
agents; `CLAUDE.md` points to it. On-demand rules are in
[`.agents/rules/`](.agents/rules/) and step-by-step skills in
[`.agents/skills/`](.agents/skills/). [`knowledge/`](knowledge/) is an OKF
bundle for project memory (decisions, constraints and caveats the code cannot
show), read and written with `pixi run okf`.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of
conduct and the process for submitting pull requests. If you use AI tools while
contributing, read the [AI Policy](AI_POLICY.md) first: it covers disclosure,
review responsibility, and how to credit AI assistance in commits.

## License

This project is licensed under the terms specified in the [LICENSE](LICENSE)
file.
