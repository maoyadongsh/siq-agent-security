"""Operator-side assembly of existing SIQ authority. Never passed to the model."""

import os
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from .contracts import AgentError, UserTask, canonical, digest
from .security import Identity, JsonAPI, SecurityClient


class LocalDaemon:
    """A new isolated daemon, never an existing personal state directory."""

    def __init__(self, binary: Path, directory: Path):
        self.binary, self.directory = binary.resolve(), directory.resolve()
        self.state = self.directory / "siq-state"
        self._proc, self._log = None, None

    def __enter__(self):
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.state.mkdir(mode=0o700)  # fail rather than reuse or overwrite security state
        (self.state / "config.json").write_bytes(canonical({"intent_enforcement": "required", "enforcement_mode": "block"}))
        os.chmod(self.state / "config.json", 0o600)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT")}
        env.update(SIQ_AGENT_SECURITY_STATE_DIR=str(self.state), SIQ_AGENT_SECURITY_MODE="block")
        self._log = tempfile.TemporaryFile(mode="w+t")
        try:
            self._proc = subprocess.Popen([str(self.binary), "serve", "--port", str(port), "--mode", "block"],
                                          cwd=self.directory, env=env, stdout=self._log, stderr=self._log)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise AgentError("siq_daemon_exited")
                self._log.seek(0)
                found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self._log.read())
                if found:
                    paired = JsonAPI(self.endpoint, "").request("/v1/pair", {"code": found[1]})
                    self.admin = JsonAPI(self.endpoint, paired["session"])
                    self.decision = JsonAPI(self.endpoint, (self.state / "token").read_text().strip())
                    return self
                time.sleep(0.05)
            raise AgentError("siq_daemon_readiness_timeout")
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_args):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        if self._log is not None:
            self._log.close()


def deploy_application_grant(api: JsonAPI, repo: Path, agent_id: str, workspace: Path,
                             contacts_path: Path, hosts: list[str], *, approval_required=False):
    admissions = [api.request("/v1/admit", {"path": str(repo / "skills" / name)})["admission"]
                  for name in ("secure-research", "secure-report", "secure-delivery")]
    if any(a["verdict"] == "quarantine" for a in admissions):
        raise AgentError("application_skill_quarantined")
    result = api.request("/v1/grants", {"admission_id": admissions[-1]["admission_id"],
        "platform": "hermes", "subject_id": agent_id, "subject_type": "agent_instance", "redact_secrets": False})
    route = "/v1/grants/" + result["grant"]["grant_id"]

    def step(name, **body):
        nonlocal result
        result = api.request(route + "/" + name, {"expected_revision": result["state_revision"],
                             "actor_id": "isolated-hackathon-operator", **body})
        return result

    step("patch-desired", tools=["web_fetch", "read_file", "write_file", "send_message"] + (["verify_report"] if approval_required else []),
         filesystem={"read_only": [str(contacts_path.parent)], "read_write": [str(workspace)]},
         network=[{"endpoint": h, "effect": "allow"} for h in sorted(set(hosts))])
    for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
        if overlap["resolution"] == "unresolved":
            step("resolve-overlap", index=index)
    if approval_required:
        step("require-approval", schema_version="grant-tool-approval/v1", tools=["verify_report"])
    challenge = step("challenge")["challenge"]
    step("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
    step("deploy")
    return {"grant_id": result["grant"]["grant_id"], "status": result["grant"]["status"],
            "admission_ids": [a["admission_id"] for a in admissions]}


class TaskAuthority:
    def __init__(self, admin: JsonAPI, decision: JsonAPI, identity: Identity, task: UserTask,
                 *, github: str, mcp: str, contacts_path: Path, contacts: dict[str, str],
                 delivery_url: str, requirements: list[dict] | None = None, revision: str | None = None,
                 approval_required=False, confidential_path: Path | None = None):
        self.admin, self.identity, self.task = admin, identity, task
        self.client = SecurityClient(decision, identity)
        self.github, self.mcp, self.contacts_path, self.contacts = github.rstrip("/"), mcp, contacts_path, dict(contacts)
        self.delivery_url, self.revision = delivery_url, revision
        if confidential_path is not None and (requirements is None or confidential_path != contacts_path.parent / ".env"):
            raise AgentError("confidential_fixture_path_invalid")
        self.confidential_path = confidential_path
        self.read_only = requirements is None
        now = datetime.now(timezone.utc)
        self.issued = (now - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.expires = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.scope = {**identity.request_fields(), "task_id": identity.task_id}
        self.issuer = "issuer-" + identity.task_id
        self._references: dict[tuple[str, str], str] = {}
        self.intent = admin.request("/v1/intents", {
            "schema_version": "intent/v3", "intent_id": "intent-" + identity.task_id, "task_id": identity.task_id,
            "principal": {"type": "user", "id": "hackathon-operator"},
            "agent": {"id": identity.agent_id, "platform": identity.platform}, "purpose": task.prompt,
            "allowed_tools": (["web_fetch", "read_file", "write_file", "send_message"] + (["verify_report"] if approval_required else [])) if requirements else ["web_fetch"],
            "allowed_effects": (["network.request", "file.read", "file.write", "message.send"] + (["process.exec"] if approval_required else [])) if requirements else ["network.request"],
            # Existing resource constraints are conjunctive, including missing
            # domains. Across heterogeneous tools use V3's required per-action
            # provenance constraints plus the restricted issuer and Grant scope.
            "resource_constraints": [],
            "parameter_constraints": [], "provenance_constraints": [], "effect_requirements": requirements or [],
            "issued_at": self.issued, "valid_from": self.issued, "expires_at": self.expires,
            "authority": {"issuer": "local-admin", "revision": "1", "evidence_ids": []}}, expected=201)
        admin.request("/v1/intent-bindings", {**identity.request_fields(), "intent_id": self.intent["intent_id"]}, expected=201)
        admin.request("/v1/provenance-issuers", {"issuer_id": self.issuer, "local_key_ref": "local-state",
            "allowed_source_types": ["USER", "SYSTEM", "TRUSTED_DATABASE"], "max_trust_level": "trusted",
            "scope": self.scope, "expires_at": self.expires}, expected=201)

    def _reference(self, value: str, source: str):
        key = (source, value)
        if key not in self._references:
            reference = "source-" + uuid4().hex
            assertion = self.admin.request("/v1/provenance-assertions", {
                "schema_version": "provenance-assertion/v1", "provenance_id": reference,
                "source": {"type": source, "source_id": "operator-task" if source != "TRUSTED_DATABASE" else "contact-directory",
                           "trust": "trusted"}, "scope": self.scope, "content_digest": digest(value),
                "parents": [], "derivation": "direct", "issued_at": self.issued, "expires_at": self.expires,
                "issuer": self.issuer}, expected=201)
            self._references[key] = assertion["provenance_id"]
        return self._references[key]

    def directory_result(self, actual: dict):
        if actual != self.contacts:
            raise AgentError("trusted_directory_changed")
        value = self.contacts[self.task.contact]
        return {"contacts": {self.task.contact: {
            "recipient": value, "provenance_id": self._reference(value, "TRUSTED_DATABASE")}}}

    def describe_provenance(self, request):
        entries = []
        for binding in request.get("parameter_provenance", []):
            for reference in binding["provenance_refs"]:
                entry = {"parameter_path": binding["parameter_path"], "provenance_id": reference,
                         "read_at": datetime.now(timezone.utc).isoformat()}
                if binding["parameter_path"] == "/recipient":
                    entry["matches_operator_contact"] = request["params"].get("recipient") == self.contacts[self.task.contact]
                try:
                    assertion = self.admin.request("/v1/provenance-resolve", {"provenance_id": reference, "scope": self.scope})
                    if assertion.get("provenance_id") != reference or assertion.get("scope") != self.scope:
                        raise AgentError("provenance_readback_mismatch")
                    entry.update(status="resolved", assertion=assertion)
                except AgentError as exc:
                    entry.update(status="unavailable", error_code=str(exc))
                entries.append(entry)
        return entries

    def approved_url(self, value):
        root = self.github + "/repos/" + quote(self.task.repository, safe="/")
        if value == root + "/commits/HEAD" or (not self.read_only and value in (self.mcp, self.delivery_url)):
            return True
        for path in self.task.scope:
            prefix = root + "/contents/" + quote(path, safe="/") + "?ref="
            if value.startswith(prefix):
                suffix = value[len(prefix):]
                return bool(re.fullmatch(r"[0-9a-f]{40}", suffix)) and (self.revision is None or suffix == self.revision)
        return False

    def prepare(self, request: dict) -> dict:
        bindings = list(request["parameter_provenance"])
        params = request["params"]
        # Only source values derived from the operator's fixed task can be signed.
        # Arbitrary model paths/URLs are forwarded without a manufactured trusted ref.
        for path, source, permitted in (
            ("/url", "SYSTEM", self.approved_url(params.get("url", ""))),
            ("/path", "USER", params.get("path") in (self.task.report_path, str(self.contacts_path))
             or (self.confidential_path is not None and params.get("path") == str(self.confidential_path))),
        ):
            key = path[1:]
            if permitted and isinstance(params.get(key), str) and not any(b["parameter_path"] == path for b in bindings):
                bindings.append({"parameter_path": path, "provenance_refs": [self._reference(params[key], source)]})
        assertion = self.admin.request("/v1/context-assertions", {
            "schema_version": "context-assertion/v1", "assertion_id": "ctx-" + uuid4().hex,
            "issuer_id": "local-admin", "subject": self.identity.request_fields(), "task_id": self.identity.task_id,
            "claims": {"workspace_root": str(Path(self.task.report_path).parent)}, "issued_at": self.issued,
            "expires_at": self.expires, "request_binding": digest({**self.identity.request_fields(),
                "task_id": self.identity.task_id, "tool": request["tool"], "tool_call_id": request["tool_call_id"], "params": params})}, expected=201)
        return {"context_assertion_id": assertion["assertion_id"], "parameter_provenance": bindings}
