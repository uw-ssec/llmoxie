# Troubleshooting

**Load when:** a documented command fails or behaves unexpectedly.

## Issue: "pre-commit not found" or command fails

**Solution:** Run `pixi install` first. Pixi manages pre-commit installation.

## Issue: Pre-commit check fails after making fixes

**Behavior:** Pre-commit hooks like `trailing-whitespace` auto-fix files. When
this happens:

- The hook shows "Failed" with "files were modified by this hook"
- You must re-stage the fixed files: `git add <files>`
- Re-run `pixi run pre-commit` to verify

**This is expected behavior, not an error.**

## Issue: Modifying pixi.toml breaks the environment

**Solution:**

```bash
# Validate syntax, reinstall environment
pixi install

# If still broken, remove and reinstall
rm -rf .pixi
pixi install
```

## Issue: Platform-specific problems (non-macOS)

**Solution:** Edit `pixi.toml` and add platforms:

```toml
platforms = ["osx-arm64", "linux-64", "win-64"]
```

Then run `pixi install`.
