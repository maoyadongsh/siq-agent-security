"""Run the reviewed Windows-only adapter installer test fix, offline.

The operator creates an empty, protected NTFS root for this run. This runner
checks its ACL and never changes ACLs or production files. Raw logs stay there;
separately labelled, path-redacted copies are written to the delivery directory.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil


SOURCE = "2f84d5af6934f3cc17354107f66beae6dc8e1b59"
BASE = "b303c6f92392f3a44c306d81ad7323c6291ef4f2"
CHANGED = (
    "apps/agentshield/internal/adapterinstall/backup_restore_test.go",
    "apps/agentshield/internal/adapterinstall/install_entry_test.go",
)
GO_SHA256 = "d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490"
TESTS = (
    "TestHermesNativeEvidenceSeparatesRegistrationFromCompatibility",
    "TestConfiguredEndpointReadsConnectionDocumentOnly",
    "TestHermesControlledInstallPathChecksBeforeNativeInstall",
    "TestInstallEntryIsNeverTakenOver",
    "TestUninstallOfOneInstanceRestoresOnlyThatInstance",
)
ACL_CHECK = r"""
$ErrorActionPreference='Stop'
$a=Get-Acl -LiteralPath $env:SIQ_TEST_PRIVATE_ROOT
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed=@($sid,'S-1-5-18','S-1-5-32-544')
$seen=@()
foreach($r in $a.Access){
  $identity=$r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
  if($identity -notin $allowed -or $r.AccessControlType -ne 'Allow' -or $r.IsInherited -or
     $r.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
     $r.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' -or
     $r.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None){throw 'unexpected private ACL'}
  $seen+=,$identity
}
if(!$a.AreAccessRulesProtected -or $a.Access.Count -ne 3 -or @($seen | Select-Object -Unique).Count -ne 3){throw 'private ACL required'}
@{protected=$true;ace_count=3;principals=@('current-user','SYSTEM','Administrators');rights='FullControl';broad_aces=$false}|ConvertTo-Json -Compress
"""


def utc():
    return dt.datetime.now(dt.UTC).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "go", "git", "pwsh", "private-root", "cache-root", "delivery", "python3"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve(strict=True)
    go = args.go.resolve(strict=True)
    root = args.private_root.resolve(strict=True)
    cache = args.cache_root.resolve(strict=True)
    python3 = args.python3.resolve(strict=True)
    delivery = args.delivery.resolve(strict=True)
    if os.name != "nt" or list(root.iterdir()):
        raise RuntimeError("Fresh empty private Windows root required")
    if cache.name != "cache" or not cache.is_dir():
        raise RuntimeError("Expected the previous owned private Go build cache")
    if digest(go.read_bytes()) != GO_SHA256:
        raise RuntimeError("Unexpected Go toolchain identity")

    def git(*argv):
        return subprocess.check_output(
            [str(args.git), "-c", "core.longpaths=true", "-C", str(checkout), *argv],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def source_state():
        return {"source": git("rev-parse", "HEAD").decode().strip(),
                "source_dirty": bool(git("status", "--porcelain").strip())}

    before = source_state()
    if before != {"source": SOURCE, "source_dirty": False}:
        raise RuntimeError("Reviewed clean candidate required")
    if git("diff", "--name-only", BASE, SOURCE).decode().splitlines() != list(CHANGED):
        raise RuntimeError("Expected exactly the two reviewed test-file changes")
    if "Signed-off-by:" not in git("show", "-s", "--format=%B", SOURCE).decode():
        raise RuntimeError("Expected local DCO sign-off")

    def check_acl(path):
        return json.loads(subprocess.check_output(
            [str(args.pwsh), "-NoProfile", "-NonInteractive", "-Command", ACL_CHECK],
            env={**os.environ, "SIQ_TEST_PRIVATE_ROOT": str(path)}, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ))

    acl = check_acl(root)
    cache_acl = check_acl(cache.parent)
    for name in ("home", "tmp", "build", "gopath", "appdata", "localappdata"):
        (root / name).mkdir()
    telemetry = root / "appdata" / "go" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "mode").write_text("off 2026-09-14", encoding="ascii")
    git_config = root / "git-empty.config"
    git_config.write_text("", encoding="ascii")
    git_template = root / "git-template"
    git_template.mkdir()
    system = Path(os.environ["SystemRoot"])
    home = root / "home"
    env = {
        "SystemRoot": str(system), "WINDIR": str(system), "SystemDrive": system.drive,
        "COMSPEC": str(system / "System32" / "cmd.exe"),
        "PATH": os.pathsep.join((str(go.parent), str(args.git.resolve().parent), str(python3.parent), str(args.pwsh.resolve().parent), str(system / "System32" / "WindowsPowerShell" / "v1.0"), str(system / "System32"))),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD", "HOME": str(home), "USERPROFILE": str(home),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(git_config),
        "GIT_TEMPLATE_DIR": str(git_template), "GIT_TERMINAL_PROMPT": "0",
        "HOMEDRIVE": home.drive, "HOMEPATH": str(home)[len(home.drive):],
        "GOENV": "off", "GOWORK": "off", "GOFLAGS": "", "GOOS": "windows",
        "GOARCH": "amd64", "CGO_ENABLED": "0", "GOPROXY": "off", "GOSUMDB": "off",
        "GOTOOLCHAIN": "local", "GOCACHEPROG": "", "GOMAXPROCS": "2",
        "GOROOT": str(go.parent.parent), "TMP": str(root / "tmp"), "TEMP": str(root / "tmp"),
        "GOTMPDIR": str(root / "build"), "GOCACHE": str(cache),
        "GOPATH": str(root / "gopath"), "APPDATA": str(root / "appdata"),
        "LOCALAPPDATA": str(root / "localappdata"),
    }
    assert all(not key.startswith("SIQ_") for key in env)
    python_identity = json.loads(subprocess.check_output([str(python3), "-I", "-S", "-c", "import json,sys; print(json.dumps({\"version\":sys.version,\"platform\":sys.platform,\"implementation\":sys.implementation.name}))"], env=env, text=True))
    python_identity["exe_sha256"] = digest(python3.read_bytes())
    python_identity["distribution"] = "Existing MSYS2 mingw64 installation; native platform recorded above"
    openssl_path = shutil.which("openssl", path=env["PATH"])
    openssl_identity = {"available_in_allowlist_path": bool(openssl_path)}
    if openssl_path:
        openssl_identity["version"] = subprocess.check_output([openssl_path, "version"], env=env, text=True).strip()
        openssl_identity["exe_sha256"] = digest(Path(openssl_path).read_bytes())
    go_version = subprocess.check_output([str(go), "version"], env=env, text=True).strip()
    go_identity = json.loads(subprocess.check_output(
        [str(go), "env", "-json", "GOHOSTOS", "GOHOSTARCH", "GOOS", "GOARCH", "CGO_ENABLED", "GOVERSION", "GOTOOLCHAIN", "GOTELEMETRY"],
        env=env, text=True,
    ))
    if (go_version != "go version go1.27.1 windows/amd64"
            or go_identity["GOTELEMETRY"] != "off"):
        raise RuntimeError("Unexpected Go platform or telemetry setting")
    go_build = subprocess.check_output([str(go), "version", "-m", str(go)], env=env)
    (root / "go-toolchain-build.private.txt").write_bytes(go_build)
    patch = git("diff", "--binary", BASE, SOURCE, "--", *CHANGED)
    (delivery / "change.patch").write_bytes(patch)

    replacements = ((root, "<PRIVATE_RUN_ROOT>"), (checkout, "<CHECKOUT>"),
                    (cache.parent, "<OWNED_CACHE_ROOT>"), (go.parent.parent, "<GO_TOOLCHAIN>"))

    def redact(text):
        for path, label in replacements:
            for value in (str(path), path.as_posix()):
                text = text.replace(value, label)
        text = re.sub(r"S-1-5-21-[0-9-]+", "<SID>", text)
        # Refuse publication if an unrecognized personal path escaped replacement.
        if re.search(r"(?i)[A-Z]:[/\\]Users[/\\]|S-1-5-21-", text):
            raise RuntimeError("Unrecognized personal path/identity in derived output")
        return text

    (delivery / "go-toolchain-build.txt").write_text(redact(go_build.decode()), encoding="utf-8")

    def run_phase(name, argv, outer_timeout):
        phase_before = source_state()
        if phase_before != before:
            raise RuntimeError("Candidate changed before phase")
        started = utc()
        raw_path = root / (name + ".private.log")
        timed_out = False
        cleanup_exit = None
        print(json.dumps({"phase_started": name, "started_utc": started}), flush=True)
        with raw_path.open("xb") as stream:
            process = subprocess.Popen(
                [str(go), *argv], cwd=checkout / "apps" / "agentshield", env=env,
                stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            write_json(root / "active-process.private.json", {"phase": name, "pid": process.pid, "started_utc": started})
            try:
                exit_code = process.wait(timeout=outer_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup = subprocess.run(
                    [str(system / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                (root / (name + "-timeout-cleanup.private.log")).write_bytes(cleanup.stdout + cleanup.stderr)
                cleanup_exit = cleanup.returncode
                exit_code = process.wait(timeout=20)
        finished = utc()
        raw = raw_path.read_bytes()
        events = []
        non_json = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                non_json.append(line)
        derived = []
        for event in events:
            if "Output" in event:
                event["Output"] = redact(event["Output"])
            derived.append(json.dumps(event, ensure_ascii=False))
        derived_raw = (("\n".join(derived) + "\n") if derived else "").encode("utf-8")
        (delivery / (name + ".jsonl")).write_bytes(derived_raw)
        (delivery / (name + "-non-json.txt")).write_text(redact("\n".join(non_json)), encoding="utf-8")
        terminals = [{key: event[key] for key in ("Package", "Test", "Action", "Elapsed") if key in event}
                     for event in events if "Test" in event and event.get("Action") in {"pass", "fail", "skip"}]
        top = [event for event in terminals if "/" not in event["Test"]]
        subs = [event for event in terminals if "/" in event["Test"]]
        count = lambda rows: {action: sum(row["Action"] == action for row in rows) for action in ("pass", "fail", "skip")}
        result = {
            "name": name, "argv": argv, "cwd": "apps/agentshield", "started_utc": started,
            "finished_utc": finished, "exit_code": exit_code, "outer_timeout_seconds": outer_timeout,
            "outer_timed_out": timed_out, "cleanup_exit": cleanup_exit, "go_process_reaped": process.poll() is not None,
            "source_before": phase_before, "source_after": source_state(), "event_count": len(events),
            "top_level_counts": count(top), "subtest_counts": count(subs), "top_level_results": top,
            "subtest_results": subs,
            "package_terminal_events": [event for event in events if "Test" not in event and event.get("Action") in {"pass", "fail", "skip"}],
            "raw_log_bytes": len(raw), "raw_log_sha256": digest(raw),
            "derived_jsonl_bytes": len(derived_raw), "derived_jsonl_sha256": digest(derived_raw),
            "non_json_lines": len(non_json), "panic_test_timed_out": b"panic: test timed out" in raw,
        }
        write_json(root / (name + "-summary.private.json"), result)
        write_json(delivery / (name + "-summary.json"), result)
        print(json.dumps({"phase_finished": name, "exit_code": exit_code,
                          "top_level_counts": result["top_level_counts"], "subtest_counts": result["subtest_counts"]}), flush=True)
        return result

    phases = [run_phase("module-vet", ["vet", "-p=2", "./..."], 300)]
    phases.append(run_phase("module-tests", ["test", "-json", "-p=2", "-parallel=1", "-count=1", "-timeout=90s", "./..."], 900))
    summary = {
        "candidate": SOURCE, "base": BASE, "source_before": before, "source_after": source_state(),
        "changed_files": list(CHANGED), "dco_signoff_present": True, "change_patch_sha256": digest(patch),
        "changed_file_sha256": {name: digest((checkout / name).read_bytes()) for name in CHANGED},
        "python3_identity": python_identity, "openssl_identity": openssl_identity,
        "go_version": go_version, "go_identity": go_identity, "go_exe_sha256": GO_SHA256,
        "go_build_identity_sha256": digest(go_build), "runner_sha256": digest(Path(__file__).read_bytes()),
        "private_root_acl": acl, "private_root_acl_after": check_acl(root), "cache_parent_acl": cache_acl,
        "cache_policy": "Reuse the previously owned N03 cold-run private build cache; previous logs and summaries unchanged",
        "fresh_synthetic_environment": ["HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TMP", "TEMP", "GOTMPDIR", "GOPATH", "APPDATA", "LOCALAPPDATA"],
        "child_environment_is_allowlist": True,
        "offline_environment": {key: env[key] for key in ("GOENV", "GOWORK", "GOFLAGS", "GOPROXY", "GOSUMDB", "GOTOOLCHAIN", "GOCACHEPROG", "GOMAXPROCS")},
        "native_host_optins_absent": ["SIQ_HERMES_NATIVE_CLI", "SIQ_OPENCLAW_NATIVE_ROOT", "SIQ_OPENCLAW_NATIVE_NODE"],
        "scope": "Windows module checks with temporary state and local/injected transports; fixed localhost.localdomain system DNS lookup, in-memory TaskDefinition parsing and random-task-name queries are permitted; no native host acceptance",
        "phases": phases,
    }
    write_json(root / "summary.private.json", summary)
    write_json(delivery / "summary.json", summary)
    print(json.dumps({"completed": True, "candidate": SOURCE, "phase_exits": {phase["name"]: phase["exit_code"] for phase in phases}}), flush=True)
    return 1 if any(phase["exit_code"] != 0 for phase in phases) else 0


if __name__ == "__main__":
    raise SystemExit(main())
