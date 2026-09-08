#!/usr/bin/env python3
"""Check research entry points, license scope and community form structure."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    required = ["LICENSE", "NOTICE", "DCO", "CONTRIBUTING.md", "SECURITY.md",
                "GOVERNANCE.md", "CODE_OF_CONDUCT.md", "CITATION.cff",
                "REPRODUCIBILITY.md", "THIRD_PARTY_NOTICES.md"]
    for name in required:
        assert (ROOT / name).is_file(), f"missing {name}"
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text())
    assert cff["cff-version"] == "1.2.0" and cff["type"] == "software"
    assert cff["authors"] and cff["repository-code"].startswith("https://github.com/")
    scope = json.loads((ROOT / "LICENSES/scope.json").read_text())
    assert scope["default_project_owned_license"] == "Apache-2.0"
    for name in scope["cc_by_4_documents"]:
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), f"missing scope path {name}"
    forms = list((ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"))
    assert len(forms) == 7
    for form in forms:
        data = yaml.safe_load(form.read_text())
        if form.name == "config.yml":
            assert data["blank_issues_enabled"] is False
        else:
            assert data["name"] and data["description"] and data["body"]
            ids = [b["id"] for b in data["body"] if "id" in b]
            assert len(ids) == len(set(ids))
    docs = [ROOT / p for p in required if p.endswith(".md")]
    docs += list((ROOT / "docs/research").glob("*.md"))
    docs += [ROOT / "LICENSES/README.md"]
    for doc in docs:
        for target in re.findall(r"\]\(([^\s)]+)\)", doc.read_text()):
            if ":" in target or target.startswith("#"):
                continue
            path = (doc.parent / target.split("#")[0]).resolve()
            assert path.is_relative_to(ROOT) and path.exists(), f"broken link in {doc.name}: {target}"
    print(json.dumps({"result": "passed", "community_forms": len(forms) - 1,
                      "cc_documents": len(scope["cc_by_4_documents"]), "documents": len(docs)}))


if __name__ == "__main__":
    main()
