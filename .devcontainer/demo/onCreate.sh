#!/bin/bash
# onCreate script for LLMaven Demo Codespace
# The pixi environment, Pulumi, and Claude Code are pre-installed in the Docker image.
# This script handles .env setup, ownership fix, and fallback for forks.

set -e

echo "=== LLMaven Demo Codespace Setup ==="

# Ensure .pixi directory is owned by vscode user
sudo chown -R vscode:vscode .pixi 2>/dev/null || true

# Copy .env.example to .env if it doesn't exist
if [ ! -f docker/.env ]; then
    echo "Creating docker/.env from .env.example..."
    cp docker/.env.example docker/.env
fi

# Fallback: if pixi environment is missing (e.g., fork with different repo name),
# run the full install. The pre-built image places .pixi at /workspaces/llmaven/.pixi
# which won't match if the workspace folder has a different name.
if [ ! -d ".pixi/envs/llmaven" ]; then
    echo "Pixi environment not found — running full install (this may take a few minutes)..."
    pixi install -e llmaven
    pixi run -e llmaven install-pulumi
fi

# Verification
echo ""
echo "=== Setup Complete ==="
echo "Pixi: $(pixi --version)"
echo "Node: $(node --version 2>/dev/null || echo 'not found')"
echo "Claude Code: $(claude --version 2>/dev/null || echo 'not found')"
echo "Pulumi: $(pixi run -e llmaven pulumi version 2>/dev/null || echo 'not found')"
echo ""
echo "Next steps:"
echo "  1. Set your ANTHROPIC_API_KEY for Claude Code: export ANTHROPIC_API_KEY=your-key"
echo "  2. Edit docker/.env with your LLM provider API keys"
echo "  3. Run 'pixi run -e llmaven up' to start Docker services"
echo "  4. Follow demo/README.md for the full walkthrough"
