FROM ghcr.io/mlflow/mlflow:v3.6.0

RUN pip install --no-cache-dir "psycopg2-binary==2.9.11" "boto3==1.40.73"

ENTRYPOINT ["mlflow", "server"]
