#!/usr/bin/env python3
"""Produce apps/control-api/app/tests/fixtures/threat/match_oracle_v1.json.

Independent of the Go analyzer: freezes field-level expectations
(line / excerpt / excerpt_sha256 / content_sha256 / detected_type) for the
shared regex rulepack layer. AST-only hits are listed separately and must not
be claimed as Go↔Python parity.

Run from apps/control-api:
  uv run python scripts/gen_threat_match_oracle_v1.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.threat_analysis import analyze  # noqa: E402

CORPUS = ROOT / "app" / "tests" / "fixtures" / "threat" / "corpus.json"
OUT = ROOT / "app" / "tests" / "fixtures" / "threat" / "match_oracle_v1.json"

PYTHON_ONLY = sorted(
    [
        "threat-py-os-system",
        "threat-py-subprocess-shell",
        "threat-py-ctypes-load",
        "threat-py-syntax-parse-failed",
    ]
)


def main() -> None:
    doc = json.loads(CORPUS.read_text(encoding="utf-8"))
    vectors: list[dict] = []
    for s in doc["samples"]:
        content = s["content"].encode("utf-8")
        result = analyze(content, filename=s.get("filename"))
        content_sha = hashlib.sha256(content).hexdigest()
        shared = [m for m in result.matches if m.rule_id not in PYTHON_ONLY]
        python_only = [m for m in result.matches if m.rule_id in PYTHON_ONLY]

        labelled = None
        rule_id = s.get("rule_id")
        if rule_id:
            hit = next((m for m in shared if m.rule_id == rule_id), None)
            if hit is None and s["label"] in ("malicious", "benign_known_fp"):
                raise SystemExit(f"labelled shared rule missing for {s['id']}: {rule_id}")
            if hit is not None:
                labelled = {
                    "rule_id": hit.rule_id,
                    "line": hit.line,
                    "excerpt": hit.excerpt,
                    "excerpt_sha256": hit.excerpt_sha256,
                    "severity": hit.severity,
                    "confidence": hit.confidence,
                }

        vectors.append(
            {
                "sample_id": s["id"],
                "label": s["label"],
                "filename": s.get("filename") or "",
                "content_sha256": content_sha,
                "detected_type": result.detected_type,
                "expected_shared_match": labelled,
                "shared_rule_ids": sorted({m.rule_id for m in shared}),
                "python_only_rule_ids": sorted({m.rule_id for m in python_only}),
            }
        )

    oracle = {
        "schema": "threat_match_oracle/v1",
        "contract": (
            "Field-level parity for the shared regex rulepack layer (Go + Python). "
            "expected_shared_match freezes line/excerpt/excerpt_sha256 for the "
            "corpus-labelled rule_id. python_only_rule_ids are AST-only (Python); "
            "Go must not claim them."
        ),
        "python_only_rule_ids": PYTHON_ONLY,
        "corpus_path": "apps/control-api/app/tests/fixtures/threat/corpus.json",
        "vectors": vectors,
    }
    OUT.write_text(json.dumps(oracle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} vectors={len(vectors)}")


if __name__ == "__main__":
    main()
