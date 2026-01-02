# Adding New API Endpoints

This guide covers the step-by-step process for adding new REST API endpoints to
LLMaven.

## Overview

LLMaven follows a layered architecture:

1. **Schema** → Define request/response models
2. **Service** → Implement business logic
3. **Endpoint** → Create the route handler
4. **Router** → Register the endpoint
5. **Tests** → Add test coverage

---

## Step 1: Create Schema

Create a new file in `src/llmaven/schemas/`:

```python
# src/llmaven/schemas/new_feature.py
from pydantic import BaseModel

class NewFeatureRequest(BaseModel):
    param: str

class NewFeatureResponse(BaseModel):
    result: str
    status_code: int
```

---

## Step 2: Create Service

Create a new file in `src/llmaven/services/`:

```python
# src/llmaven/services/new_feature_service.py
def process_feature(param: str) -> dict:
    # Business logic here
    return {"result": "...", "status_code": 200}
```

---

## Step 3: Create Endpoint

Create a new file in `src/llmaven/v1/endpoints/`:

```python
# src/llmaven/v1/endpoints/new_feature.py
from fastapi import APIRouter, HTTPException
from llmaven.schemas.new_feature import NewFeatureRequest, NewFeatureResponse
from llmaven.services.new_feature_service import process_feature

router = APIRouter()

@router.post("/new_feature/", response_model=NewFeatureResponse)
async def new_feature(request: NewFeatureRequest):
    try:
        return process_feature(request.param)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## Step 4: Register Router

Update `src/llmaven/v1/router.py`:

```python
from llmaven.v1.endpoints import new_feature
router.include_router(new_feature.router)
```

---

## Step 5: Add Tests

Create a test file in `tests/`:

```python
# tests/test_new_feature.py
import pytest
from fastapi.testclient import TestClient
from llmaven.main import app

client = TestClient(app)

def test_new_feature_success():
    response = client.post("/v1/new_feature/", json={"param": "test"})
    assert response.status_code == 200
    assert "result" in response.json()
```

---

## Verification

After implementing, verify with:

```bash
# Run the specific test
pytest tests/test_new_feature.py -v

# Start the server and test manually
llmaven server serve --env development --reload
# Then visit http://localhost:8000/docs to test via Swagger UI
```
