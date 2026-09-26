"""Record/compare protected source hashes and actual uncached Go regression results."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTECTED = (
    "adapters/runtime/", "apps/control-api/app/data/",
    *(f"apps/agentshield/internal/{name}/" for name in (
        "receipt", "threat", "rulepack", "grant", "state", "statefs", "signing",
        "intent", "provenance", "skillcontext", "trustedcontext", "runtimeauthz",
    )),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
    ).decode().split("\0")
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              for p in tracked if p.startswith(PROTECTED) and (ROOT / p).is_file()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log = args.output.with_suffix(".go-test.jsonl")
    with log.open("w") as stream:
        run = subprocess.run(["go", "test", "-count=1", "-json", "./..."],
                             cwd=ROOT / "apps/agentshield", stdout=stream, stderr=subprocess.STDOUT, check=False)
    events = []
    for line in log.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    passed = sorted({e["Package"] + "/" + e["Test"] for e in events
                     if e.get("Action") == "pass" and e.get("Test")})
    result = {"protected_hashes": hashes, "passed_tests": passed,
              "test_exit_code": run.returncode, "log": str(log.resolve().relative_to(ROOT)),
              "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    if args.baseline:
        before = json.loads(args.baseline.read_text())
        result["protected_unchanged"] = before["protected_hashes"] == hashes
        # Subtest names sometimes contain t.TempDir's random path. Compare stable
        # top-level tests, retain every detailed result, and hash protected tests.
        def roots(tests):
            return {re.sub(r"(/(?:Test|Fuzz)[^/]+)(?:/.*)?$", r"\1", name) for name in tests}
        result["comparison"] = "top-level test identities; detailed subtests retained in logs"
        result["missing_previously_passing_tests"] = sorted(roots(before["passed_tests"]) - roots(passed))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    ok = (run.returncode == 0 and bool(passed) and result.get("protected_unchanged", True)
          and not result.get("missing_previously_passing_tests"))
    print(json.dumps({"passed_tests": len(passed), "protected_files": len(hashes), "passed": ok}))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
