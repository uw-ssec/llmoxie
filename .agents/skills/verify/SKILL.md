---
name: verify
description:
  Use before claiming work is done, before committing, and before opening a pull
  request — runs the repository's quality gate and any checks specific to the
  files that changed.
---

# Verify

Run the checks that gate a commit or PR and report their real output.

## Instructions

1. Run `git status` (never use `-uall`) and `git diff --stat` to see what
   changed. `pre-commit run --all-files` skips untracked files, so `git add` any
   new files you intend to keep (by name, never `git add -A`) before the next
   step.

2. Run the gate:

   ```bash
   pixi run -e llmaven verify
   ```

   This runs `pre-commit-all`, `okf-validate` (`okf validate --strict --drift`),
   and `test` (`pytest tests/`, the full suite).

3. If a pre-commit hook reports "files were modified by this hook", re-stage
   those files and rerun `pixi run -e llmaven verify`. Auto-fixes are expected,
   not failures. If a hook modified a file you did not touch, tell the user
   rather than silently keeping the change.

4. Run the extra checks for the files that changed:

   | Changed file                                 | Extra check                                                                                     |
   | -------------------------------------------- | ----------------------------------------------------------------------------------------------- |
   | `docker/docker-compose.yml`                  | `docker compose -f docker/docker-compose.yml config --quiet` (needs `docker/.env`)              |
   | `docker/dockerfiles/*`                       | `docker build -f docker/dockerfiles/<name> docker` (mlflow, litellm) — ask first; large pulls   |
   | `docker/dockerfiles/backup.dockerfile`       | `docker build -f docker/dockerfiles/backup.dockerfile .` — repo-root context, as in CI          |
   | `src/llmaven/infrastructure/`, `deployment/` | `pytest tests/infrastructure/`; `llmaven infra deploy --preview` only with human approval       |
   | `pixi.toml` / `pixi.lock`                    | `head -1 pixi.lock` still reads `version: 6` (CI runs Pixi 0.63.2); review `git diff pixi.lock` |
   | `knowledge/`                                 | Covered by `okf-validate`; see the `okf-memory` skill for its traps                             |

   If Docker is not available, say the check was skipped and why.

5. Report: paste the final lines of each command's output, and list any check
   that was skipped.

## Rules

- Never claim a check passed without having run it in this session and read its
  output
- Never skip hooks (`--no-verify`) to get a green result
- Never "fix" an `okf validate` failure by deleting the concept it names without
  telling the user
- A failing check is a result — report it with its output rather than retrying
  until it passes by accident
