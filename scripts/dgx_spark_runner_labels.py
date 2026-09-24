#!/usr/bin/env python3
"""Read the current Actions job's scheduling labels; never synthesize evidence."""

import json
import os
import re
import sys
import urllib.request


class RunnerEvidenceError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RunnerEvidenceError("runner_api_redirect_denied")


def capture_labels(environment, *, opener=None):
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    sha = environment.get("GITHUB_SHA", "")
    token = environment.get("GITHUB_TOKEN", "")
    runner_name = environment.get("RUNNER_NAME", "")
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
            or not re.fullmatch(r"[1-9][0-9]{0,9}", attempt)
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not token or not runner_name
            or environment.get("GITHUB_JOB") != "native-candidate"
            or environment.get("RUNNER_ENVIRONMENT") != "self-hosted"
            or environment.get("RUNNER_OS") != "Linux"
            or environment.get("RUNNER_ARCH") != "ARM64"
            or environment.get("GITHUB_API_URL") != "https://api.github.com"):
        raise RunnerEvidenceError("runner_context_invalid")
    url = (f"https://api.github.com/repos/{repository}/actions/runs/{run_id}"
           f"/attempts/{attempt}/jobs?per_page=100")
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "siq-native-candidate-gate",
    })
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RunnerEvidenceError("runner_api_failed")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise RunnerEvidenceError("runner_api_response_too_large")
    payload = json.loads(raw)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or payload.get("total_count") != len(jobs) or len(jobs) > 100:
        raise RunnerEvidenceError("runner_job_list_incomplete")
    matched = [job for job in jobs if isinstance(job, dict) and job.get("name") == "native-candidate"]
    if len(matched) != 1:
        raise RunnerEvidenceError("runner_job_ambiguous")
    job = matched[0]
    if (job.get("run_id") != int(run_id) or job.get("head_sha") != sha
            or job.get("runner_name") != runner_name or job.get("status") != "in_progress"
            or type(job.get("runner_id")) is not int or job["runner_id"] <= 0):
        raise RunnerEvidenceError("runner_job_mismatch")
    labels = job.get("labels")
    if (not isinstance(labels, list) or not labels or len(labels) > 64
            or any(not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", label)
                   for label in labels)
            or len(labels) != len(set(labels))):
        raise RunnerEvidenceError("runner_labels_invalid")
    return labels


def main():
    try:
        labels = capture_labels(os.environ)
    except Exception:  # noqa: BLE001 - keep credentials out of all CLI error paths
        # HTTP errors and payloads may contain authentication material; keep stderr fixed.
        print("FAIL: current Actions runner evidence is unavailable", file=sys.stderr)
        return 1
    print("NATIVE_GATE_RUNNER_LABELS=" + json.dumps(labels, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
