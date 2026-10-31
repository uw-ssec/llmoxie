# Pinned by digest: tag v1.106.6 (signed upstream release).
FROM ghcr.io/berriai/litellm:v1.106.6@sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06

# Since v1.106.x the image ships a uv-built venv with no pip executable, but the
# bundled ensurepip works. Re-pinning litellm makes the build fail instead of
# letting mlflow's dependencies silently replace the verified litellm package.
# mlflow-skinny covers the LiteLLM mlflow callback; full mlflow caps
# cryptography<47 and would downgrade the base image's patched cryptography.
RUN python -m ensurepip \
 && python -m pip install --no-cache-dir \
      "litellm==1.106.6" "mlflow-skinny==3.6.0" "azure-storage-blob>=12.0.0,<13" "azure-identity>=1.0.0,<2"
