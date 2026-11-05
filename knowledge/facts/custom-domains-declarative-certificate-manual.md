---
type: Fact
title: Custom domains are declarative; issuing the certificate stays manual
description: "A hostname not in custom_domains is removed by the next deploy, and Pulumi can't issue the managed certificate in one pass because attach, certificate and bind form a cycle."
tags: [azure, container-apps, tls]
generated: { by: "claude-code:claude-opus-5-5", at: "2026-11-05T22:22:48Z" }
status: stable
code_refs: [src/llmaven/infrastructure/resources/container_apps.py, src/llmaven/infrastructure/config/schema.py, tests/infrastructure/test_custom_domains.py]
sources:
  - resource: "PR #204"
  - resource: "issue #193 (custom-domains comment)"
  - resource: tests/infrastructure/test_custom_domains.py
---

**Status at e248584:** binding is implemented (#204). Issuing certificates from Pulumi is design only.

Ingress is declarative. A hostname not listed in `custom_domains` is removed by the next deploy, including one bound by hand; that happening to a deployment is why #204 added the setting. Removal of unlisted hostnames is intended.

Each entry binds with SNI to a certificate that must already exist under `managedCertificates/`. Hand-uploaded `certificates/` aren't supported. First issuance is a manual `az containerapp hostname add`, then `hostname bind --validation-method CNAME`.

Pulumi can't do this in one pass. Azure issues a managed certificate only after the hostname is attached, azure-native has no standalone binding resource (unlike Terraform's `azurerm_container_app_custom_domain`), and attach, certificate and bind form a cycle on one `ContainerApp`. A two-pass config-driven design is in a #193 comment.

The CNAME must be DNS-only, since a proxied Cloudflare record fails validation. The `asuid` TXT verification ID differs per subscription.

**Sources:** PR #204; issue #193 (custom-domains comment); tests/infrastructure/test_custom_domains.py

# Related Concepts
- [Making a deploy a true no-op: revisions, probes and the preview gate](../decisions/no-op-deploy-controls.md): Declarative ingress is one source of unexpected deploy diffs
