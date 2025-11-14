# Authentication Setup Guide

This guide walks through setting up user authentication for the LLMaven Proxy.

## Overview

The proxy uses Azure Table Storage to manage user API keys. When authentication is enabled (default), clients must provide a valid API key in the `Authorization` header using Bearer token format.

## Prerequisites

See: [../infra/README.md](../infra/README.md)

## Add Users

See users.py CLI:

## Step 4: Configure the Proxy

Set environment variables:

```bash
# Azure Storage credentials (shared with logging)
AZURE_STORAGE_ACCOUNT_NAME=your-storage-account-name
AZURE_STORAGE_ACCOUNT_KEY=your-storage-account-key
```

## Logging Behavior

With authentication enabled, log files include the user ID:

```
{user_id}_{model}_{YYYYMMDD}.jsonl
```

Example:

```
abc-123-def_gpt-4_20241022.jsonl
```

Without authentication:

```
{model}_{YYYYMMDD}.jsonl
```

## Caching Behavior

- API keys are cached in memory for **5 minutes**
- Cache refreshes automatically in the background
- If Azure Table Storage is unavailable:
  - Proxy uses stale cached keys (fail-open design)
  - Ensures service availability during Azure outages
  - Logs warning messages

## Disabling Authentication

For development or testing:

```bash
AUTH_ENABLED=false
```

When disabled:

- No `Authorization` header required
- All requests are proxied without validation
- Logs do not include `user_id`

## Example: OpenAI Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-proxy:8000/v1",
    api_key="your-proxy-api-key-here"  # Not your OpenAI key!
)
```
