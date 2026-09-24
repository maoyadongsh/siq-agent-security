#!/usr/bin/env python3
"""Reject soft-pass or unpinned changes to the DGX Spark native gate workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/dgx-spark-native-candidate.yml"
POLICY = ROOT / "deploy/dgx-spark/native-candidate-gate.v1.json"
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^@\s]+)@([0-9a-f]{40})\b", re.MULTILINE)
ANY_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
DIRECT_INPUT_RE = re.compile(r"\$\{\{\s*inputs\.")

EXPECTED_ACTIONS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "astral-sh/setup-uv": "d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def _run_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*[|>]-?\s*$", lines[index])
        if not match:
            index += 1
            continue
        indent = len(match.group(1))
        index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            current = len(line) - len(line.lstrip(" "))
            if line.strip() and current <= indent:
                break
            body.append(line)
            index += 1
        blocks.append("\n".join(body))
    return blocks


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    errors: list[str] = []

    trigger = re.search(r"(?ms)^on:\s*\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:)", workflow)
    if trigger is None or trigger.group("body").strip() != "workflow_dispatch:":
        errors.append("native gate must be workflow_dispatch-only")
    expected_runner = "runs-on: [self-hosted, Linux, ARM64, dgx-spark, siq-openshell]"
    if expected_runner not in workflow:
        errors.append("native gate is missing the exact self-hosted DGX Spark labels")
    if "continue-on-error:" in workflow or re.search(r"(?i)\bSKIP(?:PED)?\b", workflow):
        errors.append("native gate must not contain soft-pass or skip behavior")
    if "SIQ_RESEARCH_ROOT: ${{ vars.SIQ_RESEARCH_ROOT }}" not in workflow:
        errors.append("research root must come from the repository runner variable")
    if "SIQ_HERMES_ROOT: ${{ vars.SIQ_HERMES_ROOT }}" not in workflow:
        errors.append("Hermes root must come from the repository runner variable")
    if "runner.labels" in workflow or re.search(r"^\s*NATIVE_GATE_RUNNER_LABELS:", workflow, re.MULTILINE):
        errors.append("runner labels must come from the current Actions job API")
    if "actions: read" not in workflow or "GITHUB_TOKEN: ${{ github.token }}" not in workflow:
        errors.append("runner job discovery requires the step-scoped read-only Actions token")
    if "--require-level live_environment" not in workflow:
        errors.append("candidate doctor must require live_environment")
    required_fragments = (
        'python3 scripts/dgx_spark_runner_labels.py >> "${GITHUB_ENV}"',
        "gateway_runtime_identity.py",
        "http://127.0.0.1:17672/healthz",
        "sandbox_resource_governance.py",
        "--gateway-status healthy",
        "native_candidate_gate.py capture-platform",
        "native_candidate_gate.py bind-resource-audit",
        "native_candidate_gate.py verify",
        "if-no-files-found: error",
    )
    for fragment in required_fragments:
        if fragment not in workflow:
            errors.append(f"native gate is missing required operation: {fragment}")
    for suite_id in (
        "security_candidate_contracts",
        "security_hermes_adapter",
        "research_openshell_contracts",
        "hermes_native_regression",
    ):
        if f'"id": "{suite_id}"' not in policy or f"--suite {suite_id}" not in workflow:
            errors.append(f"suite is not bound in both policy and workflow: {suite_id}")

    found = dict(USES_RE.findall(workflow))
    for action, reference in ANY_USES_RE.findall(workflow):
        if not re.fullmatch(r"[0-9a-f]{40}", reference):
            errors.append(f"Action is not pinned to a commit SHA: {action}@{reference}")
    for action, expected in EXPECTED_ACTIONS.items():
        if found.get(action) != expected:
            errors.append(f"unexpected or missing Action pin: {action}")

    for block in _run_blocks(workflow):
        if DIRECT_INPUT_RE.search(block):
            errors.append("run block directly interpolates workflow inputs")
            break
    conditional_lines = [line.strip() for line in workflow.splitlines() if line.strip().startswith("if:")]
    if conditional_lines != ["if: always()"]:
        errors.append("only the evidence upload may be conditional, and it must always run")
    upload_path = "path: ${{ env.NATIVE_PUBLIC_DIR }}/*.json"
    if upload_path not in workflow or "NATIVE_PRIVATE_DIR }}" in workflow:
        errors.append("artifact upload must include public JSON only")
    if re.search(r"path:.*(?:private|\.log)", workflow, re.IGNORECASE):
        errors.append("private logs must never be uploaded")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: DGX Spark native candidate workflow is pinned and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
