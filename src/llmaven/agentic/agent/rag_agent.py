"""RAG Agent implementation using pydantic-ai.

This module provides the RAGAgent class that orchestrates hybrid search
with LLM-based answer generation and structured output.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent, RunContext

from llmaven.agentic.settings import config
from llmaven.agentic.providers import create_llm_model
from llmaven.agentic.search.hybrid_searcher import HybridSearcher
from llmaven.agentic.search.models import SearchResult
from llmaven.agentic.agent.models import RAGResponse, Citation
from llmaven.agentic.exceptions import AgenticRAGError, ProviderConfigurationError

logger = logging.getLogger(__name__)


class RAGAgentDependencies:
    """Dependencies for RAG Agent.

    This class holds the dependencies that the agent needs to access
    during execution (hybrid searcher, collection name, etc.).
    """

    def __init__(
        self,
        hybrid_searcher: HybridSearcher,
        collection_name: str | None = None,
    ):
        """Initialize RAG agent dependencies.

        Args:
            hybrid_searcher: HybridSearcher instance for knowledge retrieval
            collection_name: Optional collection name override
        """
        self.hybrid_searcher = hybrid_searcher
        self.collection_name = collection_name or config.collection_name


class RAGAgent:
    """RAG Agent with structured output and citation support.

    This class wraps a pydantic-ai Agent that can search a knowledge base
    and generate answers with citations.

    Attributes:
        agent: The underlying pydantic-ai Agent
        hybrid_searcher: HybridSearcher for knowledge retrieval
        collection_name: Name of the Qdrant collection
    """

    def __init__(
        self,
        collection_name: str | None = None,
        hybrid_searcher: HybridSearcher | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ):
        """Initialize RAG Agent.

        Args:
            collection_name: Collection to search (defaults to config)
            hybrid_searcher: HybridSearcher instance (creates new if None)
            llm_provider: LLM provider override (defaults to config)
            llm_model: LLM model override (defaults to config)

        Raises:
            AgenticRAGError: If agent initialization fails
            ProviderConfigurationError: If provider configuration is invalid
        """
        self.collection_name = collection_name or config.collection_name
        self.hybrid_searcher = hybrid_searcher or HybridSearcher(
            collection_name=self.collection_name
        )

        # Override config if provider/model specified
        if llm_provider:
            config.llm_provider = llm_provider
        if llm_model:
            config.llm_model = llm_model

        # Create LLM model using provider factory
        try:
            llm = create_llm_model()
            logger.info(f"Initializing RAG Agent with provider: {config.llm_provider}, model: {config.llm_model}")

            # Create the agent with structured output
            # Note: pydantic-ai uses 'output_type' not 'result_type'
            self.agent = Agent(
                llm,
                output_type=RAGResponse,
                system_prompt=self._get_system_prompt(),
            )

            # Register the search tool
            self._register_tools()

            logger.info(
                f"RAG Agent initialized for collection '{self.collection_name}' "
                f"with provider '{config.llm_provider}' and model '{config.llm_model}'"
            )

        except ProviderConfigurationError:
            raise
        except Exception as e:
            raise AgenticRAGError(f"Failed to initialize RAG Agent: {e}") from e

    def _get_system_prompt(self) -> str:
        """Get system prompt for the RAG agent.

        Returns:
            System prompt string
        """
        return """You are a helpful AI assistant with access to a knowledge base.

When answering questions:
1. Use the search_knowledge_base tool to find relevant information
2. Synthesize information from multiple sources when available
3. Always cite your sources with relevant quotes
4. Provide a confidence score based on the quality and quantity of sources
5. If you don't find relevant information, say so honestly

Your responses should be accurate, well-structured, and backed by citations.
"""

    def _register_tools(self) -> None:
        """Register tools for the agent."""

        @self.agent.tool
        async def search_knowledge_base(
            ctx: RunContext[RAGAgentDependencies], query: str, limit: int = 5
        ) -> list[dict[str, Any]]:
            """Search the knowledge base for relevant information.

            Args:
                ctx: RunContext with RAGAgentDependencies
                query: Search query
                limit: Maximum number of results to return

            Returns:
                List of search results with text, source, score, etc.
            """
            logger.info(f"Tool called: search_knowledge_base(query='{query[:50]}...', limit={limit})")

            try:
                # Execute hybrid search
                results = ctx.deps.hybrid_searcher.search(query=query, limit=limit)

                # Convert SearchResult objects to dicts for the LLM
                search_results = []
                for result in results:
                    search_results.append(
                        {
                            "text": result.text,
                            "source_file": result.file_path,
                            "heading_hierarchy": result.heading_hierarchy,
                            "score": result.score,
                            "chunk_index": result.chunk_index,
                        }
                    )

                logger.info(f"Search returned {len(search_results)} results")
                return search_results

            except Exception as e:
                logger.error(f"Search failed: {e}")
                raise

    async def run(
        self,
        query: str,
        message_history: list[dict[str, str]] | None = None,
    ) -> RAGResponse:
        """Run the RAG agent on a query.

        Args:
            query: User query
            message_history: Optional conversation history

        Returns:
            RAGResponse with answer, citations, and confidence

        Raises:
            AgenticRAGError: If agent execution fails
        """
        logger.info(f"Running RAG agent with query: '{query[:50]}...'")

        try:
            # Create dependencies
            deps = RAGAgentDependencies(
                hybrid_searcher=self.hybrid_searcher,
                collection_name=self.collection_name,
            )

            # Run the agent with timeout wrapper
            try:
                import asyncio
                try:
                    # Add timeout wrapper (300 seconds = 5 minutes)
                    result = await asyncio.wait_for(
                        self.agent.run(
                            query,
                            deps=deps,
                            message_history=message_history,
                        ),
                        timeout=300.0
                    )
                except asyncio.TimeoutError:
                    raise AgenticRAGError("LLM generation timed out after 300 seconds")
            except Exception as run_error:
                raise

            # pydantic-ai Agent.run() returns AgentRunResult with .output attribute, not .data
            try:
                output = result.output
                logger.info(
                    f"Agent completed: {output.sources_used} sources, "
                    f"confidence={output.confidence:.2f}"
                )
                return output
            except Exception as output_error:
                raise

        except Exception as e:
            raise AgenticRAGError(f"Agent execution failed: {e}") from e

    def run_sync(
        self,
        query: str,
        message_history: list[dict[str, str]] | None = None,
    ) -> RAGResponse:
        """Synchronous wrapper for run().

        Handles both cases: when event loop is running and when it's not.
        Uses a thread with a new event loop if the current loop is already running.

        Args:
            query: User query
            message_history: Optional conversation history

        Returns:
            RAGResponse with answer, citations, and confidence
        """
        import asyncio
        import threading
        from concurrent.futures import ThreadPoolExecutor

        # Check if event loop is already running
        try:
            asyncio.get_running_loop()
            # Loop is running - use a thread with a new event loop
            def run_in_thread():
                """Run the async function in a new event loop in a separate thread."""
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(self.run(query, message_history))
                finally:
                    new_loop.close()

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_thread)
                result = future.result()
        except RuntimeError:
            # No running loop - use asyncio.run() (cleaner than run_until_complete)
            result = asyncio.run(self.run(query, message_history))

        return result
