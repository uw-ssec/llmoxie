# Pinned by digest: tag v1.108.6 (signed upstream release).
FROM ghcr.io/berriai/litellm:v1.108.6@sha256:c64fe10f82a1f77906f88574f954317c50f67c617e0c97b70ac8fc61b74d3ec3

# Since v1.106.x the image ships a uv-built venv with no pip executable, but the
# bundled ensurepip works. Re-pinning litellm makes the build fail instead of
# letting mlflow's dependencies silently replace the verified litellm package.
# mlflow-skinny covers the LiteLLM mlflow callback; full mlflow caps
# cryptography<47 and would downgrade the base image's patched cryptography.
RUN python -m ensurepip \
 && python -m pip install --no-cache-dir \
      "litellm==1.108.6" "mlflow-skinny==3.6.0" "azure-storage-blob>=12.0.0,<13" "azure-identity>=1.0.0,<2"
