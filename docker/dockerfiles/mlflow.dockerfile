FROM ghcr.io/mlflow/mlflow:v3.6.0

RUN pip install --no-cache-dir "psycopg2-binary==2.9.11" "azure-storage-blob==12.31.0"

ENTRYPOINT ["mlflow", "server"]
