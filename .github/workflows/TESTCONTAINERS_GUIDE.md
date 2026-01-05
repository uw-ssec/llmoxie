# Testcontainers Guide for LLMaven

This guide explains how LLMaven uses testcontainers-python for running
integration tests with Qdrant.

## Overview

Instead of using GitHub Actions service containers (which only work on Linux),
LLMaven uses **testcontainers-python** to programmatically manage Qdrant
containers. This approach:

- ✅ Works on both Linux and macOS (when Docker is available)
- ✅ Provides dynamic port allocation (no port conflicts)
- ✅ Automatically cleans up containers after tests
- ✅ Allows tests to run locally with the same setup as CI
- ✅ No manual container management required

## How It Works

### 1. Pytest Fixtures (`tests/agentic/conftest.py`)

The project provides session-scoped fixtures that start Qdrant containers once
and share them across all tests:

```python
@pytest.fixture(scope="session")
def qdrant_container():
    """Provide a Qdrant testcontainer for integration tests."""
    with QdrantContainer() as container:
        yield container

@pytest.fixture
def qdrant_url(qdrant_container):
    """Provide the Qdrant HTTP API URL for tests."""
    return qdrant_container.get_api_url()
```

### 2. Using Fixtures in Tests

Tests can request these fixtures to get access to a running Qdrant instance:

```python
def test_qdrant_collection(qdrant_url):
    """Test creating a Qdrant collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance

    # Use the URL from the testcontainer
    client = QdrantClient(url=qdrant_url)

    # Create collection
    client.create_collection(
        collection_name="test_collection",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )

    # Verify
    collections = client.get_collections().collections
    assert any(c.name == "test_collection" for c in collections)
```

### 3. Container Lifecycle

- **Session Start**: First test requests `qdrant_container` → container starts
- **During Tests**: All tests share the same container (via `session` scope)
- **Session End**: After all tests complete → container automatically stops and
  removes

### 4. CI Integration

The GitHub Actions workflow simply needs Docker to be available:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check Docker status
        run: |
          docker info  # Ensure Docker is running
          docker ps

      - name: Run tests
        run: pixi run -e llmaven pytest tests/agentic/ -v
        # Testcontainers will handle Qdrant automatically
```

## Requirements

### Docker

Testcontainers requires Docker to be installed and running:

**Linux (GitHub Actions)**:

- ✅ Docker is pre-installed on ubuntu-latest runners
- ✅ Docker daemon is already running

**macOS (GitHub Actions)**:

- ⚠️ Currently disabled in CI due to Docker arm64 runner instability
- 🔗 See: https://github.com/docker/actions-toolkit/issues/317

**Local Development**:

- Install Docker Desktop (macOS/Windows) or Docker Engine (Linux)
- Ensure Docker daemon is running: `docker info`
- Ensure your user has Docker permissions:
  ```bash
  # Linux only
  sudo usermod -aG docker $USER
  # Log out and log back in
  ```

### Python Package

Testcontainers is already in project dependencies:

```toml
# pixi.toml
testcontainers = ">=4.8.0,<4.9"
```

## Configuration

### Default Behavior

By default, testcontainers:

- Uses `qdrant/qdrant:latest` image
- Allocates random available ports (e.g., 6333 → 49152)
- Starts container on-demand when fixture is requested
- Cleans up container when pytest exits

### Custom Configuration

You can customize container behavior in `conftest.py`:

```python
@pytest.fixture(scope="session")
def qdrant_container():
    """Custom Qdrant container configuration."""
    with QdrantContainer(
        image="qdrant/qdrant:v1.7.0",  # Specific version
        # Additional configuration as needed
    ) as container:
        yield container
```

### Environment Variables

Testcontainers respects these environment variables:

- `DOCKER_HOST`: Docker daemon URL (default: `unix:///var/run/docker.sock`)
- `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`: Override Docker socket path
- `TESTCONTAINERS_RYUK_DISABLED`: Disable automatic cleanup (default: `false`)

## Advantages vs Service Containers

| Feature              | GitHub Service Containers | Testcontainers              |
| -------------------- | ------------------------- | --------------------------- |
| **Platform Support** | Linux only                | Linux + macOS (with Docker) |
| **Port Management**  | Manual (6333:6333)        | Automatic (dynamic ports)   |
| **Local Testing**    | Manual `docker run`       | Automatic via pytest        |
| **Cleanup**          | Manual or job end         | Automatic after tests       |
| **Configuration**    | YAML workflow             | Python code (more flexible) |
| **Isolation**        | One per job               | One per test session        |

## Troubleshooting

### Docker Not Running

**Error**: `Cannot connect to the Docker daemon`

**Solution**:

```bash
# Check Docker status
docker info

# Start Docker
# macOS: Open Docker Desktop
# Linux: sudo systemctl start docker
```

### Permission Denied

**Error**:
`Permission denied while trying to connect to the Docker daemon socket`

**Solution**:

```bash
# Linux only
sudo usermod -aG docker $USER
# Log out and log back in
```

### Container Cleanup Issues

**Error**: Orphaned containers after tests

**Solution**:

```bash
# List testcontainers (prefix: testcontainers-)
docker ps -a | grep testcontainers

# Clean up manually
docker rm -f $(docker ps -aq --filter "name=testcontainers")
```

### Port Already in Use

**Error**: `Bind for 0.0.0.0:6333 failed: port is already allocated`

**Solution**:

- Testcontainers uses dynamic ports, so this shouldn't happen
- If you see this, check for manual Qdrant containers:
  ```bash
  docker ps | grep qdrant
  docker stop <container-id>
  ```

## Best Practices

### 1. Use Session Scope for Shared Resources

```python
@pytest.fixture(scope="session")  # Share across all tests
def qdrant_container():
    with QdrantContainer() as container:
        yield container
```

### 2. Separate Unit and Integration Tests

```python
# Unit tests (no Qdrant)
tests/agentic/test_models.py
tests/agentic/test_exceptions.py

# Integration tests (with Qdrant)
tests/agentic/test_qdrant_manager.py
tests/agentic/test_ingestion_pipeline.py
```

### 3. Mark Integration Tests

```python
import pytest

@pytest.mark.integration
def test_with_qdrant(qdrant_url):
    # Integration test
    pass

# Run only unit tests (fast)
pytest -m "not integration"

# Run only integration tests
pytest -m integration
```

### 4. Handle Container Startup Time

```python
def test_container_ready(qdrant_container):
    """Ensure container is ready before running tests."""
    import time
    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_container.get_api_url())

    # Wait for Qdrant to be ready (usually < 1 second)
    max_retries = 10
    for i in range(max_retries):
        try:
            client.get_collections()
            break
        except Exception:
            if i == max_retries - 1:
                raise
            time.sleep(0.5)
```

## Additional Resources

- [Testcontainers Python Documentation](https://testcontainers-python.readthedocs.io/)
- [Qdrant Container Module](https://testcontainers-python.readthedocs.io/en/latest/modules/qdrant/README.html)
- [Pytest Fixtures Guide](https://docs.pytest.org/en/stable/fixture.html)
- [Docker Installation](https://docs.docker.com/get-docker/)

## Migration from Service Containers

If you're migrating existing tests from GitHub service containers:

**Before (GitHub service containers)**:

```yaml
# .github/workflows/ci.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - 6333:6333
```

```python
# test.py
def test_qdrant():
    client = QdrantClient(url="http://localhost:6333")  # Hardcoded port
```

**After (testcontainers)**:

```yaml
# .github/workflows/ci.yml
# No services section needed!
```

```python
# conftest.py
@pytest.fixture(scope="session")
def qdrant_container():
    with QdrantContainer() as container:
        yield container

@pytest.fixture
def qdrant_url(qdrant_container):
    return qdrant_container.get_api_url()

# test.py
def test_qdrant(qdrant_url):
    client = QdrantClient(url=qdrant_url)  # Dynamic port via fixture
```

**Benefits**:

- ✅ Works locally without manual `docker run`
- ✅ Works on both Linux and macOS CI runners
- ✅ No port conflicts
- ✅ Automatic cleanup
