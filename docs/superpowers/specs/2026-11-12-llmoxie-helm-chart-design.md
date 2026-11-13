# llmoxie Helm Chart Design

- **Date:** 2026-11-12
- **Issue:** [#236](https://github.com/uw-ssec/llmoxie/issues/236), project 1
  ("The chart")
- **Branch:** `llmoxie-helm`
- **Status:** Draft. The open questions at the end are not settled, so this is
  not ready to plan from.
- **AI assistance:** drafted with `claude-code:claude-fable-5-2` from a design
  discussion with a maintainer. Sections say which parts the maintainer decided
  and which are proposals.

## Why

Partner organizations want their own llmoxie instance on infrastructure they
own: AWS, GCP, or an HPC center. Today llmoxie deploys only to dedicated Azure
services through a Pulumi program. A Helm chart lets UW SSEC install the same
platform on any conformant Kubernetes cluster (AKS, EKS, GKE, K3s, RKE2). After
the install the partner's own staff run it, with UW SSEC supporting as needed.

## Goals

Decided by the maintainer:

- Production ready from the first release.
- Batteries included: one install brings up LiteLLM, MLflow, PostgreSQL, Redis,
  and backup and restore.
- Every battery can be switched off or replaced by something the site already
  runs, the way `mlflow.enabled` works in the Pulumi config today.
- Installs next to existing workloads on a cluster the partner already operates,
  including one that already runs JupyterHub.
- k3s replaces docker-compose as the laptop and CI stack.
- Follow the direction of
  [nebari-infrastructure-core](https://github.com/uw-ssec/nebari-infrastructure-core)
  (NIC) and borrow its foundational pieces and patterns where they fit.
- RustFS is the bundled object store. That makes S3 the protocol llmoxie's code
  speaks to object storage.
- The Azure install on AKS runs RustFS like every other site. The chart does not
  speak Azure Blob.
- A site's database backups live in a separate place from the cluster they
  protect. The local stack models that place with a second cluster.
- A restore must bring back the LiteLLM service.
- A site keeps the LiteLLM keys in its own secret store, never beside the
  backups. A salt key encrypts stored credentials from the first install, and
  the chart generates keys only when told to.

## Non-goals

Proposed, to confirm. Each is a later project in #236:

- Connecting a JupyterHub (project 2).
- Creating a cluster, including the AKS cluster for Azure (project 3).
- Moving the Azure production instance and its data (project 4).
- Hosting models. Each site points LiteLLM at its own provider.

## Anti-goals

Proposed, to confirm. The chart has failed if:

- It runs only where Azure services exist.
- A competent Kubernetes administrator cannot upgrade, back up, and restore it
  from the chart's own documentation.
- An upgrade, reinstall, or restore changes the LiteLLM salt key. That key
  encrypts credentials stored in the database
  (`requirements/litellm-master-and-salt-key` in project memory).
- A production install runs on keys that exist only inside the cluster.

## What the prototype is

`charts/llmoxie/` on this branch, installed on a local k3s cluster by
`pixi run -e llmaven k3s-up` and checked by `pixi run -e llmaven k3s-smoke`. It
is throwaway: it exists to test the shape below, and keeping any of it is a
decision to make after this design is settled.

| Piece          | Prototype implementation                                                        |
| -------------- | ------------------------------------------------------------------------------- |
| LiteLLM        | Deployment and Service; request logs go to S3 through `s3_logger.py`            |
| MLflow         | Deployment and Service; artifacts under `s3://mlflow/`                          |
| PostgreSQL     | CloudNativePG `Cluster`, PostgreSQL 17, databases `litellm_db` and `mlflow_db`  |
| Redis          | Valkey 8.1, one replica, no persistence                                         |
| Object storage | RustFS 1.0.5, one replica, on a persistent volume                               |
| Backup         | One `pg_dump` `CronJob` per database, writing to RustFS in a second cluster     |
| Cluster layer  | CloudNativePG operator chart 0.29.1, installed by `scripts/k3s/up.sh`           |
| Local clusters | k3d 5.9.0 (k3s in Docker): `llmoxie` and `llmoxie-backup` on one Docker network |

Changes outside the chart that S3 needed:

- `docker/dockerfiles/mlflow.dockerfile` adds `boto3`.
- `docker/dockerfiles/backup.dockerfile` adds `s3fs`, and
  `scripts/backup_postgres.py` accepts `s3://` destinations.
- The LiteLLM image is unchanged; it already ships `boto3`.

Azure Blob still works in all three, so the Pulumi deployment is unaffected.
`k3s-up` builds the three images from the local Dockerfiles and loads them into
the cluster, as docker-compose built them, because the published images do not
have these changes yet.

## What the prototype showed

Verified on the local cluster on 2026-11-12:

- `k3s-up` took 102 seconds to create the main cluster, load the already built
  images, and install the chart. An earlier single-cluster run that also built
  the three images took 155 seconds. The pods were ready within a minute of the
  chart install.
- The smoke test passes eight checks: LiteLLM liveness, a chat completion
  through a mock model, MLflow health, an MLflow trace for that request, an
  MLflow artifact stored in the `mlflow` bucket, the request log object for that
  request, LiteLLM's connections to Redis, and a backup dump written to the
  backup cluster by a manual run of the backup job.
- The backup is independent of the main cluster. With the main cluster stopped,
  the dump was read from the backup cluster (276,921 bytes, starting with
  `PGDMP`, the `pg_dump` custom-format header). The main cluster's RustFS holds
  no `backups` bucket.
- The restore drill (`pixi run -e llmaven k3s-restore-drill`) passes in 175
  seconds. It seeds a virtual key and a model stored in the database, backs up,
  deletes the main cluster, builds a new one, and restores `litellm_db` from the
  backup cluster with LiteLLM stopped. On LiteLLM 1.108.6, with a salt key set:
  - Before the restore, the new cluster rejects the virtual key (HTTP 401).
  - After the restore, with a new master key and a new salt key, the virtual key
    works again, but the model stored in the database is gone ("Invalid model
    name").
  - With only the old salt key put back, and the master key still new, the
    stored model answers again.
  - An earlier run without a salt key gave the same result with the master key
    in the salt key's place: the stored model came back only under the old
    master key.
- After the main cluster was stopped and started, all eight checks passed again,
  and the objects, MLflow traces, and spend-log rows written before the stop
  were still there.
- Objects in every bucket were still there after the RustFS pod was deleted and
  recreated (checked before backups moved to the second cluster).
- The generated LiteLLM keys (checked for the master key, before the salt key
  was added), RustFS keys, and Redis password are unchanged after
  `helm upgrade`, and no pod restarts.
- Each toggle renders as intended: `mlflow.enabled=false` removes MLflow and its
  callbacks, `redis.mode=disabled` removes Redis and its settings, and setting
  PostgreSQL, Redis, and object storage to `external` with backups off leaves
  only LiteLLM and MLflow. External storage with no endpoint leaves
  `AWS_ENDPOINT_URL` unset, which is what AWS S3 needs.
- The chart refuses `litellm.replicas > 1` without Redis, which carries over the
  rule the Pulumi program enforces today.

Traps found:

- **k3s can fail on first boot and stay failed.** Once, a new cluster's k3s shut
  down seconds after starting ("cloud-controller-manager exited ... forbidden")
  and did so again on every restart, while `k3d cluster create --wait` reported
  success. Two clusters created the same way right after came up fine, so the
  cause is a race and not the shared network. `up.sh` now checks that a new
  cluster's node is Ready and recreates the cluster once if it is not.
- **The operator must exist first.** Helm cannot install a `Cluster` resource
  before the CloudNativePG operator defines it. The chart checks and fails with
  a message that says so.
- **Nothing creates buckets.** On Azure the storage stacks create the
  containers. Each consumer in the chart now checks for its bucket and creates
  it only when missing, so buckets a site made in advance are left alone. On the
  Azure path, `adlfs`'s `makedirs` does not create a container and reports no
  error.
- **`pg_dump` and the server must share a major version.** The backup image
  ships `pg_dump` 17.11. A newer server cannot be dumped at all. An older one
  can, but the restore then trips on a setting the newer `pg_dump` writes: into
  PostgreSQL 16, `pg_restore` rejected `transaction_timeout` as an unrecognized
  parameter and exited non-zero. The chart now bundles PostgreSQL 17. The Azure
  deployment runs the same image against PostgreSQL 16, so a restore there would
  likely report the same error (inferred, not tested).
- **The kubelet deletes loaded images under disk pressure.** With the Docker
  VM's disk 93% full, the kubelet garbage-collected the backup image between job
  runs. An image loaded from the host cannot be pulled again, so the next backup
  job hung on `ErrImagePull`. `up.sh` turns image garbage collection off for the
  main local cluster. A local registry would be the sturdier fix.
- **Cross-cluster names take a minute or two.** k3d adds the backup cluster's
  node name to the main cluster's DNS after creation. A backup started sooner
  failed to resolve it. `up.sh` now returns only once a pod can reach the store.
- **Service links.** Kubernetes injects `<SERVICE>_PORT` variables into every
  pod. A Service named `mlflow` would set `MLFLOW_PORT=tcp://...`, which
  `mlflow server` reads as its listen port. Every pod sets
  `enableServiceLinks: false`.
- **Generated secrets depend on `lookup`.** Helm's `lookup` returns nothing
  under `helm template` and under Argo CD, so a generated key would change on
  every render there. NIC is GitOps based, so this matters; see Secrets below.
- **`pixi.lock` cannot take new dependencies today.** Every Pixi release that
  can still solve this workspace writes lock format 7, and CI's pinned Pixi
  0.63.2 cannot read it. The prototype runs helm and kubectl through pinned
  `pixi exec` wrappers (`scripts/k3s/bin/`) instead of adding them to a feature.
  This was observed on one machine; bumping CI's Pixi and re-locking would
  confirm it and remove the workaround.

Not prototyped: restore as a chart feature (the drill is a script), restoring
`mlflow_db`, high availability, ingress and TLS, network policies, more than one
LiteLLM replica, resource requests and security contexts, external modes against
real services (they were rendered, not run), a CI workflow, and removing
docker-compose. The new S3 code paths have no unit tests.

## Proposed design

Everything in this section is a proposal for the maintainer to confirm or
change.

### Two layers

NIC installs operators once per cluster and applications on top. The chart
follows that split:

- **Cluster layer:** the CloudNativePG operator, and whatever ingress and
  certificate handling the site uses. Installed once per cluster, and skipped
  where the site already has them.
- **llmoxie release:** everything else, in one namespace, with no cluster-wide
  objects. This is what lets it sit beside a JupyterHub without touching it.

### Three modes per battery

| Battery        | `bundled`               | `external`                             | `disabled`                    |
| -------------- | ----------------------- | -------------------------------------- | ----------------------------- |
| PostgreSQL     | CloudNativePG `Cluster` | Secret with host, port, user, password | Not allowed                   |
| Redis          | Valkey                  | Host plus a password Secret            | Only with one LiteLLM replica |
| Object storage | RustFS                  | Any S3 endpoint plus a key Secret      | Not allowed                   |
| MLflow         | `mlflow.enabled=true`   | To decide                              | `mlflow.enabled=false`        |
| Backup         | Not offered             | An S3 destination outside the cluster  | `backup.enabled=false`        |

### PostgreSQL

- CloudNativePG, as NIC chose in its ADR-0007. One `Cluster` holds both
  databases.
- PostgreSQL 17, the major version of the `pg_dump` in the backup image, so
  dumps restore without errors. Azure runs 16; a dump from 16 restores forward
  into 17 (inferred, not tested).
- Production default of three instances for failover; one instance for laptops
  and CI.
- Backup and restore move to CloudNativePG's own continuous backup to object
  storage, which gives point-in-time restore. The `pg_dump` job stays as an
  optional logical export. A restore is a new `Cluster` bootstrapped from the
  backup, documented as a runbook and exercised in CI.

### Redis

Valkey, single node, no persistence. It holds rate-limit, budget, and router
state, so losing it resets counters and loses no records. Valkey is BSD licensed
and does not depend on Bitnami images.

### Object storage

Decided by the maintainer: the bundled store is
[RustFS](https://github.com/rustfs/rustfs), so llmoxie talks to object storage
over the S3 API.

How it was chosen. llmoxie's code spoke only the Azure Blob protocol, and AWS,
GCP, and HPC sites have no Blob endpoint. NIC does not solve this either: its
ADR-0012 on object storage for applications was rejected. Four S3-compatible
servers were run as single pods on the local cluster and probed with `boto3` and
`s3fs` on twelve behaviors (multipart upload and abort, paged and delimited
lists, range reads, copy, presigned URLs, streamed writes, batch delete,
lifecycle rules, and keys such as `a/b` beside `a/b/c`):

| Candidate              | Probe | License    | Notes                                                            |
| ---------------------- | ----- | ---------- | ---------------------------------------------------------------- |
| RustFS 1.0.5           | 12/12 | Apache-2.0 | One binary, one volume. 1.0.0 shipped on 2026-09-16              |
| SeaweedFS 4.53         | 12/12 | Apache-2.0 | Twelve years of releases; heavier, starts services we don't need |
| Garage 2.5.0           | 12/12 | AGPL-3.0   | Smallest; needs a scripted layout and key bootstrap              |
| Versity gateway 1.11.0 | 9/12  | Apache-2.0 | An S3 front for a filesystem, not a store                        |

CubeFS was read, not run: its Helm chart needs host networking, host paths,
privileged pods, hand-labeled nodes, and at least three masters, so it belongs
in `external` mode, like Ceph. MinIO's repository is archived.

Consequences:

- `bundled` is one RustFS pod on one volume. It has no redundancy, and RustFS
  documents that a single-drive deployment cannot be expanded in place. Database
  backups never go there.
- `external` takes any S3 endpoint and a Secret with an access key and a secret
  key. It is the mode for sites with their own store: S3 on AWS, Ceph or CubeFS
  at an HPC center.
- RustFS is young. Because the interface is plain S3, replacing the bundled
  server later is a values change and a data copy.

Also decided by the maintainer: the AKS install runs RustFS like every other
site. So the chart speaks S3 only, and every site runs the same storage path
that the laptop and CI stack tests.

What follows from that (inferred, to confirm):

- The Azure Blob code (`adl_logger.py`, `wasbs://` artifacts, `az://` backups)
  serves only the Pulumi Container Apps deployment and retires with it in
  project 4.
- Moving production in project 4 includes copying blobs from the storage account
  into RustFS. MLflow experiments keep the artifact location they were created
  with, so existing ones will still point at `wasbs://` until that is rewritten.
  Project memory records the same trap from the MinIO to Azurite change.
- On AKS the bundled store's durability is that of one Azure managed disk.

Still open, proposed here:

- **One request logger.** The prototype adds `s3_logger.py` next to the Azure
  `adl_logger.py`, with the same record and key layout. The real change is one
  logger in the LiteLLM image. LiteLLM also ships a built-in S3 logging
  callback, which would need no custom code but writes a different record than
  `llmaven infra extract` reads today.
- **MLflow artifact access.** With storage inside the cluster, MLflow clients
  outside it cannot reach the bucket. Running MLflow with `--serve-artifacts`
  sends uploads through the tracking server instead.

### Backup destination

Decided by the maintainer: a site's database backups live in a separate place
from the cluster. Today's Azure deployment follows the same rule with a separate
Pulumi stack for backup storage, so that destroying the main stack cannot take
the backups with it.

In the chart (proposed, to confirm):

- `backup.storage` names the destination: an S3 endpoint, region, bucket, and a
  Secret with the keys. It is configured separately from application storage.
- The chart bundles no backup destination. With `backup.enabled=true` and no
  destination it refuses to install, so running without backups is a choice
  someone makes, not a default someone inherits.
- It also refuses a destination that is the release's own bundled store. It
  cannot check more than that; whether the destination is really somewhere else
  is the site's responsibility.

In the local stack: a second k3d cluster, `llmoxie-backup`, runs only RustFS.
Both clusters join one Docker network, and the main cluster reaches the backup
store at the backup cluster's node name and a pinned NodePort. `up.sh` generates
the store's keys once and hands them to the llmoxie release as a Secret.

Still open: whether the backup engine stays `pg_dump`. The PostgreSQL section
proposes CloudNativePG's continuous backup, which would write to this same
destination.

### Restore

Decided by the maintainer: a restore must bring back the LiteLLM service. That
means its virtual keys, users, teams, budgets, and the models and provider
credentials stored in the database, all of which live in `litellm_db`.

The procedure the drill proved, for a cluster that is gone:

1. Install the chart on a new cluster, supplying the old salt key. The master
   key may be new.
2. Stop LiteLLM, so it holds no connections and writes nothing.
3. Run `pg_restore --clean --if-exists` on the dump from the backup destination,
   into `litellm_db`.
4. Start LiteLLM.

What a site must keep outside the cluster to do this:

- The dump, which the backup job already sends there.
- The LiteLLM salt key. LiteLLM encrypts stored provider credentials with it, so
  a restore under a different salt key brings back the virtual keys but not the
  stored models.
- The values the chart was installed with.

Proposed, to confirm:

- Restore ships as a documented runbook plus a Job the chart can render on
  request, using the backup image, which already has `pg_restore` and the
  storage client.
- The same procedure restores `mlflow_db`. That was not exercised.
- A daily `pg_dump` can lose up to a day of keys and spend. If that is too much,
  it argues for CloudNativePG's continuous backup.

### Ingress and TLS

- Gateway API routes, which fit NIC's Envoy Gateway and the Traefik that k3s
  ships.
- The public route exposes only an allowlist of exact LiteLLM paths, as the
  Traefik sidecar does on Azure. Management routes stay reachable only inside
  the cluster, and a network policy limits which pods may call them.
- TLS in the three modes NIC offers: self-signed, Let's Encrypt, or a
  certificate the site supplies.

### Secrets

- Every secret accepts an existing Kubernetes Secret, so sites can feed them
  from their own secret store.
- LiteLLM has two keys, read from one Secret (`litellm.keys.existingSecret`,
  entries `master-key` and `salt-key`). Decided by the maintainer:
  - The site keeps both in its own secret store (AWS Secrets Manager, GCP Secret
    Manager, Azure Key Vault, Vault), under different access than the backup
    destination. A site without one keeps them in an encrypted file or a
    password manager and creates the Secret by hand.
  - The chart never writes a key outside the cluster, and no copy sits beside
    the backups. The dump holds provider credentials encrypted with the salt
    key, and virtual keys only as hashes, so a stolen dump is of limited use
    without the key.
  - The salt key is set from the first install and never changes. The master key
    is then only the admin credential and can be rotated.
  - Without `existingSecret` the chart refuses to install. Setting
    `litellm.keys.generate=true` makes it generate both keys in the cluster; the
    local and CI stacks do this.
- One Secret for both keys, not two, is the agent's call.
- The Redis password and the RustFS keys are still generated once and kept
  across upgrades when no existing Secret is given.
- GitOps installs must supply existing Secrets, because generation does not work
  there. NIC creates such secrets once, outside git; the chart documentation
  would say the same.
- How the Secret gets from the secret store into the cluster (External Secrets
  Operator, a CSI driver, or by hand) is left to the site. Whether the cluster
  layer should offer one is part of the cluster-layer question below.
- The Azure production move is the exception: its database holds credentials
  encrypted with the master key and no salt key, and adding a salt key there
  breaks their decryption (#200). That move keeps its current arrangement or
  migrates deliberately; it is designed in the production-move project.

### Images and configuration

- The chart pins each image by digest and ties them to the chart's `appVersion`.
  The prototype uses `latest`.
- The request logger moves into the LiteLLM image. The prototype mounts
  `charts/llmoxie/files/s3_logger.py` from a ConfigMap, beside the LiteLLM
  config.

### Local and CI stack

- k3d runs k3s in Docker, so it needs nothing beyond the Docker the project
  already requires, on macOS and on CI's Ubuntu runners.
- The kubeconfigs are written under `.kube/` and never merged into
  `~/.kube/config`, so the tasks cannot reach a real cluster by accident.
- Two clusters cost about 500 MiB of extra memory for the second k3s server.
- `k3s-up` builds the service images from the local Dockerfiles and loads them
  into the cluster, so a Dockerfile change is tested before it is published.
- The restore drill runs in CI as well as on laptops, so a change that breaks
  restore is caught before a site needs one.
- The smoke script grows into a pytest suite that runs against any kubeconfig,
  following NIC's ADR-0017, so the same checks prove a partner install.
- docker-compose is removed once the k3s stack covers what contributors use it
  for.

## Open questions

For the maintainer, most important first:

1. **Backup engine.** Keep the `pg_dump` job, or move to CloudNativePG's
   continuous backup with point-in-time restore?
2. **Cluster layer packaging.** Is the cluster layer a second chart in this
   repository, a documented prerequisite, or something NIC installs?
3. **Installer.** Does `llmaven infra` grow a Kubernetes path that drives the
   chart from a config file, as NIC's CLI does, or is plain `helm install` with
   a values file the interface?
4. **Monitoring.** What replaces the Azure alerts and budget from #222?
   Prometheus rules shipped with the chart would be the Kubernetes equivalent,
   but they assume the site runs Prometheus.
5. **HPC.** Does "HPC" always mean a Kubernetes cluster run by the HPC center?
6. **First partner.** Whose environment is the first real target? It decides
   which external modes get tested first.
7. **Pixi.** Bump CI's pinned Pixi and re-lock, so helm and kubectl become
   ordinary dependencies?
8. **MLflow `external`.** Should a site be able to point LiteLLM at an MLflow it
   already runs?

## Prototype layout

```
charts/llmoxie/
  Chart.yaml
  values.yaml               # battery modes and defaults
  ci/k3s-values.yaml        # local stack: NodePorts and a mock model
  files/s3_logger.py        # request logger for S3
  templates/                # litellm, mlflow, postgres, redis, object-storage, backup
scripts/k3s/
  install_k3d.sh            # pinned k3d download, checksum verified
  up.sh                     # both clusters, local images, operator, chart
  backup-store.yaml         # RustFS for the backup cluster
  smoke.py                  # eight checks against the local stack
  restore_drill.py          # destroy the main cluster, restore LiteLLM
  bin/helm, bin/kubectl     # pinned `pixi exec` wrappers
docker/dockerfiles/         # mlflow adds boto3, backup adds s3fs
scripts/backup_postgres.py  # accepts s3:// destinations
pixi.toml                   # k8s feature: tasks and KUBECONFIG, no dependencies
```
