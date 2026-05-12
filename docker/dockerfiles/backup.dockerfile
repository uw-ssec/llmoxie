FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fsspec adlfs pyyaml

WORKDIR /app
COPY scripts/backup_postgres.py .

ENTRYPOINT ["python", "backup_postgres.py"]
