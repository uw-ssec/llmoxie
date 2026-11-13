# AI Policy

AI-assisted contributions are welcome. We ask that you:

- Disclose that AI was used and name the harness and model. On a pull request,
  fill in the "AI assistance disclosure" section of the PR template and/or apply
  the `ai-assisted` label.
- Review and understand every line you submit; you are responsible for it.
- Meet the same quality, testing, and style standards as any contribution.
  `pixi run pre-commit-all` must pass before you open a pull request.
- Not use fully autonomous agents to open issues or pull requests.
- Respond to reviewers yourself.
- Clearly mark AI text in descriptions and issues.

This applies to issues and comments as well as pull requests. Using AI for
translation or grammar help is fine. Contributions that ignore this policy may
be closed.

Only humans can be named as co-authors, and AI can _never_ sign off on a commit.
The
[Linux kernel trailer](https://docs.kernel.org/process/coding-assistants.html)
is used to credit AI assistance, naming the coding agent as a lowercase,
hyphenated slug and the model identifier it reports, joined by a colon into one
machine-readable token:

```text
Assisted-by: <harness>:<model>
```

For example:

```text
Assisted-by: claude-code:claude-fable-5-1
```

Specialized analysis tools that contributed to the change may follow the model
(for example `Assisted-by: claude-code:claude-fable-5-1 mypy`); basic tools such
as git, formatters, and test runners are not listed. Use the same harness and
model string in the PR's disclosure section so the commits and the pull request
agree.

See the `commit` skill under `.agents/skills/` for the full commit-message
convention.
