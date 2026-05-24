"""Agentic chat endpoint for RAG-based conversations.

This module provides the API endpoint for RAG chat with structured
responses including citations and confidence scores.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llmaven.agentic.agent import RAGAgent
from llmaven.agentic.agent.models import RAGResponse
from llmaven.agentic.exceptions import AgenticRAGError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agentic/chat", tags=["agentic"])


class AgenticChatRequest(BaseModel):
    """Request schema for agentic chat endpoint.

    Attributes:
        query: User query or question
        collection: Collection name (optional, defaults to config)
        conversation_id: Optional conversation ID for tracking history
        message_history: Optional conversation history
        llm_provider: Optional LLM provider override
        llm_model: Optional LLM model override
        tags: Optional list of tags for request filtering and analysis
    """

    query: str = Field(..., description="User query or question", min_length=1)
    collection: Optional[str] = Field(None, description="Collection name")
    conversation_id: Optional[str] = Field(
        None, description="Conversation ID for tracking history"
    )
    message_history: Optional[list[dict[str, str]]] = Field(
        None, description="Conversation history"
    )
    llm_provider: Optional[str] = Field(
        None, description="LLM provider override (openai, ollama, huggingface)"
    )
    llm_model: Optional[str] = Field(None, description="LLM model override")
    tags: Optional[list[str]] = Field(
        None, description="Tags for request filtering and analysis in log data"
    )

@router.post("", response_model=RAGResponse)
async def agentic_chat(request: AgenticChatRequest):
    """Execute RAG chat with structured response and citations.

    This endpoint creates a RAG agent that:
    1. Searches the knowledge base for relevant information
    2. Generates an answer using an LLM
    3. Returns structured output with citations and confidence

    Args:
        request: AgenticChatRequest with query and chat parameters

    Returns:
        RAGResponse with answer, citations, and confidence

    Raises:
        HTTPException: If chat execution fails
    """
    try:
        logger.info(
            f"Agentic chat request: query='{request.query[:50]}...', "
            f"collection={request.collection}, conversation_id={request.conversation_id}"
        )

        # Create RAG agent
        agent = RAGAgent(
            collection_name=request.collection,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            tags=request.tags,
        )

        # Execute agent
        response = await agent.run(
            query=request.query,
            message_history=request.message_history,
        )

        logger.info(
            f"Agentic chat completed: confidence={response.confidence:.2f}, "
            f"sources={response.sources_used}, citations={len(response.citations)}"
        )

        return response

    except AgenticRAGError as e:
        logger.error(f"Agentic chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in agentic chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
