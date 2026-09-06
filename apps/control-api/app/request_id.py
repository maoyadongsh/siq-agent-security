"""客户端 Request-ID 规范化（DEV11-D / M-P5c）。

客户端值仅作 correlation，不得充当身份或审计主键。
非法/超长/含控制字符时丢弃并由服务端生成。
"""

from __future__ import annotations

import re
import uuid

# 与 AuditEvent.request_id String(64) 对齐；留出 req- 前缀余量
MAX_CLIENT_REQUEST_ID_LEN = 64
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_server_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:20]}"


def normalize_client_request_id(raw: str | None) -> str:
    """返回可用于 correlation 的 request_id；非法输入一律服务端生成。"""
    if raw is None:
        return new_server_request_id()
    value = raw.strip()
    if not value or len(value) > MAX_CLIENT_REQUEST_ID_LEN:
        return new_server_request_id()
    # 拒绝控制字符 / 空白 / 非打印（防日志与审计注入）
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return new_server_request_id()
    if not _CLIENT_REQUEST_ID_RE.fullmatch(value):
        return new_server_request_id()
    return value
