#!/usr/bin/env bash
# Install the pixi environment (if a manifest exists) and auto-activate it in
# interactive shells.
set -euo pipefail

GREEN="\033[0;32m"
BOLD="\033[1m"
RESET="\033[0m"

STAGE="post-create"

say()  { printf "%b\n==> [%s] %s%b\n" "${BOLD}${GREEN}" "${STAGE}" "$*" "${RESET}"; }
info() { printf "      %s\n" "$*"; }

say "$(pixi --version)"

if [ -f pixi.toml ] || [ -f pyproject.toml ]; then
  say "Installing pixi environment"
  pixi install
else
  info "No pixi.toml or pyproject.toml found; skipping pixi install"
  exit 0
fi

say "Configuring shell auto-activation of the pixi env"
BASHRC="${HOME}/.bashrc"
HOOK_MARKER='# >>> pixi shell-hook >>>'
if ! grep -qF "${HOOK_MARKER}" "${BASHRC}" 2>/dev/null; then
  {
    echo ""
    echo "${HOOK_MARKER}"
    echo 'if [ -z "${PIXI_ENVIRONMENT_NAME:-}" ]; then'
    pixi shell-hook
    echo 'fi'
    echo "# <<< pixi shell-hook <<<"
  } >> "${BASHRC}"
  info "Added pixi shell-hook to ~/.bashrc"
else
  info "~/.bashrc already has the pixi shell-hook"
fi

say "complete"
