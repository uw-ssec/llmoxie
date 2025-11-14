# Container Build and Deployment

## Overview

The LLMaven Proxy is containerized using Docker and automatically built/published to GitHub Container Registry (GHCR).

## Container Details

- **Base Image:** `python:3.11-alpine`
- **Build:** Multi-stage build for optimized size
- **Port:** 8888 (internal)
- **Health Check:** `GET /health` endpoint
- **Registry:** `ghcr.io/uw-ssec/llmaven/proxy`

## Automated Builds

### Triggers

- Push to `main` branch (when `proxy/**` files change)
- Manual workflow dispatch via GitHub Actions UI

### Tags Generated

1. `latest` - Always points to most recent build
2. `YYYYMMDD` - Date-based tag (e.g., `20241022`)
3. `YYYYMMDD-sha-abc123` - Date + git commit SHA

### Platforms

- `linux/amd64`
- `linux/arm64`

## Local Development

### Build locally:

```bash
cd /path/to/llmaven
docker build -t llmaven-proxy:dev -f proxy/Dockerfile .
```

### Run locally (without authentication):

```bash
docker run -it --rm \
  -p 8888:8888 \
  -e OPENAI_API_KEY=your-key \
  -e OPENAI_BASE_URL=your-service \
  -e STORAGE_TYPE=local \
  -e AUTH_ENABLED=false \
  -v $(pwd)/logs:/app/logs \
  llmaven-proxy:dev
```

### Run locally (with authentication):

```bash
docker run -it --rm \
  -p 8888:8888 \
  -e OPENAI_API_KEY=your-key \
  -e OPENAI_BASE_URL=your-service \
  -e STORAGE_TYPE=azure \
  -e AUTH_ENABLED=true \
  -e AZURE_STORAGE_ACCOUNT_NAME=your-account \
  -e AZURE_STORAGE_ACCOUNT_KEY=your-key \
  llmaven-proxy:dev
```

### Test:

```bash
curl http://localhost:8888/health
```

## Production Deployment

### Pull from GHCR:

```bash
docker pull ghcr.io/uw-ssec/llmaven/proxy:latest
```

### Kubernetes Deployment:

See main README.md for full Kubernetes manifests.

### Required Environment Variables:

- `OPENAI_API_KEY` - OpenAI API key (from Kubernetes Secret)
- `OPENAI_BASE_URL` - OpenAI API endpoint
- `STORAGE_TYPE` - `local` or `azure`
- `AZURE_STORAGE_ACCOUNT_NAME` - (if using Azure storage or authentication)
- `AZURE_STORAGE_ACCOUNT_KEY` - (if using Azure, from Secret)

### Authentication Variables (if enabled):

- `AUTH_ENABLED` - Default: `true` (set to `false` to disable)

**Note:** Azure Storage credentials are shared between logging (Blob Storage) and authentication (Table Storage).

### Optional Environment Variables:

- `PROXY_TIMEOUT` - Default: `300` seconds
- `LOCAL_LOG_DIR` - Default: `logs`
- `AZURE_STORAGE_CONTAINER` - Default: `proxy-logs`
