"""Decision-token client for the existing SIQ API, with no policy implementation."""

import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .contracts import AgentError, canonical, strict_json, string
from .models import NoRedirect


def observation_text(result):
    # Observe is a text-scanning API. JSON escaping alone hides quote-sensitive
    # patterns in source/MCP strings. Preserve the structure and literal leaves.
    parts = [canonical(result).decode()]
    size = len(parts[0])
    pending = [result]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            size += len(value.encode()) + 1
            if size > 64 << 10:
                raise AgentError("tool_observation_too_large")
            parts.append(value)
    if size > 64 << 10:
        raise AgentError("tool_observation_too_large")
    return "\n".join(parts)


class JsonAPI:
    def __init__(self, endpoint: str, token: str, *, timeout: float = 10):
        parts = urlsplit(endpoint)
        if (parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1", "::1")
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/")):
            raise AgentError("siq_endpoint_not_loopback")
        self.endpoint, self._token, self.timeout = endpoint.rstrip("/"), token, timeout
        self._http = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path: str, body=None, *, expected: int = 200):
        if not path.startswith("/v1/"):
            raise AgentError("siq_route_invalid")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self._token}
        try:
            with self._http.open(Request(self.endpoint + path, headers=headers,
                                        data=None if body is None else canonical(body)),
                                 timeout=self.timeout) as response:
                if response.status != expected:
                    raise AgentError("siq_status_invalid")
                result = strict_json(response.read((1 << 20) + 1))
                if not isinstance(result, dict):
                    raise AgentError("siq_response_invalid")
                return result
        except HTTPError as exc:
            # Only a bounded reason code can cross into the UI/logging boundary.
            with exc:
                try:
                    code = strict_json(exc.read(65537)).get("reason_code", "siq_http_error")
                except (AgentError, AttributeError):
                    code = "siq_http_error"
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
                code = "siq_http_error"
            raise AgentError(code) from None
        except (URLError, OSError, TimeoutError) as exc:
            raise AgentError("siq_unavailable") from exc


@dataclass(frozen=True)
class Identity:
    platform: str
    session_id: str
    agent_id: str
    task_id: str

    def request_fields(self):
        return {"platform": self.platform, "session_id": self.session_id, "agent_id": self.agent_id}


class SecurityClient:
    def __init__(self, api: JsonAPI, identity: Identity):
        self._api, self.identity = api, identity

    def decide(self, request: dict) -> dict:
        result = self._api.request("/v1/decide", request)
        if (result.get("action") not in ("allow", "deny", "hold")
                or result.get("effective_action") != result.get("action")
                or result.get("authority_status") not in ("valid", "invalid")):
            raise AgentError("siq_decision_invalid")
        for name in ("receipt_id", "action_id", "reason_code"):
            string(result.get(name), maximum=256)
        if result["action"] in ("allow", "hold") and result["authority_status"] != "valid":
            raise AgentError("siq_authority_invalid")
        return result

    def observe(self, request: dict, decision: dict, result: dict):
        return self._api.request("/v1/observe", {
            **request, "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "result": observation_text(result)})

    def recheck_hold(self, request: dict, decision: dict) -> dict:
        body = {k: request[k] for k in ("platform", "session_id", "agent_id", "tool", "tool_call_id", "params")}
        result = self._api.request("/v1/hold-status", {
            **body, "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"]})
        if (result.get("schema_version") != "hold-status/v1"
                or result.get("action_id") != decision["action_id"]
                or result.get("decision_receipt_id") != decision["receipt_id"]
                or result.get("status") not in ("pending", "approved", "denied", "expired", "consumed")):
            raise AgentError("siq_hold_response_invalid")
        for name in ("reason_code", "expires_at"):
            string(result.get(name), maximum=128)
        return result

    def report_source(self, report_id: str, content: dict, source_id: str):
        return self._api.request("/v1/provenance-reports", {
            **self.identity.request_fields(), "report_id": report_id,
            "source": {"type": "MCP", "source_id": source_id}, "content": content}, expected=201)

    def select_source(self, parent_id: str, pointer: str, content: dict):
        return self._api.request("/v1/provenance-select", {
            **self.identity.request_fields(), "parent_id": parent_id,
            "pointer": pointer, "content": content}, expected=201)


class EvidenceClient:
    """Read server-derived completion. Writing effects requires separate observers."""

    def __init__(self, api: JsonAPI):
        self._api = api

    def completion(self, task_id: str) -> dict:
        result = self._api.request("/v1/tasks/" + quote(task_id, safe="") + "/completion")
        if (result.get("schema_version") != "completion-status/v1" or result.get("task_id") != task_id
                or result.get("status") not in ("verified", "incomplete", "unknown", "conflicting")
                or not isinstance(result.get("requirements"), list)):
            raise AgentError("siq_completion_invalid")
        if result["status"] == "verified" and (not result["requirements"] or any(
                not isinstance(item, dict) or item.get("status") != "verified"
                or not isinstance(item.get("evidence_ids"), list) or not item["evidence_ids"]
                for item in result["requirements"])):
            raise AgentError("siq_completion_invalid")
        return result
