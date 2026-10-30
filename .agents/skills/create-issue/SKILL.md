---
name: create-issue
description:
  Use when work needs tracking in GitHub rather than implementing it now — a bug
  to file, a feature to capture, or follow-up work discovered mid-task.
---

# Create Issue

Create a GitHub issue for tracking work.

## Arguments

A description of the issue to create.

## Instructions

1. Based on the description, determine:

   - **Type**: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `ci`,
     `build`, `test`
   - **Scope**: the area of the codebase affected — one of the scopes in
     [pre-commit-and-quality.md](../../rules/pre-commit-and-quality.md#commit-messages)
   - **Title**: conventional commit format:
     `type(scope): short imperative description`

2. Draft a structured issue body with relevant sections:

```bash
gh issue create --title "type(scope): description" --body "$(cat <<'EOF'
## Summary

<1-2 sentences describing the problem or feature>

## Requirements

<bulleted list of specific requirements or acceptance criteria>
- [ ] Requirement 1
- [ ] Requirement 2

## Context

<any relevant context, links, or background — omit if not needed>

## Implementation Notes

<optional technical direction or constraints — omit if not needed>
EOF
)"
```

3. Return the issue URL and number to the user.

## Title Convention

| Type            | Example                                                      |
| --------------- | ------------------------------------------------------------ |
| `feat(infra)`   | `feat(infra): add a Key Vault for the LiteLLM master key`    |
| `fix(data)`     | `fix(data): keep sessions that span midnight together`       |
| `refactor(cli)` | `refactor(cli): split infra commands out of cli.py`          |
| `docs(docker)`  | `docs(docker): document the local Azurite blob emulator`     |
| `chore(deps)`   | `chore(deps): bump the LiteLLM image to the next stable tag` |

## Rules

- Title must use conventional commit format: `type(scope): description`
- Keep title under 70 characters
- Use imperative mood ("add" not "adds", "fix" not "fixes")
- Requirements section should have checkboxes for trackable items
- Omit sections that aren't relevant (don't pad with empty sections)
- If the description is vague, ask clarifying questions before creating
- NEVER include sensitive information in the issue body
