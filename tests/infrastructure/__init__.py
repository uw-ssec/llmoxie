"""Tests for CLI infra commands."""

# keycloak.image must be pinned by digest once Keycloak is enabled.
PINNED_KEYCLOAK_IMAGE = "ghcr.io/uw-ssec/llmoxie-keycloak:26.5.5@sha256:" + "b" * 64
