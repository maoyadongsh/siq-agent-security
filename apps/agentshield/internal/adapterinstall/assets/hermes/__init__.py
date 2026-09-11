# ruff: noqa: N999 -- platform plugin directory is loaded by path.
"""Hermes runtime adapter for siq-agent-security (dev-spec §4.2).

Thin by contract: this plugin only maps Hermes hooks to the local decision API.
It holds no rules, no policy and no signing key. Configuration (all optional)
comes from ``~/.hermes/plugins/siq-agent-security/config.json`` or environment:

    {"endpoint": "http://127.0.0.1:47611", "token_path": "<state>/token",
     "enforcement_mode": "block", "timeout_s": 5}

Fail-closed table (dev-spec §3.8.4): in ``block`` mode an unreachable /
timed-out / 401 / malformed decision service blocks the tool call; in
``audit_only`` / ``warn`` it allows and prints a warning to stderr.

``hold`` has no approval channel in Hermes and degrades to block with a pointer
to the siq-agent-security console (spec §4.2).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULTS = {
    "endpoint": "http://127.0.0.1:47611",
    "token_path": "",
    "enforcement_mode": "block",
    "timeout_s": 5,
    "platform": "hermes",
    "agent_id": "",
    "mcp_sources": {},
}


def _env(*keys: str) -> str:
    for k in keys:
        if v := (os.environ.get(k) or "").strip():
            return v
    return ""


def _state_dir() -> Path:
    if d := _env("SIQ_AGENT_SECURITY_STATE_DIR", "AGENTSHIELD_STATE_DIR"):
        return Path(d)
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "siq-agent-security"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "siq-agent-security"
    xdg = os.environ.get("XDG_STATE_HOME")
    return (Path(xdg) if xdg else home / ".local" / "state") / "siq-agent-security"


def _load_config() -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    path = Path(__file__).with_name("config.json")
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("invalid config")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("invalid config")
        cfg.update(value)
    except FileNotFoundError:
        pass  # Retain the supported legacy environment-only configuration.
    except (OSError, ValueError, TypeError):
        cfg["_config_error"] = True
    for key, envs in (
        ("endpoint", ("SIQ_AGENT_SECURITY_ENDPOINT", "AGENTSHIELD_ENDPOINT")),
        ("enforcement_mode", ("SIQ_AGENT_SECURITY_MODE", "AGENTSHIELD_MODE")),
        ("agent_id", ("SIQ_AGENT_SECURITY_AGENT_ID", "AGENTSHIELD_AGENT_ID")),
    ):
        if v := _env(*envs):
            if key == "agent_id" and "runtime_identity_id" in cfg:
                check = os.environ.get("SIQ_RUNTIME_CHECK_ID", "")
                if not (re.fullmatch(r"rc-[a-f0-9]{32}", check) and v == "rca-" + check[3:]):
                    continue
            cfg[key] = v
    if not cfg["token_path"]:
        cfg["token_path"] = str(_state_dir() / "token")
    return cfg


_CFG = _load_config()
_TOKEN: str | None = None


def _check_launch_present() -> bool:
    return any(os.environ.get(name) for name in (
        "SIQ_RUNTIME_CHECK_ID", "SIQ_RUNTIME_CHECK_INSTANCE", "SIQ_RUNTIME_CHECK_TOKEN"
    ))


def _managed() -> bool:
    return ("runtime_identity_id" in _CFG or bool(_CFG.get("_config_error"))
            or str(_CFG.get("agent_id", "")).startswith("hri-"))


def _token() -> str | None:
    global _TOKEN
    if _CFG.get("_config_error"):
        return None
    if _check_launch_present():
        check = os.environ.get("SIQ_RUNTIME_CHECK_ID", "")
        instance = os.environ.get("SIQ_RUNTIME_CHECK_INSTANCE", "")
        credential = os.environ.get("SIQ_RUNTIME_CHECK_TOKEN", "")
        if (re.fullmatch(r"rc-[a-f0-9]{32}", check)
                and re.fullmatch(r"hi-[a-f0-9]{32}", instance)
                and re.fullmatch(r"[a-f0-9]{64}", credential)
                and _CFG.get("agent_id") == "rca-" + check[3:]):
            return credential
        return None
    if _TOKEN is None:
        try:
            path = Path(_CFG["token_path"])
            if path.is_symlink():
                return None
            with path.open("r", encoding="ascii") as handle:
                _TOKEN = handle.read(513).strip()
            if len(_TOKEN) > 512:
                _TOKEN = ""
        except (OSError, UnicodeError, ValueError, TypeError):
            _TOKEN = ""
    if _managed() and not (
            re.fullmatch(r"ri-[a-f0-9]{32}\.[a-f0-9]{64}", _TOKEN or "")
            and _TOKEN.startswith(str(_CFG.get("runtime_identity_id", "")) + ".")):
        return None
    return _TOKEN or None


def _local_endpoint() -> str | None:
    try:
        value = str(_CFG["endpoint"])
        endpoint = urllib.parse.urlsplit(value)
        if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "::1", "localhost")
                or endpoint.username is not None or endpoint.password is not None
                or endpoint.query or endpoint.fragment or endpoint.path not in ("", "/")
                or endpoint.port is None or not 1 <= endpoint.port <= 65535):
            return None
        if endpoint.hostname == "localhost":
            return f"http://127.0.0.1:{endpoint.port}"  # Pin credential transport; no DNS re-resolution.
        return value.rstrip("/")
    except (ValueError, TypeError):
        return None


def _post(path: str, body: dict[str, Any], *, expected: int = 200) -> dict[str, Any] | None:
    tok = _token()
    endpoint = _local_endpoint()
    if not tok or not endpoint or not path.startswith("/v1/"):
        return None
    try:
        encoded = json.dumps(body, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None
    if len(encoded) > 1 << 20:
        return None
    req = urllib.request.Request(
        endpoint + path,
        data=encoded,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoCheckRedirect())
        with opener.open(req, timeout=float(_CFG["timeout_s"])) as resp:
            if resp.status != expected:
                return None
            raw = resp.read((1 << 20) + 1)
            if len(raw) > 1 << 20:
                return None
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, ValueError, TypeError, OSError):
        return None


def _fail_closed(reason: str, *, tool: str = "", session_id: str = "") -> dict[str, str] | None:
    mode = str(_CFG["enforcement_mode"])
    hard = mode == "block" or _managed() or _check_launch_present()
    outcome = "deny" if hard else "allow"
    _append_pending(
        {
            "schema": "pending_decision/v1",
            "recorded_at": _utcnow(),
            "platform": "hermes",
            "tool": tool,
            "session_id": session_id,
            "enforcement_mode": mode,
            "outcome": outcome,
            "reason": reason if reason.startswith("decision") else f"decision service unavailable ({reason})",
            "signed": False,
        }
    )
    if hard:
        return {
            "action": "block",
            "message": f"siq-agent-security: decision service unavailable ({reason}); blocked (fail-closed)",
        }
    print(
        f"siq-agent-security: decision service unavailable ({reason}); allowing in {mode} mode",
        file=sys.stderr,
    )
    return None


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # Python 3.10 compatibility


def _append_pending(rec: dict[str, Any]) -> None:
    try:
        root = Path(str(_CFG.get("token_path") or "")).expanduser().resolve().parent
        if root.name == "runtime-identity-secrets":
            root = root.parent
        dest_dir = root / "pending"
        dest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = dest_dir / "decisions.jsonl"
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


_CORRELATIONS: dict[tuple[str, str, str], tuple[float, str, str]] = {}
_CORRELATION_LOCK = threading.Lock()
_CORRELATION_TTL = 300
_CORRELATION_MAX = 2048


def _remember_decision(sid, tool, call_id, decision):
    if not call_id or not decision.get("action_id") or not decision.get("receipt_id"):
        return True  # server can resolve a unique legacy tuple
    now = time.monotonic()
    key = (sid, tool, call_id)
    with _CORRELATION_LOCK:
        for old in [k for k, v in _CORRELATIONS.items() if v[0] <= now]:
            del _CORRELATIONS[old]
        if key in _CORRELATIONS:
            _CORRELATIONS[key] = (now + _CORRELATION_TTL, "", "")
            return False
        if len(_CORRELATIONS) >= _CORRELATION_MAX:
            return False
        _CORRELATIONS[key] = (now + _CORRELATION_TTL, decision["action_id"], decision["receipt_id"])
    return True


def _decision_reference(sid, tool, call_id):
    with _CORRELATION_LOCK:
        value = _CORRELATIONS.get((sid, tool, call_id))
        if value and value[1] and value[0] > time.monotonic():
            return {"action_id": value[1], "decision_receipt_id": value[2]}
    return {}


class _NoCheckRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _attach_runtime_check(session_id: str) -> bool:
    """Map an explicit test launch to its native session; grant no authority here."""
    names = ("SIQ_RUNTIME_CHECK_ID", "SIQ_RUNTIME_CHECK_INSTANCE", "SIQ_RUNTIME_CHECK_TOKEN")
    check_id, instance, credential = (os.environ.get(name, "") for name in names)
    if not any((check_id, instance, credential)):
        return True
    agent = str(_CFG.get("agent_id", ""))
    if (
        not re.fullmatch(r"rc-[a-f0-9]{32}", check_id)
        or not re.fullmatch(r"hi-[a-f0-9]{32}", instance)
        or not re.fullmatch(r"[a-f0-9]{64}", credential)
        or not re.fullmatch(r"rca-[a-f0-9]{32}", agent)
        or not isinstance(session_id, str)
        or not session_id
        or len(session_id) > 256
    ):
        return False
    try:
        endpoint = _local_endpoint()
        if endpoint is None:
            return False
        body = {
            "schema_version": "local-runtime-check-attach/v1",
            "check_id": check_id,
            "instance_id": instance,
            "agent_id": agent,
            "session_id": session_id,
        }
        req = urllib.request.Request(
            endpoint + "/v1/runtime-checks/attach",
            data=json.dumps(body, allow_nan=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + credential},
        )
        # Never forward the launch credential to a redirect target or proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoCheckRedirect())
        with opener.open(req, timeout=5) as response:
            if response.status != 200:
                return False
            raw = response.read(4097)
            if len(raw) > 4096:
                return False
            value = json.loads(raw)
        return (
            isinstance(value, dict)
            and value.get("attached") is True
            and value
            == {
                "schema_version": "local-runtime-check-attached/v1",
                "check_id": check_id,
                "session_id": session_id,
                "attached": True,
            }
        )
    except (OSError, ValueError, TypeError, UnicodeError, urllib.error.URLError):
        return False


def _enroll_runtime_session(session_id: str) -> bool:
    if _check_launch_present():
        return True  # Separate short-lived check capability already attached.
    if not _managed():
        return True
    identity = _CFG.get("runtime_identity_id")
    agent = _CFG.get("agent_id")
    if (_CFG.get("_config_error") or not isinstance(identity, str)
            or not re.fullmatch(r"ri-[a-f0-9]{32}", identity)
            or not isinstance(agent, str) or not re.fullmatch(r"hri-[a-f0-9]{32}", agent)
            or not isinstance(session_id, str) or not session_id or len(session_id) > 256):
        return False
    result = _post("/v1/runtime-sessions", {
        "schema_version": "local-runtime-session-enroll/v1", "session_id": session_id,
    })
    if not isinstance(result, dict) or set(result) != {
            "schema_version", "identity_id", "platform", "agent_id", "session_id",
            "binding_id", "intent_id", "expires_at"}:
        return False
    return (result.get("schema_version") == "local-runtime-session-enrolled/v1"
            and result.get("identity_id") == identity and result.get("platform") == "hermes"
            and result.get("agent_id") == agent and result.get("session_id") == session_id
            and isinstance(result.get("binding_id"), str)
            and re.fullmatch(r"bind-[a-f0-9]{64}", result["binding_id"]) is not None
            and isinstance(result.get("intent_id"), str)
            and re.fullmatch(r"int-ri-[a-f0-9]{64}", result["intent_id"]) is not None
            and isinstance(result.get("expires_at"), str) and bool(result["expires_at"]))


def _pre_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    parameter_provenance: Any = None,
    context_assertion_id: Any = None,
    **_: Any,
):
    if not _attach_runtime_check(session_id):
        return {"action": "block", "message": "siq-agent-security: runtime check session could not be verified"}
    if not _enroll_runtime_session(session_id):
        return _fail_closed("instance session could not be verified", tool=tool_name, session_id=session_id)
    sid = session_id or task_id or "hermes-default"
    authority_refs = {}
    if parameter_provenance is not None:
        authority_refs["parameter_provenance"] = parameter_provenance
    if context_assertion_id is not None:
        authority_refs["context_assertion_id"] = context_assertion_id
    decision = _post(
        "/v1/decide",
        {
            **authority_refs,
            "platform": _CFG["platform"],
            "session_id": sid,
            "agent_id": _CFG["agent_id"] or os.environ.get("HERMES_PROFILE", "default"),
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "params": args if isinstance(args, dict) else {},
            "context": {"cwd": os.getcwd(), "host": "hermes"},
        },
    )
    if decision is None and authority_refs:
        return {"action": "block", "message": "siq-agent-security: authority references could not be verified"}
    if decision is None:
        return _fail_closed("no response", tool=tool_name, session_id=sid)
    action = decision.get("action")
    reason = str(decision.get("reason", ""))
    rid = decision.get("receipt_id", "")
    if action == "allow":
        if not _remember_decision(sid, tool_name, tool_call_id, decision):
            if authority_refs:
                return {"action": "block", "message": "siq-agent-security: authority decision correlation unavailable"}
            return _fail_closed("decision correlation conflict or capacity", tool=tool_name, session_id=sid)
        return None
    if action == "redact":
        # Hermes pre_tool_call cannot rewrite params; treat as block with guidance
        return {
            "action": "block",
            "message": f"siq-agent-security: parameters contain a secret literal; remove it and retry (receipt {rid})",
        }
    if action == "hold":
        return {
            "action": "block",
            "message": (
                f"siq-agent-security: {reason}. Approve in the console ({_CFG['endpoint']}) and retry (receipt {rid})"
            ),
        }
    if action == "deny":
        return {"action": "block", "message": f"siq-agent-security denied: {reason} (receipt {rid})"}
    if authority_refs:
        return {"action": "block", "message": "siq-agent-security: invalid authority decision response"}
    return _fail_closed("malformed decision", tool=tool_name, session_id=sid)


_PROVENANCE_REFS: dict[tuple[str, str, str], tuple[float, str]] = {}
_PROVENANCE_LOCK = threading.Lock()


def provenance_reference(session_id: str, tool_name: str, tool_call_id: str) -> str | None:
    """Return a previously captured low-trust reference; daemon still verifies it."""
    with _PROVENANCE_LOCK:
        value = _PROVENANCE_REFS.get((session_id, tool_name, tool_call_id))
        return value[1] if value and value[0] > time.monotonic() else None


def _capture_mcp_result(sid, tool, call_id, result):
    sources = _CFG.get("mcp_sources")
    identity = sources.get(tool) if isinstance(sources, dict) else None
    if not call_id or not isinstance(identity, str) or not identity or len(identity) > 4096:
        return
    agent = _CFG["agent_id"] or os.environ.get("HERMES_PROFILE", "default")

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    try:
        source_id = hashlib.sha256(canonical({"server": identity, "tool": tool})).hexdigest()
        report_id = hashlib.sha256(canonical([_CFG["platform"], sid, agent, tool, call_id])).hexdigest()
        body = {
            "report_id": report_id,
            "platform": _CFG["platform"],
            "session_id": sid,
            "agent_id": agent,
            "source": {"type": "MCP", "source_id": source_id, "trust": "untrusted"},
            "content": result,
        }
        if len(canonical(body)) > 60 * 1024:
            return  # reserve space for the HTTP JSON encoder; never truncate provenance content
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return
    with _PROVENANCE_LOCK:
        now = time.monotonic()
        for key in [key for key, value in _PROVENANCE_REFS.items() if value[0] <= now]:
            del _PROVENANCE_REFS[key]
        key = (sid, tool, call_id)
        # Repeated call IDs are not silently rebound to a different tool result.
        _PROVENANCE_REFS.pop(key, None)
        if len(_PROVENANCE_REFS) >= _CORRELATION_MAX:
            return
        report = _post("/v1/provenance-reports", body, expected=201)
        if report and isinstance(report.get("provenance_id"), str) and report["provenance_id"]:
            _PROVENANCE_REFS[key] = (now + _CORRELATION_TTL, report["provenance_id"])


def _post_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    _capture_mcp_result(session_id or task_id or "hermes-default", tool_name, tool_call_id, result)
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    _post(
        "/v1/observe",
        {
            "platform": _CFG["platform"],
            "session_id": session_id or task_id or "hermes-default",
            "agent_id": _CFG["agent_id"] or os.environ.get("HERMES_PROFILE", "default"),
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "params": args if isinstance(args, dict) else {},
            "result": text[: 64 * 1024],
            **_decision_reference(session_id or task_id or "hermes-default", tool_name, tool_call_id),
        },
    )


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
