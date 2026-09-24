import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


labels = load("runner_labels_tested", "dgx_spark_runner_labels.py")
workflow = load("runner_workflow_tested", "check_dgx_spark_native_candidate_workflow.py")


class RunnerLabelsTest(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "GITHUB_REPOSITORY": "fixture/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_SHA": "a" * 40, "GITHUB_TOKEN": "fixture-private-token", "GITHUB_JOB": "native-candidate",
            "GITHUB_API_URL": "https://api.github.com", "RUNNER_NAME": "fixture-runner",
            "RUNNER_ENVIRONMENT": "self-hosted", "RUNNER_OS": "Linux", "RUNNER_ARCH": "ARM64",
        }
        self.job = {"name": "native-candidate", "run_id": 123, "head_sha": "a" * 40,
                    "runner_name": "fixture-runner", "runner_id": 42, "status": "in_progress",
                    "labels": ["self-hosted", "Linux", "ARM64", "dgx-spark", "siq-openshell"]}

    def opener(self, jobs=None, *, raw=None, count=None):
        jobs = [self.job] if jobs is None else jobs
        body = raw if raw is not None else json.dumps({"jobs": jobs,
                   "total_count": len(jobs) if count is None else count}).encode()
        response = io.BytesIO(body)
        response.status = 200
        opener = mock.Mock()
        opener.open.return_value = response
        return opener

    def test_fetch_binds_attempt_sha_and_current_running_job(self):
        opener = self.opener()
        self.assertEqual(labels.capture_labels(self.environment, opener=opener), self.job["labels"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
            "https://api.github.com/repos/fixture/project/actions/runs/123/attempts/2/jobs?per_page=100")
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-private-token")
        self.assertNotIn("fixture-private-token", request.full_url)

    def test_bad_context_rejected_before_http(self):
        for key, value in {"GITHUB_API_URL": "http://attacker.invalid", "GITHUB_TOKEN": "",
                           "GITHUB_RUN_ID": "../123", "GITHUB_RUN_ATTEMPT": "0",
                           "GITHUB_REPOSITORY": "other/project/extra", "GITHUB_SHA": "main",
                           "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_ARCH": "X64",
                           "RUNNER_OS": "Windows", "GITHUB_JOB": "other"}.items():
            with self.subTest(key=key):
                opener = self.opener()
                with self.assertRaises(labels.RunnerEvidenceError):
                    labels.capture_labels(self.environment | {key: value}, opener=opener)
                opener.open.assert_not_called()

    def test_mismatched_job_is_not_evidence(self):
        for key, value in {"run_id": 124, "head_sha": "b" * 40, "runner_name": "other",
                           "runner_id": 0, "status": "completed"}.items():
            with self.subTest(key=key), self.assertRaises(labels.RunnerEvidenceError):
                labels.capture_labels(self.environment, opener=self.opener([self.job | {key: value}]))

    def test_absent_duplicate_and_truncated_jobs_denied(self):
        for opener in [self.opener([]), self.opener([self.job, self.job]), self.opener(count=101)]:
            with self.assertRaises(labels.RunnerEvidenceError):
                labels.capture_labels(self.environment, opener=opener)

    def test_malformed_or_injectable_labels_denied(self):
        for value in [None, [], ["Linux", "Linux"], ["Linux\nOTHER_ENV=forged"], [42], "ARM64"]:
            with self.subTest(value=value), self.assertRaises(labels.RunnerEvidenceError):
                labels.capture_labels(self.environment, opener=self.opener([self.job | {"labels": value}]))

    def test_redirect_and_oversized_response_denied(self):
        with self.assertRaises(labels.RunnerEvidenceError):
            labels.NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid")
        with self.assertRaises(labels.RunnerEvidenceError):
            labels.capture_labels(self.environment, opener=self.opener(raw=b"x" * 2_000_001))

    def test_cli_failure_never_echoes_error_token_or_partial_env(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(labels, "capture_labels", side_effect=RuntimeError("fixture-private-token")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(labels.main(), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn("fixture-private-token", err.getvalue())

    def test_cli_outputs_only_validated_labels(self):
        out = io.StringIO()
        with mock.patch.object(labels, "capture_labels", return_value=self.job["labels"]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(labels.main(), 0)
        key, value = out.getvalue().strip().split("=", 1)
        self.assertEqual(key, "NATIVE_GATE_RUNNER_LABELS")
        self.assertEqual(json.loads(value), self.job["labels"])

    def test_workflow_rejects_missing_fetch_or_synthetic_labels(self):
        original = workflow.WORKFLOW.read_text()
        bad = [original.replace('python3 scripts/dgx_spark_runner_labels.py >> "${GITHUB_ENV}"', 'true'),
               original.replace('env:\n', 'env:\n  NATIVE_GATE_RUNNER_LABELS: ${{ toJSON(runner.labels) }}\n', 1),
               original.replace('  actions: read\n', '')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            for text in bad:
                path.write_text(text)
                with mock.patch.object(workflow, "WORKFLOW", path), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(workflow.main(), 1)


if __name__ == "__main__":
    unittest.main()
