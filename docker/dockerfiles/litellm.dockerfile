FROM ghcr.io/berriai/litellm:v1.82.3-stable

RUN pip install --no-cache-dir "mlflow==3.6.0" "azure-storage-blob>=12.0.0" "azure-identity>=1.0.0"

# Copy AdlLogger module for LiteLLM callbacks. LiteLLM will always look in the same directory as config.yaml for callback modules, so we copy it there.
COPY src/llmaven/proxy/adl_logger.py /app/config/adl_logger.py
