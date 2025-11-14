"""API v1 main router.

This module aggregates all v1 endpoints into a single router.
"""

from __future__ import annotations

from fastapi import APIRouter
from .endpoints import generate, retrieve

# Create the main v1 router
router = APIRouter(prefix="/v1")

router.include_router(generate.router)
router.include_router(retrieve.router)
