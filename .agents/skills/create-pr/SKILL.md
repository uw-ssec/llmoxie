---
name: create-pr
description:
  Use when a branch's work is complete and ready to be proposed for review
  against main, or when the user asks to open a pull request.
---

# Create PR

Create a pull request for the current branch.

## Instructions

1. Run these commands in parallel to understand the current state:

   - `git status` (never use `-uall`)
   - `git diff --stat` (check for uncommitted changes)
   - `git branch --show-current` (current branch)
   - `git log --oneline main..HEAD` (all commits being PR'd)
   - `git diff main...HEAD --stat` (full diff summary against main)

2. If there are uncommitted changes, ask whether to commit first.

3. If the branch hasn't been pushed, push with `git push -u origin <branch>`.

4. Analyze ALL commits in the branch (not just the latest) to draft:

   - **Title**: Use conventional commit format: `type(scope): short description`
     (under 70 chars)
   - **Body**: Structured summary with test plan

5. Create the PR:

```bash
gh pr create --title "type(scope): description" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points covering what changed and why>

## Changes
<bulleted list of specific changes, grouped by area if needed>

## Test plan
- [ ] <specific testable checklist items>
EOF
)"
```

6. If there's a related issue, add `Closes #N` in the body.
7. Return the PR URL to the user.

## Title Convention

Use the same conventional commit types as the `commit` skill:

- `feat(scope):` for new features
- `fix(scope):` for bug fixes
- `refactor(scope):` for restructuring
- `docs(scope):` for documentation
- `chore(scope):` for maintenance

## Rules

- Keep title under 70 characters
- Always include a test plan with specific checkboxes
- Never create a PR from `main` to `main`
- If the branch name contains a hint (e.g., `feat/`, `fix/`), use that as the
  commit type
- On an AI-assisted PR, disclose it: fill the "AI assistance disclosure" section
  of `.github/pull_request_template.md`, and/or apply the `ai-assisted` label.
  AI-assisted commits carry an `Assisted-by: <harness>:<model>` trailer and
  never an agent-added `Signed-off-by:` — see the `commit` skill for the format
- NEVER add "Generated with" or similar marketing lines to PR titles or bodies.
  This is attribution, not promotion
- If the PR is large or complex, consider breaking it into smaller PRs with
  focused scope and clear dependencies
