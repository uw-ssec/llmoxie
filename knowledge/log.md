## 2026-11-13
* **Update**: Updated concept `decisions/no-op-deploy-controls.md`.
* **Update**: Updated concept `requirements/traefik-sidecar-allowlist-and-client-ip.md`.

## 2026-11-12
* **Update**: Updated concept `facts/litellm-image-install-quirks.md`.
* **Update**: Updated concept `bugs/failed-pg-dump-can-consume-retention.md`.
* **Update**: Updated concept `decisions/litellm-image-digest-pin-and-one-way-upgrade.md`.

## 2026-11-06
* **Update**: Updated concept `decisions/monitoring-alerts-config.md`.
* **Update**: Updated concept `facts/production-readiness-gaps.md`.
* **Update**: Linked `decisions/monitoring-alerts-config.md` to `facts/production-readiness-gaps.md` (Alerting closes the monitoring gaps this fact tracks and records how the alert config behaves).
* **Creation**: Documented concept `decisions/monitoring-alerts-config.md` (Monitoring alerts are email-only, opt-in per environment, and the budget is scoped to the resource group).

## 2026-11-05
* **Update**: Updated concept `architecture/backup-storage-isolated-stack.md`.
* **Update**: Updated concept `requirements/foundry-subnet-only-network-acl.md`.
* **Update**: Updated concept `requirements/traefik-sidecar-allowlist-and-client-ip.md`.
* **Update**: Updated concept `decisions/stay-on-oss-litellm-gateway.md`.
* **Update**: Linked `decisions/calver-with-hatch-vcs.md` to `facts/image-builds-and-workflow-pinning.md` (Tags drive the same image workflow).
* **Update**: Linked `facts/production-readiness-gaps.md` to `facts/managed-redis-rollout-and-limits.md` (Redis was split out of #193).
* **Update**: Linked `facts/production-readiness-gaps.md` to `requirements/litellm-master-and-salt-key.md` (Salt key was split out of #193).
* **Update**: Linked `facts/known-stale-docs.md` to `bugs/ci-false-green-and-repro-traps.md` (Workflow docs that have drifted).
* **Update**: Linked `facts/known-stale-docs.md` to `facts/ruff-rules-pinned-explicitly.md` (Another rule file that has drifted).
* **Update**: Linked `requirements/pyproject-runtime-deps-gap.md` to `facts/pixi-lock-hash-needs-ci-version.md` (Fixing this edits pyproject.toml and stales the lock).
* **Update**: Linked `facts/image-builds-and-workflow-pinning.md` to `bugs/ci-false-green-and-repro-traps.md` (What CI does and doesn't cover).
* **Update**: Linked `facts/ruff-rules-pinned-explicitly.md` to `facts/pixi-lock-hash-needs-ci-version.md` (This edit is what staled the lock on #210).
* **Update**: Linked `facts/pixi-channel-change-resolves-all-envs.md` to `facts/pixi-lock-hash-needs-ci-version.md` (Same lockfile, different stale-lock cause).
* **Update**: Linked `facts/pixi-lock-hash-needs-ci-version.md` to `bugs/ci-false-green-and-repro-traps.md` (Another way local and CI results differ).
* **Update**: Linked `decisions/minio-replaced-by-azurite.md` to `decisions/platform-only-scope.md` (The scope guard pins the resulting compose services).
* **Update**: Linked `decisions/config-updates-ruamel-round-trip.md` to `architecture/pulumi-state-store-bootstrap.md` (Bootstrap writes state names back through this updater).
* **Update**: Linked `bugs/cli-output-data-safety.md` to `architecture/backup-storage-isolated-stack.md` (The captured value feeds the backup job's deployment).
* **Update**: Linked `facts/request-log-sources-differ.md` to `decisions/data-pipeline-moves-to-llmoxie-analysis.md` (Sources the analysis pipeline consumes).
* **Update**: Linked `facts/request-log-sources-differ.md` to `decisions/infra-extract-design.md` (Which sources extract reads).
* **Update**: Linked `bugs/infra-extract-completeness.md` to `decisions/infra-extract-design.md` (Completeness gaps in the same command).
* **Update**: Linked `decisions/infra-extract-design.md` to `decisions/data-pipeline-moves-to-llmoxie-analysis.md` (Extract output feeds the analysis pipeline).
* **Update**: Linked `requirements/secret-loading-logs-use-pulumi-log.md` to `decisions/rebrand-keeps-deployed-identifiers.md` (The same loader's env prefix is part of the rebrand plan).
* **Update**: Linked `facts/loadtest-fallback-detection.md` to `decisions/litellm-image-digest-pin-and-one-way-upgrade.md` (Headers need rechecking on the pinned version).
* **Update**: Linked `decisions/stay-on-oss-litellm-gateway.md` to `decisions/litellm-image-digest-pin-and-one-way-upgrade.md` (The version this snapshot was read at).
* **Update**: Linked `architecture/litellm-config-and-logger-mounted-as-secrets.md` to `decisions/no-op-deploy-controls.md` (Revision controls that decide when a config change takes effect).
* **Update**: Linked `requirements/litellm-master-and-salt-key.md` to `decisions/litellm-image-digest-pin-and-one-way-upgrade.md` (The boot check arrived with this upgrade).
* **Update**: Linked `facts/litellm-image-install-quirks.md` to `decisions/litellm-image-digest-pin-and-one-way-upgrade.md` (How the pinned image is extended).
* **Update**: Linked `bugs/backup-config-not-gitignored.md` to `architecture/backup-storage-isolated-stack.md` (Config file for the same backup path).
* **Update**: Linked `bugs/failed-pg-dump-can-consume-retention.md` to `architecture/backup-storage-isolated-stack.md` (A failure mode of the same job).
* **Update**: Linked `bugs/backup-job-default-traps.md` to `architecture/backup-storage-isolated-stack.md` (Configuration traps in the backup job).
* **Update**: Linked `architecture/backup-storage-isolated-stack.md` to `architecture/pulumi-state-store-bootstrap.md` (The main stack's group and state store are bootstrapped differently).
* **Update**: Linked `facts/floci-az-e2e-feasibility.md` to `facts/managed-redis-rollout-and-limits.md` (Another case where mocks prove inputs, not deployability).
* **Update**: Linked `requirements/traefik-sidecar-allowlist-and-client-ip.md` to `facts/production-readiness-gaps.md` (Addresses the public-surface item in #193).
* **Update**: Linked `requirements/foundry-subnet-only-network-acl.md` to `decisions/no-op-deploy-controls.md` (Disabled features must keep --expect-no-changes passing).
* **Update**: Linked `facts/managed-redis-rollout-and-limits.md` to `decisions/no-op-deploy-controls.md` (Enabling Redis is a one-time expected diff).
* **Update**: Linked `facts/fresh-stack-startup-requirements.md` to `bugs/key-vault-access-policy-replace.md` (Access policy ordering).
* **Update**: Linked `facts/custom-domains-declarative-certificate-manual.md` to `decisions/no-op-deploy-controls.md` (Declarative ingress is one source of unexpected deploy diffs).
* **Update**: Linked `decisions/no-op-deploy-controls.md` to `architecture/pulumi-state-store-bootstrap.md` (The preview gate refuses when bootstrap would change Azure).
* **Update**: Linked `bugs/azure-subscription-and-expired-login.md` to `architecture/pulumi-state-store-bootstrap.md` (Both concern what deploy does before Pulumi runs).
* **Update**: Linked `requirements/keep-llmaven-blob-container.md` to `decisions/rebrand-keeps-deployed-identifiers.md` (One of the identifiers that must not change).
* **Update**: Linked `bugs/image-defaults-point-at-frozen-packages.md` to `decisions/rebrand-keeps-deployed-identifiers.md` (Part of the unfinished rename).
* **Update**: Linked `facts/rebrand-compat-and-safe-names.md` to `decisions/rebrand-keeps-deployed-identifiers.md` (Compatibility details for the same rebrand).
* **Update**: Linked `facts/project-history-superseded-directions.md` to `decisions/platform-only-scope.md` (Earlier stages of the project scope).
* **Update**: Linked `decisions/data-pipeline-moves-to-llmoxie-analysis.md` to `decisions/platform-only-scope.md` (The same scoping decision applied to the data pipeline).
* **Creation**: Documented concept `decisions/calver-with-hatch-vcs.md` (Releases use CalVer vYYYY.M.MICRO, with the version from hatch-vcs (planned)).
* **Creation**: Documented concept `facts/production-readiness-gaps.md` (Production-readiness gaps are tracked in #193, and some settings do less than they suggest).
* **Creation**: Documented concept `facts/known-stale-docs.md` (Docs and comments that disagree with the code at e248584).
* **Creation**: Documented concept `requirements/pyproject-runtime-deps-gap.md` (jsonlines and mlflow are imported by the package but declared only in pixi.toml).
* **Creation**: Documented concept `facts/image-builds-and-workflow-pinning.md` (Image builds never run on PRs, and workflow actions are pinned by SHA).
* **Creation**: Documented concept `facts/ruff-rules-pinned-explicitly.md` (Ruff rules are pinned explicitly so hook updates can't widen lint policy).
* **Creation**: Documented concept `bugs/ci-false-green-and-repro-traps.md` (CI was once green while tests failed, and two traps make CI failures hard to reproduce).
* **Creation**: Documented concept `facts/pixi-channel-change-resolves-all-envs.md` (Changing workspace channels re-solves every Pixi environment).
* **Creation**: Documented concept `facts/pixi-lock-hash-needs-ci-version.md` (Any pyproject.toml edit can stale pixi.lock, and a newer local Pixi hides it).
* **Creation**: Documented concept `decisions/minio-replaced-by-azurite.md` (Azurite replaced MinIO for local MLflow artifacts).
* **Creation**: Documented concept `decisions/config-updates-ruamel-round-trip.md` (Config updates use a ruamel.yaml round-trip, not regex or PyYAML).
* **Creation**: Documented concept `bugs/cli-output-data-safety.md` (CLI tidy-ups can corrupt captured values).
* **Creation**: Documented concept `facts/request-log-sources-differ.md` (ADLS logs, LiteLLM spend logs and MLflow traces are different datasets).
* **Creation**: Documented concept `bugs/infra-extract-completeness.md` (infra extract has no pagination, and a malformed response still skips a day).
* **Creation**: Documented concept `decisions/infra-extract-design.md` (infra extract sits under infra and writes day-partitioned JSONL).
* **Creation**: Documented concept `requirements/secret-loading-logs-use-pulumi-log.md` (Secret-loading diagnostics stay on pulumi.log).
* **Creation**: Documented concept `facts/loadtest-fallback-detection.md` (Load test fallback detection depends on /model/info, because /v1/messages hides fallbacks).
* **Creation**: Documented concept `decisions/stay-on-oss-litellm-gateway.md` (LiteLLM stays as the gateway; OSS limits shape what must be built around it).
* **Creation**: Documented concept `architecture/litellm-config-and-logger-mounted-as-secrets.md` (LiteLLM's config and logger are mounted at deploy time, not built into the image).
* **Creation**: Documented concept `requirements/litellm-master-and-salt-key.md` (Never add a fresh salt key to an existing database, and rotate the master key by migration).
* **Creation**: Documented concept `facts/litellm-image-install-quirks.md` (The LiteLLM image has no pip, wget or curl, and needs mlflow-skinny).
* **Creation**: Documented concept `decisions/litellm-image-digest-pin-and-one-way-upgrade.md` (LiteLLM is pinned by version and digest, and upgrades across migrations are one-way).
* **Creation**: Documented concept `bugs/backup-config-not-gitignored.md` (llmaven-backup-config.yaml isn't covered by .gitignore).
* **Creation**: Documented concept `bugs/failed-pg-dump-can-consume-retention.md` (A failed pg_dump can leave a truncated blob that counts toward retention).
* **Creation**: Documented concept `bugs/backup-job-default-traps.md` (Backup job defaults disagree with the docs and may miss the important database).
* **Creation**: Documented concept `architecture/backup-storage-isolated-stack.md` (Backup storage is a separate Pulumi stack; the backup job stays in the main stack).
* **Creation**: Documented concept `facts/floci-az-e2e-feasibility.md` (Azure E2E through floci-az needs a spike and can't replace a real preview).
* **Creation**: Documented concept `requirements/traefik-sidecar-allowlist-and-client-ip.md` (Path-level access control needs a sidecar with an allowlist (planned)).
* **Creation**: Documented concept `requirements/foundry-subnet-only-network-acl.md` (Stack-managed Foundry accepts traffic only from the Container Apps subnet (planned)).
* **Creation**: Documented concept `facts/managed-redis-rollout-and-limits.md` (Managed Redis arrives automatically on the next deploy and is unproven live).
* **Creation**: Documented concept `facts/fresh-stack-startup-requirements.md` (What a fresh stack needs for LiteLLM to start).
* **Creation**: Documented concept `facts/custom-domains-declarative-certificate-manual.md` (Custom domains are declarative; issuing the certificate stays manual).
* **Creation**: Documented concept `decisions/no-op-deploy-controls.md` (Making a deploy a true no-op: revisions, probes and the preview gate).
* **Creation**: Documented concept `bugs/key-vault-access-policy-replace.md` (Key Vault access policies get wiped by two separate mechanisms).
* **Creation**: Documented concept `bugs/azure-subscription-and-expired-login.md` (The configured subscription has two paths, and az account show doesn't prove the login works).
* **Creation**: Documented concept `architecture/pulumi-state-store-bootstrap.md` (The Pulumi state store and resource group live outside the Pulumi program).
* **Creation**: Documented concept `requirements/keep-llmaven-blob-container.md` (Never drop the llmaven blob container from storage config).
* **Creation**: Documented concept `bugs/image-defaults-point-at-frozen-packages.md` (infra init and schema defaults still point at frozen llmaven-* images).
* **Creation**: Documented concept `facts/rebrand-compat-and-safe-names.md` (Rebrand compatibility plan, and llmaven names that look like deployed state but aren't).
* **Creation**: Documented concept `decisions/rebrand-keeps-deployed-identifiers.md` (The llmoxie rebrand must not rename identifiers that carry live state).
* **Creation**: Documented concept `facts/project-history-superseded-directions.md` (Earlier directions that were dropped, and PRs closed with no stated reason).
* **Creation**: Documented concept `decisions/data-pipeline-moves-to-llmoxie-analysis.md` (New data-pipeline features belong in llmoxie-analysis, not src/llmaven/data).
* **Creation**: Documented concept `decisions/platform-only-scope.md` (The repo is the LiteLLM and MLflow platform only; RAG lives in llmoxie-rag).

## 2026-10-28
* **Creation**: Initialized OKF v0.2 knowledge bundle.
