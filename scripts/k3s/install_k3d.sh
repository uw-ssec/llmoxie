#!/usr/bin/env bash
# Install the pinned k3d CLI (k3s in Docker) into the active pixi environment.
#
# conda-forge's `k3d` package is an unrelated Jupyter library, so the binary
# comes from the k3d GitHub release and is checked against the release checksum.
set -euo pipefail

K3D_VERSION="v5.9.0"
dest="${CONDA_PREFIX:?run this through pixi}/bin/k3d"

if [[ -x "$dest" ]] && "$dest" version | grep -q "k3d version ${K3D_VERSION}$"; then
    exit 0
fi

case "$(uname -s)-$(uname -m)" in
Darwin-arm64)
    asset="k3d-darwin-arm64"
    sha256="fe106541d5d0a3f18debcd4d432a16f8c0ce3e6ddc06f8fbb6f696a122313e00"
    ;;
Linux-x86_64)
    asset="k3d-linux-amd64"
    sha256="06d8f25bc3a971c4eb29e0ff08429b180402db0f4dec838c9eac427e296800a0"
    ;;
*)
    echo "No pinned k3d build for $(uname -s)-$(uname -m)" >&2
    exit 1
    ;;
esac

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL -o "$tmp" \
    "https://github.com/k3d-io/k3d/releases/download/${K3D_VERSION}/${asset}"
echo "${sha256}  ${tmp}" | shasum -a 256 -c - >/dev/null
install -m 0755 "$tmp" "$dest"
echo "Installed k3d ${K3D_VERSION} to ${dest}"
