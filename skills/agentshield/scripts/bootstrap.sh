#!/bin/sh
# Locate or verify the agentshield binary, then start serve on loopback.
# Never execute a downloaded file until its sha256 matches skill-manifest.json.
# Manifest signature is verified against the v1 local trust root below.
set -eu

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_OVERRIDE=${AGENTSHIELD_STATE_DIR:-}
MANIFEST="$SKILL_DIR/skill-manifest.json"
VERIFY_PY="$SKILL_DIR/scripts/verify_manifest.py"

# v1 local trust root (Ed25519, base64). Used to verify skill-manifest.json.
RELEASE_PUBKEY_B64='rlDnDsQ3RCwpdX2deW/iUqey1RZiWYvFCp2Ux6xplRo='

log() { printf 'agentshield-bootstrap: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

find_bin() {
  if [ -n "${AGENTSHIELD_BIN:-}" ] && [ -x "$AGENTSHIELD_BIN" ]; then
    printf '%s\n' "$AGENTSHIELD_BIN"
    return
  fi
  if command -v agentshield >/dev/null 2>&1; then
    command -v agentshield
    return
  fi
  if [ -x "$HOME/.local/bin/agentshield" ]; then
    printf '%s\n' "$HOME/.local/bin/agentshield"
    return
  fi
  repo_bin="$SKILL_DIR/../../apps/agentshield/agentshield"
  if [ -x "$repo_bin" ]; then
    printf '%s\n' "$repo_bin"
    return
  fi
  return 1
}

verify_manifest() {
  bin=$1
  [ -f "$MANIFEST" ] || die "skill-manifest.json missing; refusing to start"
  command -v python3 >/dev/null 2>&1 || die "python3 required to verify skill-manifest.json"
  extra=""
  if [ -n "${AGENTSHIELD_REQUIRE_PINNED:-}" ]; then
    extra=""
  else
    extra="--allow-local"
  fi
  # shellcheck disable=SC2086
  python3 "$VERIFY_PY" --manifest "$MANIFEST" --pubkey "$RELEASE_PUBKEY_B64" --bin "$bin" $extra \
    || die "skill-manifest.json verification failed"
}

BIN=$(find_bin) || die "agentshield binary not found. Build apps/agentshield or set AGENTSHIELD_BIN. Refusing to download without a signed skill-manifest.json."
verify_manifest "$BIN" || die "binary hash does not match skill-manifest.json"

log "using $BIN"
"$BIN" version >&2 || die "binary failed to run"

# Start serve if loopback is not already taken.
port=${AGENTSHIELD_PORT:-47611}
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
      AGENTSHIELD_STATE_DIR="$STATE_OVERRIDE" "$BIN" serve --port "$port" &
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
