# search_knowledge_base tool implementation

from pydantic import BaseModel, Field


class SearchKnowledgeBaseInput(BaseModel):
    """Input parameters for the search_knowledge_base tool."""

    query: str = Field(
        ...,
        description="The search query to find relevant information in the knowledge base",
        min_length=1,
        max_length=10000,
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results to return",
        ge=1,
        le=100,
    )
    collection_name: str | None = Field(
        default=None,
        description="Qdrant collection to search (defaults to configured collection)",
    )
    enable_rerank: bool | None = Field(
        default=None,
        description="Whether to apply ColBERT reranking (defaults to config setting)",
    )


class SearchResultOutput(BaseModel):
    """Single search result returned by the tool."""

    text: str = Field(description="The text content of the retrieved chunk")
    source_file: str = Field(description="Path to the source document")
    heading_hierarchy: str | None = Field(
        default=None,
        description="Document heading hierarchy for context",
    )
    score: float = Field(description="Relevance score (0.0 to 1.0)")
    chunk_index: int = Field(description="Index of chunk within source document")


class SearchKnowledgeBaseOutput(BaseModel):
    """Output from the search_knowledge_base tool."""

    results: list[SearchResultOutput] = Field(
        description="List of search results ordered by relevance"
    )
    total_results: int = Field(description="Number of results returned")
    query: str = Field(description="The original search query")
    collection_name: str = Field(description="The collection that was searched")
