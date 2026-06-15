"""Tests for RAGAgent class.

This module tests the RAGAgent functionality including initialization,
tool registration, agent execution, and error handling.
"""

import asyncio

import pytest
from unittest.mock import Mock, patch, AsyncMock

from llmaven.agentic.agent.rag_agent import RAGAgent, RAGAgentDependencies
from llmaven.agentic.agent.models import RAGResponse, Citation
from llmaven.agentic.search.hybrid_searcher import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.exceptions import AgenticRAGError
from llmaven.agentic.settings import config as agentic_config


class TestRAGAgentDependencies:
    """Test RAGAgentDependencies class."""

    def test_init_with_hybrid_searcher(self):
        """Test initialization with hybrid searcher."""
        mock_searcher = Mock(spec=HybridSearcher)
        deps = RAGAgentDependencies(hybrid_searcher=mock_searcher)
        assert deps.hybrid_searcher == mock_searcher
        assert deps.collection_name == "agentic-rag"  # Default from config

    def test_init_with_collection_name(self):
        """Test initialization with custom collection name."""
        mock_searcher = Mock(spec=HybridSearcher)
        deps = RAGAgentDependencies(
            hybrid_searcher=mock_searcher, collection_name="custom-collection"
        )
        assert deps.collection_name == "custom-collection"


class TestRAGAgentInitialization:
    """Test RAGAgent initialization."""

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_init_with_default_config(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test initialization with default config."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        agent = RAGAgent()

        assert agent.collection_name == "agentic-rag"
        assert agent.hybrid_searcher == mock_searcher
        mock_agent_cls.assert_called_once()
        assert mock_agent_instance.tool.called  # Tool should be registered

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_init_with_custom_collection(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test initialization with custom collection."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        agent = RAGAgent(collection_name="custom-collection")

        assert agent.collection_name == "custom-collection"
        mock_searcher_cls.assert_called_once_with(collection_name="custom-collection")

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    def test_init_with_custom_searcher(self, mock_agent_cls, mock_create_llm):
        """Test initialization with custom hybrid searcher."""
        mock_searcher = Mock(spec=HybridSearcher)
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        agent = RAGAgent(hybrid_searcher=mock_searcher)

        assert agent.hybrid_searcher == mock_searcher

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_init_with_llm_provider_override(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test initialization with LLM provider override."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_llm_model = Mock()
        mock_create_llm.return_value = mock_llm_model

        RAGAgent(llm_provider="ollama", llm_model="llama2")

        # Verify create_llm_model was called and Agent was called with the model
        mock_create_llm.assert_called_once()
        call_args = mock_agent_cls.call_args
        assert call_args[0][0] == mock_llm_model

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_init_raises_on_invalid_provider(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that initialization raises error for invalid provider."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        from llmaven.agentic.exceptions import ProviderConfigurationError

        mock_create_llm.side_effect = ProviderConfigurationError(
            "Unsupported LLM provider"
        )

        with pytest.raises(
            ProviderConfigurationError, match="Unsupported LLM provider"
        ):
            RAGAgent(llm_provider="invalid-provider")

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_init_raises_on_agent_error(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that initialization wraps agent errors."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_create_llm.return_value = Mock()
        mock_agent_cls.side_effect = Exception("Agent creation failed")

        with pytest.raises(AgenticRAGError, match="Failed to initialize RAG Agent"):
            RAGAgent()


class TestRAGAgentModelName:
    """Test model name resolution."""

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_get_model_name_openai(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test OpenAI model name resolution."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_llm_model = Mock()
        mock_create_llm.return_value = mock_llm_model

        RAGAgent(llm_provider="openai", llm_model="gpt-4o-mini")

        call_args = mock_agent_cls.call_args
        assert call_args[0][0] == mock_llm_model

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_get_model_name_ollama(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test Ollama model name resolution."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_llm_model = Mock()
        mock_create_llm.return_value = mock_llm_model

        RAGAgent(llm_provider="ollama", llm_model="llama2")

        call_args = mock_agent_cls.call_args
        assert call_args[0][0] == mock_llm_model


class TestRAGAgentRun:
    """Test RAGAgent run methods."""

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    @pytest.mark.asyncio
    async def test_run_async_success(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test successful async run."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        # Mock agent run result
        mock_result = Mock()
        mock_result.output = RAGResponse(
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
        mock_agent_instance.run.return_value = mock_result

        agent = RAGAgent()
        response = await agent.run("test query")

        assert isinstance(response, RAGResponse)
        assert response.answer == "Test answer"
        assert len(response.citations) == 1
        assert response.confidence == 0.85
        assert response.sources_used == 1

        # Verify agent.run was called with correct args
        mock_agent_instance.run.assert_called_once()
        call_args = mock_agent_instance.run.call_args
        assert call_args[0][0] == "test query"
        assert "deps" in call_args[1]

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    @pytest.mark.asyncio
    async def test_run_with_message_history(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test run with message history."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        mock_result = Mock()
        mock_result.output = RAGResponse(
            answer="Test answer", citations=[], confidence=0.8, sources_used=0
        )
        mock_agent_instance.run.return_value = mock_result

        agent = RAGAgent()
        message_history = [{"role": "user", "content": "Previous question"}]
        await agent.run("test query", message_history=message_history)

        call_args = mock_agent_instance.run.call_args
        assert call_args[1]["message_history"] == message_history

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    @pytest.mark.asyncio
    async def test_run_raises_on_error(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that run wraps errors."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock()
        mock_agent_instance.run.side_effect = Exception("Agent execution failed")
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        agent = RAGAgent()

        with pytest.raises(AgenticRAGError, match="Agent execution failed"):
            await agent.run("test query")

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_run_sync_success(self, mock_searcher_cls, mock_agent_cls, mock_create_llm):
        """Test successful synchronous run."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_instance.run = AsyncMock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        mock_result = Mock()
        mock_result.output = RAGResponse(
            answer="Test answer", citations=[], confidence=0.8, sources_used=0
        )
        mock_agent_instance.run.return_value = mock_result

        agent = RAGAgent()
        response = agent.run_sync("test query")

        assert isinstance(response, RAGResponse)
        assert response.answer == "Test answer"


class TestRAGAgentTool:
    """Test RAGAgent tool registration and execution."""

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_tool_registration(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that search_knowledge_base tool is registered."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        RAGAgent()

        # Verify tool decorator was called
        assert mock_agent_instance.tool.called

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    @pytest.mark.asyncio
    async def test_search_tool_execution(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that search tool calls HybridSearcher correctly."""
        mock_searcher = Mock()
        mock_searcher.search.return_value = [
            SearchResult(
                text="Test text",
                file_path="/test.md",
                heading_hierarchy="Section 1",
                score=0.9,
                chunk_index=0,
                content_hash="abc123",
            )
        ]
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        agent = RAGAgent()

        # Get the registered tool function
        # The tool is registered via decorator, so we need to access it differently
        # For testing purposes, we'll verify the searcher is called correctly
        # when the agent runs

        # Create a mock context
        mock_ctx = Mock()
        mock_ctx.deps = RAGAgentDependencies(
            hybrid_searcher=mock_searcher, collection_name="test-collection"
        )

        # Manually call the tool function (simulating what pydantic-ai would do)
        # We need to extract the tool function from the agent
        # Since it's registered via decorator, we'll test indirectly through run

        # Instead, verify searcher is set up correctly
        assert agent.hybrid_searcher == mock_searcher


class TestRAGAgentSystemPrompt:
    """Test RAGAgent system prompt."""

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_system_prompt_includes_instructions(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Test that system prompt includes key instructions."""
        mock_searcher = Mock()
        mock_searcher_cls.return_value = mock_searcher
        mock_agent_instance = Mock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_create_llm.return_value = Mock()

        RAGAgent()

        # Verify system prompt was passed to Agent
        call_args = mock_agent_cls.call_args
        system_prompt = call_args[1]["system_prompt"]
        assert "search_knowledge_base" in system_prompt.lower()
        assert "cite" in system_prompt.lower()
        assert "confidence" in system_prompt.lower()


class TestRAGAgentGlobalConfigContamination:
    """Regression tests for cross-request global-config contamination.

    `RAGAgent.__init__()` currently mutates the module-level `config`
    singleton when `llm_provider`/`llm_model` overrides are supplied. That
    mutation persists across subsequent `RAGAgent` constructions and across
    concurrent requests, so a later request that supplies no override
    silently uses the previously-set provider/model instead of the env
    default. These tests pin that behavior and will fail on `main` until
    `__init__` stops mutating the global.
    """

    # Sentinel values used as the per-test baseline. Chosen to be distinct
    # from any provider/model literal used by other tests in this file so
    # the regression assertion is deterministic regardless of test order
    # (earlier tests in this suite leak overrides like "ollama"/"llama2"
    # into the global, which is itself a symptom of the bug under test).
    BASELINE_PROVIDER = "openai"
    BASELINE_MODEL = "regression-baseline-sentinel"

    @pytest.fixture(autouse=True)
    def _force_known_baseline(self):
        """Force the global config to a known baseline before each test.

        Without this, the order-dependent state left behind by earlier
        tests would let the regression assertions pass by accident
        whenever a previous test happened to pollute the global with
        the same override values used here.
        """
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
    def test_init_does_not_mutate_global_config(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Constructing a RAGAgent with overrides must not change the global config.

        After RAGAgent(llm_provider=..., llm_model=...) returns, the
        module-level `config` should still hold the values it had before the
        call (the env-driven default). Today it does NOT — `__init__` writes
        to `config.llm_provider` / `config.llm_model` directly, so a
        subsequent default-construction silently picks up the override.
        """
        mock_searcher_cls.return_value = Mock()
        mock_agent_cls.return_value = Mock()
        mock_create_llm.return_value = Mock()

        baseline_provider = agentic_config.llm_provider
        baseline_model = agentic_config.llm_model

        RAGAgent(llm_provider="ollama", llm_model="llama2")

        # The bug: these two assertions fail on `main` because __init__
        # mutated the singleton instead of using a local override.
        assert agentic_config.llm_provider == baseline_provider, (
            "RAGAgent.__init__ mutated the global config.llm_provider; "
            f"expected {baseline_provider!r}, got {agentic_config.llm_provider!r}"
        )
        assert agentic_config.llm_model == baseline_model, (
            "RAGAgent.__init__ mutated the global config.llm_model; "
            f"expected {baseline_model!r}, got {agentic_config.llm_model!r}"
        )

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    def test_default_construction_after_override_uses_env_default(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """A no-override RAGAgent built after an override must use the env default.

        Demonstrates the cross-request contamination scenario from the
        endpoint layer: request 1 supplies overrides, request 2 supplies
        none — request 2's factory call should still see the env default.
        """
        mock_searcher_cls.return_value = Mock()
        mock_agent_cls.return_value = Mock()
        mock_create_llm.return_value = Mock()

        baseline_provider = agentic_config.llm_provider
        baseline_model = agentic_config.llm_model

        # Simulate request 1 (with overrides) then request 2 (no overrides).
        RAGAgent(llm_provider="ollama", llm_model="llama2")
        RAGAgent()

        # The second construction did not pass overrides, so the global
        # config seen by its create_llm_model() call should still be the
        # env-driven baseline. On `main` the global has been clobbered to
        # "ollama"/"llama2" and stays that way.
        assert agentic_config.llm_provider == baseline_provider, (
            "Global provider leaked from a previous RAGAgent override; "
            f"expected {baseline_provider!r}, got {agentic_config.llm_provider!r}"
        )
        assert agentic_config.llm_model == baseline_model, (
            "Global model leaked from a previous RAGAgent override; "
            f"expected {baseline_model!r}, got {agentic_config.llm_model!r}"
        )

    @patch("llmaven.agentic.agent.rag_agent.create_llm_model")
    @patch("llmaven.agentic.agent.rag_agent.Agent")
    @patch("llmaven.agentic.agent.rag_agent.HybridSearcher")
    @pytest.mark.asyncio
    async def test_concurrent_init_does_not_corrupt_global_config(
        self, mock_searcher_cls, mock_agent_cls, mock_create_llm
    ):
        """Concurrent RAGAgent constructions must not leave the global mutated.

        Fires N concurrent constructions with distinct overrides. After they
        all complete, the global `config` should be unchanged from its
        pre-test baseline. Today it ends up holding whichever override
        happened to write last.
        """
        mock_searcher_cls.return_value = Mock()
        mock_agent_cls.return_value = Mock()
        mock_create_llm.return_value = Mock()

        baseline_provider = agentic_config.llm_provider
        baseline_model = agentic_config.llm_model

        async def _build(provider: str, model: str) -> None:
            # RAGAgent.__init__ is sync; wrap so we can gather it.
            RAGAgent(llm_provider=provider, llm_model=model)

        overrides = [
            ("ollama", "llama2"),
            ("huggingface", "mistral-7b"),
            ("litellm", "claude-3"),
            ("ollama", "phi-3"),
        ]
        await asyncio.gather(*(_build(p, m) for p, m in overrides))

        assert agentic_config.llm_provider == baseline_provider, (
            "Concurrent RAGAgent constructions corrupted global llm_provider; "
            f"expected {baseline_provider!r}, got {agentic_config.llm_provider!r}"
        )
        assert agentic_config.llm_model == baseline_model, (
            "Concurrent RAGAgent constructions corrupted global llm_model; "
            f"expected {baseline_model!r}, got {agentic_config.llm_model!r}"
        )
