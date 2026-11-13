<!--
  Pull Request Template
  =====================
  Sizing targets: 200-400 lines changed, ~15-20 minutes of review, one
  logical change. Reviewers may return an oversized PR for splitting
  without a detailed review.

  Delete sections that genuinely do not apply, but do not delete the
  Author verification section on an AI-assisted PR.
-->

## 📄 Description

<!-- What does this PR change? Why is it needed? -->

## 🔗 Related Issues

Resolves #\<issue-number>

<!-- Also note dependencies, e.g. "Blocked by #N", if any. -->

## 💡 Type of change

| Type             | Checked? |
| ---------------- | -------- |
| 🐞 Bug fix       | [ ]      |
| ✨ New feature   | [ ]      |
| 📝 Documentation | [ ]      |
| ♻️ Refactor      | [ ]      |
| 🛠️ Build/CI      | [ ]      |
| Other (explain)  | [ ]      |

## 🤖 AI assistance disclosure

<!-- Disclosure is required, lightweight, and shame-free. Its purpose is
     reviewer calibration, not judgment. Leaving the box unchecked asserts
     that no AI assistance was used. -->

- [ ] This PR is AI-assisted

**Harness / model:**

<!-- e.g. claude-code:claude-fable-5-1 — the same `<harness>:<model>` token
     as the `Assisted-by:` trailer on the commits -->

## 🔍 Author verification

<!-- Required on AI-assisted PRs. Reviewers spend attention proportional to
     the "less certain" list, so be specific and honest. -->

**I personally verified:**

<!-- e.g. ran the full test suite against dataset X; stepped through the
     boundary-condition logic by hand -->

**Less certain about:**

<!-- e.g. the rewritten retry logic in client.py:120-160 — please look
     closely -->

**AI-generated portions:**

<!-- Which files/functions, and roughly how much -->

- [ ] I own every line in this PR and can explain any of it on request
- [ ] I am available for a synchronous walkthrough if a reviewer requests one

## 🧪 How to test

<!-- Steps reviewers can run to exercise the change, not just read it -->

## ✅ Checklist

- [ ] `pre-commit run --all-files` passes and CI is green
- [ ] PR title follows
      [Conventional Commits](https://github.com/uw-ssec/rse-guidelines/blob/main/conventional-commits.md)
- [ ] Change is within the sizing targets (200-400 lines), or the reason it
      cannot be split is explained above
- [ ] Tests added/updated where needed
- [ ] Tests assert meaningful expected values rather than only "doesn't crash",
      and a human wrote or approved those values
- [ ] Docs added/updated if applicable
- [ ] I have linked the issue this PR closes, if any
- [ ] No secrets, credentials, or restricted data entered any prompt
- [ ] No hallucinated config keys, API parameters, or imports; referenced APIs
      exist in the pinned versions
- [ ] Branched from and targeting the correct branch; no direct pushes to
      protected branches

## 📝 Notes to reviewers

<!-- Anything specific reviewers should know before starting -->
