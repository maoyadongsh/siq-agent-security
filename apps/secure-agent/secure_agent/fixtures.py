"""Deterministic loopback servers. Receiver events are collected at the sink."""

import base64
import hashlib
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .contracts import AgentError, canonical, digest, strict_json


class FixtureServices:
    def __init__(self, fixtures: Path, *, mcp_mode: str = "benign"):
        if mcp_mode not in ("benign", "attack", "same-value"):
            raise AgentError("fixture_mcp_mode_invalid")
        self.repository = strict_json((fixtures / "github/repository.json").read_bytes())
        self.contacts = strict_json((fixtures / "contacts/directory.json").read_bytes())
        self.mcp = strict_json((fixtures / "mcp" / (mcp_mode + ".json")).read_bytes())
        self._key = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._messages: list[dict] = []
        self._events: dict[str, dict] = {}
        self._initialized = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _authorized(self):
                return (self.headers.get("Host") == f"127.0.0.1:{service.server.server_port}"
                        and secrets.compare_digest(self.headers.get("X-SIQ-Fixture-Token", ""), service._key))

            def _json(self, value, status=200):
                raw = canonical(value)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health" and self.headers.get("Host") == f"127.0.0.1:{service.server.server_port}":
                    self._json({"service": "siq-hackathon-fixtures", "status": "ready"})
                    return
                if not self._authorized():
                    self.send_error(403)
                    return
                path = urlsplit(self.path)
                if path.path == "/messages":
                    self._json({"messages": service.messages()})
                    return
                root = "/github/repos/" + service.repository["repository"]
                if self.path == root + "/commits/HEAD" and self.headers.get("Accept") == "application/vnd.github.sha":
                    raw = service.repository["revision"].encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.github.sha")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if path.path.startswith(root + "/contents/") and parse_qs(path.query) == {"ref": [service.repository["revision"]]}:
                    name = unquote(path.path[len(root + "/contents/"):])
                    text = service.repository["files"].get(name)
                    if text is not None:
                        self._json({"type": "file", "encoding": "base64",
                                    "content": base64.b64encode(text.encode()).decode()})
                        return
                self.send_error(404)

            def do_POST(self):
                if not self._authorized():
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                    if not 0 <= size <= 256 << 10:
                        raise ValueError
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError
                    body = strict_json(raw)
                except (ValueError, AgentError):
                    self.send_error(400)
                    return
                if self.path == "/mcp":
                    method = body.get("method") if isinstance(body, dict) else None
                    if method == "initialize":
                        self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": {
                            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "siq-controlled-contact", "version": "1"}}})
                        return
                    if method == "notifications/initialized":
                        service._initialized = True
                        self._json({}, 202)
                        return
                    if method == "tools/call" and service._initialized and body.get("params") == {
                            "name": "lookup_contact", "arguments": {"name": "Alice"}}:
                        self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": service.mcp})
                        return
                    self.send_error(400)
                    return
                if self.path.startswith("/messages/"):
                    route = self.path.removeprefix("/messages/")
                    recipient = next((v for v in service.contacts.values() if digest(v) == route), None)
                    action = self.headers.get("X-SIQ-Action-ID")
                    if recipient is None or not action or not isinstance(body, dict) or set(body) != {"body"} or not isinstance(body["body"], str):
                        self.send_error(400)
                        return
                    received = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    event = {"scheme": "http", "host": "127.0.0.1", "port": str(service.server.server_port),
                        "resolved_target": f"127.0.0.1:{service.server.server_port}",
                        "request_id": "hackathon-sink-" + hashlib.sha256(action.encode()).hexdigest()[:24],
                        "request_digest": digest({"method": "POST", "uri": self.path,
                                                  "body_digest": hashlib.sha256(raw).hexdigest()}),
                        "received_at": received}
                    with service._lock:
                        if action in service._events:
                            self.send_error(409)
                            return
                        service._events[action] = event
                        service._messages.append({"recipient": recipient, "action_id": action,
                            "payload_digest": hashlib.sha256(body["body"].encode()).hexdigest(),
                            "received_at": received})
                    self._json({"success": True}, 201)
                    return
                self.send_error(404)

        return Handler

    def headers(self):
        return {"X-SIQ-Fixture-Token": self._key}

    def messages(self):
        with self._lock:
            return strict_json(canonical(self._messages))

    def event(self, action_id):
        with self._lock:
            event = self._events.get(action_id)
            return strict_json(canonical(event)) if event else None

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
