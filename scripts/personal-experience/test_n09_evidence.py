"""Offline adversarial regressions; no runtime or model is invoked."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from n09_evidence import (  # noqa: E402
    EXPECTED_CHECKS, Invalid, checks_complete, read_json, safe_ref, sha256,
)
spec = importlib.util.spec_from_file_location("n09_check", HERE / "n09-baseline-check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs/evidence").mkdir(parents=True)
        self.ref = "docs/evidence/leg.json"
        self.report = {"passed": True, "binary_sha256": "a" * 64, "checks": ["allow"]}
        self.matrix = {
            "schema_version": "personal-acceptance-baseline/v2", "batch": "fixture",
            "recorded_at": "2026-09-14T00:00:00Z", "notes": [], "evidence_sha256": {},
            "legs": [{"leg_id": "L1", "platform": "openclaw", "os": "linux",
                      "binary_sha256": "a" * 64, "started_at": "2026-09-14T00:00:00Z",
                      "finished_at": "2026-09-14T00:01:00Z", "report_ref": self.ref,
                      "report_sha256": "", "checks_passed": 1}],
            "cells": [{"platform": p, "os": o, "rows": [
                {"item": i, "status": "blocked", "classification": "static_check",
                 "reason": "environment_unavailable", "evidence_refs": [], "coverage": [],
                 "note": "fixture: no observation"} for i in checker.ITEMS
            ]} for p in checker.PLATFORMS for o in checker.OS_NAMES],
        }
        self.row = self.matrix["cells"][3]["rows"][2]
        self.row.update(status="controlled_start", classification="native_machine",
                        evidence_refs=[self.ref], coverage=[{"leg_id": "L1", "checks": ["allow"]}])
        del self.row["reason"]
        self.bind_report()

    def bind_report(self):
        path = self.root / self.ref
        path.write_text(json.dumps(self.report), encoding="utf-8")
        digest = sha256(path)
        self.matrix["evidence_sha256"] = {self.ref: digest}
        self.matrix["legs"][0]["report_sha256"] = digest

    def validate(self):
        path = self.root / "matrix.json"
        path.write_text(json.dumps(self.matrix), encoding="utf-8")
        checker.check(path, self.root)

    def test_valid_partial_and_explicit_complete(self):
        self.validate()
        self.report["acceptance_scope"] = {
            "platform": "openclaw", "os": "linux", "completed_items": ["J3"]}
        self.bind_report()
        self.row["classification"] = "complete_acceptance"
        self.validate()

    def test_linux_workbuddy_scope_exclusion_is_whole_cell_only(self):
        cell = next(c for c in self.matrix["cells"]
                    if (c["platform"], c["os"]) == ("workbuddy", "linux"))
        for row in cell["rows"]:
            row.update(status="out_of_scope", reason="product_scope_excluded",
                       classification="static_check", evidence_refs=[], coverage=[],
                       note="2026-09-17 product scope: Linux supports Hermes and OpenClaw only")
        self.validate()
        cell["rows"][0]["status"] = "blocked"
        cell["rows"][0]["reason"] = "environment_unavailable"
        with self.assertRaises(Invalid):
            self.validate()
        cell["rows"][0]["status"] = "out_of_scope"
        cell["rows"][0]["reason"] = "product_scope_excluded"
        cell["rows"][0]["evidence_refs"] = [self.ref]
        with self.assertRaises(Invalid):
            self.validate()
        cell["rows"][0]["evidence_refs"] = []
        other = self.matrix["cells"][0]["rows"][0]
        other.update(status="out_of_scope", reason="product_scope_excluded")
        with self.assertRaises(Invalid):
            self.validate()

    def test_failed_report_even_with_recomputed_hash(self):
        for change in ({"passed": False}, {"checks": {"allow": False}},
                       {"status": "failed"}, {"checks": []},
                       {"checks": ["allow", "allow"]},
                       {"journey_checks": {"allow": {"passed": False}}},
                       {"journey_checks": {"allow": {"passed": True}, "hidden": {"passed": False}}},
                       {"candidate_sha256": "b" * 64}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.report)
                self.report.update(change)
                self.bind_report()
                with self.assertRaises(Invalid):
                    self.validate()
                self.report = original

    def test_matrix_bindings_reject_fabrication(self):
        original = copy.deepcopy(self.matrix)
        mutations = [
            lambda m: m.update(schema_version="personal-acceptance-baseline/v1"),
            lambda m: m.update(evidence_sha256={}),
            lambda m: m["legs"].append(copy.deepcopy(m["legs"][0])),
            lambda m: m["legs"][0].update(checks_passed=True),
            lambda m: m["legs"][0].update(checks_passed=2),
            lambda m: m["legs"][0].update(binary_sha256="b" * 64),
            lambda m: m["legs"][0].update(os="windows"),
            lambda m: m["legs"][0].update(finished_at="2026-09-13T00:00:00Z"),
            lambda m: m["cells"][3]["rows"][2].update(classification="imagined"),
            lambda m: m["cells"][3]["rows"][2].update(classification="complete_acceptance"),
            lambda m: m["cells"][3]["rows"][2].update(coverage=[]),
            lambda m: m["cells"][3]["rows"][2]["coverage"][0].update(checks=["fabricated"]),
            lambda m: m["cells"][3]["rows"][2].update(status="unverified"),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.matrix = copy.deepcopy(original)
                mutate(self.matrix)
                with self.assertRaises(Invalid):
                    self.validate()

    def test_path_escape_and_symlinks(self):
        sibling = self.root / "docs/evidence-escape"
        sibling.mkdir()
        (sibling / "leg.json").write_text("{}")
        for ref in ("docs/evidence-escape/leg.json", "docs/evidence/../evidence-escape/leg.json",
                    "docs//evidence/leg.json", "docs/evidence/./leg.json",
                    str(self.root / self.ref), "C:/docs/evidence/leg.json", "docs\\evidence\\leg.json"):
            with self.subTest(ref=ref), self.assertRaises(Invalid):
                safe_ref(self.root, ref)
        link = self.root / "docs/evidence/link.json"
        try:
            link.symlink_to(sibling / "leg.json")
        except OSError as exc:
            self.skipTest(f"host cannot construct symlink: {type(exc).__name__}")
        with self.assertRaises(Invalid):
            safe_ref(self.root, "docs/evidence/link.json")

    def test_strict_json(self):
        path = self.root / "bad.json"
        for raw in ('{"passed":false,"passed":true}', '{"value":NaN}', '[]', '{',
                    '{"value":' + '[' * 2000 + '0' + ']' * 2000 + '}'):
            path.write_text(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(Invalid):
                read_json(path)

    def test_leg_requires_every_completed_assertion(self):
        names = sorted(EXPECTED_CHECKS)
        journey = {name: {"passed": True} for name in names}
        self.assertTrue(checks_complete(names, journey))
        self.assertFalse(checks_complete([], {}))
        self.assertFalse(checks_complete(names[:-1], journey))
        self.assertFalse(checks_complete(names[:-1] + [names[0]], journey))
        journey[names[-1]]["passed"] = False
        self.assertFalse(checks_complete(names, journey))
        journey[names[-1]]["passed"] = True
        journey["hidden"] = {"passed": False}
        self.assertFalse(checks_complete(names, journey))

    def test_archived_review_matrix(self):
        repo = HERE.parents[1]
        checker.check(repo / "docs/evidence/personal-experience/n09-independent-review-20260914/matrix.json", repo)


if __name__ == "__main__":
    unittest.main()
