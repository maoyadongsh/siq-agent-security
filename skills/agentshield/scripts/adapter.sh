#!/bin/sh
# Probe well-known platform dirs and call `agentshield adapter install`.
set -eu
SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

find_bin() {
  if [ -n "${AGENTSHIELD_BIN:-}" ] && [ -x "$AGENTSHIELD_BIN" ]; then
    printf '%s\n' "$AGENTSHIELD_BIN"
    return
  fi
  if command -v agentshield >/dev/null 2>&1; then
    command -v agentshield
    return
  fi
  repo_bin="$SKILL_DIR/../../apps/agentshield/agentshield"
  if [ -x "$repo_bin" ]; then
    printf '%s\n' "$repo_bin"
    return
  fi
  return 1
}

BIN=$(find_bin) || {
  echo "adapter.sh: run scripts/bootstrap.sh first" >&2
  exit 1
}

if [ $# -gt 0 ]; then
  exec "$BIN" adapter install "$1"
fi
exec "$BIN" adapter install
