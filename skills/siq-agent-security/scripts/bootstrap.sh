#!/bin/sh
# Locate or verify the siq-agent-security binary, then start serve on loopback.
# Never execute a downloaded file until its sha256 matches skill-manifest.json.
# Manifest signature is verified against the v1 local trust root (via resolve_verified_bin.sh).
set -eu

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_OVERRIDE=${SIQ_AGENT_SECURITY_STATE_DIR:-${AGENTSHIELD_STATE_DIR:-}}
RESOLVE="$SKILL_DIR/scripts/resolve_verified_bin.sh"

log() { printf 'siq-agent-security-bootstrap: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

[ -x "$RESOLVE" ] || [ -f "$RESOLVE" ] || die "missing resolve_verified_bin.sh"
BIN=$(sh "$RESOLVE") || die "binary verification failed"

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
