#!/bin/bash
# onCreate script for LLMaven Demo Codespace
# Installs pixi dependencies, Pulumi CLI, and Claude Code

set -e

echo "=== LLMaven Demo Codespace Setup ==="

# Ensure .pixi directory is owned by vscode user
sudo chown vscode .pixi 2>/dev/null || true

# Install pixi dependencies for the llmaven environment
echo "Installing pixi dependencies (llmaven environment)..."
pixi install -e llmaven

# Install Pulumi CLI for infrastructure demo (Section 3)
echo "Installing Pulumi CLI..."
pixi run -e llmaven install-pulumi

# Install Claude Code CLI
echo "Installing Claude Code CLI..."
npm install -g @anthropic-ai/claude-code

# Copy .env.example to .env if it doesn't exist
if [ ! -f docker/.env ]; then
    echo "Creating docker/.env from .env.example..."
    cp docker/.env.example docker/.env
fi

echo ""
echo "=== Setup Complete ==="
echo "Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
echo "Pixi: $(pixi --version)"
echo ""
echo "Next steps:"
echo "  1. Set your ANTHROPIC_API_KEY for Claude Code: export ANTHROPIC_API_KEY=your-key"
echo "  2. Edit docker/.env with your LLM provider API keys"
echo "  3. Run 'pixi run -e llmaven up' to start Docker services"
echo "  4. Follow demo/README.md for the full walkthrough"
