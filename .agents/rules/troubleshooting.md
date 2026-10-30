# Troubleshooting

**Load when:** a documented command fails or behaves unexpectedly.

## Issue: "pre-commit not found" or command fails

**Solution:** Run `pixi install -e llmaven` first, and pass `-e llmaven` to
`pixi run`. pre-commit is only in the `llmaven` environment.

## Issue: Pre-commit check fails after making fixes

**Behavior:** Pre-commit hooks like `trailing-whitespace` auto-fix files. When
this happens:

- The hook shows "Failed" with "files were modified by this hook"
- You must re-stage the fixed files: `git add <files>`
- Re-run `pixi run -e llmaven pre-commit` to verify

**This is expected behavior, not an error.**

## Issue: Modifying pixi.toml breaks the environment

**Solution:**

```bash
# Validate syntax, reinstall environment
pixi install -e llmaven

# If still broken, ask the user before removing .pixi and reinstalling
```

## Issue: Platform not supported

`pixi.toml` supports `linux-64` and `osx-arm64` only. Adding a platform forces a
full re-solve of every environment, including the CUDA wheel pinned under
`[target.linux-64.pypi-dependencies]`; raise it with a maintainer rather than
adding it in an unrelated PR.

## Issue: `pixi.lock` changed format or CI cannot read it

**Cause:** a Pixi newer than CI's `v0.63.2` re-solved the lock and wrote a newer
lock-file `version:`. **Solution:** discard the lock change and re-lock with
Pixi 0.63.2.

## Issue: `okf validate` fails in `pixi run -e llmaven verify`

**Solution:** Follow the "Repo-specific traps" in the `okf-memory` skill — the
usual causes are an orphaned concept (no `relate` link), a `description:` that
prettier or a hand edit folded across lines, or a `code_refs` path that is not
tracked. Never fix it by deleting the concept without telling the user.

## Issue: `docker compose` fails on missing variables

**Solution:** `docker/docker-compose.yml` reads `docker/.env`, which is
gitignored. Create it from `docker/.env.example`;
`docker compose -f docker/docker-compose.yml config` shows the resolved file and
any unset variables.

## Issue: Packages missing or at the wrong version

**Solution:** reinstall the environment and check that the package imports:

```bash
pixi install -e llmaven
pixi run -e llmaven llmaven version
```

If that doesn't fix it, ask the user before running `pixi clean`, which deletes
`.pixi/`.
