FROM ghcr.io/berriai/litellm:v1.82.3-stable

RUN pip install --no-cache-dir "mlflow==3.6.0" "azure-storage-blob>=12.0.0,<13" "azure-identity>=1.0.0,<2"
