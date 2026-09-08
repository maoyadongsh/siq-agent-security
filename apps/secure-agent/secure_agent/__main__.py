"""Explicit isolated CLI; production/demo never substitutes a fixture model."""

import argparse
from pathlib import Path

from .application import SecureApplication
from .authority import LocalDaemon
from .contracts import AgentError, canonical
from .fixtures import FixtureServices
from .models import FixtureProvider, from_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True, help="new isolated run directory")
    parser.add_argument("--mode", choices=("demo", "test"), default="demo")
    parser.add_argument("--scenario", choices=("normal", "mcp-attack", "same-value", "fake-success", "conflicting", "trifecta"), default="normal")
    parser.add_argument("--repository", default="fixture/secure-project")
    parser.add_argument("--scope", nargs="+", default=["README.md", "service.py"])
    parser.add_argument("--github-endpoint", help="explicit GitHub API base; otherwise controlled fixture")
    parser.add_argument("--prompt", default="Analyze the latest repository code, write a security review, and deliver it to Alice.")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    try:
        model = (FixtureProvider(mode="test", recipient_index=int(args.scenario in ("mcp-attack", "same-value")))
                 if args.mode == "test" else from_environment(mode="demo"))
        mcp_mode = {"mcp-attack": "attack", "same-value": "same-value"}.get(args.scenario, "benign")
        with LocalDaemon(args.binary, args.state_dir) as daemon, FixtureServices(repo / "demo/fixtures", mcp_mode=mcp_mode) as fixtures:
            result = SecureApplication(repo, daemon, fixtures, model).run(args.prompt,
                repository=args.repository, question="Review the supplied code for concrete security issues",
                scope=tuple(args.scope), github_endpoint=args.github_endpoint, trifecta=args.scenario == "trifecta",
                effect_mode=args.scenario if args.scenario in ("fake-success", "conflicting") else "normal")
            print(canonical(result).decode())
    except AgentError as exc:
        print(canonical({"status": "failed", "reason_code": str(exc)}).decode())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
