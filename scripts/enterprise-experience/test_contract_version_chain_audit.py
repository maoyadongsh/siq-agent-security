"""contract-version-chain-audit 合成仓库组合测试。

所有用例只作用于临时合成目录，不读取真实仓库正文，也不改动任何真实文件。
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("contract-version-chain-audit.py")
_SPEC = importlib.util.spec_from_file_location("contract_version_chain_audit", SCRIPT)
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(base: Path) -> Path:
    """闭链基线：只有 v1 建档且被发出，因此默认审计通过。"""
    root = base / "repo"
    (root / "packages" / "contracts").mkdir(parents=True)
    write(root, "packages/contracts/enterprise-widget.v1.md", "# widget v1\n")
    write(root, "apps/control-api/app/widget.py", 'VERSION = "enterprise-widget/v1"\n')
    return root


class ContractVersionChainAuditTest(unittest.TestCase):
    def test_runtime_json_and_env_variants_are_not_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            for relative in ("apps/control-api/var/state.json",
                             "apps/control-api/backups/state.json",
                             "apps/control-api/.env.production.json",
                             "apps/control-api/.tmp/probe.json"):
                write(root, relative, '{"value": "enterprise-widget/v2"}')
            self.assertNotIn(("enterprise-widget", 2), tool.collect_emitted(root))

    def test_source_and_contract_symlinks_are_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            outside = Path(tmp) / "synthetic.json"
            outside.write_text('{"value": "enterprise-widget/v2"}')
            (root / "apps/control-api/app/alias.json").symlink_to(outside)
            (root / "packages/contracts/enterprise-widget.v2.md").symlink_to(outside)
            self.assertNotIn(("enterprise-widget", 2), tool.collect_emitted(root))
            self.assertNotIn(2, tool.collect_documented(root)["enterprise-widget"])
            self.assertFalse(tool._alias_target_ok(root, "packages/contracts/enterprise-widget.v2.md"))

    def test_production_version_without_contract_is_a_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "apps/control-api/app/widget.py",
                  'VERSION = "enterprise-widget/v1"\nNEXT = "enterprise-widget/v2"\n')
            report = tool.audit(root)
            self.assertFalse(report["closed_version_chain"])
            self.assertEqual([(item["family"], item["version"])
                              for item in report["undocumented_versions"]],
                             [("enterprise-widget", 2)])
            self.assertEqual(report["undocumented_versions"][0]["locations"],
                             ["apps/control-api/app/widget.py"])

    def test_test_reference_alone_is_not_a_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "apps/control-api/app/tests/test_widget.py", 'BAD = "enterprise-widget/v99"\n')
            write(root, "apps/web/src/widget.test.ts", "const v = 'enterprise-widget/v98';\n")
            write(root, "edge/agent/widget_test.go", 'const v = "enterprise-widget/v97"\n')
            write(root, "apps/agentshield/testdata/contracts/w.json",
                  json.dumps({"schema_version": "enterprise-widget/v96"}))
            report = tool.audit(root)
            self.assertTrue(report["closed_version_chain"])
            self.assertEqual(sorted(item["version"] for item in report["test_only_version_references"]),
                             [96, 97, 98, 99])

    def test_unrelated_family_without_any_contract_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "connectors/widget/connector.go", 'const p = "connector-protocol/v1"\n')
            report = tool.audit(root)
            self.assertTrue(report["closed_version_chain"])

    def test_alias_closes_a_cross_filename_gap_only_when_target_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "packages/contracts/enterprise-widget-ancestry.v2.md", "# ancestry v2\n")
            aliases = {"enterprise-widget/v2": "packages/contracts/enterprise-widget-ancestry.v2.md"}
            report = tool.audit(root, aliases)
            self.assertTrue(report["closed_version_chain"])
            self.assertEqual(report["alias_count"], 1)

    def test_alias_target_must_be_an_existing_contract_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self.assertFalse(tool._alias_target_ok(root, "packages/contracts/missing.v2.md"))
            self.assertFalse(tool._alias_target_ok(root, "apps/control-api/app/widget.py"))
            self.assertFalse(tool._alias_target_ok(root, "/etc/passwd"))
            self.assertFalse(tool._alias_target_ok(root, "https://example.test/x.md"))
            self.assertFalse(tool._alias_target_ok(root, "../../etc/passwd"))
            self.assertFalse(tool._alias_target_ok(root, None))

    def test_broken_navigation_link_detected_but_directory_link_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            (root / "apps" / "control-api" / "app" / "adapters").mkdir(parents=True)
            write(root, "packages/contracts/enterprise-widget.v1.md",
                  "# widget v1\n\n见 [缺失](enterprise-gone.v2.md) 与 [目录](../../apps/control-api/app/adapters/)\n")
            report = tool.audit(root)
            self.assertEqual(report["broken_navigation_links"],
                             [{"contract": "packages/contracts/enterprise-widget.v1.md",
                               "link": "enterprise-gone.v2.md"}])

    def test_external_url_and_anchor_links_are_not_links_to_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "packages/contracts/enterprise-widget.v1.md",
                  "# widget\n[外链](https://example.test/a.md) [锚点](#section)\n")
            self.assertEqual(tool.audit(root)["broken_navigation_links"], [])

    def test_sensitive_suffixes_and_skip_dirs_are_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            marker = "enterprise-widget/v2"
            write(root, "apps/control-api/app/secret.private", f'X = "{marker}"\n')
            write(root, "apps/control-api/app/key.pem", f'X = "{marker}"\n')
            write(root, "node_modules/pkg/index.js", f'X = "{marker}"\n')
            write(root, "apps/control-api/app/__pycache__/cached.py", f'X = "{marker}"\n')
            write(root, "apps/agentshield/internal/ui/embedded/assets/index.abc123.js", f'X = "{marker}"\n')
            self.assertTrue(tool.audit(root)["closed_version_chain"])

    def test_report_is_written_exclusively_and_refused_on_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "apps/control-api/app/widget.py",
                  'VERSION = "enterprise-widget/v1"\nNEXT = "enterprise-widget/v2"\n')
            out = Path(tmp) / "report.json"
            self.assertEqual(tool.main(["--repo", str(root), "--out", str(out)]), tool.EXIT_GAPS)
            first = out.read_text(encoding="utf-8")
            self.assertEqual(tool.main(["--repo", str(root), "--out", str(out)]),
                             tool.EXIT_REPORT_WRITE_FAILED)
            self.assertEqual(out.read_text(encoding="utf-8"), first)

    def test_closed_repo_exits_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "apps/control-api/app/widget.py", 'VERSION = "enterprise-widget/v1"\n')
            out = Path(tmp) / "report.json"
            self.assertEqual(tool.main(["--repo", str(root), "--out", str(out)]), tool.EXIT_PASS)
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["closed_version_chain"])

    def test_missing_repo_or_bad_alias_file_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(tool.main(["--repo", str(Path(tmp) / "nope"),
                                        "--out", str(Path(tmp) / "r.json")]), tool.EXIT_USAGE)
            root = make_repo(Path(tmp))
            bad = Path(tmp) / "aliases.json"
            bad.write_text(json.dumps({"aliases": {"enterprise-widget/v2": "packages/contracts/gone.md"}}),
                           encoding="utf-8")
            self.assertEqual(tool.main(["--repo", str(root), "--out", str(Path(tmp) / "r.json"),
                                        "--aliases", str(bad)]), tool.EXIT_USAGE)

    def test_documented_but_unemitted_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "packages/contracts/enterprise-gadget.v1.md", "# gadget v1\n")
            report = tool.audit(root)
            self.assertIn(("enterprise-gadget", 1),
                          [(item["family"], item["version"]) for item in report["documented_but_unemitted"]])
            # 未发出仅作提示，不使审计失败。
            self.assertTrue(report["closed_version_chain"])


if __name__ == "__main__":
    unittest.main()
