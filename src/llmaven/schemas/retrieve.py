from typing import Any

from pydantic import BaseModel


class RetrieveRequest(BaseModel):
    documents: list[dict[str, Any]] | None = []
    query: str
    existing_collection: str | None = None
    existing_qdrant_path: str | None = None
    embedding_model: str
