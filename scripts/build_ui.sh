#!/usr/bin/env bash
# Build the AgentShield local console and place it where Go embed expects it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/web"
if [[ ! -d node_modules ]]; then
  npm ci
fi
npm run build:local
