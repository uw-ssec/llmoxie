import traceback
from fastapi import APIRouter, HTTPException
from ...services.retrieval_service import perform_retrieval
from ...schemas.retrieve import RetrieveRequest

router = APIRouter(prefix="/retrieve", tags=["retrieve"])


@router.post("")
async def retrieve(request: RetrieveRequest):
    try:
        result = perform_retrieval(
            request.documents,
            request.query,
            request.existing_collection,
            request.existing_qdrant_path,
            request.embedding_model
        )
        return result
    except Exception as e:
        print("Error in retrieval:", str(e))  # Print error to logs
        print(traceback.format_exc())  # Print full traceback
        raise HTTPException(status_code=500, detail=str(e))
