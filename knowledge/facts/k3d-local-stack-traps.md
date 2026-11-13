---
type: Fact
title: "Three traps in the local k3d stack: first-boot failure, image garbage collection, and slow cross-cluster DNS"
description: "k3s can shut down for good on first boot while k3d reports success, the kubelet deletes host-loaded images when the disk is over 85% full, and a second cluster's node name resolves only a minute or two after creation."
tags: [k3d, k3s, local-stack, kubernetes]
generated: { by: "claude-code:claude-fable-5-2", at: "2026-11-12T22:17:35Z" }
status: stable
code_refs: [scripts/k3s/up.sh]
---

**Status at a7e7d32:** observed on 2026-11-12 with k3d 5.9.0 and k3s v1.35.5+k3s1 on colima (macOS arm64), in the uncommitted prototype on branch `llmoxie-helm`. `scripts/k3s/up.sh` works around all three.

- **First-boot failure.** Once, a new cluster's k3s logged `Shutdown request received: cloud-controller-manager exited ... configmaps "extension-apiserver-authentication" is forbidden` two seconds after starting and did the same on every restart, while `k3d cluster create --wait` returned success. Two clusters created the same way right afterwards were fine, so it is a race (inferred from that, not reproduced on demand). `up.sh` checks that a new cluster's node becomes Ready and recreates the cluster once if not; that recovery path has not fired since, so it is untested.
- **Image garbage collection.** The service images are built on the host and loaded with `k3d image import`. With the Docker VM's disk at 93%, above the kubelet's 85% threshold, the kubelet deleted the backup image between job runs, and the next job hung on `ErrImagePull` because a loaded image cannot be pulled. `up.sh` creates the main cluster with `--kubelet-arg=image-gc-high-threshold=100`. A local registry would be the sturdier fix and was not tried.
- **Cross-cluster DNS.** The backup job reaches the backup cluster at `k3d-llmoxie-backup-server-0:30900` over the shared Docker network `llmoxie-local`. k3d writes that name into the main cluster's CoreDNS `NodeHosts`, and pods could not resolve it for the first minute or two. `up.sh` returns only once a pod can connect.

**Sources:** scripts/k3s/up.sh; docs/superpowers/specs/2026-11-12-llmoxie-helm-chart-design.md

# Related Concepts
- [Database backups live outside the cluster they protect](../requirements/backups-outside-the-cluster.md): The second local cluster exists because backups must live outside the main one
