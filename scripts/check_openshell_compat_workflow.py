#!/usr/bin/env python3
"""DEV17-C / M-C1b: OpenShell workflow must not interpolate inputs into shell; pin Actions; require download digest."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "openshell-compat.yml"

USES_RE = re.compile(r"^\s*-\s*uses:\s*([^@\s]+)@([0-9a-f]{40})\b", re.M)
BAD_TAG_RE = re.compile(r"^\s*-\s*uses:\s*([^@\s]+)@(v?\d[\w.-]*)\s*$", re.M)
# Direct interpolation of workflow inputs into a run: script body is forbidden.
DIRECT_INPUT_RE = re.compile(r"\$\{\{\s*inputs\.[^}]+\}\}")

EXPECTED = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "astral-sh/setup-uv": "d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
}


def _run_blocks(text: str) -> list[str]:
    """Extract YAML `run: |` / `run: >` multiline bodies (best-effort)."""
    blocks: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)run:\s*[|>]-?\s*$", line)
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        i += 1
        body: list[str] = []
        while i < len(lines):
            cur = lines[i]
            if cur.strip() == "":
                body.append(cur)
                i += 1
                continue
            cur_indent = len(cur) - len(cur.lstrip(" "))
            if cur_indent <= indent and cur.lstrip().startswith("-"):
                break
            if cur_indent <= indent and re.match(r"^\s*[A-Za-z0-9_-]+:", cur):
                break
            body.append(cur)
            i += 1
        blocks.append("\n".join(body))
    return blocks


def main() -> int:
    text = WF.read_text(encoding="utf-8")
    errors: list[str] = []

    for m in BAD_TAG_RE.finditer(text):
        errors.append(f"unpinned action tag: {m.group(1)}@{m.group(2)}")

    found: dict[str, str] = {}
    for m in USES_RE.finditer(text):
        found[m.group(1)] = m.group(2)
    for name, sha in EXPECTED.items():
        got = found.get(name)
        if got is None:
            errors.append(f"missing pinned uses for {name}")
        elif got != sha:
            errors.append(f"{name} pinned to {got}, expected {sha}")

    if "cli_bin_sha256:" not in text:
        errors.append("missing workflow input cli_bin_sha256")
    if "CLI_BIN_SHA256:" not in text or "CLI_BIN_ASSET:" not in text:
        errors.append("download step must pass URL/digest via env:")
    if "sha256sum -c" not in text:
        errors.append("download step must verify with sha256sum -c")
    if "LIVE_SANDBOX:" not in text:
        errors.append("compat step must pass live_sandbox via env:")
    if "timeout-minutes:" not in text:
        errors.append("job must set timeout-minutes")

    for block in _run_blocks(text):
        if DIRECT_INPUT_RE.search(block):
            errors.append(
                "run: block interpolates ${{ inputs.* }} — pass via env: instead"
            )
            break

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: openshell-compat.yml download contract + Action pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
