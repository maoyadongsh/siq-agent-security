"""Security contracts for optional SonarCloud CI; no service access required."""

from copy import deepcopy
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCAN_ACTION = "SonarSource/sonarqube-scan-action@22918119ff8e1ca75a623e15c8296b6ea4fbe28f"
GUARD = """
github.repository == 'maoyadongsh/siq-agent-security' &&
vars.SONAR_ENABLED == 'true' &&
github.actor != 'dependabot[bot]' &&
(
  ((github.event_name == 'push' || github.event_name == 'workflow_dispatch') &&
   github.ref == 'refs/heads/main') ||
  (github.event_name == 'pull_request' &&
   vars.SONAR_PR_ANALYSIS_ENABLED == 'true' &&
   github.event.pull_request.user.login != 'dependabot[bot]' &&
   github.event.pull_request.head.repo.full_name == github.repository &&
   github.event.pull_request.base.ref == 'main')
)
"""


def validate_workflow(data):
    """Reject changes that weaken the reviewed credential boundary."""
    def require(condition):
        if not condition:
            raise ValueError("SonarCloud workflow contract violated")

    require(set(data["on"]) == {"push", "pull_request", "workflow_dispatch"})
    require(data["on"]["push"]["branches"] == ["main"])
    require(data["on"]["pull_request"]["branches"] == ["main"])
    require(data["permissions"] == {"contents": "read"})
    require(set(data["jobs"]) == {"notice", "sonarcloud"})
    job = data["jobs"]["sonarcloud"]
    require("permissions" not in job)
    require(" ".join(job["if"].split()) == " ".join(GUARD.split()))
    require(int(job["timeout-minutes"]) <= 20)
    steps = job["steps"]
    checkout, config, scan = steps
    require(checkout["with"] == {"fetch-depth": "0", "persist-credentials": "false"})
    require(config["run"] == "python3 scripts/research/sonarcloud_config.py")
    require(scan["uses"] == SCAN_ACTION)
    require(scan["with"]["skipSignatureVerification"] == "false")
    args = scan["with"]["args"].split()
    require("-Dsonar.qualitygate.wait=true" in args)
    require("-Dsonar.qualitygate.timeout=300" in args)
    require(scan["env"]["SONAR_TOKEN"] == "${{ secrets.SONAR_TOKEN }}")
    require(scan["env"]["SONAR_REGION"] == "${{ steps.config.outputs.region }}")
    require("continue-on-error" not in job)
    for item in data["jobs"].values():
        require("permissions" not in item)
        for step in item["steps"]:
            require("continue-on-error" not in step)
            if "uses" in step:
                require(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", step["uses"]) is not None)
    serialized = json.dumps(data)
    require(serialized.count("secrets.") == 1)
    require("pull_request_target" not in serialized and "workflow_run" not in serialized)


class SonarWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(
            (ROOT / ".github/workflows/sonarcloud.yml").read_text(), Loader=yaml.BaseLoader
        )

    def test_workflow_credential_contract(self):
        validate_workflow(self.workflow)

    def test_privileged_events_are_rejected(self):
        for event in ("pull_request_target", "workflow_run"):
            changed = deepcopy(self.workflow)
            changed["on"][event] = {}
            with self.assertRaises(ValueError):
                validate_workflow(changed)

    def test_fork_and_main_guards_cannot_be_removed(self):
        for guard in (
            "github.event.pull_request.head.repo.full_name == github.repository",
            "github.ref == 'refs/heads/main'",
            "github.actor != 'dependabot[bot]'",
            "github.event.pull_request.user.login != 'dependabot[bot]'",
            "vars.SONAR_PR_ANALYSIS_ENABLED == 'true'",
        ):
            changed = deepcopy(self.workflow)
            changed["jobs"]["sonarcloud"]["if"] = changed["jobs"]["sonarcloud"]["if"].replace(guard, "true")
            with self.assertRaises(ValueError):
                validate_workflow(changed)

    def test_token_cannot_move_to_job_or_another_step(self):
        changed = deepcopy(self.workflow)
        changed["jobs"]["notice"]["env"] = {"SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}"}
        with self.assertRaises(ValueError):
            validate_workflow(changed)

    def test_floating_actions_and_disabled_signature_check_are_rejected(self):
        for field, value in (("uses", "SonarSource/sonarqube-scan-action@v8"), ("signature", "true")):
            changed = deepcopy(self.workflow)
            scan = changed["jobs"]["sonarcloud"]["steps"][-1]
            if field == "uses":
                scan["uses"] = value
            else:
                scan["with"]["skipSignatureVerification"] = value
            with self.assertRaises(ValueError):
                validate_workflow(changed)

    def test_quality_gate_cannot_be_soft_passed(self):
        changed = deepcopy(self.workflow)
        changed["jobs"]["sonarcloud"]["continue-on-error"] = "true"
        with self.assertRaises(ValueError):
            validate_workflow(changed)
        changed = deepcopy(self.workflow)
        scan = changed["jobs"]["sonarcloud"]["steps"][-1]
        scan["with"]["args"] = scan["with"]["args"].replace("-Dsonar.qualitygate.wait=true", "")
        with self.assertRaises(ValueError):
            validate_workflow(changed)

    def test_scope_retains_normal_tests_without_fabricated_coverage(self):
        properties = dict(
            line.split("=", 1)
            for line in (ROOT / "sonar-project.properties").read_text().splitlines()
            if line and not line.startswith("#")
        )
        self.assertEqual(properties["sonar.sources"], properties["sonar.tests"])
        for root in properties["sonar.sources"].split(","):
            self.assertTrue((ROOT / root).is_dir())
        for pattern in ("**/*_test.go", "**/test_*.py", "**/*.test.ts", "**/test-*.py", "**/test-*.cjs"):
            self.assertIn(pattern, properties["sonar.test.inclusions"].split(","))
        self.assertNotIn("**/tests/**", properties["sonar.test.exclusions"].split(","))
        self.assertFalse(any("coverage" in key.lower() for key in properties))
        self.assertNotIn("sonar.organization", properties)
        self.assertNotIn("sonar.projectKey", properties)

    def test_admission_corpus_is_excluded_but_implementation_and_tests_remain(self):
        properties = dict(
            line.split("=", 1)
            for line in (ROOT / "sonar-project.properties").read_text().splitlines()
            if line and not line.startswith("#")
        )
        fixture = "apps/agentshield/internal/admission/testdata/skills/malicious/py-env-exfil/scripts/exfil.py"
        production = "apps/agentshield/internal/admission/admission.go"
        test = "apps/agentshield/internal/admission/admission_test.go"
        for name in (fixture, production, test):
            self.assertTrue((ROOT / name).is_file())
        for field in ("sonar.exclusions", "sonar.test.exclusions"):
            patterns = properties[field].split(",")
            self.assertTrue(any(fnmatchcase(fixture, p) for p in patterns))
            self.assertFalse(any(fnmatchcase(production, p) for p in patterns))
            self.assertFalse(any(fnmatchcase(test, p) for p in patterns))
        self.assertTrue(any(fnmatchcase(test, p) for p in properties["sonar.test.inclusions"].split(",")))


if __name__ == "__main__":
    unittest.main()
