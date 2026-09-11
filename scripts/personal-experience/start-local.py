#!/usr/bin/env python3
"""Start or reuse a local development build after verifying its health protocol.

Only run a binary you built or independently verified. This tool neither
downloads binaries nor changes the signed Skill package. Production installer
integration is tracked separately in UX-014.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def healthy(binary, port, env):
    try:
        result = subprocess.run(
            [str(binary), "status", "--port", str(port)],
            env=env,
            capture_output=True,
            text=True,
            timeout=7,
            check=False,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            return False
        return (
            data.get("schema_version") == "local-service-health/v1"
            and data.get("product") == "siq-agent-security"
            and data.get("status") == "ready"
            and data.get("local_mode") is True
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def ensure_started(binary, state_dir, port, timeout=15):
    env = {**os.environ, "SIQ_AGENT_SECURITY_STATE_DIR": str(state_dir), "AGENTSHIELD_STATE_DIR": str(state_dir)}
    endpoint = f"http://127.0.0.1:{port}"
    if healthy(binary, port, env):
        return {"status": "ready", "reused": True, "endpoint": endpoint}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            raise RuntimeError("端口被其他服务或旧版 SIQ 占用；请检查端口或升级对应服务。未终止任何进程。")
    except ConnectionRefusedError:
        pass  # An empty port may be used. Other network errors are not proof it is free.
    except OSError as exc:
        raise RuntimeError("无法确认本地端口可用；请检查网络设置后重试。") from exc

    options = (
        {"start_new_session": True}
        if os.name != "nt"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    )
    process = subprocess.Popen(
        [str(binary), "serve", "--port", str(port)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("SIQ 启动失败；请运行 serve 检查配置、状态目录写锁或端口冲突。未删除写锁。")
        if healthy(binary, port, env):
            return {"status": "ready", "reused": False, "endpoint": endpoint, "pid": process.pid}
        time.sleep(0.2)
    # Leave the owned child available for diagnosis: do not guess whether it is
    # executing work or remove a writer lock merely because readiness is slow.
    raise RuntimeError(f"SIQ 尚未就绪（本次启动 PID {process.pid}）；请运行 status 检查，不会自动终止进程或删除写锁。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="explicit, trusted local build")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=47611)
    parser.add_argument("--open", action="store_true", help="open the local management page after readiness")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error("binary is missing")
    try:
        result = ensure_started(binary, args.state_dir.resolve(), args.port)
        result["schema_version"] = "local-development-launch/v1"
        if args.open:
            result["browser_opened"] = webbrowser.open(result["endpoint"] + "/overview")
        result["next"] = "使用相同状态目录运行 siq-agent-security pair 获取配对码。"
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
