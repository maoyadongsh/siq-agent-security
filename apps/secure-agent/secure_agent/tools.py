"""Concrete trusted adapters; the closed gateway calls these only after SIQ."""

import base64
import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .authority import TaskAuthority
from .confidential import NOTE
from .contracts import AgentError, canonical, digest, strict_json
from .fixtures import FixtureServices
from .models import NoRedirect
from .security import JsonAPI


class ToolAdapters:
    def __init__(self, authority: TaskAuthority, fixtures: FixtureServices, *,
                 effect_mode: str = "normal", expected_report: str | None = None):
        if effect_mode not in ("normal", "fake-success", "conflicting"):
            raise AgentError("effect_mode_invalid")
        self.authority, self.fixtures = authority, fixtures
        self.effect_mode, self.expected_report = effect_mode, expected_report
        self.gateway = None
        self._http = build_opener(ProxyHandler({}), NoRedirect())

    def executors(self):
        return {"web_fetch": self.fetch, "read_file": self.read, "write_file": self.write,
                "send_message": self.send, "verify_report": self.verify_report}

    def verify_report(self, params, _decision):
        if set(params) != {"path"} or params["path"] != self.authority.task.report_path or self.expected_report is None:
            raise AgentError("tool_verification_path_invalid")
        path = Path(params["path"])
        if path.is_symlink() or path.parent.resolve() != path.parent:
            raise AgentError("tool_report_symlink_rejected")
        # Fixed program and interpreter; no shell, model code, environment or
        # imports from the report directory. Only the file path is an argument.
        program = ("import hashlib,os,sys; "
                   "f=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW); "
                   "data=os.read(f,262145); os.close(f); "
                   "sys.exit(2) if len(data)>262144 else None; "
                   "print(hashlib.sha256(data).hexdigest())")
        process = subprocess.Popen([sys.executable, "-I", "-S", "-c", program, str(path)],
            cwd=path.parent, env={}, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, _stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise AgentError("tool_verification_timeout") from exc
        expected = hashlib.sha256(self.expected_report.encode()).hexdigest()
        if process.returncode != 0 or stdout != (expected + "\n").encode():
            raise AgentError("tool_verification_failed")
        return {"success": True, "digest": expected, "process_id": process.pid, "exit_code": process.returncode}

    def fetch(self, params, decision):
        endpoint = params["url"]
        if not self.authority.approved_url(endpoint):
            raise AgentError("tool_url_outside_task")
        method = params.get("method", "GET")
        if method not in ("GET", "POST"):
            raise AgentError("tool_http_method_invalid")
        headers = {"Content-Type": "application/json", "User-Agent": "siq-secure-agent"}
        revision_request = endpoint.endswith("/commits/HEAD") and method == "GET"
        if revision_request:
            # GitHub's SHA media type retrieves only the needed revision, without
            # collecting irrelevant commit author email metadata.
            headers["Accept"] = "application/vnd.github.sha"
        if endpoint.startswith(self.fixtures.endpoint + "/"):
            headers.update(self.fixtures.headers())
        if endpoint == self.authority.delivery_url:
            if self.effect_mode == "fake-success":
                return {"status": 200, "json": {"success": True}}
            headers["X-SIQ-Action-ID"] = decision["action_id"]
        data = canonical(params["json"]) if "json" in params else None
        if endpoint == self.authority.delivery_url and self.effect_mode == "conflicting":
            data = canonical({"body": "Substituted report bytes from the controlled fault fixture."})
        try:
            with self._http.open(Request(endpoint, data=data, headers=headers, method=method), timeout=10) as response:
                raw = response.read((48 << 10) + 1)
                if len(raw) > 48 << 10:
                    raise AgentError("tool_http_response_too_large")
                if revision_request:
                    if not re.fullmatch(rb"[0-9a-f]{40}\n?", raw):
                        raise AgentError("github_revision_invalid")
                    return {"status": response.status, "revision": raw.decode().strip()}
                result = {"status": response.status, "json": strict_json(raw) if raw else {}}
        except (URLError, OSError, TimeoutError) as exc:
            raise AgentError("tool_http_failed") from exc
        entry = result["json"]
        if isinstance(entry, dict) and entry.get("type") == "file" and entry.get("encoding") == "base64":
            try:
                # Feed decoded text to SIQ's Observe scan; base64 must not conceal
                # a secret or PII in a GitHub contents response.
                result["decoded_text"] = base64.b64decode("".join(entry["content"].split()), validate=True).decode()
            except (KeyError, ValueError, UnicodeError, AttributeError) as exc:
                raise AgentError("github_content_invalid") from exc
        return result

    def read(self, params, _decision):
        path = Path(params["path"])
        if self.authority.confidential_path is not None and path == self.authority.confidential_path:
            if set(params) != {"path"} or path.parent.resolve() != path.parent:
                raise AgentError("tool_confidential_fixture_invalid")
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise AgentError("tool_confidential_fixture_invalid")
                    content = stream.read(len(NOTE) + 1)
            except OSError:
                raise AgentError("tool_confidential_fixture_invalid") from None
            if content != NOTE:
                raise AgentError("tool_confidential_fixture_invalid")
            return {"content": content.decode()}
        if path != self.authority.contacts_path or path.is_symlink() or not path.is_file():
            raise AgentError("tool_directory_path_invalid")
        return self.authority.directory_result(strict_json(path.read_bytes()))

    def write(self, params, _decision):
        path = Path(params["path"])
        if str(path) != self.authority.task.report_path or params.get("content") != self.expected_report:
            raise AgentError("tool_report_commitment_mismatch")
        if path.parent.resolve() != path.parent or path.is_symlink():
            raise AgentError("tool_report_symlink_rejected")
        # Exclusive creation gives each run a new artifact; never overwrite a
        # pre-existing file or follow a symlink supplied by another process.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(params["content"].encode())
            stream.flush()
            os.fsync(stream.fileno())
        return {"success": True, "digest": hashlib.sha256(params["content"].encode()).hexdigest()}

    def send(self, params, _decision):
        if self.gateway is None or params.get("body") != self.expected_report:
            raise AgentError("tool_message_commitment_mismatch")
        # The separately authorized HTTP route is an opaque mailbox identifier.
        # Payload is still plaintext in SIQ parameters, not an unscanned digest.
        route = self.fixtures.endpoint + "/messages/" + digest(params["recipient"])
        sent = self.gateway.call("web_fetch", {"url": route, "method": "POST", "json": {"body": params["body"]}})
        return {"success": sent.value.get("json", {}).get("success") is True,
                "transport_action_id": sent.decision["action_id"]}

    def observation(self, request, decision, result):
        """Explicit projection for two routing-only adapters, not generic redaction.

        Full routing values are bound to signed provenance before projection and
        remain in the eventual message decision. Other text and decoded GitHub
        content are scanned unchanged. This does not claim universal taint flow.
        """
        observed = strict_json(canonical(result))
        if request["tool"] == "read_file" and request["params"].get("path") == str(self.authority.contacts_path):
            for entry in observed["contacts"].values():
                entry["recipient_digest"] = digest(entry.pop("recipient"))
            observed["routing_source"] = "TRUSTED_DATABASE"
            observed["raw_result_digest"] = digest(result)
        elif request["tool"] == "web_fetch" and request["params"].get("url") == self.authority.mcp:
            message = observed.get("json", {})
            body = message.get("result", {}) if isinstance(message, dict) else {}
            content = body.get("structuredContent") if isinstance(body, dict) else None
            if isinstance(content, dict) and isinstance(content.get("recipient"), str):
                original = result["json"]["result"]
                parent = self.authority.client.report_source(decision["action_id"], original, self.authority.mcp)
                child = self.authority.client.select_source(parent["provenance_id"], "/structuredContent/recipient", original)
                content["recipient_digest"] = digest(content.pop("recipient"))
                observed["routing_provenance_id"] = child["provenance_id"]
                observed["raw_result_digest"] = digest(result)
        return observed


class EffectObservers:
    def __init__(self, authority: TaskAuthority, fixtures: FixtureServices, report: str):
        self.authority, self.fixtures, self.report = authority, fixtures, report
        self._clients = {}
        for kind, source in (("file", {"type": "host_observer", "source_id": "hackathon-file", "independence": "host_independent"}),
                             ("network", {"type": "test_oracle", "source_id": "hackathon-sink", "independence": "external_independent"})):
            token = authority.admin.request("/v1/effect-observers", {"source": source,
                "scope": authority.scope, "expires_in": 3600}, expected=201)["token"]
            self._clients[kind] = JsonAPI(authority.admin.endpoint, token)

    def begin(self, request, decision):
        if request["tool"] != "write_file":
            return None
        observation_id = "file-" + decision["action_id"]
        self._clients["file"].request("/v1/file-observations", {"observation_id": observation_id,
            "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"],
            "path": request["params"]["path"], "expected_digest": hashlib.sha256(self.report.encode()).hexdigest(),
            "max_bytes": 256 << 10}, expected=201)
        return observation_id

    def finish(self, handle, request, decision):
        if handle is not None:
            return self._clients["file"].request("/v1/file-observations/" + handle + "/finish",
                {"path": request["params"]["path"]}, expected=201)
        if request["tool"] != "web_fetch" or request["params"].get("url") != self.authority.delivery_url:
            return None
        event = self.fixtures.event(decision["action_id"])
        if event is None:
            return None  # no fabricated absence evidence; Completion stays incomplete
        endpoint = urlsplit(self.authority.delivery_url)
        return self._clients["network"].request("/v1/network-observations", {
            "observation_id": "network-" + decision["action_id"], "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "observation": {
                "requested_scheme": endpoint.scheme, "requested_host": endpoint.hostname,
                "requested_port": str(endpoint.port), "received": event}}, expected=201)
