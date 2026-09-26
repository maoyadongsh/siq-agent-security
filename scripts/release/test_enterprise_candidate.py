import json
import os
import platform
import re
import subprocess
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import enterprise_candidate as candidate
import package


class EnterpriseCandidateTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo,
                                       env={**candidate.build_env(), "GIT_CONFIG_NOSYSTEM": "1",
                                            "GIT_CONFIG_GLOBAL": os.devnull}).decode().strip()

    def fixture(self):
        for directory, filename, symbol in (("edge/agent", "main.go", "agentVersion"),
                                            ("connectors/directory", "directory.go", "connectorVersion")):
            path = self.repo / directory
            path.mkdir(parents=True)
            (path / "go.mod").write_text("module example.test/fixture\n\ngo 1.22\n")
            (path / filename).write_text(
                f'package main\nimport "fmt"\nvar {symbol} = "0.1.0"\n'
                f'func main() {{ fmt.Println({symbol}) }}\n')
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "LICENSES/fixture.txt"):
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("Synthetic release fixture; no product source.\n")
        for name in ("hermes", "openclaw"):
            path = self.repo / "connectors" / name
            path.mkdir()
            (path / "fixture.txt").write_text("Unselected synthetic connector source.\n")
        expected = self.root / "expected.json"
        expected.write_text(json.dumps({"schema_version": "siq-release-source-inventory/v1",
                                        "files": package.inventory(self.repo)}))
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic fixture")
        return Namespace(source_root=self.repo, source_sha=self.git("rev-parse", "HEAD"),
                         version="1.2.3-rc.1", connector=["directory"],
                         expected_source_inventory=expected, out_dir=self.root / "candidate")

    def test_environment_is_allowlisted_and_offline(self):
        env = candidate.build_env({"PATH": "/tools", "GOFLAGS": "bad", "GITHUB_TOKEN": "secret",
                                   "SIQ_AGENT_SECURITY_RELEASE_SEED": "secret", "GOPROXY": "https://bad"})
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GOFLAGS", env)
        self.assertNotIn("SIQ_AGENT_SECURITY_RELEASE_SEED", env)
        self.assertEqual(env["GOPROXY"], "off")
        self.assertEqual(env["GOENV"], "off")

    def test_invalid_selection_and_existing_output_do_not_execute(self):
        args = Namespace(source_sha="a" * 40, version="1.2.3", connector=["directory", "directory"],
                         source_root=self.repo, out_dir=self.root / "existing")
        with patch.object(package, "run") as run:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                candidate.build(args)
            args.connector = ["directory"]
            args.out_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                candidate.build(args)
            run.assert_not_called()

    def test_review_mismatch_prevents_build_and_output(self):
        args = self.fixture()
        doc = json.loads(args.expected_source_inventory.read_text())
        doc["files"]["LICENSE"]["sha256"] = "0" * 64
        args.expected_source_inventory.write_text(json.dumps(doc))
        with patch.object(package, "run", wraps=package.run) as run:
            with self.assertRaisesRegex(ValueError, "differs"):
                candidate.build(args)
            self.assertFalse(any(call.args[0][0] == "go" for call in run.call_args_list))
        self.assertFalse(args.out_dir.exists())

    def test_real_fixed_commit_cross_build_and_version_stamping(self):
        args = self.fixture()
        # Neither tracked working-tree edits nor untracked files may enter the candidate.
        (self.repo / "LICENSE").write_text("unreviewed working tree change")
        (self.repo / "edge/agent/untracked.txt").write_text("not reviewed")
        result = candidate.build(args)
        self.assertEqual(result["schema_version"], "enterprise-release-candidate/v1")
        for key in ("signed", "installable", "published"):
            self.assertIs(result[key], False)
        self.assertFalse((args.out_dir / "release.json").exists())
        self.assertNotIn("edge/agent/untracked.txt", result["source_inventory"])
        self.assertIn("Synthetic", (args.out_dir / "LICENSE").read_text())
        self.assertEqual(len(result["artifacts"]), 4)
        signing_bytes = (args.out_dir / "publisher-signing-input.json").read_bytes()
        signing = json.loads(signing_bytes)
        self.assertEqual(set(signing), {"schema_version", "product", "version", "source_commit", "artifacts", "signed_by"})
        self.assertEqual(signing["schema_version"], "enterprise-release/v1")
        self.assertEqual(signing["artifacts"], result["artifacts"])
        self.assertEqual(signing["source_commit"], args.source_sha)
        self.assertEqual(signing["version"], args.version)
        self.assertEqual(signing_bytes, json.dumps(signing, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
        portable, = args.out_dir.glob("*-unsigned-candidate.zip")
        prefix = portable.stem
        with zipfile.ZipFile(portable) as bundle:
            expected = {f"{prefix}/{name}" for name in package.inventory(args.out_dir)
                        if name not in (portable.name, "SHA256SUMS")}
            self.assertEqual(set(bundle.namelist()), expected)
            for item in bundle.infolist():
                relative = item.filename.removeprefix(prefix + "/")
                self.assertEqual(bundle.read(item), (args.out_dir / relative).read_bytes())
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                if relative.startswith("bin/"):
                    self.assertEqual((item.external_attr >> 16) & 0o777, 0o755)
        sums = (args.out_dir / "SHA256SUMS").read_text().splitlines()
        self.assertIn(f"{package.digest(portable)}  {portable.name}", sums)
        for artifact in result["artifacts"]:
            binary = args.out_dir / artifact["path"]
            self.assertEqual(package.digest(binary), artifact["sha256"])
            self.assertEqual(binary.stat().st_size, artifact["bytes"])
            native = {"aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
            if platform.system() == "Linux" and artifact["arch"] == native:
                self.assertEqual(subprocess.check_output([binary]).decode().strip(), args.version)
        second = self.root / "second"
        args.out_dir = second
        repeated = candidate.build(args)
        self.assertEqual(result, repeated)
        self.assertEqual(package.inventory(self.root / "candidate"), package.inventory(second))

    def test_build_failure_leaves_no_output(self):
        args = self.fixture()
        original = package.run

        def fail_build(argv, **kwargs):
            if argv[:2] == ["go", "build"]:
                raise ValueError("synthetic compiler failure")
            return original(argv, **kwargs)

        with (patch.object(package, "run", side_effect=fail_build),
              self.assertRaisesRegex(ValueError, "compiler failure")):
            candidate.build(args)
        self.assertFalse(args.out_dir.exists())

    def test_old_constant_version_commit_rejected_before_compilation(self):
        args = self.fixture()
        relative = "edge/agent/main.go"
        source = self.repo / relative
        source.write_text(source.read_text().replace("var agentVersion", "const agentVersion"))
        self.git("add", relative)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic old version")
        args.source_sha = self.git("rev-parse", "HEAD")
        doc = json.loads(args.expected_source_inventory.read_text())
        doc["files"][relative].update(sha256=package.digest(source), bytes=source.stat().st_size)
        args.expected_source_inventory.write_text(json.dumps(doc))
        with patch.object(package, "run", wraps=package.run) as run:
            with self.assertRaisesRegex(ValueError, "version stamping"):
                candidate.build(args)
            self.assertFalse(any(call.args[0][0] == "go" for call in run.call_args_list))
        self.assertFalse(args.out_dir.exists())

    def test_archive_verification_failure_leaves_no_output(self):
        args = self.fixture()
        with (patch.object(package, "zip_verified", side_effect=ValueError("archive content mismatch")),
              self.assertRaisesRegex(ValueError, "archive content mismatch")):
            candidate.build(args)
        self.assertFalse(args.out_dir.exists())

    def test_actual_connector_describe_reports_stamped_version(self):
        for name in candidate.CONNECTORS:
            binary = self.root / name
            package.run(["go", "build", "-mod=readonly", "-buildvcs=false", "-trimpath",
                         "-ldflags", "-X main.connectorVersion=1.2.3-rc.1", "-o", binary, "."],
                        cwd=package.ROOT / "connectors" / name,
                        env=candidate.build_env(), phase="native describe fixture build")
            # Describe only: no scope, scan, identity, service or network request.
            reply = subprocess.check_output([binary, "--serve"],
                                            input=b'{"id":"fixture","op":"describe"}\n',
                                            env=candidate.build_env(), timeout=10)
            doc = json.loads(reply)
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["result"]["version"], "1.2.3-rc.1")

    def test_signing_request_keeps_original_publisher(self):
        for relative in ("edge/agent/installplan/release.go", "apps/agentshield/internal/skillmanifest/manifest.go"):
            source = (package.ROOT / relative).read_text()
            match = re.search(r'const ReleasePublicKeyB64 = "([^"]+)"', source)
            self.assertIsNotNone(match)
            self.assertEqual(candidate.PUBLISHER_PUBLIC_KEY, match.group(1))


if __name__ == "__main__":
    unittest.main()
