from typing import Any, Dict, List, Optional

from pydantic import BaseModel

class RetrieveRequest(BaseModel):
    documents: Optional[List[Dict[str, Any]]] = []
    query: str
    existing_collection: Optional[str] = None
    existing_qdrant_path: Optional[str] = None
    embedding_model: str
