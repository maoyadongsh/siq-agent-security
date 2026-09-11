#!/usr/bin/env python3
"""Verify legacy adapter records with two real local binaries in synthetic HOME."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-binary", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    previous, current = args.previous_binary.resolve(), args.binary.resolve()
    checks = []
    with tempfile.TemporaryDirectory(prefix="siq-adapter-upgrade-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL")}
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "LOCALAPPDATA": str(home / "AppData/Local"),
                "HERMES_HOME": str(home / ".hermes"),
                "SIQ_AGENT_SECURITY_STATE_DIR": str(root / "state"),
            }
        )

        def command(binary, *arguments):
            result = subprocess.run(
                [str(binary), "adapter", *arguments],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                # Captured output may contain local configuration; do not echo it.
                raise RuntimeError("isolated adapter command failed: " + arguments[0])
            return json.loads(result.stdout)

        default = home / ".hermes"
        work = default / "profiles/work"
        work.mkdir(parents=True)
        for path in (default, work):
            (path / "config.yaml").write_text("model: isolated-fixture\n")
        wrapper = home / ".local/bin/hermes-skills-install"
        if os.name != "nt":
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/sh\n# original fixture wrapper\n")
            wrapper.chmod(0o751)
        command(previous, "install", "hermes")
        assert (default / "plugins/siq-agent-security/plugin.yaml").is_file()
        checks.append("previous_binary_installed_default_profile")
        instances = command(current, "instances", "hermes")["instances"]
        default_id = next(item["instance_id"] for item in instances if Path(item["config_dir"]) == default)
        work_id = next(item["instance_id"] for item in instances if Path(item["config_dir"]) == work)
        preview = command(current, "preview", "hermes", "install", "--instance", default_id)
        assert preview["instance_id"] == default_id
        command(current, "install", "hermes", "--instance", default_id)
        command(current, "install", "hermes", "--instance", work_id)
        checks.append("current_binary_read_previous_encrypted_record_and_upgraded")
        command(current, "uninstall", "hermes", "--instance", default_id)
        assert not (default / "plugins/siq-agent-security/plugin.yaml").exists()
        assert (work / "plugins/siq-agent-security/plugin.yaml").is_file()
        assert (default / "config.yaml").read_text() == "model: isolated-fixture\n"
        checks.append("default_uninstall_preserved_named_profile_and_original_configuration")
        if os.name != "nt":
            assert wrapper.read_text() == "#!/bin/sh\n# original fixture wrapper\n"
            assert wrapper.stat().st_mode & 0o777 == 0o751
            checks.append("original_legacy_wrapper_content_and_mode_restored")
        command(current, "uninstall", "hermes", "--instance", work_id)
        assert not (work / "plugins/siq-agent-security/plugin.yaml").exists()
        checks.append("named_profile_uninstalled_independently")
    report = {
        "schema_version": "personal-adapter-upgrade-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "previous_binary_sha256": hashlib.sha256(previous.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(current.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "os": platform.system(),
        "architecture": platform.machine(),
        "checks": checks,
        "scope": "real binary upgrade and encrypted ownership compatibility; isolated profiles; no host runtime claim",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
