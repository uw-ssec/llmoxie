# GitHub Actions Workflows

This directory contains GitHub Actions workflows for continuous integration and
deployment.

## Workflows

### CI Workflow (`ci.yml`)

**Purpose**: Runs automated tests and code quality checks on every push and pull
request.

**Triggers**:

- Push to `main` or `feature/**` branches
- Pull requests to `main`
- Manual workflow dispatch

**Jobs**:

#### 1. `test-linux` - Linux Tests

- **Platform**: Ubuntu Latest
- **Tests**: The full suite in a single step:
  `pixi run -e llmaven pytest tests/ --verbose --tb=short --color=yes`. Any test
  failure fails the job.
- **Environment**: pixi-managed Python 3.12 with llmaven environment

#### 2. `pre-commit` - Code Quality Checks

- **Platform**: Ubuntu Latest
- **Checks**:
  - File format checks (YAML, Markdown, JSON)
  - Trailing whitespace and end-of-file fixes
  - Code spelling with codespell
  - GitHub workflow validation
  - Prettier formatting
- **Configuration**: `.pre-commit-config.yaml`

#### 3. `summary` - CI Summary

- **Platform**: Ubuntu Latest
- **Purpose**: Aggregates results from all jobs and generates a summary
- **Always runs**: Even if previous jobs fail

**Environment Variables**:

- `PIXI_VERSION`: v0.63.2 (pixi package manager version)

**Caching**:

- Pixi dependencies are cached for faster builds
- Cache is written only on pushes to `main` branch

**Timeouts**:

- Test job: 30 minutes
- Pre-commit: 10 minutes

---

### Build Services Workflow (`build-services.yml`)

**Purpose**: Builds and pushes Docker container images for MLflow and LiteLLM
services.

**Triggers**:

- Push to `main` with changes in `docker/**`
- Release published
- Manual workflow dispatch

**Images Built**:

1. MLflow (`ghcr.io/{repo}-mlflow`)
2. LiteLLM (`ghcr.io/{repo}-litellm`)

**Features**:

- Multi-platform builds (linux/amd64, linux/arm64)
- GitHub Container Registry (ghcr.io)
- Docker layer caching via GitHub Actions cache
- Automatic tagging (branch, PR, semver, SHA, latest)

---

### Proxy Container Workflow (`proxy-container.yml`)

**Purpose**: Builds and pushes the reverse proxy container image.

**Triggers**: Similar to build-services.yml

---

## Local Testing

### Running Tests Locally

```bash
# Install dependencies
pixi install -e llmaven

# Run the full test suite (the same command CI runs)
pixi run -e llmaven pytest tests/ -v

# Run pre-commit hooks
pixi run -e llmaven pre-commit run --all-files
```

---

## Troubleshooting

### Common Issues

**1. Pixi installation fails**

- Ensure pixi version matches `PIXI_VERSION` in workflow
- Check that `pixi.toml` and `pixi.lock` are up to date

**2. Pre-commit hooks fail**

- Run `pixi run -e llmaven pre-commit run --all-files` locally
- Check `.pre-commit-config.yaml` for hook configuration
- Update hooks: `pixi run -e llmaven pre-commit autoupdate`

**3. Cache issues**

- GitHub Actions cache is immutable once written
- Clear cache via GitHub UI: Settings > Actions > Caches
- Cache is scoped to branch (main branch cache is shared)

---

## Workflow Maintenance

### Updating Pixi Version

1. Update `PIXI_VERSION` in `ci.yml`
2. Test locally with new version: `pixi --version`
3. Update pixi.toml `requires-pixi` field if needed

### Adding New Tests

1. Add test files to `tests/` directory
2. CI picks them up automatically; the single `pytest tests/` step runs the
   whole directory

### Modifying Pre-commit Hooks

1. Edit `.pre-commit-config.yaml`
2. Test locally: `pixi run -e llmaven pre-commit run --all-files`
3. Commit changes (pre-commit will auto-update on next run)

---

## Best Practices

1. **Keep workflows fast**: Use caching, parallel jobs, and fail-fast strategies
2. **Separate concerns**: Different jobs for tests, linting, builds
3. **Platform awareness**: Use service containers on Linux, mock on macOS
4. **Informative summaries**: Use `$GITHUB_STEP_SUMMARY` for readable output
5. **Conditional execution**: Use `if: always()` for cleanup/summary jobs
6. **Timeout limits**: Prevent runaway jobs with reasonable timeouts

---

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Pixi Documentation](https://pixi.sh)
- [Pre-commit Documentation](https://pre-commit.com)
