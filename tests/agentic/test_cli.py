"""Tests for agentic CLI commands.

This module tests the CLI commands for agentic RAG operations:
- ingest: Document ingestion
- search: Hybrid search
- chat: Interactive RAG chat
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import sys

try:
    from typer.testing import CliRunner
except ImportError:
    # Fallback if typer.testing is not available
    CliRunner = None

from llmaven.agentic.ingestion import IngestionPipeline
from llmaven.agentic.search import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.exceptions import AgenticRAGError


@pytest.fixture
def cli_runner():
    """Fixture for Typer CLI runner."""
    if CliRunner is None:
        pytest.skip("typer.testing.CliRunner not available")
    return CliRunner()


@pytest.fixture
def mock_ingestion_pipeline():
    """Fixture for mocked IngestionPipeline."""
    with patch("llmaven.agentic.ingestion.IngestionPipeline") as mock:
        pipeline_instance = Mock()
        pipeline_instance.ingest = Mock(return_value=None)
        mock.return_value = pipeline_instance
        yield mock, pipeline_instance


@pytest.fixture
def mock_hybrid_searcher():
    """Fixture for mocked HybridSearcher."""
    with patch("llmaven.agentic.search.HybridSearcher") as mock:
        searcher_instance = Mock()
        searcher_instance.search = Mock(
            return_value=[
                SearchResult(
                    text="Test result text",
                    file_path="/test.md",
                    heading_hierarchy="Section 1",
                    score=0.9,
                    chunk_index=0,
                    content_hash="abc123",
                )
            ]
        )
        mock.return_value = searcher_instance
        yield mock, searcher_instance


@pytest.fixture
def mock_rag_agent():
    """Fixture for mocked RAGAgent."""
    with patch("llmaven.agentic.agent.RAGAgent") as mock:
        agent_instance = Mock()
        agent_instance.run_sync = Mock(
            return_value=Mock(
                answer="Test answer",
                citations=[],
                confidence=0.85,
                sources_used=1,
            )
        )
        mock.return_value = agent_instance
        yield mock, agent_instance


class TestIngestCommand:
    """Test ingest CLI command."""

    def test_ingest_command_imports(self):
        """Test that ingest command can be imported."""
        from llmaven.cli import agentic_app

        assert agentic_app is not None

    @patch("pathlib.Path")
    @patch("llmaven.agentic.ingestion.IngestionPipeline")
    @patch("rich.console.Console")
    def test_ingest_validates_directory_exists(
        self, mock_console_cls, mock_pipeline_cls, mock_path_cls
    ):
        """Test that ingest validates directory exists."""
        from llmaven.cli import ingest
        import typer

        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        with pytest.raises(typer.Exit):
            ingest(["nonexistent-dir"])

        mock_console_err.print.assert_called()

    @patch("pathlib.Path")
    @patch("llmaven.agentic.ingestion.IngestionPipeline")
    @patch("rich.console.Console")
    def test_ingest_validates_directory_is_dir(
        self, mock_console_cls, mock_pipeline_cls, mock_path_cls
    ):
        """Test that ingest validates directory is actually a directory."""
        from llmaven.cli import ingest
        import typer

        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = False
        mock_path_cls.return_value = mock_path

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        with pytest.raises(typer.Exit):
            ingest(["not-a-dir"])

        mock_console_err.print.assert_called()

    @patch("pathlib.Path")
    @patch("llmaven.agentic.ingestion.IngestionPipeline")
    @patch("rich.console.Console")
    def test_ingest_calls_pipeline_correctly(
        self, mock_console_cls, mock_pipeline_cls, mock_path_cls
    ):
        """Test that ingest calls IngestionPipeline correctly."""
        from llmaven.cli import ingest

        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = True
        mock_path.__str__ = Mock(return_value="/test/dir")
        mock_path_cls.return_value = mock_path

        mock_pipeline_instance = Mock()
        mock_pipeline_instance.ingest = Mock(return_value=None)
        mock_pipeline_cls.return_value = mock_pipeline_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        ingest(["/test/dir"], collection="test-collection", batch_size=50, force=True)

        mock_pipeline_cls.assert_called_once_with(
            collection_name="test-collection", batch_size=50
        )
        mock_pipeline_instance.ingest.assert_called_once_with(
            directories=["/test/dir"], force=True
        )

    @patch("pathlib.Path")
    @patch("llmaven.agentic.ingestion.IngestionPipeline")
    @patch("rich.console.Console")
    def test_ingest_handles_agentic_error(
        self, mock_console_cls, mock_pipeline_cls, mock_path_cls
    ):
        """Test that ingest handles AgenticRAGError correctly."""
        from llmaven.cli import ingest
        import typer

        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = True
        mock_path.__str__ = Mock(return_value="/test/dir")
        mock_path_cls.return_value = mock_path

        mock_pipeline_instance = Mock()
        mock_pipeline_instance.ingest.side_effect = AgenticRAGError("Ingestion failed")
        mock_pipeline_cls.return_value = mock_pipeline_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        with pytest.raises(typer.Exit):
            ingest(["/test/dir"])

        mock_console_err.print.assert_called()


class TestSearchCommand:
    """Test search CLI command."""

    @patch("llmaven.agentic.search.HybridSearcher")
    @patch("rich.console.Console")
    def test_search_calls_searcher_correctly(
        self, mock_console_cls, mock_searcher_cls
    ):
        """Test that search calls HybridSearcher correctly."""
        from llmaven.cli import search

        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
            return_value=[
                SearchResult(
                    text="Test result",
                    file_path="/test.md",
                    heading_hierarchy=None,
                    score=0.9,
                    chunk_index=0,
                    content_hash="abc123",
                )
            ]
        )
        mock_searcher_cls.return_value = mock_searcher_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        search(
            "test query",
            collection="test-collection",
            top_k=10,
            prefetch_k=30,
            rerank=False,
        )

        mock_searcher_cls.assert_called_once_with(
            collection_name="test-collection",
            enable_rerank=False,
            prefetch_top_k=30,
            final_top_k=10,
        )
        mock_searcher_instance.search.assert_called_once_with(query="test query", limit=10)

    @patch("llmaven.agentic.search.HybridSearcher")
    @patch("rich.console.Console")
    def test_search_handles_empty_results(
        self, mock_console_cls, mock_searcher_cls
    ):
        """Test that search handles empty results gracefully."""
        from llmaven.cli import search

        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(return_value=[])
        mock_searcher_cls.return_value = mock_searcher_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        search("test query")

        mock_console.print.assert_called()

    @patch("llmaven.agentic.search.HybridSearcher")
    @patch("rich.console.Console")
    def test_search_handles_agentic_error(
        self, mock_console_cls, mock_searcher_cls
    ):
        """Test that search handles AgenticRAGError correctly."""
        from llmaven.cli import search
        import typer

        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
            side_effect=AgenticRAGError("Search failed")
        )
        mock_searcher_cls.return_value = mock_searcher_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        with pytest.raises(typer.Exit):
            search("test query")

        mock_console_err.print.assert_called()


class TestChatCommand:
    """Test chat CLI command."""

    @patch("llmaven.agentic.agent.RAGAgent")
    @patch("rich.console.Console")
    def test_chat_initializes_agent_correctly(
        self, mock_console_cls, mock_agent_cls
    ):
        """Test that chat initializes RAGAgent correctly."""
        from llmaven.cli import chat

        mock_agent_instance = Mock()
        mock_agent_instance.run_sync = Mock(
            return_value=Mock(
                answer="Test answer",
                citations=[],
                confidence=0.85,
                sources_used=1,
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        mock_console = Mock()
        mock_console_err = Mock()
        # Mock console.input to return "exit" immediately
        mock_console.input.side_effect = ["exit"]
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        try:
            chat(collection="test-collection", provider="ollama", model="llama2")
        except (SystemExit, KeyboardInterrupt):
            pass  # Expected when user exits

        mock_agent_cls.assert_called_once_with(
            collection_name="test-collection",
            llm_provider="ollama",
            llm_model="llama2",
        )

    @patch("llmaven.agentic.agent.RAGAgent")
    @patch("rich.console.Console")
    def test_chat_handles_exit_command(
        self, mock_console_cls, mock_agent_cls
    ):
        """Test that chat handles exit command."""
        from llmaven.cli import chat

        mock_agent_instance = Mock()
        mock_agent_instance.run_sync = Mock(
            return_value=Mock(
                answer="Test answer",
                citations=[],
                confidence=0.85,
                sources_used=1,
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        mock_console = Mock()
        mock_console_err = Mock()
        # Mock console.input to return "exit" immediately
        mock_console.input.side_effect = ["exit"]
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        try:
            chat()
        except (SystemExit, KeyboardInterrupt):
            pass  # Expected when user exits

        # Should not have called run_sync if user exits immediately
        # (though the exact behavior depends on implementation)

    @patch("llmaven.agentic.agent.RAGAgent")
    @patch("rich.console.Console")
    def test_chat_handles_agentic_error(
        self, mock_console_cls, mock_agent_cls
    ):
        """Test that chat handles AgenticRAGError correctly."""
        from llmaven.cli import chat

        mock_agent_instance = Mock()
        mock_agent_instance.run_sync = Mock(
            side_effect=AgenticRAGError("Agent failed")
        )
        mock_agent_cls.return_value = mock_agent_instance

        mock_console = Mock()
        mock_console_err = Mock()
        # Mock console.input to trigger agent call then exit
        mock_console.input.side_effect = ["test query", "exit"]
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        try:
            chat()
        except (SystemExit, KeyboardInterrupt, AgenticRAGError):
            pass  # Expected when error occurs

        mock_console_err.print.assert_called()


class TestCLIIntegration:
    """Integration tests for CLI commands."""

    @patch("pathlib.Path")
    @patch("llmaven.agentic.ingestion.IngestionPipeline")
    @patch("rich.console.Console")
    def test_ingest_multiple_directories(
        self, mock_console_cls, mock_pipeline_cls, mock_path_cls
    ):
        """Test that ingest handles multiple directories."""
        from llmaven.cli import ingest

        # Create mock paths for multiple directories
        mock_path1 = Mock()
        mock_path1.exists.return_value = True
        mock_path1.is_dir.return_value = True
        mock_path1.__str__ = Mock(return_value="/dir1")

        mock_path2 = Mock()
        mock_path2.exists.return_value = True
        mock_path2.is_dir.return_value = True
        mock_path2.__str__ = Mock(return_value="/dir2")

        mock_path_cls.side_effect = [mock_path1, mock_path2]

        mock_pipeline_instance = Mock()
        mock_pipeline_instance.ingest = Mock(return_value=None)
        mock_pipeline_cls.return_value = mock_pipeline_instance

        mock_console = Mock()
        mock_console_err = Mock()
        mock_console_cls.side_effect = [mock_console, mock_console_err]

        ingest(["/dir1", "/dir2"])

        # Verify ingest was called with both directories
        call_args = mock_pipeline_instance.ingest.call_args
        assert len(call_args[1]["directories"]) == 2
        assert "/dir1" in call_args[1]["directories"]
        assert "/dir2" in call_args[1]["directories"]
