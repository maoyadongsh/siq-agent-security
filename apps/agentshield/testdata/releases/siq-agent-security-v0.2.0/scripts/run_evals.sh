#!/bin/sh
# Run skills/siq-agent-security/evals/evals.json against a local binary.
set -eu
SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
EVALS="$SKILL_DIR/evals/evals.json"

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
  echo "run_evals.sh: siq-agent-security binary not found" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || {
  echo "run_evals.sh: python3 required" >&2
  exit 1
}

SIQ_AGENT_SECURITY_BIN="$BIN" python3 - "$EVALS" "$SKILL_DIR" "$BIN" <<'PY'
import json, os, subprocess, sys
evals_path, skill_dir, binary = sys.argv[1], sys.argv[2], sys.argv[3]
cases = json.loads(open(evals_path, encoding="utf-8").read())
failed = 0
for c in cases:
    if c.get("type") == "routing_negative":
        print(f"SKIP {c['id']} (routing; not executed by this runner)")
        continue
    fixture = os.path.join(skill_dir, "evals", c["fixture"])
    proc = subprocess.run([binary, "admit", fixture], capture_output=True, text=True)
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"FAIL {c['id']}: stdout is not JSON (exit {proc.returncode})")
        print(proc.stderr[:500])
        failed += 1
        continue
    verdict = doc.get("verdict")
    want = c["expected_verdict"]
    rules = {f.get("rule_id") for f in doc.get("findings") or []}
    ok = verdict == want and proc.returncode == c["expected_exit"]
    for r in c.get("must_include_rules") or []:
        if r not in rules:
            ok = False
    for r in c.get("must_not_include_rules") or []:
        if r in rules and any(f.get("rule_id")==r and f.get("disposition")=="quarantine" for f in doc.get("findings") or []):
            ok = False
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"{status} {c['id']} verdict={verdict} exit={proc.returncode} want={want}/{c['expected_exit']}")
    if not ok:
        q = sorted({f.get("rule_id") for f in doc.get("findings") or [] if f.get("disposition")=="quarantine"})
        print(f"  quarantine_rules={q}")
sys.exit(1 if failed else 0)
PY
