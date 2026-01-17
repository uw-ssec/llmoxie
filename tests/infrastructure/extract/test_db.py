"""Integration test for LiteLLM log extraction (optional)."""

import os
from datetime import datetime
from pathlib import Path

import pytest

from llmaven.infrastructure.extract.litellm import LiteLLMLogExtractor


@pytest.mark.integration
def test_extract_against_real_database(tmp_path):
    host = os.getenv("LITELLM_DB_HOST")
    port = os.getenv("LITELLM_DB_PORT")
    database = os.getenv("LITELLM_DB_NAME")
    user = os.getenv("LITELLM_DB_USER")
    password = os.getenv("LITELLM_DB_PASSWORD")

    if not all([host, port, database, user, password]):
        pytest.skip("Set LITELLM_DB_* env vars to run integration tests.")

    extractor = LiteLLMLogExtractor(
        host=host,
        port=int(port),
        database=database,
        user=user,
        password=password,
    )

    extractor.connect_to_postgres()
    try:
        output_path = Path(tmp_path) / "litellm-logs.zip"
        extractor.extract_to_zip(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 1),
            output_path=output_path,
        )
        assert output_path.exists()
    finally:
        extractor.disconnect_from_postgres()
