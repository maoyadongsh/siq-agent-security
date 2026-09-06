#!/usr/bin/env python3
"""DEV18-C: capability matrix + production runbook honesty gates."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_GO = ROOT / "apps" / "agentshield" / "internal" / "skillmanifest" / "matrix.go"
SKILL_MANIFEST = ROOT / "skills" / "siq-agent-security" / "skill-manifest.json"
CAP_MATRIX = ROOT / "docs" / "agentshield-capability-matrix-v1.md"
RUNBOOK = ROOT / "docs" / "enterprise-production-runbook-v1.md"
PROFILES = ROOT / "docs" / "agentshield-capability-profiles-v1.md"

EVIDENCE_DIRS = [
    ROOT / "docs" / "evidence" / "agentshield" / "hermes-linux-2026-09-05",
    ROOT / "docs" / "evidence" / "agentshield" / "openclaw-linux-2026-09-05",
    ROOT / "docs" / "evidence" / "agentshield" / "codebuddy-linux-2026-09-05",
]

FORBIDDEN_OVERCLAIMS = [
    r"L3_enforce\s*[：:]\s*evidenced",
    r"enforcement_verified\s*(已通过|完成|通过)",
    r"真实 IdP\s*(已通过|联调通过|验收通过)",
    r"真实 PostgreSQL.*(已验收|恢复演练通过)",
    r"managed-linux\s*(已实现|已验收|通过)",
]


def main() -> int:
    errors: list[str] = []

    for path in (MATRIX_GO, SKILL_MANIFEST, CAP_MATRIX, RUNBOOK, PROFILES):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")

    if MATRIX_GO.is_file():
        text = MATRIX_GO.read_text(encoding="utf-8")
        # Forbid assigning status supported in DefaultMatrix rows (comments/ValidateMatrix may mention the word).
        if re.search(r'(?m)^\s*row\([^)]*"supported"', text) or re.search(
            r'Status:\s*"supported"', text
        ):
            errors.append("matrix.go must not assign status supported in DefaultMatrix")
        # Also reject any row(..., "supported", ...) call argument.
        if re.search(r'",\s*"supported"\s*,', text):
            errors.append("matrix.go DefaultMatrix must not use supported status literal as row arg")
        if "DefaultMatrix" not in text:
            errors.append("matrix.go missing DefaultMatrix")

    if SKILL_MANIFEST.is_file():
        doc = json.loads(SKILL_MANIFEST.read_text(encoding="utf-8"))
        rows = doc.get("support_matrix") or []
        for i, row in enumerate(rows):
            if row.get("status") == "supported":
                errors.append(f"skill-manifest support_matrix[{i}] claims supported")

    if CAP_MATRIX.is_file():
        text = CAP_MATRIX.read_text(encoding="utf-8")
        for needle in (
            "L3_enforce",
            "unverified",
            "零行 `supported`",
            "hermes-linux-2026-09-05",
            "readback_verified",
        ):
            if needle not in text:
                errors.append(f"capability matrix missing required phrase: {needle}")
        # Every L3_enforce cell in the main table should be unverified or n/a
        if re.search(r"\|\s*evidenced\s*\|\s*experimental\s*\|[^\n]*L3_enforce", text):
            errors.append("capability matrix appears to evidence L3_enforce")

    if RUNBOOK.is_file():
        text = RUNBOOK.read_text(encoding="utf-8")
        for section in (
            "受控入口与 TLS",
            "OIDC",
            "PostgreSQL",
            "Edge 设备",
            "事故处置",
            "明确不在本 runbook 宣称通过的项",
        ):
            if section not in text:
                errors.append(f"runbook missing section: {section}")
        if "模板" not in text and "template" not in text.lower():
            errors.append("runbook must declare template/gap status")
        if "blocked" not in text:
            errors.append("runbook must retain blocked gaps")

    if PROFILES.is_file():
        text = PROFILES.read_text(encoding="utf-8")
        if "agentshield-capability-matrix-v1.md" not in text:
            errors.append("capability profiles must link capability matrix")
        if "enterprise-production-runbook-v1.md" not in text:
            errors.append("capability profiles must link production runbook")

    for d in EVIDENCE_DIRS:
        if not d.is_dir():
            errors.append(f"missing evidence dir {d.relative_to(ROOT)}")
        elif not (d / "00-summary.json").is_file() and not (d / "README.md").is_file():
            errors.append(f"evidence dir lacks summary/README: {d.name}")

    for path in (CAP_MATRIX, RUNBOOK, PROFILES):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pat in FORBIDDEN_OVERCLAIMS:
            if re.search(pat, text):
                errors.append(f"{path.name}: overclaim matched /{pat}/")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: capability matrix + runbook honesty gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
