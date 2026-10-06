"""Read-only source inventory for evaluation planning; does not execute the product."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(repo: Path) -> dict:
    local_file = repo / "apps/agentshield/internal/server/server.go"
    local = []
    for number, line in enumerate(local_file.read_text().splitlines(), 1):
        match = re.search(r'HandleFunc\("([^"\n]+)"', line)
        if match:
            local.append({"path": match[1], "line": number,
                          "registration": line.strip(), "file": str(local_file.relative_to(repo))})
    enterprise, schema, ui = [], [], []
    inputs = {local_file}
    for path in sorted((repo / "apps/control-api/app/routers").glob("*.py")):
        inputs.add(path)
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                        and decorator.args and isinstance(decorator.args[0], ast.Constant)
                        and isinstance(decorator.args[0].value, str)):
                    enterprise.append({"path": decorator.args[0].value,
                                       "method": decorator.func.attr.upper(), "handler": node.name,
                                       "file": str(path.relative_to(repo)), "line": node.lineno})
    for path in sorted((repo / "packages/contracts").glob("*.schema.json")):
        inputs.add(path)
        value = json.loads(path.read_text())
        schema.append({"file": str(path.relative_to(repo)), "sha256": digest(path),
                       "title": value.get("title"),
                       "schema_version": value.get("properties", {}).get("schema_version"),
                       "required": value.get("required", [])})
    for relative in ["apps/web/src/App.tsx", "apps/web/src/local/App.tsx"]:
        path = repo / relative
        inputs.add(path)
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = re.search(r'<Route path="([^"]+)"', line)
            if match:
                ui.append({"file": relative, "line": number, "path": match[1]})
    connectors = [p.parent.name for p in sorted((repo / "connectors").glob("*/go.mod"))]
    for pattern in ["docs/adr/*.md", "packages/contracts/enterprise-*.md",
                    "apps/agentshield/internal/receipt/*.go",
                    "apps/agentshield/internal/skillcontext/*.go",
                    "apps/agentshield/internal/completion/*.go",
                    "apps/secure-agent/secure_agent/*.py"]:
        inputs.update(p for p in repo.glob(pattern) if not p.is_symlink())
    return {"schema_version": "siq-evaluation-product-surface/v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "repository_head": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
            "scope": "working-tree static inventory; not product execution, exhaustive code audit or route reachability proof",
            "local_registration_count": len(local), "local_registrations": local,
            "enterprise_decorator_count": len(enterprise), "enterprise_route_declarations": enterprise,
            "schema_count": len(schema), "schemas": schema, "ui_routes": ui,
            "connector_modules": connectors,
            "input_sha256": {str(p.relative_to(repo)): digest(p) for p in sorted(inputs)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = collect(args.repo.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.out), "local_registrations": value["local_registration_count"],
                      "enterprise_declarations": value["enterprise_decorator_count"],
                      "schemas": value["schema_count"], "connectors": len(value["connector_modules"])}))


if __name__ == "__main__":
    main()
