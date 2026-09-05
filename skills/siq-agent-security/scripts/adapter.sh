#!/bin/sh
# Probe well-known platform dirs and call `siq-agent-security adapter install`.
set -eu
SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

find_bin() {
  for cand in "${SIQ_AGENT_SECURITY_BIN:-}" "${AGENTSHIELD_BIN:-}"; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then
      printf '%s\n' "$cand"
      return
    fi
  done
  for name in siq-agent-security agentshield; do
    if command -v "$name" >/dev/null 2>&1; then
      command -v "$name"
      return
    fi
  done
  for leaf in siq-agent-security agentshield; do
    repo_bin="$SKILL_DIR/../../apps/agentshield/$leaf"
    if [ -x "$repo_bin" ]; then
      printf '%s\n' "$repo_bin"
      return
    fi
  done
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
