#!/usr/bin/env bash
# Compare cross-compiled agentshield binaries to skill-manifest.json pins.
# Does not sign, does not read AGENTSHIELD_RELEASE_SEED, does not print secrets.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: agentshield-release-check.sh [--build] [--bin-dir DIR] [--manifest PATH]

  --build         cross-compile four targets into --bin-dir (default: /tmp/agentshield-release-bin)
  --bin-dir DIR   directory that already contains the four artifact names
  --manifest PATH skills/agentshield/skill-manifest.json (default: repo path)

Exit 0 if sha256 and bytes match the signed manifest. Exit 1 on drift.
EOF
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR=""
DO_BUILD=0
MANIFEST="${ROOT}/skills/agentshield/skill-manifest.json"
GO_BIN="${HOME}/sdk/go/bin/go"
if ! command -v go >/dev/null 2>&1 && [[ -x "$GO_BIN" ]]; then
  export PATH="$(dirname "$GO_BIN"):$PATH"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) DO_BUILD=1; shift ;;
    --bin-dir) BIN_DIR="${2:-}"; shift 2 ;;
    --manifest) MANIFEST="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$BIN_DIR" ]]; then
  BIN_DIR="/tmp/agentshield-release-bin"
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "missing manifest: $MANIFEST" >&2
  exit 1
fi

VERSION="$(python3 - "$MANIFEST" <<'PY'
import json, sys
print(json.load(open(sys.argv[1])).get("binary", {}).get("version") or "0.1.0")
PY
)"

if [[ "$DO_BUILD" -eq 1 ]]; then
  mkdir -p "$BIN_DIR"
  module="${ROOT}/apps/agentshield"
  ldflags="-s -w -X main.Version=${VERSION}"
  for spec in linux/amd64 linux/arm64 darwin/arm64 windows/amd64; do
    os="${spec%/*}"
    arch="${spec#*/}"
    ext=""
    if [[ "$os" == windows ]]; then ext=".exe"; fi
    name="agentshield-${os}-${arch}${ext}"
    echo "building ${os}/${arch} -> ${name}" >&2
    GOOS="$os" GOARCH="$arch" CGO_ENABLED=0 \
      go build -C "$module" -trimpath -ldflags "$ldflags" -o "${BIN_DIR}/${name}" ./cmd/agentshield
  done
fi

python3 - "$MANIFEST" "$BIN_DIR" <<'PY'
import hashlib, json, os, sys

manifest_path, bin_dir = sys.argv[1], sys.argv[2]
doc = json.load(open(manifest_path))
arts = doc.get("binary", {}).get("artifacts") or []
if len(arts) < 4:
    print(f"manifest has {len(arts)} artifacts, expected 4", file=sys.stderr)
    sys.exit(1)

bad = 0
for a in arts:
    os_name, arch = a.get("os"), a.get("arch")
    ext = ".exe" if os_name == "windows" else ""
    name = f"agentshield-{os_name}-{arch}{ext}"
    path = os.path.join(bin_dir, name)
    if not os.path.isfile(path):
        print(f"MISSING {name}", file=sys.stderr)
        bad += 1
        continue
    raw = open(path, "rb").read()
    got = hashlib.sha256(raw).hexdigest()
    want = a.get("sha256") or ""
    want_n = int(a.get("bytes") or 0)
    ok_hash = got == want
    ok_n = len(raw) == want_n
    status = "ok" if ok_hash and ok_n else "DRIFT"
    print(f"{status:5} {name} bytes={len(raw)} sha256={got[:16]}…")
    if not ok_hash:
        print(f"      manifest sha256={want}", file=sys.stderr)
        bad += 1
    if not ok_n:
        print(f"      manifest bytes={want_n}", file=sys.stderr)
        bad += 1

if bad:
    print(f"pin mismatch on {bad} check(s); refuse gh release create", file=sys.stderr)
    sys.exit(1)
print("all four artifacts match skill-manifest.json")
PY
