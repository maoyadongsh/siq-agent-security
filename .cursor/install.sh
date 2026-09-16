#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for siq-agent-security.
# Base image already provides Python 3.12, Go 1.22, Node 22 and npm; this script
# installs the one missing tool (uv) and prepares each app's dependency state.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PATH="$HOME/.local/bin:$PATH"

echo "== toolchain =="
python3 --version
go version
node --version
npm --version

# uv: pinned resolver used by the control plane (see apps/control-api/uv.lock).
if ! command -v uv >/dev/null 2>&1; then
  echo "== installing uv =="
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

echo "== control-api: locked dependency sync =="
(cd apps/control-api && uv sync --dev --locked)

echo "== web: locked npm install =="
(cd apps/web && npm ci)

echo "== agentshield (Go): warm module cache and build =="
(cd apps/agentshield && go build ./... )

echo "install complete"
