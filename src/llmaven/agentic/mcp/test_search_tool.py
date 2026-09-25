import pytest
from unittest.mock import Mock, patch

from fastmcp import Client
from pydantic import ValidationError

from llmaven.agentic.mcp.server import mcp
from llmaven.agentic.mcp.tools.search import SearchKnowledgeBaseInput
from llmaven.agentic.search.models import SearchResult


@pytest.fixture
def mock_hybrid_searcher():
    searcher = Mock()
    searcher.search.return_value = [
        SearchResult(
            text="Test content",
            file_path="/test/doc.md",
            heading_hierarchy="Test > Section",
            score=0.95,
            chunk_index=0,
        )
    ]
    searcher._models_initialized = False
    return searcher


@pytest.mark.asyncio
async def test_search_knowledge_base_returns_results(mock_hybrid_searcher):
    with patch(
        "llmaven.agentic.mcp.server.HybridSearcher", return_value=mock_hybrid_searcher
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "search_knowledge_base",
                {"query": "test query", "limit": 5},
            )

            data = result.structured_content
            assert data["total_results"] == 1
            assert data["results"][0]["text"] == "Test content"
            assert data["results"][0]["source_file"] == "/test/doc.md"
            assert data["results"][0]["score"] == 0.95
            mock_hybrid_searcher.search.assert_called_once_with(
                query="test query", limit=5, enable_rerank=None
            )


@pytest.mark.asyncio
async def test_search_knowledge_base_handles_empty_results(mock_hybrid_searcher):
    mock_hybrid_searcher.search.return_value = []
    with patch(
        "llmaven.agentic.mcp.server.HybridSearcher", return_value=mock_hybrid_searcher
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "search_knowledge_base",
                {"query": "test query"},
            )

            data = result.structured_content
            assert data["total_results"] == 0
            assert data["results"] == []


def test_search_knowledge_base_validates_limit():
    with pytest.raises(ValidationError):
        SearchKnowledgeBaseInput(query="test", limit=0)  # below ge=1

    with pytest.raises(ValidationError):
        SearchKnowledgeBaseInput(query="test", limit=101)  # above le=100

    with pytest.raises(ValidationError):
        SearchKnowledgeBaseInput(query="")  # below min_length=1


@pytest.mark.asyncio
async def test_search_knowledge_base_uses_custom_collection(mock_hybrid_searcher):
    with patch(
        "llmaven.agentic.mcp.server.HybridSearcher", return_value=mock_hybrid_searcher
    ) as mock_cls:
        async with Client(mcp) as client:
            await client.call_tool(
                "search_knowledge_base",
                {"query": "test", "collection_name": "custom-collection"},
            )

        # When collection_name is specified, a new HybridSearcher is created with it
        mock_cls.assert_called_with(collection_name="custom-collection")
