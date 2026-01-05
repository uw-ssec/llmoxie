"""Data models for RAG agent responses.

This module defines Pydantic models for structured RAG responses
with citations and confidence scores.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class Citation(BaseModel):
    """Citation from a source document.

    Attributes:
        source_file: Path to the source file
        quote: Relevant quote from the source
        relevance_score: Relevance score (0.0-1.0)
        heading_hierarchy: Optional heading hierarchy context
    """

    source_file: str = Field(..., description="Path to the source file")
    quote: str = Field(..., description="Relevant quote from the source")
    relevance_score: float = Field(
        ..., description="Relevance score (0.0-1.0)", ge=0.0, le=1.0
    )
    heading_hierarchy: str | None = Field(None, description="Heading hierarchy context")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_file": "/docs/architecture.md",
                "quote": "The system uses a multi-tier architecture with microservices...",
                "relevance_score": 0.92,
                "heading_hierarchy": "Architecture > System Design",
            }
        }
    )


class RAGResponse(BaseModel):
    """Structured response from RAG agent.

    Attributes:
        answer: The generated answer to the query
        citations: List of citations supporting the answer
        confidence: Confidence score for the answer (0.0-1.0)
        sources_used: Number of source documents consulted
    """

    answer: str = Field(..., description="Generated answer to the query")
    citations: list[Citation] = Field(
        default_factory=list, description="Citations supporting the answer"
    )
    confidence: float = Field(
        ..., description="Confidence score (0.0-1.0)", ge=0.0, le=1.0
    )
    sources_used: int = Field(
        0, description="Number of source documents consulted", ge=0
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "The system architecture follows a microservices pattern...",
                "citations": [
                    {
                        "source_file": "/docs/architecture.md",
                        "quote": "The system uses a multi-tier architecture...",
                        "relevance_score": 0.92,
                        "heading_hierarchy": "Architecture > System Design",
                    }
                ],
                "confidence": 0.88,
                "sources_used": 3,
            }
        }
    )
