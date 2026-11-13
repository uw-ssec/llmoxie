# Repository Map

**Load when:** you need to know what this repository is, where a file lives, or
what CI runs against it.

## Repository Overview

This is the **LLMoxie console**: a web console through which organizations
manage their use of a shared LiteLLM gateway, while LiteLLM itself stays
internal. One container image runs three services (`console-web`,
`console-broker`, `console-init`). The services it works with (LiteLLM,
Keycloak, Postgres, a reverse proxy, mail) are deployed elsewhere; `README.md`
lists what the console expects of them.

**Repository Stats:**

- **Type:** Python web application (FastAPI, Jinja templates), shipped as a
  container image
- **Languages:** Python 3.12, HTML templates, SQL
- **Build System:** Pixi (v0.49.0+) for the development environment and tasks;
  `docker build` for the image, which installs the locked `requirements.txt`
- **Platform:** macOS (osx-arm64) and Linux (linux-64, linux-aarch64)
- **License:** BSD 3-Clause

## Project Structure & Key Files

```
.
├── .devcontainer/               # Codespaces / Dev Containers image: pixi + coding agent CLIs
├── .agents/
│   ├── rules/                   # On-demand rules referenced by AGENTS.md
│   └── skills/                  # User-invocable skills (/commit, /create-pr, ...)
├── .claude/
│   └── skills -> ../.agents/skills  # Symlink so Claude Code discovers the skills
├── .github/
│   ├── dependabot.yml           # Dependabot config for GitHub Actions
│   ├── pull_request_template.md # PR template (requires pre-commit checks)
│   ├── release.yml              # Release notes configuration
│   ├── workflows/               # GitHub Actions (image build, zizmor workflow linting, Copilot agent setup)
│   └── ISSUE_TEMPLATE/          # Issue templates (bug, feature, docs, onboard, etc.)
├── console_app/
│   ├── policy.py                # Who may do what, deny by default; used by web and broker
│   ├── web/                     # console-web: public pages, sign-in, sessions, templates
│   └── broker/                  # console-broker: org data and every call to LiteLLM, Keycloak and the hub
├── db/console-db.sql            # console_db: tables, the two roles, row-level security
├── tests/                       # End-to-end suite; needs a running stack (see README "Tests")
├── init_admin_key.py            # console-init: creates the broker's LiteLLM key, once
├── Dockerfile                   # One image for all three services; target `tests` adds the suite
├── requirements.txt             # Locked versions for the image
├── requirements-test.txt        # Extra locked versions for the test image
├── knowledge/                   # OKF project memory, managed by the okf CLI (okf-memory skill)
├── .pre-commit-config.yaml      # Pre-commit hook configuration
├── pixi.toml                    # **PRIMARY CONFIG**: Dependencies, tasks, features
├── pixi.lock                    # Lock file (auto-generated, don't manually edit)
├── .gitignore                   # Ignores .pixi/ and .DS_Store
├── AGENTS.md                    # Entry point for AI assistants
├── CLAUDE.md                    # Points Claude Code at AGENTS.md (@AGENTS.md)
├── CODE_OF_CONDUCT.md           # Contributor Covenant v2.0
├── CONTRIBUTING.md              # Contribution guidelines (references Conventional Commits)
├── LICENSE                      # BSD 3-Clause License
├── README.md                    # Project documentation
└── onboarded.md                 # Empty file (excluded from pre-commit)
```

## Continuous Integration & Validation

**Image build:** `.github/workflows/image.yml` builds the console image and its
test image on every pull request and push to `main`. The test suite needs a
running stack and is not run in CI; run it with `pixi run test <docker network>`
(see `README.md`).

**GitHub Actions:** `.github/workflows/zizmor.yml` runs
[zizmor](https://github.com/zizmorcore/zizmor) static analysis to lint workflow
files for security issues. Changes to anything under `.github/workflows/` must
keep this check passing.

**Copilot cloud agent:** `.github/workflows/copilot-setup-steps.yml` prepares
the GitHub Copilot coding agent's environment (pixi install from `pixi.lock`,
pre-commit hook environments). Copilot reads `AGENTS.md` and `.agents/skills/`
on its own; keep the pinned `pixi-version` in sync with
`.devcontainer/Dockerfile`.

**Pre-commit.ci Integration:** The `.pre-commit-config.yaml` includes a `ci:`
section, suggesting integration with https://pre-commit.ci for automated PR
checks. Verify if enabled on the repository.

**Dependabot:** Configured to update GitHub Actions weekly (groups all action
updates together).

## Further Reading

For more information on SSEC best practices, see:
https://rse-guidelines.readthedocs.io/en/latest/llms-full.txt
