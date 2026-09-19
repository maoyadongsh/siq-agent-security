#!/bin/sh
# Probe well-known platform dirs, verify release manifest, then call adapter install.
# Shares resolve_verified_bin.sh with bootstrap.sh (DEV04-B): never exec an unverified binary.
set -eu
SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RESOLVE="$SKILL_DIR/scripts/resolve_verified_bin.sh"

die() { echo "adapter.sh: $*" >&2; exit 1; }

[ -f "$RESOLVE" ] || die "missing resolve_verified_bin.sh; refuse to run unverified binary"
BIN=$(sh "$RESOLVE") || die "run scripts/bootstrap.sh first (or fix verification)"

if [ $# -gt 0 ]; then
  exec "$BIN" adapter install "$1"
fi
exec "$BIN" adapter install
