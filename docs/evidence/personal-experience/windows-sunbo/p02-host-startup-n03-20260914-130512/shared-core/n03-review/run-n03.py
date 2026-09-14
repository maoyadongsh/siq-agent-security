"""Run three fixed-source Windows component tests in an existing private root.

The operator creates an empty NTFS root protected for current-user/SYSTEM/Admins.
This runner verifies that ACL; it never changes parent or user-directory ACLs.
All raw output remains private. Publish only separately reviewed derived evidence.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess

SOURCE = "9cc18630be584692905e1ce612b91a9ba5aee610"
TESTS = (
    "TestLateUpdateOutcomeCannotOverwriteUserReconfiguration",
    "TestSaveUpdateSourcePreservesIncompatibleRecords",
    "TestScheduledCheckNewVersionDoesNotConfirm",
)
ACL_CHECK = r"""
$ErrorActionPreference='Stop'
$a=Get-Acl -LiteralPath $env:SIQ_N03_PRIVATE_ROOT
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--go", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--outer-timeout", type=int, choices=(180, 300), default=180)
    args = parser.parse_args()
    checkout = args.checkout.resolve(strict=True)
    go = args.go.resolve(strict=True)
    root = args.private_root.resolve(strict=True)
    if os.name != "nt" or list(root.iterdir()):
        raise RuntimeError("Requires Windows and a fresh empty private root")

    def git(*argv):
        return subprocess.check_output(["git", "-C", str(checkout), *argv], text=True).strip()

    source_before = git("rev-parse", "HEAD")
    dirty_before = bool(git("status", "--porcelain"))
    if source_before != SOURCE or dirty_before:
        raise RuntimeError("Fixed clean source required")
    acl_env = {**os.environ, "SIQ_N03_PRIVATE_ROOT": str(root)}
    acl = json.loads(subprocess.check_output(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ACL_CHECK],
        env=acl_env, text=True,
    ))
    cache = root / "cache"
    cache_source = "fresh-private-cache"
    if args.cache_root is not None:
        cache = args.cache_root.resolve(strict=True)
        if not cache.is_dir() or cache.name != "cache":
            raise RuntimeError("Expected the previous owned cache directory")
        subprocess.check_output(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ACL_CHECK],
            env={**os.environ, "SIQ_N03_PRIVATE_ROOT": str(cache.parent)}, text=True,
        )
        cache_source = cache.parent.name + "/cache"
    for name in ("tmp", "build", "cache", "gopath", "appdata", "localappdata"):
        (root / name).mkdir()
    telemetry = root / "appdata" / "go" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "mode").write_text("off 2026-09-14", encoding="ascii")
    env = {
        **os.environ, "GOENV": "off", "GOWORK": "off", "GOFLAGS": "",
        "GOOS": "windows", "GOARCH": "amd64", "CGO_ENABLED": "0",
        "GOPROXY": "off", "GOSUMDB": "off", "GOTOOLCHAIN": "local",
        "GOCACHEPROG": "", "TMP": str(root / "tmp"), "TEMP": str(root / "tmp"),
        "GOTMPDIR": str(root / "build"), "GOCACHE": str(cache),
        "GOPATH": str(root / "gopath"), "APPDATA": str(root / "appdata"),
        "LOCALAPPDATA": str(root / "localappdata"),
    }
    env.pop("GOROOT", None)
    env.pop("GOMODCACHE", None)
    version = subprocess.check_output([str(go), "version"], env=env, text=True).strip()
    goenv = json.loads(subprocess.check_output(
        [str(go), "env", "-json", "GOHOSTOS", "GOHOSTARCH", "GOOS", "GOARCH", "CGO_ENABLED", "GOVERSION", "GOTOOLCHAIN", "GOTELEMETRY"],
        env=env, text=True,
    ))
    if goenv["GOHOSTOS"] != "windows" or goenv["GOOS"] != "windows" or goenv["GOTELEMETRY"] != "off":
        raise RuntimeError("Unexpected Go platform or telemetry mode")
    module_identity = subprocess.check_output([str(go), "version", "-m", str(go)], env=env)
    (root / "go-toolchain-build.private.txt").write_bytes(module_identity)
    argv = ["test", "./internal/skillinstall", "-run", "^(" + "|".join(TESTS) + ")$", "-count=1", "-p=1", "-parallel=1", "-timeout=90s", "-json"]
    command = [str(go), *argv]
    start = utc()
    timed_out = False
    cleanup = None
    with (root / "n03-tests.private.jsonl").open("xb") as stream:
        process = subprocess.Popen(command, cwd=checkout / "apps" / "agentshield", env=env, stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        (root / "active-process.private.json").write_text(json.dumps({"pid": process.pid, "started_utc": start}), encoding="utf-8")
        try:
            code = process.wait(timeout=args.outer_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            killed = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            (root / "timeout-cleanup.private.txt").write_bytes(killed.stdout)
            cleanup = killed.returncode
            code = process.wait(timeout=20)
    finish = utc()
    raw = (root / "n03-tests.private.jsonl").read_bytes()
    result = {
        "source_before": source_before, "source_after": git("rev-parse", "HEAD"),
        "source_dirty_before": dirty_before, "source_dirty_after": bool(git("status", "--porcelain")),
        "go_version": version, "go_identity": goenv,
        "go_exe_sha256": hashlib.sha256(go.read_bytes()).hexdigest(),
        "go_build_identity_sha256": hashlib.sha256(module_identity).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_utc": start, "finished_utc": finish, "exit_code": code,
        "outer_timeout_seconds": args.outer_timeout, "outer_timed_out": timed_out,
        "timeout_cleanup_exit": cleanup, "go_process_reaped": process.poll() is not None,
        "test_argv": argv, "cwd": "apps/agentshield", "private_root_acl": acl,
        "offline_environment": {k: env[k] for k in ("GOENV", "GOWORK", "GOFLAGS", "GOPROXY", "GOSUMDB", "GOTOOLCHAIN", "GOCACHEPROG")},
        "isolated_environment_paths": ["TMP", "TEMP", "GOTMPDIR", "GOCACHE", "GOPATH", "APPDATA", "LOCALAPPDATA"],
        "cache_source": cache_source,
        "cache_policy": "Reuse only the prior owned private Go build cache; prior logs and summaries remain immutable" if args.cache_root else "Fresh private Go build cache",
        "raw_log_bytes": len(raw), "raw_log_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "Windows component tests using temporary synthetic state and in-memory upstream; no real host or model acceptance",
    }
    (root / "runner-summary.private.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
