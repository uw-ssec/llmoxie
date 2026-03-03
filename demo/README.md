# LLMaven NAIRR Demo

**Event:** NAIRR Demo Day — March 12, 2026 **Duration:** ~90 minutes
**Audience:** NAIRR stakeholders, researchers, infrastructure engineers

## What is LLMaven?

LLMaven is an AI-powered tool library for scientific discovery, providing a
unified infrastructure for deploying and managing large language models. This
demo walks through LLMaven's infrastructure capabilities: CLI tooling,
Docker-based local services, Azure cloud deployment, AI-assisted development
workflows, and observability.

---

## Setup

Choose one of the two setup paths below.

### Option A: GitHub Codespaces (Recommended)

1. Click **Code** > **Codespaces** > **New with options**
2. Under **Dev container configuration**, select **"LLMaven Demo (NAIRR)"**
3. Click **Create codespace**
4. Wait for the `onCreate` script to complete (~1 minute). Tools are
   pre-installed in the Docker image:
   - pixi dependencies (`demo` environment — lean, no ML packages)
   - Pulumi CLI (for infrastructure demo)
   - Claude Code CLI (for RSE Plugins demo)
   - Azure CLI (pre-installed via devcontainer feature)
5. Set your Anthropic API key for Claude Code:
   ```bash
   export ANTHROPIC_API_KEY=your-key-here
   ```
6. Edit `docker/.env` with your LLM provider API keys (Azure OpenAI, Anthropic,
   etc.)
7. Start the Docker services:
   ```bash
   pixi run -e demo up
   ```

> **Note:** Port forwarding is automatic in Codespaces. When services start,
> you'll get notifications to open web UIs (LiteLLM, MLflow, MinIO Console,
> Qdrant). The `.devcontainer/demo/` configuration is separate from the main
> GPU-based devcontainer used for development.
>
> Participants can fork this repo and launch their own Codespace to follow
> along.

### Option B: Local Machine

**Prerequisites:**

- [pixi](https://pixi.sh) installed (>= 0.55.0)
- Docker Desktop running
- Azure CLI installed and authenticated (`az login`) — for Section 3
- Claude Code installed (`npm install -g @anthropic-ai/claude-code`) — for
  Section 4
- LLM provider API keys (Azure OpenAI, Anthropic, etc.)

**Quick start:**

```bash
git clone https://github.com/uw-ssec/llmaven.git
cd llmaven
cp docker/.env.example docker/.env
# Edit docker/.env with your API keys
pixi install -e demo
pixi run -e demo up
```

---

## Demo Sections

| #   | Section                                        | Time       | Guide                        |
| --- | ---------------------------------------------- | ---------- | ---------------------------- |
| 0   | Setup verification                             | 5 min      | (below)                      |
| 1   | [CLI Walkthrough](01_cli_demo.md)              | 10 min     | LLMaven CLI commands         |
| 2   | [Services Architecture](02_services_demo.md)   | 20 min     | Docker Compose stack         |
| 3   | [Infrastructure Deployment](03_infra_demo.md)  | 15 min     | Azure deployment dry run     |
| 4   | [RSE Plugins Workflow](04_rse_plugins_demo.md) | 25 min     | Live AI-assisted development |
| 5   | [Logging & Observability](05_logging_demo.md)  | 10 min     | MLflow, container logs       |
| —   | Buffer / Q&A                                   | 5 min      | —                            |
|     | **Total**                                      | **90 min** |                              |

Each section is independently runnable — you can skip or reorder as needed.

---

## Section 0: Setup Verification (5 min)

Before starting the demo, verify everything is working:

```bash
# Check pixi environment is available
pixi run -e demo llmaven version
# Expected: LLMaven version 0.1.0

# Check Docker services are running
pixi run -e demo status
# Expected: All containers show "Up" and "healthy"

# Quick health checks
curl -s http://localhost:4000/health/liveliness  # LiteLLM
curl -s http://localhost:8080/health              # MLflow
curl -s http://localhost:6333/health              # Qdrant
curl -s http://localhost:9000/minio/health/live   # MinIO
```

If any service is not running, start them with `pixi run -e demo up` and wait
~60 seconds for all health checks to pass.

---

## Tips for Presenting

- **Split terminal:** Keep one terminal for demo commands (Sections 1-4) and
  another running `pixi run -e demo logs` to show live service activity
- **Pre-test everything:** Run through the full demo at least once before
  presenting. If using Codespaces, launch a fresh Codespace the day before to
  verify setup
- **Use Codespaces:** Avoid "works on my machine" issues by presenting from a
  Codespace. The demo devcontainer uses a pre-built Docker image with all tools
  baked in for near-instant readiness
- **Have fallbacks ready:** Sections 3 and 4 include pre-captured output for
  when Azure CLI or API access is unavailable
- **Pace yourself:** The timing estimates include buffer. If a section runs
  long, trim the next one rather than rushing
- **Engage the audience:** Pause after each section for questions. The
  architecture diagrams in Section 2 are good conversation starters
