# Contributing to LLMaven

Thank you for your interest in contributing to LLMaven! This project is developed
by [UW SSEC](https://escience.washington.edu/software-engineering/ssec/) and
welcomes contributions from the community.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Code Style](#code-style)
- [Reporting Issues](#reporting-issues)

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/llmoxie.git
   cd llmoxie
   ```
3. **Add the upstream remote** so you can pull in future changes:
   ```bash
   git remote add upstream https://github.com/uw-ssec/llmoxie.git
   ```

## Development Setup

LLMaven uses [pixi](https://pixi.sh) to manage dependencies and environments.

1. **Install pixi** if you haven't already:
   ```bash
   curl -fsSL https://pixi.sh/install.sh | bash
   ```

2. **Install project dependencies:**
   ```bash
   pixi install
   ```

3. **Activate the development environment:**
   ```bash
   pixi shell -e llmaven
   ```

4. **Install pre-commit hooks:**
   ```bash
   pre-commit install
   ```

5. **Verify your setup** by running the test suite (see below).

## Running Tests

```bash
# All tests
pixi run -e llmaven pytest tests/

# Core tests only (fast)
pixi run -e llmaven pytest tests/ --ignore=tests/agentic/ --ignore=tests/v1/

# Agentic tests
pixi run -e llmaven pytest tests/agentic/

# API endpoint tests
pixi run -e llmaven pytest tests/v1/

# With coverage
pixi run -e llmaven pytest tests/ --cov=llmaven
```

## Submitting a Pull Request

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b fix/short-description
   # or
   git checkout -b feat/short-description
   ```

2. **Make your changes.** Keep commits focused — one logical change per commit.

3. **Write or update tests** for any code you change.

4. **Run the full test suite** and ensure it passes.

5. **Run pre-commit** to catch formatting and lint issues:
   ```bash
   pre-commit run --all-files
   ```

6. **Push your branch** and open a pull request against `main`:
   ```bash
   git push origin your-branch-name
   ```

7. **Fill in the PR template** — link the issue your PR closes with
   `Closes #<issue-number>` in the description.

8. **Respond to review feedback** promptly. A maintainer will review your PR
   and may request changes before merging.

### Commit message format

Follow the conventional commits style used in this repo:

```
<type>: short summary (#issue-number)

Optional longer explanation.
```

Common types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `ci`.

## Code Style

- **Formatter:** [ruff](https://docs.astral.sh/ruff/) (enforced via pre-commit)
- **Linter:** ruff (enforced via pre-commit)
- **Type hints:** encouraged throughout; required for public API surfaces
- **Dependencies:** runtime deps go in `pyproject.toml`; dev-only tools go in
  `pixi.toml`. Do not add a package to both unless there is a specific reason.
- **Comments:** only when the *why* is non-obvious. Avoid restating what the
  code already says.

## Reporting Issues

- Search [existing issues](https://github.com/uw-ssec/llmoxie/issues) before
  opening a new one.
- Use the appropriate issue template (bug report or feature request).
- Provide enough detail to reproduce the problem or understand the request.

## Code of Conduct

This project follows the
[Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating,
you agree to uphold its standards. Please report unacceptable behaviour to the
maintainers.
