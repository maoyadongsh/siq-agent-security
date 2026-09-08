#!/usr/bin/env python3
"""Operate only this repository's isolated hackathon profile on Linux."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / ".tmp/hackathon-profile"
CURRENT = PROFILE / "current"


def profile():
    if PROFILE.is_symlink() or PROFILE.parent.is_symlink() or CURRENT.is_symlink():
        raise RuntimeError("refusing a symlinked profile")
    PROFILE.mkdir(parents=True, mode=0o700, exist_ok=True)
    marker = PROFILE / "owner.json"
    expected = {"schema_version": "hackathon-profile/v1", "repository": str(ROOT)}
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text()) != expected:
            raise RuntimeError("profile ownership mismatch")
    else:
        if any(PROFILE.iterdir()):
            raise RuntimeError("refusing to adopt an existing unmarked directory")
        marker.write_text(json.dumps(expected))
        marker.chmod(0o600)


def state():
    document = CURRENT / "service.json"
    if document.is_symlink():
        raise RuntimeError("refusing symlinked service metadata")
    value = json.loads(document.read_text())
    if value.get("schema_version") != "hackathon-service/v1" or value.get("state_dir") != str(CURRENT):
        raise RuntimeError("service ownership mismatch")
    from urllib.parse import urlsplit
    url = urlsplit(value["endpoint"])
    if url.scheme != "http" or url.hostname != "127.0.0.1" or url.path or url.query or url.fragment or url.username:
        raise RuntimeError("invalid service endpoint")
    return value


def alive(value, prefix=""):
    try:
        fields = Path(f"/proc/{int(value[prefix + 'pid'])}/stat").read_text().split(") ", 1)[1].split()
        return fields[0] != "Z" and fields[19] == value[prefix + "process_start"]
    except (OSError, ValueError, IndexError, KeyError):
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("service redirect rejected")


def request(value, route, body=None, request_id=None):
    headers = {"Content-Type": "application/json", "X-SIQ-Demo": "1", "Authorization": "Bearer " + value["token"]}
    if request_id:
        headers["Idempotency-Key"] = request_id
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(value["endpoint"] + route, headers=headers,
                            data=None if body is None else json.dumps(body).encode()), timeout=5) as response:
        return json.load(response)


def stop():
    value = state()
    if alive(value):
        request(value, "/hackathon/v1/shutdown", {})
    elif alive(value, "daemon_"):
        # An unexpectedly exited supervisor may leave its exact owned daemon.
        # PID plus kernel start time prevents signalling a reused PID.
        os.kill(value["daemon_pid"], signal.SIGTERM)
    deadline = time.monotonic() + 80
    while (alive(value) or alive(value, "daemon_")) and time.monotonic() < deadline:
        time.sleep(0.2)
    if alive(value) or alive(value, "daemon_"):
        raise RuntimeError("service is still exiting; no state was removed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "reset", "pair", "healthcheck", "normal", "mcp-attack", "provenance", "fake-success", "approval", "trifecta"))
    parser.add_argument("--mode", choices=("demo", "test"), default="demo")
    parser.add_argument("--provider", choices=("ornith", "stepfun"), default=os.environ.get("SIQ_MODEL_PROVIDER", "stepfun"))
    parser.add_argument("--port", type=int, default=47621)
    args = parser.parse_args()
    profile()
    if args.action == "start":
        if CURRENT.exists():
            raise RuntimeError("current profile already exists; stop/reset it before a new start")
        env = dict(os.environ)
        env.update(PYTHONPATH=str(ROOT / "apps/secure-agent"), SIQ_MODEL_PROVIDER=args.provider)
        if args.provider == "ornith":
            env.setdefault("SIQ_ORNITH_ENDPOINT", "http://127.0.0.1:8006/v1")
            env.setdefault("SIQ_ORNITH_MODEL", "Ornith-1.5-35B-A3B-NVFP4")
        # Build the existing local Web application and embed it in the existing
        # binary. No second SPA or security daemon is introduced.
        subprocess.run(["npm", "ci"], cwd=ROOT / "apps/web", check=True)
        subprocess.run(["npm", "run", "build:local"], cwd=ROOT / "apps/web", check=True)
        binary = PROFILE / "siq-agent-security"
        subprocess.run(["go", "build", "-o", str(binary), "./cmd/agentshield"], cwd=ROOT / "apps/agentshield",
                       env={**env, "GOTOOLCHAIN": "go1.26.6"}, check=True)
        CURRENT.mkdir(mode=0o700)
        log_path = CURRENT / "service.log"
        with os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as log:
            child = subprocess.Popen([sys.executable, "-m", "secure_agent.service", "--binary", str(binary),
                "--state-dir", str(CURRENT), "--mode", args.mode, "--port", str(args.port)], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("service startup failed; inspect the private profile service.log")
            if (CURRENT / "service.json").exists() and log_path.stat().st_size:
                value = state()
                health = request(value, "/health")
                if health["status"] == "ready":
                    print(log_path.read_text().splitlines()[0])
                    return
            time.sleep(0.1)
        raise RuntimeError("startup readiness timed out; inspect the owned service before retrying")
    if args.action == "stop":
        stop()
        print(json.dumps({"status": "stopped"}))
    elif args.action == "reset":
        if CURRENT.exists():
            if (CURRENT / "service.json").exists():
                stop()
            elif (CURRENT / "siq-state").exists():
                raise RuntimeError("incomplete startup state; verify its process before reset")
            archived = PROFILE / ("archive-" + uuid4().hex)
            CURRENT.rename(archived)
            print(json.dumps({"status": "reset", "audit_archive": str(archived)}))
        else:
            print(json.dumps({"status": "already_reset"}))
    elif args.action == "pair":
        value = state()
        if not alive(value):
            raise RuntimeError("owned service is stopped")
        print(json.dumps({"url": value["endpoint"] + "/demo", **request(value, "/hackathon/v1/pairing/renew", {})}))
    elif args.action == "healthcheck":
        value = state()
        if not alive(value):
            raise RuntimeError("owned service is stopped")
        print(json.dumps({"agent": request(value, "/health"), "web": request(value, "/web/health"),
                          "url": value["endpoint"] + "/demo"}))
    else:
        value = state()
        scenario = "same-value" if args.action == "provenance" else args.action
        task = request(value, "/hackathon/v1/tasks", {"scenario": scenario,
            "prompt": "Analyze the repository, write a security report and deliver it to Alice."}, uuid4().hex)
        print(json.dumps({"task": task["id"], "url": value["endpoint"] + "/demo", "status": "submitted"}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, URLError, ValueError, subprocess.CalledProcessError) as exc:
        # No service metadata, tokens or HTTP response bodies enter diagnostics.
        print(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
