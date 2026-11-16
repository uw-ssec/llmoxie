"""Tests for CLI infra commands."""

# keycloak.image must be pinned by digest once Keycloak is enabled.
PINNED_KEYCLOAK_IMAGE = "ghcr.io/uw-ssec/llmoxie-keycloak:26.5.5@sha256:" + "b" * 64

# console.image must be pinned by digest once the console is enabled.
PINNED_CONSOLE_IMAGE = "ghcr.io/uw-ssec/llmoxie-console:dev@sha256:" + "c" * 64
