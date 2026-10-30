# Onboarding

**Load when:** setting up this repository for the first time, or helping a new
contributor get started.

## First-Time Setup

```bash
# Install the development environment
pixi install -e llmaven

# Install the git hooks
pixi run -e llmaven pre-commit-install

# Confirm the CLI is on the path
pixi run -e llmaven llmaven version
```

## Local Services

```bash
# Create the local env file (gitignored) and fill in API keys
cp docker/.env.example docker/.env

pixi run -e llmaven up       # start PostgreSQL, MLflow, Azurite, LiteLLM
pixi run -e llmaven status   # check the containers
pixi run -e llmaven down     # stop them (keeps data)
```

Service URLs: LiteLLM <http://localhost:4000>, MLflow <http://localhost:8080>.

## Where to Go Next

- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — the human contributor workflow
- [repository-map.md](repository-map.md) — what lives where
- [infrastructure.md](infrastructure.md) — Azure deployment (needs `az login`
  and a `llmaven-config.yaml`)
