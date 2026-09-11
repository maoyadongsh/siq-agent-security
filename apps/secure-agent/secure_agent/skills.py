"""Three built-in workflows. All file/network/message access uses ToolGateway."""

import base64
import hashlib
import re
from typing import Protocol
from urllib.parse import quote

from .contracts import (
    SKILL_REQUIRES,
    AgentError,
    ContactCandidate,
    DataSensitivity,
    DeliveryInput,
    DeliveryResult,
    ReportArtifact,
    ReportInput,
    ResearchInput,
    ResearchResult,
    SkillCall,
    Source,
    canonical,
    fields,
    string,
)
from .gateway import ToolGateway
from .models import ModelProvider, proposal_schema


class SourceRecorder(Protocol):
    def report_source(self, report_id: str, content: dict, source_id: str) -> dict: ...
    def select_source(self, parent_id: str, pointer: str, content: dict) -> dict: ...


class SkillRegistry:
    """Closed built-in registry; never imports/executes code from SKILL.md."""

    @staticmethod
    def catalog() -> list[dict]:
        catalog = [
            {"name": "secure-research", "description": "Review selected GitHub files at the latest commit.",
             "input": {"repository": "owner/repo", "question": "string", "scope": ["relative file path"]},
             "output": "ResearchResult"},
            {"name": "secure-report", "description": "Write a source-linked security review report.",
             "input": {"path": "absolute report path from task"}, "output": "ReportArtifact"},
            {"name": "secure-delivery", "description": "Deliver with recipient provenance and SIQ authorization.",
             "input": {"contact": "contact name from task"}, "output": "DeliveryResult"},
        ]
        inputs = proposal_schema("model-task-plan-v2")["properties"]["skills"]["prefixItems"]
        allowed_tools = {"secure-research": ["web_fetch", "read_file"],
                         "secure-report": ["write_file", "verify_report"],
                         "secure-delivery": ["read_file", "web_fetch", "send_message"]}
        for entry, schema in zip(catalog, inputs):
            entry.update(requires=list(SKILL_REQUIRES[entry["name"]]),
                         input_schema=schema["properties"]["input"],
                         output_schema={"type": "object", "title": entry["output"]},
                         allowed_tools=allowed_tools[entry["name"]],
                         security_requirements=["signed_intent", "trusted_context", "parameter_provenance", "ToolGateway"])
        return catalog


def render_report(path: str, research: ResearchResult) -> ReportArtifact:
    content = "# Security review\n\n" + research.summary + "\n\n## Findings\n\n"
    content += "\n".join("- " + finding for finding in research.findings)
    content += "\n\n## Sources\n\n" + "\n".join(
        f"- {s.path} @ {s.revision} (SHA256 {s.digest})" for s in research.sources)
    content += "\n\nScope: selected files at the recorded revision; not a complete security certification.\n"
    return ReportArtifact(path, hashlib.sha256(content.encode()).hexdigest(), research.summary, content)


class SkillRunner:
    def __init__(self, gateway: ToolGateway, model: ModelProvider, sources: SourceRecorder,
                 *, github_endpoint: str, contacts_path: str, mcp_endpoint: str, verify_report=False,
                 confidential_path: str | None = None, sensitivity=DataSensitivity.PUBLIC):
        self._gateway, self._model, self._sources = gateway, model, sources
        self._github = github_endpoint.rstrip("/")
        self._contacts, self._mcp = contacts_path, mcp_endpoint
        self._verify_report = verify_report
        self._confidential_path = confidential_path
        self._sensitivity = DataSensitivity.parse(sensitivity)
        self._research: ResearchResult | None = None
        self._report: ReportArtifact | None = None

    def run(self, call: SkillCall):
        if call.name == "secure-research" and isinstance(call.input, ResearchInput):
            self._research = self.research(call.input)
            return self._research
        if call.name == "secure-report" and isinstance(call.input, ReportInput):
            if self._research is None:
                raise AgentError("skill_research_required")
            self._report = self.report(call.input, self._research)
            return self._report
        if call.name == "secure-delivery" and isinstance(call.input, DeliveryInput):
            if self._report is None:
                raise AgentError("skill_report_required")
            return self.delivery(call.input, self._report)
        raise AgentError("skill_unregistered")

    def _fetch(self, url: str, **extra):
        return self._gateway.call("web_fetch", {"url": url, **extra})

    def research(self, task: ResearchInput) -> ResearchResult:
        if self._confidential_path is not None:
            # Operator-only fixture: no model path or content is accepted here.
            # Observe retains session state; the confidential bytes stay local.
            # Credential paths are never grantable (ADR-025): a boundary denial
            # stops the flow here like any other denial; no human-readable
            # reason string is used to continue execution.
            self._gateway.call("read_file", {"path": self._confidential_path})
        # URL encoding prevents the candidate repository/path from changing the
        # endpoint syntax. Actual scope authorization is still performed by SIQ.
        repository = quote(task.repository, safe="/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", task.repository):
            raise AgentError("repository_invalid")
        root = self._github + "/repos/" + repository
        result = self._fetch(root + "/commits/HEAD").value
        revision = result.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise AgentError("github_revision_invalid")
        sources = []
        for path in task.scope:
            url = root + "/contents/" + quote(path, safe="/") + "?ref=" + revision
            entry = self._fetch(url).value.get("json")
            if not isinstance(entry, dict) or entry.get("type") != "file" or entry.get("encoding") != "base64":
                raise AgentError("github_file_invalid")
            try:
                raw = base64.b64decode("".join(entry["content"].split()), validate=True)
                if len(raw) > 32 << 10:
                    raise AgentError("github_file_too_large")
                content = raw.decode("utf-8")
            except (KeyError, TypeError, ValueError, UnicodeError) as exc:
                raise AgentError("github_content_invalid") from exc
            sources.append(Source(path, revision, hashlib.sha256(raw).hexdigest(), content, self._sensitivity))
        return self._model.research(task.question, tuple(sources))

    def report(self, task: ReportInput, research: ResearchResult) -> ReportArtifact:
        artifact = render_report(task.path, research)
        self._gateway.call("write_file", {"path": artifact.path, "content": artifact.content})
        if self._verify_report:
            self._gateway.call("verify_report", {"path": artifact.path})
        # This is an artifact proposal and tool report, not an effect-verification claim.
        return artifact

    def delivery(self, task: DeliveryInput, artifact: ReportArtifact) -> DeliveryResult:
        directory = self._gateway.call("read_file", {"path": self._contacts}).value
        # A trusted directory adapter provides its independently issued references.
        # The model never supplies or gets to replace these references.
        entries = directory.get("contacts", {})
        if not isinstance(entries, dict) or task.contact not in entries:
            raise AgentError("contact_not_found")
        entry = entries[task.contact]
        fields(entry, {"recipient", "provenance_id"})
        trusted = ContactCandidate(string(entry["recipient"], maximum=320),
                                   string(entry["provenance_id"], maximum=128), "TRUSTED_DATABASE")
        initialized = self._fetch(self._mcp, method="POST", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "siq-secure-agent", "version": "0.1.0"}}}).value.get("json")
        if (not isinstance(initialized, dict) or initialized.get("id") != 1
                or initialized.get("result", {}).get("protocolVersion") != "2025-06-18"):
            raise AgentError("mcp_initialize_invalid")
        self._fetch(self._mcp, method="POST", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        lookup = self._fetch(self._mcp, method="POST", json={"jsonrpc": "2.0", "id": 2,
            "method": "tools/call", "params": {"name": "lookup_contact", "arguments": {"name": task.contact}}})
        message = lookup.value.get("json")
        if not isinstance(message, dict) or message.get("id") != 2 or message.get("jsonrpc") != "2.0":
            raise AgentError("mcp_response_invalid")
        result = message.get("result")
        if not isinstance(result, dict) or result.get("isError") is not False:
            raise AgentError("mcp_tool_failed")
        value = result.get("structuredContent")
        if not isinstance(value, dict):
            raise AgentError("mcp_content_invalid")
        recipient = string(value.get("recipient"), maximum=320)
        recorded = self._sources.report_source(lookup.decision["action_id"], result, self._mcp)
        selected = self._sources.select_source(recorded["provenance_id"], "/structuredContent/recipient", result)
        candidates = (trusted, ContactCandidate(recipient, selected["provenance_id"], "MCP"))
        choice = self._model.recipient(task.contact, candidates, canonical(result).decode())
        if choice not in candidates:
            raise AgentError("recipient_candidate_invalid")
        sent = self._gateway.call("send_message", {"recipient": choice.recipient, "body": artifact.content},
            provenance=({"parameter_path": "/recipient", "provenance_refs": [choice.provenance_id]},))
        return DeliveryResult(choice.recipient, sent.decision["action_id"], sent.value.get("success") is True)
