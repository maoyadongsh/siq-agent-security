#!/bin/sh
# Shared binary resolution + skill-manifest verification for bootstrap/adapter (DEV04-B/D/E).
# Prints the *staged* verified binary path on stdout. Never executes the binary.
# Download is opt-in via SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1 (after signature verify).
# Sourced or executed with: . "$0" is NOT used — call as:
#   BIN=$(sh "$SKILL_DIR/scripts/resolve_verified_bin.sh") || exit 1
set -eu

SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MANIFEST="$SKILL_DIR/skill-manifest.json"
VERIFY_PY="$SKILL_DIR/scripts/verify_manifest.py"

# v1 local trust root (Ed25519, base64). Must stay in sync with
# apps/agentshield/internal/skillmanifest.ReleasePublicKeyB64 and bootstrap.*.
RELEASE_PUBKEY_B64='LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY='

die() { printf 'siq-agent-security-verify: error: %s\n' "$*" >&2; exit 1; }

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

stage_root() {
  if [ -n "${SIQ_AGENT_SECURITY_STAGE_DIR:-}" ]; then
    printf '%s\n' "$SIQ_AGENT_SECURITY_STAGE_DIR"
    return
  fi
  if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -d "$XDG_RUNTIME_DIR" ]; then
    printf '%s\n' "$XDG_RUNTIME_DIR/siq-agent-security-stage"
    return
  fi
  printf '%s\n' "${TMPDIR:-/tmp}/siq-agent-security-stage-$UID"
}

verify_and_stage() {
  bin=$1
  [ -f "$MANIFEST" ] || die "skill-manifest.json missing; refusing to proceed"
  command -v python3 >/dev/null 2>&1 || die "python3 required to verify skill-manifest.json"
  extra=""
  if [ -z "${SIQ_AGENT_SECURITY_REQUIRE_PINNED:-}" ] && [ -z "${AGENTSHIELD_REQUIRE_PINNED:-}" ]; then
    extra="--allow-local"
  fi
  root=$(stage_root)
  mkdir -p -m 700 "$root" 2>/dev/null || mkdir -p "$root"
  chmod 700 "$root" 2>/dev/null || true
  # shellcheck disable=SC2086
  staged=$(python3 "$VERIFY_PY" --manifest "$MANIFEST" --pubkey "$RELEASE_PUBKEY_B64" \
    --skill-dir "$SKILL_DIR" --bin "$bin" --stage-to "$root" $extra) \
    || die "skill-manifest.json verification or staging failed"
  [ -n "$staged" ] && [ -x "$staged" ] || die "staging returned empty or non-executable path"
  printf '%s\n' "$staged"
}

# DEV04-E: opt-in download from signed manifest URL only (never before signature verify).
fetch_and_stage() {
  [ -f "$MANIFEST" ] || die "skill-manifest.json missing; refusing to proceed"
  command -v python3 >/dev/null 2>&1 || die "python3 required to verify skill-manifest.json"
  root=$(stage_root)
  mkdir -p -m 700 "$root" 2>/dev/null || mkdir -p "$root"
  chmod 700 "$root" 2>/dev/null || true
  staged=$(python3 "$VERIFY_PY" --manifest "$MANIFEST" --pubkey "$RELEASE_PUBKEY_B64" \
    --skill-dir "$SKILL_DIR" --fetch-artifact --stage-to "$root") \
    || die "skill-manifest.json verification, download, or staging failed"
  [ -n "$staged" ] && [ -x "$staged" ] || die "fetch staging returned empty or non-executable path"
  printf '%s\n' "$staged"
}

if BIN=$(find_bin); then
  verify_and_stage "$BIN"
elif [ "${SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD:-}" = "1" ]; then
  fetch_and_stage
else
  die "siq-agent-security binary not found. Build apps/agentshield or set SIQ_AGENT_SECURITY_BIN. To download a pinned release artifact after signed-manifest verify, set SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1."
fi
