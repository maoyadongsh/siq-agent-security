import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from launch_rc import launch_configuration
from package_rc import (
    TARGETS,
    clean_source,
    entries,
    sha,
    validate_identity,
    verify_package,
    write_json,
)


class PackageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)
        self.root = self.parent / "candidate"
        names = ["source/apps/secure-agent/secure_agent/models.py", "source/demo/fixtures/github/repository.json",
                 "source/scripts/hackathon/launch_rc.py", "source/apps/agentshield/internal/ui/embedded/index.html",
                 "source/packages/contracts/model-task-plan-v2.schema.json", "sbom.cdx.json", "source-info.json",
                 "skills-inventory.json", "EVIDENCE_SUMMARY.md"]
        names += [f"source/skills/{name}/SKILL.md" for name in ("secure-research", "secure-report", "secure-delivery")]
        names += [f"bin/siq-agent-security-{system}-{arch}" + (".exe" if system == "windows" else "")
                  for system, arch in TARGETS]
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("verification fixture, not an executable binary\n")
            if name.startswith("bin/"):
                path.chmod(0o755)
        self.identity = {"schema_version": "hackathon-rc-source/v2", "git_sha": "a" * 40,
            "git_ref": "test", "build_time": "2026-09-08T00:00:00Z", "go_version": "go1.26.6",
            "python_version": "Python 3.13", "node_version": "v22", "target": ["linux/arm64"]}
        (self.root / "source-info.json").write_text(json.dumps(self.identity))
        manifest = {"schema_version": "hackathon-candidate/v1", "official_signature": False, "files": entries(self.root)}
        write_json(self.root / "candidate-manifest.json", manifest)
        sums = "".join(f"{v['sha256']}  {k}\n" for k, v in sorted(manifest["files"].items()))
        (self.root / "SHA256SUMS").write_text(sums + f"{sha(self.root / 'candidate-manifest.json')}  candidate-manifest.json\n")

    def test_complete_inventory_and_supported_launch_selection(self):
        verify_package(self.root)
        for machine, arch in (("aarch64", "arm64"), ("x86_64", "amd64")):
            source, binary, state = launch_configuration(self.root, self.parent / "state", machine, "Linux")
            self.assertEqual(binary.name, "siq-agent-security-linux-" + arch)
            self.assertEqual(source, self.root / "source")
            self.assertFalse(state.exists())

    def test_changed_removed_or_extra_file_is_rejected(self):
        target = self.root / "sbom.cdx.json"
        original = target.read_bytes()
        target.write_text("changed")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_package(self.root)
        target.unlink()
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_package(self.root)
        target.write_bytes(original)
        (self.root / "unexpected").write_text("extra")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_package(self.root)

    def test_symlink_executable_mode_and_checksum_changes_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.root / "sbom.cdx.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_package(self.root)
        link.unlink()
        binary = self.root / "bin/siq-agent-security-linux-arm64"
        binary.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_package(self.root)
        binary.chmod(0o755)
        (self.root / "SHA256SUMS").write_text("changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_package(self.root)

    def test_private_state_and_platform_boundaries(self):
        for state, machine, system in ((self.root / "state", "aarch64", "Linux"),
                                       (self.parent, "aarch64", "Linux"),
                                       (self.parent / "new", "aarch64", "Darwin"),
                                       (self.parent / "new", "unknown", "Linux")):
            with self.assertRaises(ValueError):
                launch_configuration(self.root, state, machine, system)

    def test_unsigned_manifest_cannot_claim_official_signature(self):
        path = self.root / "candidate-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["official_signature"] = True
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "signature claim"):
            verify_package(self.root)

    def test_clean_source_rejects_unstaged_staged_and_untracked_changes(self):
        repo = self.parent / "git"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        target = repo / "source.txt"
        target.write_text("committed\n")
        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.assertEqual(len(clean_source(repo)), 40)
        target.write_text("unstaged\n")
        with self.assertRaisesRegex(ValueError, "clean committed"):
            clean_source(repo)
        git("add", ".")
        with self.assertRaisesRegex(ValueError, "clean committed"):
            clean_source(repo)
        git("restore", "--staged", "source.txt")
        git("restore", "source.txt")
        (repo / "untracked").write_text("extra\n")
        with self.assertRaisesRegex(ValueError, "clean committed"):
            clean_source(repo)

    def test_v2_identity_requires_exact_commit_and_no_dirty_manifest(self):
        validate_identity(self.identity)
        for change in ({"git_sha": "dirty"}, {"node_version": ""}, {"dirty": False}, {"source_files": []}):
            with self.assertRaisesRegex(ValueError, "source identity invalid"):
                validate_identity({**self.identity, **change})


if __name__ == "__main__":
    unittest.main()
