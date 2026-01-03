"""Tests for Agentic RAG exception hierarchy.

This module tests the exception classes to ensure proper inheritance
and error handling behavior.
"""

import pytest

from llmaven.agentic.exceptions import (
    AgenticRAGError,
    IngestionError,
    QdrantConnectionError,
    CollectionNotFoundError,
    EmbeddingError,
    SearchError,
)


class TestExceptionHierarchy:
    """Test exception inheritance hierarchy."""

    def test_ingestion_error_inherits_from_base(self):
        """Test that IngestionError inherits from AgenticRAGError."""
        assert issubclass(IngestionError, AgenticRAGError)
        assert issubclass(IngestionError, Exception)

    def test_qdrant_connection_error_inherits_from_base(self):
        """Test that QdrantConnectionError inherits from AgenticRAGError."""
        assert issubclass(QdrantConnectionError, AgenticRAGError)
        assert issubclass(QdrantConnectionError, Exception)

    def test_collection_not_found_error_inherits_from_base(self):
        """Test that CollectionNotFoundError inherits from AgenticRAGError."""
        assert issubclass(CollectionNotFoundError, AgenticRAGError)
        assert issubclass(CollectionNotFoundError, Exception)

    def test_embedding_error_inherits_from_base(self):
        """Test that EmbeddingError inherits from AgenticRAGError."""
        assert issubclass(EmbeddingError, AgenticRAGError)
        assert issubclass(EmbeddingError, Exception)

    def test_search_error_inherits_from_base(self):
        """Test that SearchError inherits from AgenticRAGError."""
        assert issubclass(SearchError, AgenticRAGError)
        assert issubclass(SearchError, Exception)


class TestExceptionInstantiation:
    """Test exception instantiation."""

    def test_base_exception_can_be_raised(self):
        """Test that base exception can be raised."""
        with pytest.raises(AgenticRAGError):
            raise AgenticRAGError("Test error")

    def test_base_exception_with_message(self):
        """Test that base exception accepts error messages."""
        error_msg = "Something went wrong"
        with pytest.raises(AgenticRAGError, match=error_msg):
            raise AgenticRAGError(error_msg)

    def test_ingestion_error_can_be_raised(self):
        """Test that IngestionError can be raised."""
        with pytest.raises(IngestionError):
            raise IngestionError("Document ingestion failed")

    def test_qdrant_connection_error_can_be_raised(self):
        """Test that QdrantConnectionError can be raised."""
        with pytest.raises(QdrantConnectionError):
            raise QdrantConnectionError("Failed to connect to Qdrant")

    def test_collection_not_found_error_can_be_raised(self):
        """Test that CollectionNotFoundError can be raised."""
        with pytest.raises(CollectionNotFoundError):
            raise CollectionNotFoundError("Collection 'test' not found")

    def test_embedding_error_can_be_raised(self):
        """Test that EmbeddingError can be raised."""
        with pytest.raises(EmbeddingError):
            raise EmbeddingError("Failed to generate embeddings")

    def test_search_error_can_be_raised(self):
        """Test that SearchError can be raised."""
        with pytest.raises(SearchError):
            raise SearchError("Search operation failed")


class TestExceptionCatching:
    """Test exception catching behavior."""

    def test_catch_base_exception_catches_all(self):
        """Test that catching base exception catches all derived exceptions."""
        exceptions = [
            IngestionError("test"),
            QdrantConnectionError("test"),
            CollectionNotFoundError("test"),
            EmbeddingError("test"),
            SearchError("test"),
        ]

        for exc in exceptions:
            try:
                raise exc
            except AgenticRAGError:
                # Should catch all derived exceptions
                pass
            except Exception:
                pytest.fail(f"Exception {type(exc).__name__} should be caught by AgenticRAGError")

    def test_catch_specific_exception_only_catches_that_type(self):
        """Test that catching specific exception only catches that type."""
        # Raise IngestionError
        with pytest.raises(QdrantConnectionError):
            try:
                raise IngestionError("test")
            except QdrantConnectionError:
                # Should not catch IngestionError
                pytest.fail("Should not catch IngestionError with QdrantConnectionError handler")
            except IngestionError:
                # Re-raise as QdrantConnectionError to test the handler
                raise QdrantConnectionError("test")

    def test_exception_chaining(self):
        """Test that exceptions can be chained."""
        try:
            raise ValueError("Original error")
        except ValueError as e:
            with pytest.raises(IngestionError):
                raise IngestionError("Ingestion failed") from e


class TestExceptionMessages:
    """Test exception message handling."""

    def test_exception_with_custom_message(self):
        """Test exceptions with custom error messages."""
        custom_msg = "Custom error message"
        with pytest.raises(IngestionError, match=custom_msg):
            raise IngestionError(custom_msg)

    def test_exception_without_message(self):
        """Test exceptions can be raised without messages."""
        with pytest.raises(IngestionError):
            raise IngestionError()

    def test_exception_message_preserved(self):
        """Test that exception messages are preserved."""
        error_msg = "Document parsing failed"
        try:
            raise IngestionError(error_msg)
        except IngestionError as e:
            assert str(e) == error_msg


class TestExceptionImportability:
    """Test that exceptions can be imported correctly."""

    def test_base_exception_importable_from_package(self):
        """Test that base exception is importable from package."""
        from llmaven.agentic import AgenticRAGError
        assert AgenticRAGError is not None
        assert issubclass(AgenticRAGError, Exception)

    def test_all_exceptions_importable(self):
        """Test that all exceptions can be imported."""
        from llmaven.agentic.exceptions import (
            AgenticRAGError,
            IngestionError,
            QdrantConnectionError,
            CollectionNotFoundError,
            EmbeddingError,
            SearchError,
        )
        assert all(
            exc is not None
            for exc in [
                AgenticRAGError,
                IngestionError,
                QdrantConnectionError,
                CollectionNotFoundError,
                EmbeddingError,
                SearchError,
            ]
        )

    def test_exceptions_have_docstrings(self):
        """Test that exceptions have docstrings for documentation."""
        assert AgenticRAGError.__doc__ is not None
        assert IngestionError.__doc__ is not None
        assert QdrantConnectionError.__doc__ is not None
        assert CollectionNotFoundError.__doc__ is not None
        assert EmbeddingError.__doc__ is not None
        assert SearchError.__doc__ is not None


class TestExceptionUsagePatterns:
    """Test common exception usage patterns."""

    def test_raise_and_catch_in_function(self):
        """Test raising and catching exceptions in a function."""
        def process_document():
            raise IngestionError("Failed to process document")

        with pytest.raises(IngestionError):
            process_document()

    def test_exception_in_except_block(self):
        """Test raising exceptions in except blocks."""
        try:
            raise ValueError("Original error")
        except ValueError:
            with pytest.raises(QdrantConnectionError):
                raise QdrantConnectionError("Connection failed")

    def test_multiple_exception_types(self):
        """Test handling multiple exception types."""
        def operation_that_might_fail(operation_type: str):
            if operation_type == "ingestion":
                raise IngestionError("Ingestion failed")
            elif operation_type == "search":
                raise SearchError("Search failed")
            elif operation_type == "connection":
                raise QdrantConnectionError("Connection failed")

        with pytest.raises(IngestionError):
            operation_that_might_fail("ingestion")

        with pytest.raises(SearchError):
            operation_that_might_fail("search")

        with pytest.raises(QdrantConnectionError):
            operation_that_might_fail("connection")
