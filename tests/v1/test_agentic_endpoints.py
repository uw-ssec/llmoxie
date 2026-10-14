"""Tests for agentic API endpoints.

This module tests the FastAPI endpoints for agentic RAG:
- POST /v1/agentic/retrieve - Hybrid search endpoint
- POST /v1/agentic/chat - RAG chat endpoint
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from llmaven.main import app
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.agent.models import RAGResponse, Citation
from llmaven.agentic.exceptions import AgenticRAGError
from llmaven.agentic.settings import config as agentic_config

client = TestClient(app)


class TestAgenticRetrieveEndpoint:
    """Test /v1/agentic/retrieve endpoint."""

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_success(self, mock_searcher_cls):
        """Test successful retrieve request."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
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
        mock_searcher_instance.enable_rerank = True
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {
            "query": "test query",
            "collection": "test-collection",
            "top_k": 5,
            "prefetch_k": 20,
            "enable_rerank": True,
        }

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total_results" in data
        assert "reranking_enabled" in data
        assert len(data["results"]) == 1
        assert data["total_results"] == 1
        assert data["reranking_enabled"] is True

        # Verify searcher was created correctly
        mock_searcher_cls.assert_called_once_with(
            collection_name="test-collection",
            enable_rerank=True,
            prefetch_top_k=20,
            final_top_k=5,
        )

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_with_defaults(self, mock_searcher_cls):
        """Test retrieve with default parameters."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(return_value=[])
        mock_searcher_instance.enable_rerank = True
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {"query": "test query"}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 0
        assert len(data["results"]) == 0

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_without_rerank(self, mock_searcher_cls):
        """Test retrieve without reranking."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
            return_value=[
                SearchResult(
                    text="Test result",
                    file_path="/test.md",
                    heading_hierarchy=None,
                    score=0.8,
                    chunk_index=0,
                    content_hash="abc123",
                )
            ]
        )
        mock_searcher_instance.enable_rerank = False
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {
            "query": "test query",
            "enable_rerank": False,
        }

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["reranking_enabled"] is False

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_handles_agentic_error(self, mock_searcher_cls):
        """Test that retrieve handles AgenticRAGError correctly."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
            side_effect=AgenticRAGError("Search failed")
        )
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {"query": "test query"}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 500
        assert "Search failed" in response.json()["detail"]

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_handles_unexpected_error(self, mock_searcher_cls):
        """Test that retrieve handles unexpected errors correctly."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(side_effect=Exception("Unexpected error"))
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {"query": "test query"}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    def test_retrieve_validates_query_required(self):
        """Test that retrieve validates query is required."""
        payload = {}  # Missing query

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 422  # Validation error

    def test_retrieve_validates_query_not_empty(self):
        """Test that retrieve validates query is not empty."""
        payload = {"query": ""}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 422  # Validation error

    def test_retrieve_validates_top_k_positive(self):
        """Test that retrieve validates top_k is positive."""
        payload = {"query": "test", "top_k": -1}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 422  # Validation error

    def test_retrieve_validates_prefetch_k_positive(self):
        """Test that retrieve validates prefetch_k is positive."""
        payload = {"query": "test", "prefetch_k": 0}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 422  # Validation error


class TestAgenticChatEndpoint:
    """Test /v1/agentic/chat endpoint."""

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_success(self, mock_agent_cls):
        """Test successful chat request."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(
            return_value=RAGResponse(
                answer="Test answer",
                citations=[
                    Citation(
                        source_file="/test.md",
                        quote="Test quote",
                        relevance_score=0.9,
                    )
                ],
                confidence=0.85,
                sources_used=1,
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        payload = {
            "query": "test question",
            "collection": "test-collection",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
        }

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "citations" in data
        assert "confidence" in data
        assert "sources_used" in data
        assert data["answer"] == "Test answer"
        assert len(data["citations"]) == 1
        assert data["confidence"] == 0.85
        assert data["sources_used"] == 1

        # Verify agent was created correctly
        mock_agent_cls.assert_called_once_with(
            collection_name="test-collection",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
        )

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_with_message_history(self, mock_agent_cls):
        """Test chat with message history."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(
            return_value=RAGResponse(
                answer="Test answer", citations=[], confidence=0.8, sources_used=0
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        payload = {
            "query": "follow-up question",
            "message_history": [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        }

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 200

        # Verify message history was passed
        call_args = mock_agent_instance.run.call_args
        assert call_args[1]["message_history"] == payload["message_history"]

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_with_defaults(self, mock_agent_cls):
        """Test chat with default parameters."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(
            return_value=RAGResponse(
                answer="Test answer", citations=[], confidence=0.8, sources_used=0
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        payload = {"query": "test question"}

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Test answer"

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_handles_agentic_error(self, mock_agent_cls):
        """Test that chat handles AgenticRAGError correctly."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(side_effect=AgenticRAGError("Agent failed"))
        mock_agent_cls.return_value = mock_agent_instance

        payload = {"query": "test question"}

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 500
        assert "Agent failed" in response.json()["detail"]

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_handles_unexpected_error(self, mock_agent_cls):
        """Test that chat handles unexpected errors correctly."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(side_effect=Exception("Unexpected error"))
        mock_agent_cls.return_value = mock_agent_instance

        payload = {"query": "test question"}

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    def test_chat_validates_query_required(self):
        """Test that chat validates query is required."""
        payload = {}  # Missing query

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 422  # Validation error

    def test_chat_validates_query_not_empty(self):
        """Test that chat validates query is not empty."""
        payload = {"query": ""}

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 422  # Validation error

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_with_conversation_id(self, mock_agent_cls):
        """Test chat with conversation ID (for tracking)."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(
            return_value=RAGResponse(
                answer="Test answer", citations=[], confidence=0.8, sources_used=0
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        payload = {
            "query": "test question",
            "conversation_id": "conv-123",
        }

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 200
        # Conversation ID is logged but not used in agent execution
        # This test verifies it's accepted without error


class TestAgenticEndpointsIntegration:
    """Integration tests for agentic endpoints."""

    @patch("llmaven.v1.endpoints.agentic_retrieve.HybridSearcher")
    def test_retrieve_multiple_results(self, mock_searcher_cls):
        """Test retrieve with multiple results."""
        mock_searcher_instance = Mock()
        mock_searcher_instance.search = Mock(
            return_value=[
                SearchResult(
                    text=f"Result {i}",
                    file_path=f"/test{i}.md",
                    heading_hierarchy=None,
                    score=0.9 - i * 0.1,
                    chunk_index=i,
                    content_hash=f"hash{i}",
                )
                for i in range(5)
            ]
        )
        mock_searcher_instance.enable_rerank = True
        mock_searcher_cls.return_value = mock_searcher_instance

        payload = {"query": "test query", "top_k": 5}

        response = client.post("/v1/agentic/retrieve", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 5
        assert len(data["results"]) == 5

        # Verify results are ordered by score (highest first)
        scores = [r["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)

    @patch("llmaven.v1.endpoints.agentic_chat.RAGAgent")
    @pytest.mark.asyncio
    async def test_chat_with_multiple_citations(self, mock_agent_cls):
        """Test chat with multiple citations."""
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(
            return_value=RAGResponse(
                answer="Test answer",
                citations=[
                    Citation(
                        source_file=f"/test{i}.md",
                        quote=f"Quote {i}",
                        relevance_score=0.9 - i * 0.1,
                    )
                    for i in range(3)
                ],
                confidence=0.85,
                sources_used=3,
            )
        )
        mock_agent_cls.return_value = mock_agent_instance

        payload = {"query": "test question"}

        response = client.post("/v1/agentic/chat", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert len(data["citations"]) == 3
        assert data["sources_used"] == 3


class TestAgenticChatGlobalConfigContamination:
    """Cross-request contamination via /v1/agentic/chat.

    The chat endpoint constructs a fresh `RAGAgent` per request and
    forwards user-controlled `llm_provider`/`llm_model` straight in.
    `RAGAgent.__init__` writes those values into the module-level
    `agentic_config` singleton, so a *subsequent* request that supplies
    no overrides silently routes through the previous request's provider.

    These tests deliberately mock at the layer **below** `RAGAgent`
    (`create_llm_model`, `HybridSearcher`, `Agent`) so the real
    `RAGAgent.__init__` runs end-to-end through the FastAPI handler.
    """

    # Sentinel baseline distinct from any string used elsewhere in the
    # suite, so the assertion is invariant to test ordering even when
    # earlier tests leak overrides into the global singleton.
    BASELINE_PROVIDER = "openai"
    BASELINE_MODEL = "regression-baseline-sentinel"

    @pytest.fixture(autouse=True)
    def _force_known_baseline(self):
        original_provider = agentic_config.llm_provider
        original_model = agentic_config.llm_model
        agentic_config.llm_provider = self.BASELINE_PROVIDER
        agentic_config.llm_model = self.BASELINE_MODEL
        try:
            yield
        finally:
            agentic_config.llm_provider = original_provider
            agentic_config.llm_model = original_model

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_chat_request_does_not_leak_provider_to_subsequent_request(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Two sequential POSTs: request 1 has overrides, request 2 does not.

        Request 2 must be served using the env-default provider/model. On
        `main` the global config has been clobbered by request 1, so
        request 2's `RAGAgent.__init__` sees the leaked override.
        """
        mock_searcher_cls.return_value = Mock()
        # pydantic-ai Agent.run() returns AgentRunResult with .output attribute,
        # which RAGAgent.run() unwraps before returning to the endpoint.
        mock_run_result = Mock()
        mock_run_result.output = RAGResponse(
            answer="ok",
            citations=[],
            confidence=0.0,
            sources_used=0,
        )
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock(return_value=mock_run_result)
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        baseline_provider = agentic_config.llm_provider
        baseline_model = agentic_config.llm_model

        # Request 1 — supplies overrides.
        resp1 = client.post(
            "/v1/agentic/chat",
            json={
                "query": "first",
                "llm_provider": "ollama",
                "llm_model": "llama2",
            },
        )
        assert resp1.status_code == 200

        # Request 2 — no overrides, expected to use the env default.
        resp2 = client.post("/v1/agentic/chat", json={"query": "second"})
        assert resp2.status_code == 200

        # After both requests, the global must still equal the baseline.
        # Today it equals ("ollama", "llama2") because request 1 leaked.
        assert agentic_config.llm_provider == baseline_provider, (
            "Provider leaked across requests: request 1's override "
            "persisted in the global config singleton after the response "
            f"was returned (expected {baseline_provider!r}, "
            f"got {agentic_config.llm_provider!r}). Subsequent requests "
            "without an override will silently route to the wrong provider."
        )
        assert agentic_config.llm_model == baseline_model, (
            "Model leaked across requests: request 1's override persisted "
            f"in the global config singleton (expected {baseline_model!r}, "
            f"got {agentic_config.llm_model!r})."
        )
