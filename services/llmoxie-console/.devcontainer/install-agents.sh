#!/usr/bin/env bash
# Install the coding agent CLIs via their official curl installers:
#   Claude Code -> ~/.local/bin/claude
#   Codex       -> ~/.local/bin/codex
#   Copilot CLI -> ~/.local/bin/copilot
#   OpenCode    -> ~/.opencode/bin/opencode
set -euo pipefail

GREEN="\033[0;32m"
RED="\033[0;31m"
BOLD="\033[1m"
RESET="\033[0m"

STAGE="install-agents"

say()   { printf "%b\n==> [%s] %s%b\n" "${BOLD}${GREEN}" "${STAGE}" "$*" "${RESET}"; }
error() { printf "%b      [%s] ERROR: %s%b\n" "${RED}" "${STAGE}" "$*" "${RESET}" >&2; }

export PATH="${HOME}/.local/bin:${HOME}/.opencode/bin:${PATH}"

# name -> installer URL
AGENTS=(
  "claude|https://claude.ai/install.sh"
  "codex|https://chatgpt.com/codex/install.sh"
  "copilot|https://gh.io/copilot-install"
  "opencode|https://opencode.ai/install"
)

for entry in "${AGENTS[@]}"; do
  bin="${entry%%|*}"
  url="${entry#*|}"
  say "Installing ${bin} from ${url}"
  curl -fsSL "${url}" | bash
  if ! command -v "${bin}" >/dev/null 2>&1; then
    error "${bin} not found on PATH after running installer"
    exit 1
  fi
done

say "Installed versions"
claude --version
codex --version
copilot --version
opencode --version

say "complete"
