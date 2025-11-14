"""Generate CRUD endpoints.

This module provides REST API endpoints for generate operations.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status

from fastapi import APIRouter, HTTPException
from ...services.generation_service import generate_answer
from ...schemas.generate import GenerationRequest

router = APIRouter(prefix="/generate", tags=["generate"])

@router.post("")
async def retrieve(request: GenerationRequest):
    try:
        result = generate_answer(request.prompt, request.generation_model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
