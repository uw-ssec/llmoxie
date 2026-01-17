"""Unit tests for LiteLLM log extractor."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from llmaven.infrastructure.extract.exceptions import ExtractionError
from llmaven.infrastructure.extract.litellm import LiteLLMLogExtractor


def test_extract_to_zip_requires_connection():
    extractor = LiteLLMLogExtractor(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
    )

    with pytest.raises(ExtractionError):
        extractor.extract_to_zip(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 2),
            output_path="/tmp/out.zip",
        )


def test_extract_to_zip_rejects_inverted_date_range():
    extractor = LiteLLMLogExtractor(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
    )
    extractor._connection = Mock()

    with pytest.raises(ExtractionError):
        extractor.extract_to_zip(
            start_date=datetime(2026, 1, 3),
            end_date=datetime(2026, 1, 1),
            output_path="/tmp/out.zip",
        )


@patch("llmaven.infrastructure.extract.litellm.psycopg2.connect")
def test_connect_to_postgres_sets_connection(mock_connect):
    mock_connection = Mock()
    mock_connect.return_value = mock_connection

    extractor = LiteLLMLogExtractor(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
    )

    extractor.connect_to_postgres()

    mock_connect.assert_called_once_with(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
        connect_timeout=10,
    )
    assert extractor._connection is mock_connection


def test_disconnect_from_postgres_is_idempotent():
    extractor = LiteLLMLogExtractor(
        host="localhost",
        port=5432,
        database="litellm_db",
        user="postgres",
        password="test",
    )
    extractor._connection = Mock()

    extractor.disconnect_from_postgres()
    extractor.disconnect_from_postgres()

    assert extractor._connection is None
