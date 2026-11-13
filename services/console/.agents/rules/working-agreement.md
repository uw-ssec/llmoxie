# Working Agreement

**Load when:** starting any implementation, refactor, or bugfix task. This is
the behavioral baseline — how to think, how much to change, and when to stop and
ask.

Adapted from
[multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills)
`CLAUDE.md`.

**Tradeoff:** these guidelines bias toward caution over speed. For genuinely
trivial tasks, use judgment — but bias toward the guidelines when in doubt.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick one silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes,
simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports, variables, and functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it
work") require constant clarification.

## 5. Evidence Before Assertions

Never claim work is complete, fixed, or passing without having run the check and
read its output. "Should work" is not a result. When reporting:

- If a command failed, say so and include the relevant output.
- If a step was skipped, say which one and why.
- If something is done and verified, state it plainly without hedging.

For this repository the minimum verification is `pixi run pre-commit-all` — see
[pre-commit-and-quality.md](pre-commit-and-quality.md).

---

**These guidelines are working if:** diffs contain fewer unnecessary changes,
fewer rewrites are needed due to overcomplication, and clarifying questions
arrive before implementation rather than after mistakes.
