"""Record scoped source identities without reading runtime state or credentials."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPES = {
    "siq-agent-security": (
        "apps/agentshield/internal/", "adapters/runtime/", "apps/control-api/app/",
        "apps/control-api/migrations/", "edge/agent/", "connectors/",
        "packages/contracts/", "apps/web/src/", "scripts/release/",
    ),
    "siq-gateway": ("src/", "tests/"),
    "siq-platform": ("compose.yaml", "compose/", "scripts/"),
}
EXTENSIONS = {".py", ".go", ".json", ".md", ".ts", ".tsx", ".yaml", ".yml", ".sh", ".sql"}


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo).decode()


def snapshot():
    repos = {}
    for name, scopes in SCOPES.items():
        repo = ROOT.parent / name
        # Explicit source scopes and extensions exclude binaries, backup/state
        # directories and ignored credentials. Never follow source symlinks.
        paths = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        hashes = {}
        for relative in sorted(set(paths)):
            path = repo / relative
            if not relative.startswith(scopes) or path.suffix not in EXTENSIONS:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        repos[name] = {
            "head": git(repo, "rev-parse", "HEAD").strip(),
            "branch": git(repo, "branch", "--show-current").strip(),
            "source_hashes": hashes,
            "scope": list(scopes),
        }
    return {"schema_version": "siq.enterprise-source-baseline/v1",
            "recorded_at": datetime.now(UTC).isoformat(), "repositories": repos,
            "scope_note": "Source hashes only; not a runtime backup or passing test claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse overwriting baseline evidence, including following a symlink.
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: len(data["source_hashes"])
                      for name, data in result["repositories"].items()}))


if __name__ == "__main__":
    main()
