FROM ghcr.io/berriai/litellm:v1.79.1-stable

RUN pip install --no-cache-dir "mlflow==3.6.0"

RUN mkdir -p /app

COPY config.yaml /app/config.yaml
