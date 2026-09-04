#!/bin/sh
# Locate or verify the agentshield binary, then start serve on loopback.
# Never execute a downloaded file until its sha256 matches skill-manifest.json.
set -eu

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_OVERRIDE=${AGENTSHIELD_STATE_DIR:-}
MANIFEST="$SKILL_DIR/skill-manifest.json"

log() { printf 'agentshield-bootstrap: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "need sha256sum or shasum"
  fi
}

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

verify_against_manifest() {
  bin=$1
  [ -f "$MANIFEST" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  got=$(sha256_file "$bin")
  python3 - "$MANIFEST" "$got" <<'PY'
import json, sys, platform
manifest_path, got = sys.argv[1], sys.argv[2].lower()
with open(manifest_path, encoding="utf-8") as f:
    m = json.load(f)
arts = (m.get("binary") or {}).get("artifacts") or []
if not arts:
    sys.exit(0)
osname = {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(sys.platform, sys.platform)
arch = platform.machine().lower()
arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(arch, arch)
want = None
for a in arts:
    if a.get("os") == osname and a.get("arch") == arch:
        want = (a.get("sha256") or "").lower()
        break
if not want:
    sys.exit(0)
if want != got:
    sys.stderr.write("agentshield-bootstrap: sha256 mismatch for this OS/arch\n")
    sys.exit(3)
PY
}

BIN=$(find_bin) || die "agentshield binary not found. Build apps/agentshield or set AGENTSHIELD_BIN. Refusing to download without a signed skill-manifest.json."
verify_against_manifest "$BIN" || die "binary hash does not match skill-manifest.json"

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
