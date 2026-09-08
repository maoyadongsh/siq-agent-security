"""Loopback competition service, serving the existing local Web build.

The model receives no controller token or API for choosing task authority.
Only the operator can submit a fixed-scope scenario through this service.
"""

import argparse
import hmac
import mimetypes
import os
import re
import secrets
import signal
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from .application import SecureApplication
from .authority import LocalDaemon
from .contracts import AgentError, canonical, digest, fields, strict_json, string
from .fixtures import FixtureServices
from .models import FixtureProvider, from_environment
from .skills import SkillRegistry

SCENARIOS = ("normal", "mcp-attack", "same-value", "fake-success", "conflicting", "approval", "trifecta")
API = "/hackathon/v1"


class DemoService:
    def __init__(self, repo, daemon, fixtures, *, mode="demo", port=0,
                 repository="fixture/secure-project", scope=("README.md", "service.py"), github_endpoint=None):
        if mode not in ("demo", "test"):
            raise AgentError("service_mode_invalid")
        self.repo, self.daemon, self.fixtures, self.mode = repo, daemon, fixtures, mode
        self.model = from_environment(mode="demo") if mode == "demo" else None
        self.provider = self.model.name if self.model else "fixture"
        self.repository, self.scope, self.github_endpoint = repository, scope, github_endpoint
        self.web = repo / "apps/agentshield/internal/ui/embedded"
        self.token, self.pairing_code = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
        self._pairing_expires = time.monotonic() + 300
        self._lock = threading.Lock()
        self._tasks, self._requests = {}, {}
        self._approvals = {}
        self._worker = None
        self.stopping = threading.Event()
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _snapshot(self, task_id, value):
        if self.stopping.is_set():
            raise AgentError("service_stopping")
        with self._lock:
            self._tasks[task_id].update(strict_json(canonical(value)))

    def submit(self, body, request_id):
        fields(body, {"scenario", "prompt"})
        scenario = body["scenario"]
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise AgentError("scenario_invalid")
        string(body["prompt"], maximum=4096)
        if not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise AgentError("request_id_invalid")
        with self._lock:
            if self.stopping.is_set():
                raise AgentError("service_stopping")
            previous = self._requests.get(request_id)
            if previous:
                if previous[0] != canonical(body):
                    raise AgentError("request_id_conflict")
                return previous[1]
            if self._worker is not None and self._worker.is_alive():
                raise AgentError("task_already_running")
            if len(self._tasks) >= 100:
                raise AgentError("task_capacity_exceeded")
            task_id = uuid4().hex
            self._requests[request_id] = (canonical(body), task_id)
            self._tasks[task_id] = {"id": task_id, "scenario": scenario, "phase": "queued",
                "provider": self.provider, "task": None, "result": None, "error_code": None}
            self._worker = threading.Thread(target=self._run, args=(task_id, dict(body)), daemon=False)
            self._worker.start()
            return task_id

    def _run(self, task_id, body):
        model = None
        call_start = 0
        try:
            scenario = body["scenario"]
            mode = {"mcp-attack": "attack", "same-value": "same-value"}.get(scenario, "benign")
            # Only one task runs at a time. Fixed operator-owned scenario data
            # controls this fixture; no model output modifies service settings.
            self.fixtures.mcp = strict_json((self.repo / "demo/fixtures/mcp" / (mode + ".json")).read_bytes())
            model = (FixtureProvider(mode="test", recipient_index=int(scenario in ("mcp-attack", "same-value")))
                     if self.mode == "test" else self.model)
            call_start = len(getattr(model, "calls", []))
            result = SecureApplication(self.repo, self.daemon, self.fixtures, model).run(body["prompt"],
                repository=self.repository, question="Review the supplied code for concrete security issues",
                scope=self.scope, github_endpoint=self.github_endpoint,
                effect_mode=scenario if scenario in ("fake-success", "conflicting") else "normal",
                changed=lambda value: self._snapshot(task_id, value), approval_required=scenario == "approval",
                trifecta=scenario == "trifecta",
                on_hold=lambda request, decision, authority: self._hold(task_id, request, decision, authority))
            self._snapshot(task_id, {"phase": "finished", "task": result["task"], "intent": result["intent"],
                "result": result, "model_calls": result["model_calls"]})
        except Exception as exc:  # noqa: BLE001 -- private provider/tool errors never cross the HTTP boundary
            code = str(exc) if isinstance(exc, AgentError) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", str(exc)) else "agent_internal_error"
            with self._lock:
                self._tasks[task_id].update(phase="failed", error_code=code,
                    model_calls=strict_json(canonical(getattr(model, "calls", [])[call_start:])))
                if self._tasks[task_id]["task"]:
                    self._tasks[task_id]["task"].update(status="failed", error_code=code, current_step="stopped")
        finally:
            with self._lock:
                self._approvals.pop(task_id, None)

    def _hold(self, task_id, request, decision, authority):
        status = authority.client.recheck_hold(request, decision)
        with self._lock:
            self._approvals[task_id] = {"request": request, "decision": decision, "authority": authority, "resolving": False}
            self._tasks[task_id]["approval"] = {"action_id": decision["action_id"], "receipt_id": decision["receipt_id"],
                "tool": request["tool"], "params_digest": digest(request["params"]), "params": request["params"],
                "expires_at": status["expires_at"], "resolution": None}

    def resolve_approval(self, task_id, body):
        fields(body, {"action_id", "approve"})
        if type(body["approve"]) is not bool:
            raise AgentError("approval_value_invalid")
        with self._lock:
            pending = self._approvals.get(task_id)
            if pending is None or pending["decision"]["action_id"] != body["action_id"] or pending["resolving"]:
                raise AgentError("approval_not_pending")
            pending["resolving"] = True
        try:
            result = pending["authority"].admin.request("/v1/hold/" + pending["decision"]["receipt_id"],
                {"approve": body["approve"], "actor_id": "paired-hackathon-operator"})
            with self._lock:
                self._tasks[task_id]["approval"]["resolution"] = result["action"]
            return result
        except Exception:
            with self._lock:
                pending["resolving"] = False
            raise

    def renew_pairing(self):
        with self._lock:
            if self.stopping.is_set():
                raise AgentError("service_stopping")
            self.pairing_code = secrets.token_urlsafe(18)
            self._pairing_expires = time.monotonic() + 300
            return {"pairing_code": self.pairing_code, "expires_in": 300}

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *_args):
                pass

            def _send(self, value, status=200, *, content_type="application/json", cookie=None):
                raw = value if isinstance(value, bytes) else canonical(value)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(raw)

            def _host(self):
                return self.headers.get("Host") == service.endpoint.removeprefix("http://")

            def _auth(self):
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
                if not supplied:
                    cookie = SimpleCookie()
                    try:
                        cookie.load(self.headers.get("Cookie", ""))
                        supplied = cookie["siq_demo"].value if "siq_demo" in cookie else ""
                    except Exception:  # noqa: BLE001 -- malformed browser cookie is unauthenticated
                        return False
                return hmac.compare_digest(supplied.encode(), service.token.encode())

            def do_GET(self):
                if not self._host():
                    self._send({"error": "host_rejected"}, 403)
                    return
                if self.path in ("/health", "/web/health"):
                    web = self.path == "/web/health"
                    ready = not service.stopping.is_set() and (not web or (service.web / "index.html").is_file())
                    self._send({"service": "siq-hackathon-web" if web else "siq-hackathon-agent",
                        "status": "ready" if ready else "unavailable", "provider": service.provider}, 200 if ready else 503)
                    return
                if self.path.startswith(API + "/"):
                    if not self._auth():
                        self._send({"error": "pairing_required"}, 401)
                        return
                    with service._lock:
                        if self.path == API + "/tasks":
                            value = {"tasks": list(service._tasks.values()), "provider": service.provider,
                                     "scenarios": SCENARIOS, "repository": service.repository, "scope": service.scope,
                                     "skills": [skill["name"] for skill in SkillRegistry.catalog()],
                                     "contact": "Alice", "recipient": service.fixtures.contacts["Alice"]}
                        elif self.path.removeprefix(API + "/tasks/") in service._tasks:
                            value = service._tasks[self.path.removeprefix(API + "/tasks/")]
                        else:
                            self._send({"error": "not_found"}, 404)
                            return
                        raw = canonical(value)
                    self._send(raw)
                    return
                # Reuse only the existing built local SPA and its assets. Never
                # expose state files, source files or filesystem path arguments.
                relative = "index.html" if self.path in ("/", "/demo") else self.path.lstrip("/")
                path = service.web / relative
                if (relative != "index.html" and not re.fullmatch(r"assets/[A-Za-z0-9_.-]+", relative)
                        or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(service.web.resolve())):
                    self._send({"error": "not_found"}, 404)
                    return
                self._send(path.read_bytes(), content_type=mimetypes.guess_type(str(path))[0] or "application/octet-stream")

            def do_POST(self):
                if (not self._host() or self.headers.get("Origin", service.endpoint) != service.endpoint
                        or self.headers.get("X-SIQ-Demo") != "1" or self.headers.get("Content-Type") != "application/json"):
                    self._send({"error": "request_origin_rejected"}, 403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                    if not 0 <= length <= 8192:
                        raise AgentError("request_size_invalid")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise AgentError("request_size_invalid")
                    body = strict_json(raw)
                    if self.path == API + "/pair":
                        fields(body, {"code"})
                        string(body["code"], maximum=128)
                        with service._lock:
                            valid = (service.pairing_code is not None and time.monotonic() < service._pairing_expires
                                     and hmac.compare_digest(body["code"].encode(), service.pairing_code.encode()))
                            if valid:
                                service.pairing_code = None
                        if not valid:
                            self._send({"error": "pairing_invalid"}, 401)
                            return
                        self._send({"status": "paired"}, cookie="siq_demo=" + service.token + "; HttpOnly; SameSite=Strict; Path=/hackathon/v1")
                        return
                    if not self._auth():
                        self._send({"error": "pairing_required"}, 401)
                        return
                    if self.path == API + "/tasks":
                        identity = service.submit(body, self.headers.get("Idempotency-Key", ""))
                        self._send({"id": identity}, 202)
                    elif self.path == API + "/pairing/renew":
                        fields(body, set())
                        self._send(service.renew_pairing())
                    elif match := re.fullmatch(API + r"/tasks/([a-f0-9]{32})/approval", self.path):
                        self._send(service.resolve_approval(match[1], body))
                    elif self.path == API + "/shutdown":
                        fields(body, set())
                        service.stopping.set()
                        self._send({"status": "stopping"})
                    else:
                        self._send({"error": "not_found"}, 404)
                except (AgentError, ValueError) as exc:
                    code = str(exc) if isinstance(exc, AgentError) else "request_invalid"
                    self._send({"error": code}, 409 if code in ("task_already_running", "request_id_conflict", "service_stopping") else 400)

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self._worker:
            self._worker.join()  # keep SIQ and observers alive until the worker exits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("demo", "test"), default="demo")
    parser.add_argument("--port", type=int, default=47621)
    parser.add_argument("--repository", default="fixture/secure-project")
    parser.add_argument("--scope", nargs="+", default=["README.md", "service.py"])
    parser.add_argument("--github-endpoint")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    if args.mode == "demo":
        from_environment(mode="demo")  # fail before creating state, no fallback
    with (LocalDaemon(args.binary, args.state_dir) as daemon,
          FixtureServices(repo / "demo/fixtures") as fixtures,
          DemoService(repo, daemon, fixtures, mode=args.mode, port=args.port, repository=args.repository,
                      scope=tuple(args.scope), github_endpoint=args.github_endpoint) as service):
            private = {"schema_version": "hackathon-service/v1", "pid": os.getpid(), "endpoint": service.endpoint,
                "process_start": Path(f"/proc/{os.getpid()}/stat").read_text().split(") ", 1)[1].split()[19],
                "daemon_pid": daemon._proc.pid,
                "daemon_process_start": Path(f"/proc/{daemon._proc.pid}/stat").read_text().split(") ", 1)[1].split()[19],
                "siq_endpoint": daemon.endpoint, "fixture_endpoint": fixtures.endpoint, "token": service.token,
                "mode": args.mode, "state_dir": str(daemon.directory)}
            path = daemon.directory / "service.json"
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
                output.write(canonical(private).decode())
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_args: service.stopping.set())
            print(canonical({"url": service.endpoint + "/demo", "pairing_code": service.pairing_code,
                             "provider": service.provider}).decode(), flush=True)
            service.stopping.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
