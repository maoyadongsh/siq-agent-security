"""Run a fixed-source Windows adapters test/check in a fresh private fixture root.

No host processes, Python test helpers or network transports are used by the
reviewed internal/adapters package. Raw logs remain private. Public Go events
redact exact local path prefixes even when nested JSON escapes separators.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


GO_SHA = "d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490"
PACKAGE = "siq-agent-security/apps/agentshield/internal/adapters"
ALL_TESTS = sorted([
    "TestPolicyExecBlocksQuarantineWarnsConditionsAllowsClean",
    "TestPolicyExecFailsClosed", "TestCodeBuddyHookMapping",
    "TestCodeBuddyHookFailClosedTable", "TestCodeBuddyPostToolUseObservesAndNeverBlocks",
])
FOCUSED = ALL_TESTS[-2:]
ACL_CHECK = r"""
$ErrorActionPreference='Stop'
$a=Get-Acl -LiteralPath $env:SIQ_CHECK_ROOT
$own=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed=@($own,'S-1-5-18','S-1-5-32-544');$seen=@()
foreach($r in $a.Access){
 $id=$r.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
 if($id -notin $allowed -or $r.AccessControlType -ne 'Allow' -or $r.IsInherited -or
 $r.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
 $r.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' -or
 $r.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None){throw 'unexpected ACL'}
 $seen+=,$id
}
if(!$a.AreAccessRulesProtected -or $a.Access.Count -ne 3 -or @($seen | Select-Object -Unique).Count -ne 3){throw 'protected three-ACE root required'}
@{protected=$true;ace_count=3;principals=@('current-user','SYSTEM','Administrators');full_control=$true;broad_aces=$false}|ConvertTo-Json -Compress
"""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "private-root", "cache-root", "go", "git", "pwsh", "delivery"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--phase", choices=("baseline", "focused", "package", "vet", "gofmt"), required=True)
    args = p.parse_args()
    checkout, root, cache, go = [getattr(args, name).resolve(strict=True) for name in ("checkout", "private_root", "cache_root", "go")]
    delivery = args.delivery.resolve(strict=True)
    if os.name != "nt" or digest(go.read_bytes()) != GO_SHA:
        raise RuntimeError("Expected the reviewed native Windows Go toolchain")
    command_flags = {"creationflags": subprocess.CREATE_NO_WINDOW}

    def git(*argv):
        return subprocess.check_output([str(args.git), "-C", str(checkout), *argv], **command_flags)

    def source_state():
        return {"source": git("rev-parse", "HEAD").decode().strip(), "source_dirty": bool(git("status", "--porcelain").strip())}

    before = source_state()
    if before != {"source": args.source, "source_dirty": False}:
        raise RuntimeError("Fixed clean source required")

    def acl(path):
        return json.loads(subprocess.check_output([str(args.pwsh), "-NoProfile", "-NonInteractive", "-Command", ACL_CHECK], env={**os.environ, "SIQ_CHECK_ROOT": str(path)}, text=True, **command_flags))

    root_acl, cache_acl = acl(root), acl(cache.parent)
    run = root / args.phase
    run.mkdir(exist_ok=False)
    for name in ("home", "tmp", "build", "gopath", "appdata", "localappdata"):
        (run / name).mkdir()
    telemetry = run / "appdata" / "go" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "mode").write_text("off 2026-09-14", encoding="ascii")
    system = Path(os.environ["SystemRoot"])
    home = run / "home"
    env = {
        "SystemRoot": str(system), "WINDIR": str(system), "SystemDrive": system.drive,
        "COMSPEC": str(system / "System32" / "cmd.exe"),
        "PATH": os.pathsep.join((str(go.parent), str(system / "System32"))),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD", "HOME": str(home), "USERPROFILE": str(home),
        "HOMEDRIVE": home.drive, "HOMEPATH": str(home)[len(home.drive):],
        "GOENV": "off", "GOWORK": "off", "GOFLAGS": "", "GOOS": "windows", "GOARCH": "amd64",
        "CGO_ENABLED": "0", "GOPROXY": "off", "GOSUMDB": "off", "GOTOOLCHAIN": "local", "GOCACHEPROG": "", "GOMAXPROCS": "2",
        "GOROOT": str(go.parent.parent), "TMP": str(run / "tmp"), "TEMP": str(run / "tmp"),
        "GOTMPDIR": str(run / "build"), "GOCACHE": str(cache), "GOPATH": str(run / "gopath"),
        "APPDATA": str(run / "appdata"), "LOCALAPPDATA": str(run / "localappdata"),
    }
    identity = json.loads(subprocess.check_output([str(go), "env", "-json", "GOHOSTOS", "GOHOSTARCH", "GOOS", "GOARCH", "CGO_ENABLED", "GOVERSION", "GOTOOLCHAIN", "GOTELEMETRY"], env=env, text=True, **command_flags))
    if identity["GOVERSION"] != "go1.27.1" or identity["GOTELEMETRY"] != "off":
        raise RuntimeError("Unexpected Go identity or telemetry")
    go_version = subprocess.check_output([str(go), "version"], env=env, text=True, **command_flags).strip()
    argv = ["test", "-json", "-count=1", "-timeout=120s"]
    if args.phase == "focused":
        argv += ["-run", "^(" + "|".join(FOCUSED) + ")$"]
    argv += ["./internal/adapters"]
    executable = go
    if args.phase == "vet":
        argv = ["vet", "-p=2", "./..."]
    elif args.phase == "gofmt":
        executable, argv = go.with_name("gofmt.exe"), ["-l", "."]
    replacements = [(root, "<PRIVATE_RUN_ROOT>"), (checkout, "<CHECKOUT>"), (cache.parent, "<OWNED_CACHE_ROOT>"), (go.parent.parent, "<GO_TOOLCHAIN>")]
    patterns = [(re.compile(r"[\\/]+".join(re.escape(part) for part in re.split(r"[\\/]", str(path))), re.I), label) for path, label in replacements]

    def redact(text):
        for pattern, label in patterns:
            text = pattern.sub(lambda match: label, text)
        text = re.sub(r"S-1-5-21-[0-9-]+", "<SID>", text)
        if re.search(r"[A-Z]:[\\/]+Users[\\/]+|S-1-5-21-\d", text, re.I):
            raise RuntimeError("Personal identity escaped exact-prefix redaction")
        return text

    started = dt.datetime.now(dt.UTC).isoformat()
    timeout, cleanup_exit = False, None
    print(json.dumps({"phase_started": args.phase, "source": args.source, "started_utc": started}), flush=True)
    with (run / "raw.private.log").open("xb") as stream:
        proc = subprocess.Popen([str(executable), *argv], cwd=checkout / "apps" / "agentshield", env=env, stdout=stream, stderr=subprocess.STDOUT, **command_flags)
        write_json(run / "process.private.json", {"pid": proc.pid, "phase": args.phase, "started_utc": started})
        try:
            exit_code = proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            timeout = True
            cleanup = subprocess.run([str(system / "System32" / "taskkill.exe"), "/PID", str(proc.pid), "/T", "/F"], capture_output=True, **command_flags)
            (run / "timeout-cleanup.private.log").write_bytes(cleanup.stdout + cleanup.stderr)
            cleanup_exit = cleanup.returncode
            exit_code = proc.wait(timeout=20)
    finished = dt.datetime.now(dt.UTC).isoformat()
    raw = (run / "raw.private.log").read_bytes()
    events, non_json = [], []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            non_json.append(redact(line))
            continue
        if "Output" in event:
            event["Output"] = redact(event["Output"])
        events.append(event)
    derived = (("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n") if events else "").encode("utf-8")
    (delivery / (args.phase + ".jsonl")).write_bytes(derived)
    (delivery / (args.phase + "-output.txt")).write_text("\n".join(non_json), encoding="utf-8")
    terminal = [{key: event[key] for key in ("Package", "Test", "Action", "Elapsed") if key in event} for event in events if event["Action"] in ("pass", "fail", "skip") and "Test" in event]
    top = [e for e in terminal if "/" not in e["Test"]]
    count = lambda rows: {a: sum(e["Action"] == a for e in rows) for a in ("pass", "fail", "skip")}
    expected = FOCUSED if args.phase == "focused" else ALL_TESTS
    package_end = [e for e in events if e["Action"] in ("pass", "fail", "skip") and "Test" not in e]
    after = source_state()
    result = {"phase": args.phase, "source_before": before, "source_after": after, "argv": argv, "cwd": "apps/agentshield", "go_version": go_version, "go_identity": identity, "go_exe_sha256": GO_SHA, "check_executable_sha256": digest(executable.read_bytes()), "runner_sha256": digest(Path(__file__).read_bytes()), "root_acl_before": root_acl, "root_acl_after": acl(root), "cache_parent_acl": cache_acl, "cache_policy": "Reuse earlier owned private N03 build cache; prior raw evidence unchanged", "started_utc": started, "finished_utc": finished, "exit_code": exit_code, "outer_timeout_seconds": 300, "outer_timed_out": timeout, "cleanup_exit": cleanup_exit, "direct_process_reaped": proc.poll() is not None, "raw_bytes": len(raw), "raw_sha256": digest(raw), "derived_jsonl_bytes": len(derived), "derived_jsonl_sha256": digest(derived), "event_count": len(events), "non_json_lines": len(non_json), "top_level_counts": count(top), "subtest_counts": count([e for e in terminal if "/" in e["Test"]]), "terminal_tests": terminal, "package_terminal_events": package_end, "expected_top_level_tests": expected if args.phase in ("baseline", "focused", "package") else [], "expected_test_set_matches": sorted(e["Test"] for e in top) == expected if args.phase in ("baseline", "focused", "package") else None, "source_unchanged_clean": after == before, "redaction": "Exact case-insensitive owned path prefixes, repeated slash/backslash separators including nested JSON; account SID pattern. Raw bytes retained privately.", "environment": {"child_allowlist": True, "synthetic_home_profile_appdata_tmp": True, "go_proxy_sumdb_off": True, "no_host_optins_or_credentials": True, "test_path_roles": ["Go bin", "Windows System32"], "controller_git_acl_queries_inherit_controller_environment": True}, "scope": "Native Windows component tests/checks, no real host acceptance, no release SIQ binary created"}
    write_json(run / "summary.private.json", result)
    write_json(delivery / (args.phase + "-summary.json"), result)
    print(json.dumps({key: result[key] for key in ("phase", "exit_code", "outer_timed_out", "event_count", "top_level_counts", "subtest_counts", "expected_test_set_matches", "source_unchanged_clean")}), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
