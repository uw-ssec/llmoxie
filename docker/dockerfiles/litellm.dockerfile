FROM ghcr.io/berriai/litellm:v1.82.3-stable

RUN pip install --no-cache-dir "mlflow==3.6.0"
