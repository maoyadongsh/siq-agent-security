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
    summary = {"status": "passed", "synthetic_only": True, "checks": [
        "ordinary credential detected", "new credential in allowed test path detected",
        "new credential in hash-evidence path detected", "exact fixture exception restricted to test path",
        "private-key block detected", "source hash metadata is not a secret",
        "historical synthetic value exception is exact and path-restricted"], "raw_values_retained": False}
    if args.out:
        with args.out.open("x") as output:
            output.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
