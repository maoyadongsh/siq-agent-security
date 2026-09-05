#!/bin/sh
# Locate or verify the siq-agent-security binary, then start serve on loopback.
# Never execute a downloaded file until its sha256 matches skill-manifest.json.
# Manifest signature is verified against the v1 local trust root below.
set -eu

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_OVERRIDE=${SIQ_AGENT_SECURITY_STATE_DIR:-${AGENTSHIELD_STATE_DIR:-}}
MANIFEST="$SKILL_DIR/skill-manifest.json"
VERIFY_PY="$SKILL_DIR/scripts/verify_manifest.py"

# v1 local trust root (Ed25519, base64). Used to verify skill-manifest.json.
RELEASE_PUBKEY_B64='LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY='

log() { printf 'siq-agent-security-bootstrap: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

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
    if [ -x "$HOME/.local/bin/$leaf" ]; then
      printf '%s\n' "$HOME/.local/bin/$leaf"
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

verify_manifest() {
  bin=$1
  [ -f "$MANIFEST" ] || die "skill-manifest.json missing; refusing to start"
  command -v python3 >/dev/null 2>&1 || die "python3 required to verify skill-manifest.json"
  extra=""
  if [ -z "${SIQ_AGENT_SECURITY_REQUIRE_PINNED:-}" ] && [ -z "${AGENTSHIELD_REQUIRE_PINNED:-}" ]; then
    extra="--allow-local"
  fi
  # shellcheck disable=SC2086
  python3 "$VERIFY_PY" --manifest "$MANIFEST" --pubkey "$RELEASE_PUBKEY_B64" --bin "$bin" $extra \
    || die "skill-manifest.json verification failed"
}

BIN=$(find_bin) || die "siq-agent-security binary not found. Build apps/agentshield or set SIQ_AGENT_SECURITY_BIN. Refusing to download without a signed skill-manifest.json."
verify_manifest "$BIN" || die "binary hash does not match skill-manifest.json"

log "using $BIN"
"$BIN" version >&2 || die "binary failed to run"

# Start serve if loopback is not already taken.
port=${SIQ_AGENT_SECURITY_PORT:-${AGENTSHIELD_PORT:-47611}}
if command -v python3 >/dev/null 2>&1; then
  if python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
  then
    log "serve already listening on 127.0.0.1:$port"
  else
    log "starting serve on 127.0.0.1:$port"
    if [ -n "$STATE_OVERRIDE" ]; then
      SIQ_AGENT_SECURITY_STATE_DIR="$STATE_OVERRIDE" AGENTSHIELD_STATE_DIR="$STATE_OVERRIDE" "$BIN" serve --port "$port" &
    else
      "$BIN" serve --port "$port" &
    fi
    sleep 1
  fi
else
  log "python3 not found; not auto-starting serve. Run: $BIN serve"
fi

log "console: http://127.0.0.1:$port  (token file is <state>/token; never print the token)"
log "next: scripts/adapter.sh   then a human opens the console"
printf '%s\n' "$BIN"
