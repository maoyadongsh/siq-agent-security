#!/usr/bin/env python3
"""Calibrate the actual scanner with synthetic values, never real credentials."""

import argparse
import json
import secrets
import string
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_session_hash_exception(binary, config, token):
    """A reviewed content digest is excepted only at its exact field and path."""
    evidence = ("docs/evidence/personal-experience/windows-sunbo/"
                "openclaw-session-epoch-20260918/summary.json")
    outside = "docs/evidence/not-reviewed/summary.json"
    nested = "copied/" + evidence
    reviewed = "b4f6a7cf296ab0fd7f3dc39c1fe6b0520d93d21b740a61692ba991a9bf28ad47"
    reviewed_line = f'  "session_key_sha256": "{reviewed}",\n'
    files = {
        evidence: (reviewed_line * 6
                   + f'  "session_key_sha256": "{secrets.token_hex(32)}",\n'
                   + f'  "api_key": "{reviewed}",\n'
                   + f'  "token": "{token}"\n'),
        outside: reviewed_line,
        nested: reviewed_line,
    }
    with tempfile.TemporaryDirectory(prefix="siq-session-hash-calibration-") as directory:
        root = Path(directory)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for arguments in (("init", "-q", "-b", "main"),
                          ("config", "user.name", "Scanner calibration"),
                          ("config", "user.email", "scanner@example.invalid"),
                          ("config", "commit.gpgsign", "false"),
                          ("add", "."), ("commit", "-qm", "synthetic digest fixtures")):
            subprocess.run(["git", *arguments], cwd=root, capture_output=True,
                           timeout=30, check=True)
        report = root / "report.json"
        result = subprocess.run([
            str(binary.resolve()), "git", str(root), "--config", str(config.resolve()),
            "--log-opts=-1 HEAD",
            "--redact", "--report-format", "json", "--report-path", str(report),
        ], capture_output=True, timeout=30, check=False)
        rows = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
        actual = {(row["RuleID"], row["File"].replace("\\", "/"),
                   row["StartLine"]) for row in rows}
        required = {("generic-api-key", evidence, 7), ("generic-api-key", evidence, 8),
                    ("generic-api-key", outside, 1), ("generic-api-key", nested, 1),
                    ("github-pat", evidence, 9)}
        excepted = {("generic-api-key", evidence, line) for line in range(1, 7)}
        if result.returncode != 1 or not required <= actual or actual & excepted:
            raise SystemExit("scanner calibration failed: session digest exception is not exact")


def check_history(binary, config, token):
    """Root commits, merged side branches and merge-only additions remain visible."""
    with tempfile.TemporaryDirectory(prefix="siq-scanner-history-") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()

        def git(*arguments):
            return subprocess.run(["git", *arguments], cwd=repository,
                                  capture_output=True, timeout=30, check=True)

        def commit_file(name):
            (repository / name).write_text(f'token = "{token}"\n')
            git("add", name)
            git("commit", "-qm", "synthetic scanner fixture")

        git("init", "-q", "-b", "main")
        git("config", "user.name", "Scanner calibration")
        git("config", "user.email", "scanner@example.invalid")
        git("config", "commit.gpgsign", "false")
        commit_file("root.env")
        git("checkout", "--orphan", "independent")
        git("rm", "-rf", ".")
        commit_file("independent.env")
        git("checkout", "main")
        git("merge", "--allow-unrelated-histories", "--no-commit", "independent")
        (repository / "merge-only.env").write_text(f'token = "{token}"\n')
        git("add", "merge-only.env")
        git("commit", "-qm", "merge synthetic fixtures")
        git("rm", "root.env", "independent.env", "merge-only.env")
        git("commit", "-qm", "remove fixtures from current tree")
        report = root / "report.json"
        result = subprocess.run([str(binary.resolve()), "git", str(repository),
            "--config", str(config.resolve()), "--redact", "--log-opts=--full-history -m HEAD",
            "--report-format", "json", "--report-path", str(report)],
            capture_output=True, timeout=30, check=False)
        rows = json.loads(report.read_text()) if report.exists() else []
        detected = {row["File"] for row in rows if row["RuleID"] == "github-pat"}
        if result.returncode != 1 or not {"root.env", "independent.env", "merge-only.env"} <= detected:
            raise SystemExit("scanner history calibration failed: root, side branch or merge addition missed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / ".gitleaks.toml")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    token = "ghp_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))
    test_file = "apps/control-api/app/tests/test_threat_analysis.py"
    hash_file = "docs/evidence/intent-v2/calibration.json"
    historical_path = "edge/agent/evidence_test.go"
    historical_token = "ghp_" + ("0123456789" * 4)[:36]
    access_id = "AKIA" + "ABCDEFGHIJKLMNOP"
    key_start = "-" * 5 + "BEGIN RSA PRIVATE KEY" + "-" * 5
    key_end = "-" * 5 + "END RSA PRIVATE KEY" + "-" * 5
    files = {
        "ordinary.env": f'token = "{token}"\n',
        historical_path: f'token = "{historical_token}"\ntoken = "{token}"\n',
        "outside-historical.env": f'token = "{historical_token}"\n',
        test_file: f'aws_access_key_id = "{access_id}"\ntoken = "{token}"\n',
        "outside-test.env": f'aws_access_key_id = "{access_id}"\n',
        hash_file: '  "authz.go": "' + "a1b2c3d4" * 8 + '",\n  "token": "' + token + '"\n',
        "key.pem": key_start + "\n" + "QUJDREVGR0hJSktMTU5PUA==" * 4 + "\n" + key_end + "\n",
    }
    with tempfile.TemporaryDirectory(prefix="siq-scanner-calibration-") as directory:
        root = Path(directory)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        report = root / "report.json"
        result = subprocess.run([str(args.binary.resolve()), "dir", str(root), "--config", str(args.config.resolve()),
            "--redact", "--report-format", "json", "--report-path", str(report)],
            capture_output=True, timeout=30, check=False)
        rows = json.loads(report.read_text()) if report.exists() else []
        detected = {(row["RuleID"], next((name for name in files if row["File"].endswith(name)), "unknown"))
                    for row in rows}
        required = {("github-pat", name) for name in ("ordinary.env", test_file, hash_file,
                                                     historical_path, "outside-historical.env")}
        required |= {("aws-access-token", "outside-test.env"), ("private-key", "key.pem")}
        if result.returncode != 1 or not required <= detected or ("aws-access-token", test_file) in detected:
            raise SystemExit("scanner calibration failed: missing detection or overbroad/missing exception")
        if ("generic-api-key", hash_file) in detected:
            raise SystemExit("scanner calibration failed: reviewed hash metadata exception did not match")
        historical_rows = [row for row in rows if row["File"].endswith(historical_path) and row["RuleID"] == "github-pat"]
        if len(historical_rows) != 1 or historical_rows[0]["StartLine"] != 2:
            raise SystemExit("scanner calibration failed: historical test exception is not exact")
    check_session_hash_exception(args.binary, args.config, token)
    check_history(args.binary, args.config, token)
    summary = {"status": "passed", "synthetic_only": True, "checks": [
        "ordinary credential detected", "new credential in allowed test path detected",
        "new credential in hash-evidence path detected", "exact fixture exception restricted to test path",
        "private-key block detected", "source hash metadata is not a secret",
        "historical synthetic value exception is exact and path-restricted",
        "reviewed session digest exception is exact by value, field and path",
        "new digest and credentials in the same evidence file are detected",
        "same reviewed digest under a prefixed copy of the path is detected",
        "removed credentials in root, independent history and merge-only additions detected"], "raw_values_retained": False}
    if args.out:
        with args.out.open("x") as output:
            output.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
