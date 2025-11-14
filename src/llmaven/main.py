"""FastAPI application for LLMaven project.

This module provides the main FastAPI application with REST API endpoints.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import config
from .v1 import router as v1_router

# Create FastAPI application with metadata
app = FastAPI(
    title=config.api_title,
    description=config.api_description,
    version=config.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Configure CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=config.cors_allow_methods,
    allow_headers=config.cors_allow_headers,
)


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle validation errors with detailed messages.

    Args:
        request: The incoming request
        exc: The validation error

    Returns:
        JSONResponse with error details
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle general exceptions.

    Args:
        request: The incoming request
        exc: The exception

    Returns:
        JSONResponse with error message
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": str(exc),
        },
    )


# Root endpoint
@app.get("/", tags=["root"])
def read_root() -> dict[str, str]:
    """Root endpoint providing API information.

    Returns:
        Dictionary with API message and version
    """
    return {
        "message": config.api_title,
        "version": config.api_version,
        "docs": "/docs",
        "ping": "/ping",
    }


# Legacy hello endpoint for backward compatibility
@app.get("/ping", tags=["root"])
def ping() -> str:
    """Ping endpoint for service up check.

    Returns:
        The string "pong"
    """
    return "pong"


# Mount v1 router
app.include_router(v1_router.router)
