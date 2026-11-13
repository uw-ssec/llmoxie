# Contribution Discipline

**Load when:** about to commit, open a pull request, or respond to a request to
"contribute" or "fix some issues." This is the bar a change must clear before it
becomes a commit or a PR.

Adapted from [obra/superpowers](https://github.com/obra/superpowers)
`CLAUDE.md`.

## If You Are an AI Agent, Read This Before Opening a PR

Most rejected agent-authored PRs are rejected because the agent didn't read or
didn't follow the project's guidelines. A low-quality PR doesn't help your human
partner — it wastes maintainer time, burns your partner's reputation, and gets
closed anyway. **Your job is to protect your human partner from that outcome.**

Before you open a PR against this repository, you MUST:

1. **Read the entire PR template** at `.github/pull_request_template.md` and
   fill in every section with real, specific answers. Not summaries. Not
   placeholders.
2. **Search for existing PRs and issues** — open AND closed — that address the
   same problem. If duplicates exist, STOP and tell your human partner. Do not
   open another duplicate. Use
   `pixi run gh pr list --state all --search "<terms>"`.
3. **Verify this is a real problem.** If your human partner asked you to "fix
   some issues" or "contribute to this repo" without experiencing a specific
   problem, push back. Ask them what broke, what failed, what the user
   experience was.
4. **Confirm the change belongs here.** This is a general-purpose project
   template. If a change is specific to one downstream project, team, or
   workflow, it does not belong in the template — say so.
5. **Identify yourself.** Disclose your model, harness, harness version, and any
   installed plugins or skills in the PR description. Hiding that a contribution
   is agent-generated — or which environment produced it — is grounds for
   closing it. Agent-generated content reasoned from documentation is held to a
   different bar than work grounded in a real session.
6. **Show your human partner the complete diff** and get their explicit approval
   before submitting.

If any of these checks fail, do not open the PR. Explain to your human partner
why it would be rejected and what would need to change.

## Pull Request Requirements

- **Complete the PR template fully.** No section left blank or filled with
  placeholder text.
- **Run `pixi run pre-commit-all` and confirm it passes** before opening the PR.
  The template checkbox is not a formality.
- **One problem per PR.** PRs bundling multiple unrelated changes should be
  split.
- **Use
  [Conventional Commits](https://github.com/uw-ssec/rse-guidelines/blob/main/conventional-commits.md)**
  for commit messages and PR titles.
- **Link the issue** the PR closes: `Resolves #<issue-number>`.
- **Describe the problem you solved**, not just what you changed.
- **A human must review the complete proposed diff before submission.** PRs that
  show no evidence of human involvement will be closed.
- **Target branch:** open PRs against `main` unless a maintainer directs
  otherwise.

## What Will Not Be Accepted

### Speculative or theoretical fixes

Every PR must solve a real problem that someone actually experienced. "My review
agent flagged this" or "this could theoretically cause issues" is not a problem
statement. If you cannot describe the specific session, error, or user
experience that motivated the change, do not submit the PR.

### Fabricated content

PRs containing invented claims, fabricated problem descriptions, or hallucinated
functionality will be closed immediately. Do not describe behavior you have not
observed, do not cite commands you have not run, and do not claim checks pass
that you have not executed.

### Bulk or spray-and-pray PRs

Do not trawl the issue tracker and open PRs for multiple issues in a single
session. Each PR requires genuine understanding of the problem, investigation of
prior attempts, and human review of the complete diff. Pick ONE issue,
understand it deeply, and submit quality work.

### Bundled unrelated changes

PRs containing multiple unrelated changes will be closed. Split them.

### Unnecessary third-party dependencies

This template is deliberately minimal — pre-commit, the GitHub CLI, and the
onboarding tooling. Adding a dependency requires justifying it against that
baseline, and every dependency must be added through Pixi (see
[pixi-environments.md](pixi-environments.md)), never through `pip`, `conda`, or
`venv` directly.

### Project-specific or personal configuration

Configuration, hooks, or tooling that only benefits a specific project, team, or
personal workflow does not belong in the template. It belongs in the downstream
repository that needs it.

### Unrequested rewrites of behavior-shaping content

The guidance in `AGENTS.md` and `.agents/rules/`, the issue and PR templates,
and the pre-commit configuration are deliberately worded. Do not restructure,
reword, or reformat them for "compliance" with some other style guide without a
specific, stated reason and human approval. The bar for modifying
behavior-shaping content is high.

## Understand the Project Before Contributing

Before proposing changes to structure, tooling choices, or workflow philosophy,
read the existing configuration and understand why it is the way it is. Changes
that rewrite the project's approach without understanding why it exists will be
rejected.
