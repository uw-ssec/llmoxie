
"""
FastAPI proxy service for OpenAI API.

This proxy forwards all requests to the OpenAI API and supports streaming responses.
"""

import json
import logging
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Header
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from data_log import DataLogger
from auth import UserKeyStore

app = FastAPI(
    title="OpenAI API Proxy",
    description="Proxy service for OpenAI API with streaming support",
    version="1.0.0",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
PROXY_TIMEOUT = float(os.getenv("PROXY_TIMEOUT", "300"))
PROXY_PORT = int(os.getenv("PROXY_PORT", "8888"))
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

if not OPENAI_BASE_URL:
    raise ValueError("OPENAI_BASE_URL environment variable is required")

# Initialize data logger
data_log = DataLogger()

# Initialize authentication key store if enabled
key_store = None
if AUTH_ENABLED:
    key_store = UserKeyStore()

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting OpenAI API Proxy...")
    if key_store:
        logger.info("Starting background cache refresh for user keys...")
        key_store.start_background_refresh()
        logger.info("Authentication enabled with background refresh")
    else:
        logger.info("Authentication disabled")

        
async def verify_api_key(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """
    Verify API key from Authorization header.
    
    Args:
        authorization: Authorization header value (Bearer token)
    
    Returns:
        User info dict if valid, raises HTTPException if invalid
    """
    if not AUTH_ENABLED:
        return None
    
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )
    
    # Extract Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Expected: Bearer <token>"
        )
    
    api_key = authorization[7:]  # Remove "Bearer " prefix
    
    # Validate API key
    if key_store is None:
        raise HTTPException(
            status_code=500,
            detail="Authentication is not configured"
        )
    
    user_info = key_store.validate_api_key(api_key)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    return user_info


async def proxy_request(
    request: Request,
    path: str,
    method: str = "POST",
    user_info: Optional[dict] = None,
) -> Response:
    """
    Proxy a request to the OpenAI API.

    Args:
        request: The incoming FastAPI request
        path: The API path to proxy to
        method: HTTP method (GET, POST, etc.)
        user_info: Optional user information from authentication

    Returns:
        Response from the downstream service
    """
    # Get request body
    body = await request.body()

    # Parse request body for logging
    request_body = None
    if body:
        try:
            request_body = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # If JSON parsing or decoding fails, fall back to a safe string representation
            request_body = body.decode('utf-8', errors='replace')

    # Create log entry with optional user_id
    user_id = user_info.get("user_id") if user_info else None
    log_entry = data_log.create_log_entry(
        method=method,
        path=path,
        request_headers=dict(request.headers),
        request_body=request_body,
        user_id=user_id,
    )

    # Prepare headers for downstream request
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    # Add any custom headers from the original request (excluding auth)
    for key, value in request.headers.items():
        if key.lower() not in ["host", "authorization", "content-length"]:
            headers[key] = value

    # Build the downstream URL
    url = f"{OPENAI_BASE_URL}{path}"

    # Create HTTP client with streaming support
    async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
        try:
            # Make the request to the downstream service
            downstream_request = client.build_request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )
            downstream_response = await client.send(
                downstream_request,
                stream=True,
            )

            # Check if the response is streaming (for chat completions with stream=true)
            content_type = downstream_response.headers.get("content-type", "")
            is_streaming = (
                "text/event-stream" in content_type
                or downstream_response.headers.get("transfer-encoding") == "chunked"
            )

            if is_streaming:
                # Collect streaming response chunks
                collected_chunks = []

                async def stream_generator():
                    async for chunk in downstream_response.aiter_bytes():
                        # Collect chunks for logging
                        collected_chunks.append(chunk)
                        yield chunk

                    # After streaming completes, log the full exchange
                    response_text = b''.join(collected_chunks).decode('utf-8', errors='replace')
                    data_log.add_response_to_entry(
                        log_entry=log_entry,
                        status_code=downstream_response.status_code,
                        response_headers=dict(downstream_response.headers),
                        response_body=response_text,
                        streaming=True,
                    )
                    data_log.log_entry(log_entry)

                return StreamingResponse(
                    stream_generator(),
                    status_code=downstream_response.status_code,
                    headers=dict(downstream_response.headers),
                    media_type=content_type,
                )
            else:
                # Return regular response with logging
                content = await downstream_response.aread()
                # Parse response body for logging
                response_body = None
                try:
                    response_body = json.loads(content.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # If JSON parsing or decoding fails, fall back to a safe string representation
                    response_body = content.decode('utf-8', errors='replace')

                data_log.add_response_to_entry(
                    log_entry=log_entry,
                    status_code=downstream_response.status_code,
                    response_headers=dict(downstream_response.headers),
                    response_body=response_body,
                    streaming=False,
                )
                data_log.log_entry(log_entry)

                return Response(
                    content=content,
                    status_code=downstream_response.status_code,
                    headers=dict(downstream_response.headers),
                    media_type=content_type,
                )

        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="Gateway timeout") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Bad gateway: {str(exc)}") from exc


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_openai_v1(
    request: Request,
    path: str,
    authorization: Optional[str] = Header(None)
):
    """
    Proxy all OpenAI API v1 endpoints.

    This includes:
    - /v1/chat/completions (with streaming support)
    - /v1/completions
    - /v1/embeddings
    - /v1/models
    - And all other v1 endpoints
    """
    # Verify API key if authentication is enabled
    user_info = await verify_api_key(authorization)
    
    return await proxy_request(request, f"/v1/{path}", method=request.method, user_info=user_info)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "downstream": OPENAI_BASE_URL,
    }


@app.get("/")
async def root():
    """Root endpoint with service information."""
    return {
        "service": "OpenAI API Proxy",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "proxy": "/v1/*",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PROXY_PORT,
        reload=True,
    )
