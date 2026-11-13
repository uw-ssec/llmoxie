-- Console database. Run it once as a Postgres superuser, for example from the Postgres image's
-- /docker-entrypoint-initdb.d, on the server that also holds LiteLLM's and MLflow's databases
-- (`litellm` and `mlflow_db` below; change the two REVOKE lines if yours are named differently).
-- The passwords here are for local use; change them anywhere else.
--
-- Two roles, neither of which can connect to LiteLLM's or MLflow's database:
--   console_web     sessions only (table web_session)
--   console_broker  org data, and append-only access to consent and the audit log
-- Tables are owned by the superuser, so row-level security applies to the broker.

CREATE ROLE console_web LOGIN PASSWORD 'console-web-dev';
CREATE ROLE console_broker LOGIN PASSWORD 'console-broker-dev';
CREATE DATABASE console_db;
REVOKE ALL ON DATABASE console_db FROM PUBLIC;
GRANT CONNECT ON DATABASE console_db TO console_web, console_broker;
REVOKE CONNECT ON DATABASE litellm FROM PUBLIC;
REVOKE CONNECT ON DATABASE mlflow_db FROM PUBLIC;

\c console_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO console_web, console_broker;

-- ── Web tier ────────────────────────────────────────────────────────────────
CREATE TABLE web_session (
  sid_hash   text PRIMARY KEY,            -- sha256 of the cookie value
  data       jsonb NOT NULL,              -- tokens and pre-login state; never leaves the server
  expires_at timestamptz NOT NULL
);
GRANT SELECT, INSERT, UPDATE, DELETE ON web_session TO console_web;

-- ── Org data (broker) ───────────────────────────────────────────────────────
CREATE TABLE person (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer         text NOT NULL,
  subject        text NOT NULL,
  participant_id text NOT NULL UNIQUE,    -- LiteLLM user_id; the only identity that reaches the logs
  email          text,                    -- last verified sign-in email; used only to match invites
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (issuer, subject)
);

CREATE TABLE org (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug           text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,30}$'),
  name           text NOT NULL,
  budget_ceiling numeric(12,2) NOT NULL CHECK (budget_ceiling >= 0),
  -- 'removed': closed for good by an SSEC admin. The row and its records stay; nothing can use it.
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'removed')),
  mcp_server_id  text,                    -- the org's knowledge in LiteLLM (an MCP server onto okf-hub); null once removed
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE org_lead (
  org_id     uuid NOT NULL REFERENCES org,
  person_id  uuid NOT NULL REFERENCES person,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, person_id)
);

CREATE TABLE org_model (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES org,
  provider         text NOT NULL,
  model            text NOT NULL,
  public_name      text NOT NULL,         -- <org slug>/<model>, the name clients call
  litellm_model_id text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  removed_at       timestamptz
);
CREATE UNIQUE INDEX org_model_live_name ON org_model (public_name) WHERE removed_at IS NULL;

CREATE TABLE team (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES org,
  name            text NOT NULL,
  key_limit       int NOT NULL CHECK (key_limit BETWEEN 1 AND 20),
  key_budget      numeric(12,2) NOT NULL CHECK (key_budget >= 0),
  key_expiry_days int NOT NULL CHECK (key_expiry_days BETWEEN 1 AND 365),
  team_budget     numeric(12,2) NOT NULL CHECK (team_budget >= 0),
  consent_text    text NOT NULL,
  -- 'archived': closed by its lead, still visible, read-only. 'removed': taken away by an SSEC admin, hidden.
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'removed')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  archived_at     timestamptz
);
-- A removed team's name can be used again in its org.
CREATE UNIQUE INDEX team_live_name ON team (org_id, name) WHERE status <> 'removed';

CREATE TABLE team_model (
  team_id      uuid NOT NULL REFERENCES team,
  org_model_id uuid NOT NULL REFERENCES org_model,
  org_id       uuid NOT NULL REFERENCES org,
  PRIMARY KEY (team_id, org_model_id)
);

CREATE TABLE team_member (
  team_id    uuid NOT NULL REFERENCES team,
  person_id  uuid NOT NULL REFERENCES person,
  org_id     uuid NOT NULL REFERENCES org,
  status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (team_id, person_id)
);

CREATE TABLE invite (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       uuid NOT NULL REFERENCES org,
  team_id      uuid REFERENCES team,      -- null for an org-lead invite
  kind         text NOT NULL CHECK (kind IN ('lead', 'participant')),
  email        text NOT NULL,
  token_hash   text NOT NULL UNIQUE,      -- the token itself exists only in the email
  expires_at   timestamptz NOT NULL,
  status       text NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'consumed', 'needs_approval', 'rejected', 'revoked')),
  person_id    uuid REFERENCES person,    -- who used it
  signin_email text,                      -- the email they signed in with, when it did not match
  created_by   uuid NOT NULL REFERENCES person,
  created_at   timestamptz NOT NULL DEFAULT now(),
  decided_by   uuid REFERENCES person,
  decided_at   timestamptz,
  CHECK ((kind = 'lead') = (team_id IS NULL))
);

CREATE TABLE consent (                    -- append-only: a new choice is a new row
  id             bigserial PRIMARY KEY,
  org_id         uuid NOT NULL REFERENCES org,
  team_id        uuid NOT NULL REFERENCES team,
  person_id      uuid NOT NULL REFERENCES person,
  terms_accepted boolean NOT NULL,
  research_use   boolean NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE integration (                -- an outside service (a JupyterHub, say) connected to one team
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id     uuid NOT NULL REFERENCES org,
  team_id    uuid NOT NULL REFERENCES team,
  client_id  text NOT NULL,               -- the service's client in the identity provider
  name       text NOT NULL,               -- also the name of the keys it issues
  can_enroll boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL REFERENCES person,
  created_at timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz
);
CREATE UNIQUE INDEX integration_live_client ON integration (client_id) WHERE removed_at IS NULL;

CREATE TABLE api_key (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id     uuid NOT NULL REFERENCES org,
  team_id    uuid NOT NULL REFERENCES team,
  person_id  uuid NOT NULL REFERENCES person,
  name       text NOT NULL,
  key_alias  text NOT NULL UNIQUE,        -- LiteLLM key alias; the key itself is never stored here
  -- 'creating': a lead rotated it. The old secret is gone and the owner has not collected the new one yet.
  status     text NOT NULL DEFAULT 'creating' CHECK (status IN ('creating', 'active', 'deleted')),
  carried_spend numeric(14,6) NOT NULL DEFAULT 0,  -- what the secret it replaces had spent
  integration_id uuid REFERENCES integration,      -- set when an integration issued it for its owner
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE audit_event (                -- append-only
  id              bigserial PRIMARY KEY,
  at              timestamptz NOT NULL DEFAULT now(),
  actor_person_id uuid,
  actor_role      text,
  org_id          uuid,
  team_id         uuid,
  action          text NOT NULL,
  target          text,
  result          text NOT NULL,          -- ok | denied | error
  detail          jsonb NOT NULL DEFAULT '{}'
);

GRANT SELECT, INSERT, UPDATE ON person, org, org_model, team, team_member, invite, api_key, integration TO console_broker;
GRANT SELECT, INSERT, DELETE ON org_lead, team_model TO console_broker;
GRANT SELECT, INSERT ON consent, audit_event TO console_broker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO console_broker;

-- ── Row-level security: a third check after console-web and the broker's policy ──
-- The broker opens each transaction either for one org (app.org_id) or, for the few
-- operations that are not tied to one org, with app.scope = 'system'. A query that
-- forgets its org filter then returns only that org's rows.
CREATE FUNCTION app_scope() RETURNS text LANGUAGE sql STABLE
  AS $$ SELECT coalesce(current_setting('app.scope', true), '') $$;
CREATE FUNCTION app_org() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$;

ALTER TABLE org ENABLE ROW LEVEL SECURITY;
CREATE POLICY org_scope ON org TO console_broker
  USING (app_scope() = 'system' OR id = app_org())
  WITH CHECK (app_scope() = 'system' OR id = app_org());

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['org_lead', 'org_model', 'team', 'team_model', 'team_member', 'invite', 'consent', 'api_key', 'integration']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY org_scope ON %I TO console_broker
         USING (app_scope() = ''system'' OR org_id = app_org())
         WITH CHECK (app_scope() = ''system'' OR org_id = app_org())', t);
  END LOOP;
END $$;
