# Section 4: RSE Plugins — Live AI-Assisted Development

**Timing:** ~25 minutes (3 min setup, 17 min live workflow, 5 min wrap-up)
**Prerequisites:** Claude Code installed, RSE Plugins installed

## Overview

This section demonstrates [RSE Plugins](https://github.com/uw-ssec/rse-plugins) — custom AI agents and skills for Research Software Engineering workflows. We perform a **live** `/research` -> `/plan` -> `/implement` -> `/validate` cycle on the LLMaven codebase itself.

> **This is a live demo.** The prompts below are scripted, but the AI responses will vary. The workflow shows how AI-assisted development accelerates real engineering tasks while maintaining auditability and quality.

---

## Setup (3 min)

### Install RSE Plugins

In Claude Code, run:

```
/plugin marketplace add uw-ssec/rse-plugins
```

### Verify installation

After installation, you should see these capabilities:

**Agents:**
- Scientific Python Expert

**Skills (highlight these):**
- `pixi-package-manager` — pixi-aware dependency management
- `python-testing` — pytest test scaffolding following scientific Python conventions
- `code-quality-tools` — ruff, mypy, and formatting tools
- AI Research Workflows: `/research`, `/plan`, `/implement`, `/validate`

---

## The Task

**"Add unit tests for `src/llmaven/deployment/validate.py`"**

### Why this task?

- **No tests exist** for the `deployment/` module — this is a real gap
- `validate.py` has **~571 lines** of complex validation logic
- It contains a mix of:
  - **Pure functions** (easy to test): `estimate_monthly_cost()`, `check_config_for_hardcoded_secrets()`
  - **Subprocess-dependent functions** (good for showing mocking): `check_azure_cli()`, `check_subscription_access()`
  - **Orchestrator function**: `validate_config()` that coordinates all checks
- This is a **real, valuable task** — not a toy example

### Functions in `validate.py`

| Function | Type | Test Approach |
|----------|------|--------------|
| `check_azure_cli()` | Subprocess | Mock `subprocess.run` |
| `check_subscription_access()` | Subprocess | Mock `subprocess.run` |
| `check_required_providers()` | Subprocess | Mock `subprocess.run` |
| `get_llmaven_secrets()` | Env vars + file I/O | Mock `os.environ`, `tmp_path` |
| `check_secrets()` | Env vars | Mock `os.environ` |
| `check_config_for_hardcoded_secrets()` | File I/O | `tmp_path` fixture |
| `estimate_monthly_cost()` | Pure function | Direct input/output |
| `validate_config()` | Orchestrator | Mock sub-functions or integration test |

---

## Step 1: `/research` — Understand the Code (~5 min)

### Prompt

```
/research Analyze src/llmaven/deployment/validate.py to understand its public API, test patterns in the existing codebase, and what test fixtures would be needed
```

### What to show the audience

As Claude Code works, point out:

- **File discovery:** It reads `validate.py` and discovers the 7+ public functions
- **Function analysis:** It identifies that `estimate_monthly_cost()` is pure (no mocking needed) while `check_azure_cli()` needs subprocess mocking
- **Pattern recognition:** It cross-references existing test patterns in `tests/agentic/` and `tests/conftest.py`
- **Research document:** It produces a structured research document in `.agents/`

> **Presenter note:** Highlight the auditable output — the research document can be reviewed by the team. This is not a black box.

---

## Step 2: `/plan` — Plan the Test Suite (~5 min)

### Prompt

```
/plan Add unit tests for deployment/validate.py based on the research
```

### What to show the audience

- **Test structure proposal:** Claude Code proposes test classes:
  - `TestEstimateMonthlyCost` — pure function tests (dev/staging/prod tiers)
  - `TestCheckConfigForHardcodedSecrets` — file-based tests with `tmp_path`
  - `TestCheckAzureCli` — subprocess mocking
  - `TestCheckSecrets` — environment variable mocking
  - `TestValidateConfig` — orchestrator integration
- **Mocking decisions:** Which functions need mocks vs. which are pure
- **Phased plan:** Implementation broken into phases with verification steps
- **Plan file:** Saved to `.agents/plan-*.md` for review

> **Presenter note:** Discuss the plan with the audience. Ask: "Does this test structure make sense? Should we add any edge cases?" Approve when ready.

---

## Step 3: `/implement` — Write the Tests (~5 min)

### Prompt

```
/implement Execute the plan to add tests for validate.py
```

### What to show the audience

- **File creation:** `tests/deployment/test_validate.py` is created
- **Test writing:** Watch tests being written in real time:
  - `@patch("subprocess.run")` for Azure CLI functions
  - `tmp_path` fixture for file-based tests
  - `LLMavenConfig` fixtures for pure function tests
  - Parametrized tests for different environment tiers
- **Pattern following:** Tests follow existing patterns from `tests/agentic/`
- **Skill activation:** The `python-testing` skill may be activated to scaffold pytest conventions

> **Presenter note:** Show the code being written in real time. Point out how it follows patterns from the existing test suite — same assertion style, fixture approach, etc.

---

## Step 4: `/validate` — Check the Implementation (~2 min)

### Prompt

```
/validate Check the implementation against the plan
```

### What to show the audience

- **Plan-to-code comparison:** Validation checks each plan item against the implementation
- **Test execution:** Runs `pixi run -e llmaven pytest tests/deployment/ -v` to verify tests pass
- **Gap identification:** Any missing tests or unaddressed edge cases are flagged

---

## Wrap-up (5 min)

### Show the diff

```bash
git diff
```

> **Presenter note:** Walk through the changes — new test file, any fixtures added.

### Key takeaways

- **Full cycle in ~20 minutes:** Understanding -> Planning -> Implementation -> Validation
- **Auditable:** Every step produces artifacts (research doc, plan, implementation, validation report)
- **Real value:** We just added missing test coverage for a critical module
- **Customizable:** RSE Plugins are extensible — teams can add domain-specific agents and skills

### Other available plugins

- **Scientific Domain Applications** — domain-specific scientific computing patterns
- **HoloViz Visualization** — Panel, HoloViews, and dashboard development
- **Project Management** — issue tracking and project coordination

---

## Skill Spotlights

These skills may be activated during the workflow — point them out when you see them:

| Skill | What It Does | When You'll See It |
|-------|-------------|-------------------|
| **python-testing** | Scaffolds pytest tests following scientific Python conventions | During `/implement` |
| **code-quality-tools** | Applies ruff linting/formatting | During `/implement` or `/validate` |
| **pixi-package-manager** | Handles pixi-aware dependency changes | If new test deps are needed |

---

## Backup Task

If the primary task hits issues during the live demo (API outage, unexpected errors, etc.), switch to this simpler task:

### Prompt

```
/research Document the Pydantic configuration schema in src/llmaven/infrastructure/config/schema.py, including all fields, their defaults, and validation rules
```

This is a **research-only** task — no code changes, lower risk, still demonstrates the `/research` workflow effectively.

> **Presenter note:** Have this prompt ready to paste. The backup task shows the same research workflow but without the implementation risk.

---

## Pre-Demo Prep Checklist

Before the live demo:

- [ ] Run the full `/research` -> `/plan` -> `/implement` -> `/validate` workflow end-to-end to identify rough edges
- [ ] Ensure Claude Code API access is working (`claude --version`, try a simple prompt)
- [ ] Verify RSE Plugins are installed and up-to-date (`/plugin list`)
- [ ] Have the backup task prompt ready to paste
- [ ] Discard any test files from practice runs (`git checkout -- tests/`)
