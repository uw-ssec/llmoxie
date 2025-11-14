# OpenAI API Proxy

A FastAPI-based proxy service for the OpenAI API with streaming support.

## Features

- ✅ Proxies all OpenAI API v1 endpoints
- ✅ Full streaming support for chat completions (Server-Sent Events)
- ✅ Request/response logging to local file system or Azure Blob Storage
- ✅ Dynamic log file naming: `{model}_{YYYYMMDD}.jsonl`
- ✅ Environment-based configuration
- ✅ Health check endpoint

## Setup

1. **Configure environment variables:**

   Copy the example environment file and add your OpenAI API key:

   ```bash
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY
   ```

2. **Run the proxy:**

   ```bash
   # From the proxy directory
   python main.py
   ```

## Docker Deployment

See [CONTAINER.md](CONTAINER.md)

### Health Check:

```bash
curl http://localhost:8888/health
```

## Usage

Once running, the proxy will be available at `http://localhost:8000`.

**Log File Naming:**

- **With authentication:** `{user_id}_{model}_{YYYYMMDD}.jsonl`
  - Example: `abc-123-def_gpt-4_20241021.jsonl`
- **Without authentication:** `{model}_{YYYYMMDD}.jsonl`
  - Example: `gpt-4_20241021.jsonl`
- Each file contains all requests/responses for that user/model on that day

### Local Storage Example

```bash
STORAGE_TYPE=local
LOCAL_LOG_DIR=logs
```

Logs will be saved to: `logs/gpt-4_20241021.jsonl`

### Azure Blob Storage Example

```bash
STORAGE_TYPE=azure
AZURE_STORAGE_ACCOUNT_NAME=mystorageaccount
AZURE_STORAGE_ACCOUNT_KEY=your-account-key-here
AZURE_STORAGE_CONTAINER=proxy-logs
```

Logs will be uploaded to: `az://proxy-logs/gpt-4_20241021.jsonl`

## Architecture

The proxy forwards all requests to the OpenAI API while:

1. Adding the API key from environment variables
2. Preserving request headers (except auth/host)
3. Detecting and handling streaming responses
4. Supporting all HTTP methods (GET, POST, PUT, DELETE, PATCH)
5. Logging all requests and responses to storage (local or Azure)

### Log Format

Each log entry is a single JSON line with:

```json
{
  "timestamp": "2024-10-21T10:30:45.123456",
  "request": {
    "method": "POST",
    "path": "/v1/chat/completions",
    "headers": {...},
    "body": {
      "model": "gpt-4",
      "messages": [...]
    }
  },
  "response": {
    "status_code": 200,
    "headers": {...},
    "body": {...},
    "streaming": true
  }
}
```

## Architecture Notes

- **Storage**: Uses `fsspec` for unified interface to local filesystem and Azure
  Blob Storage
- **Azure Backend**: Uses `adlfs` (Azure Data Lake File System) for Azure
  operations
- Both storage backends support efficient append operations

## API Endpoints

- `GET /` - Service information
- `GET /health` - Health check
- `* /v1/{path}` - Proxy to OpenAI API v1 endpoints
