# AGENTS.md

Guidance for AI assistants (Claude Code, Codex, Cursor, Copilot, Gemini CLI, and
any other agent harness) working with this repository.

**This file is the entry point and is deliberately short.** It carries only what
every agent needs before doing anything. Detailed rules live under
[`.agents/rules/`](.agents/rules/) and are loaded on demand — read the one whose
trigger matches your current task, not all of them.

## Non-negotiables

These apply to every task, in every session:

1. **Pixi is the only package manager.** Never invoke `pip`, `conda`, or `venv`
   directly. Development happens in the `llmaven` environment: run
   `pixi install -e llmaven` first and `pixi run -e llmaven <task>` after.
2. **Verify before you claim.** Never report work as complete, fixed, or passing
   without having run the check and read its output. The minimum gate here is
   `pixi run -e llmaven verify`.
3. **Change surgically.** Every changed line must trace directly to the request.
   Don't refactor, reformat, or "improve" adjacent code you weren't asked to
   touch.
4. **Ask instead of assuming.** If the request has multiple readings or
   something is unclear, stop and name it — before implementing, not after.
5. **Never open a PR** without working through
   [`.agents/rules/contribution-discipline.md`](.agents/rules/contribution-discipline.md)
   in full, including human review of the complete diff.
6. **Check project memory before the first edit to a file.** Run
   `pixi run -e llmaven okf search --for-path <file>`. A `governance: hold` hit
   means stop and confirm with the user; a `governance: constraint` hit lists
   invariants the change must keep. See the `okf-memory` skill.
7. **Never modify `archive/`.** It holds legacy code kept for reference only.
8. **Never commit secrets or deployment config.** `llmaven-config*.yaml`,
   `.env`, and `.env.*` are gitignored; only `*.example` files are tracked.
9. **Never touch live infrastructure without explicit approval.**
   `llmaven infra deploy` (including `--preview`), `llmaven infra destroy`, and
   `pixi run -e llmaven clean` (`docker-compose down -v`) change or delete real
   resources and data.

## Rule Index

Load the rule file whose trigger matches what you are about to do.

| Rule file                                                              | Load when                                                                        |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [working-agreement.md](.agents/rules/working-agreement.md)             | Starting any implementation, refactor, or bugfix — the behavioral baseline       |
| [contribution-discipline.md](.agents/rules/contribution-discipline.md) | About to commit, open a PR, or asked to "contribute" / "fix some issues"         |
| [pixi-environments.md](.agents/rules/pixi-environments.md)             | Running any command, adding a dependency, or editing `pixi.toml`                 |
| [pre-commit-and-quality.md](.agents/rules/pre-commit-and-quality.md)   | Committing, preparing a PR, or claiming checks or tests pass                     |
| [repository-map.md](.agents/rules/repository-map.md)                   | You need to know what this repo is, where a file lives, or how it deploys        |
| [onboarding.md](.agents/rules/onboarding.md)                           | First-time setup, or helping a new contributor get started                       |
| [troubleshooting.md](.agents/rules/troubleshooting.md)                 | A documented command fails or behaves unexpectedly                               |
| [code-conventions.md](.agents/rules/code-conventions.md)               | Naming a new module, class, function, or constant, or a style question           |
| [infrastructure.md](.agents/rules/infrastructure.md)                   | Pulumi/Azure code under `infrastructure*/` or `deployment/`, or `infra` commands |

The agentic RAG system now lives in
[uw-ssec/llmoxie-rag](https://github.com/uw-ssec/llmoxie-rag).

## Skills

Step-by-step recipes live at `.agents/skills/<name>/SKILL.md` (symlinked to
`.claude/skills` for Claude Code): `commit`, `push`, `create-pr`, `merge-pr`,
`create-issue`, `clean-branches`, `verify`, and `okf-memory`. Use the matching
skill instead of improvising the workflow.

## Project Memory

Decisions, constraints, and caveats the code cannot show live in the OKF bundle
at [`knowledge/`](knowledge/). Read and write it only through the `okf` CLI
(`pixi run -e llmaven okf ...`) as described in the `okf-memory` skill — never
by hand, and never through prettier.

## Provenance

This agent framework is adapted from
[uw-ssec/project-template](https://github.com/uw-ssec/project-template). Its
behavioral and contribution rules come from two upstream sources:

- [obra/superpowers](https://github.com/obra/superpowers) `CLAUDE.md` — agent
  contribution discipline (`contribution-discipline.md`).
- [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)
  `CLAUDE.md` — behavioral guidelines that reduce common LLM coding mistakes
  (`working-agreement.md`).
