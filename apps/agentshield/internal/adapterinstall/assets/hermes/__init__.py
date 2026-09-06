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

import json
import os
import sys
import urllib.error
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
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for key, envs in (
        ("endpoint", ("SIQ_AGENT_SECURITY_ENDPOINT", "AGENTSHIELD_ENDPOINT")),
        ("enforcement_mode", ("SIQ_AGENT_SECURITY_MODE", "AGENTSHIELD_MODE")),
        ("agent_id", ("SIQ_AGENT_SECURITY_AGENT_ID", "AGENTSHIELD_AGENT_ID")),
    ):
        if v := _env(*envs):
            cfg[key] = v
    if not cfg["token_path"]:
        cfg["token_path"] = str(_state_dir() / "token")
    return cfg


_CFG = _load_config()
_TOKEN: str | None = None


def _token() -> str | None:
    global _TOKEN
    if _TOKEN is None:
        try:
            _TOKEN = Path(_CFG["token_path"]).read_text(encoding="ascii").strip()
        except OSError:
            _TOKEN = ""
    return _TOKEN or None


def _post(path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    tok = _token()
    if not tok:
        return None
    req = urllib.request.Request(
        _CFG["endpoint"].rstrip("/") + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(_CFG["timeout_s"])) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _fail_closed(reason: str, *, tool: str = "", session_id: str = "") -> dict[str, str] | None:
    mode = str(_CFG["enforcement_mode"])
    outcome = "deny" if mode == "block" else "allow"
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
    if mode == "block":
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

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _append_pending(rec: dict[str, Any]) -> None:
    try:
        root = Path(str(_CFG.get("token_path") or "")).expanduser().resolve().parent
        if not root:
            root = _state_dir()
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


def _pre_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
):
    sid = session_id or task_id or "hermes-default"
    decision = _post(
        "/v1/decide",
        {
            "platform": _CFG["platform"],
            "session_id": sid,
            "agent_id": _CFG["agent_id"] or os.environ.get("HERMES_PROFILE", "default"),
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "params": args if isinstance(args, dict) else {},
            "context": {"cwd": os.getcwd(), "host": "hermes"},
        },
    )
    if decision is None:
        return _fail_closed("no response", tool=tool_name, session_id=sid)
    action = decision.get("action")
    reason = str(decision.get("reason", ""))
    rid = decision.get("receipt_id", "")
    if action == "allow":
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
            "message": f"siq-agent-security: {reason}. Approve in the console ({_CFG['endpoint']}) and retry (receipt {rid})",
        }
    if action == "deny":
        return {"action": "block", "message": f"siq-agent-security denied: {reason} (receipt {rid})"}
    return _fail_closed("malformed decision", tool=tool_name, session_id=sid)


def _post_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any,
) -> None:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    _post(
        "/v1/observe",
        {
            "platform": _CFG["platform"],
            "session_id": session_id or task_id or "hermes-default",
            "agent_id": _CFG["agent_id"] or os.environ.get("HERMES_PROFILE", "default"),
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "params": {},
            "result": text[: 64 * 1024],
        },
    )


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
