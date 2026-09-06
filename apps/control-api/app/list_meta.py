"""列表分页元数据（DEV13-D）。

合同：
- JSON 体仍可为数组（兼容既有客户端）；
- 用响应头声明本页条数、是否截断、下一游标；
- **禁止**用「本页 length」冒充全量；截断时必须标 truncated。

头字段：
- X-SIQ-List-Limit
- X-SIQ-List-Returned
- X-SIQ-List-Truncated  (0|1)
- X-SIQ-Next-Cursor     (截断时可选)
- X-SIQ-List-Total      (可选；仅在调用方显式计算时设置)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from starlette.responses import Response

HDR_LIMIT = "X-SIQ-List-Limit"
HDR_RETURNED = "X-SIQ-List-Returned"
HDR_TRUNCATED = "X-SIQ-List-Truncated"
HDR_NEXT_CURSOR = "X-SIQ-Next-Cursor"
HDR_TOTAL = "X-SIQ-List-Total"

# 暴露给浏览器前端（与 CORS 中间件配合时需允许）
EXPOSE_HEADERS = (
    HDR_LIMIT,
    HDR_RETURNED,
    HDR_TRUNCATED,
    HDR_NEXT_CURSOR,
    HDR_TOTAL,
)


def clamp_limit(limit: int, *, default: int = 50, hard_max: int = 200) -> int:
    if limit < 1:
        return default
    return min(limit, hard_max)


def apply_list_meta(
    response: Response,
    *,
    limit: int,
    returned: int,
    truncated: bool,
    next_cursor: str | None = None,
    total: int | None = None,
) -> None:
    response.headers[HDR_LIMIT] = str(limit)
    response.headers[HDR_RETURNED] = str(returned)
    response.headers[HDR_TRUNCATED] = "1" if truncated else "0"
    if truncated and next_cursor:
        response.headers[HDR_NEXT_CURSOR] = next_cursor
    if total is not None:
        response.headers[HDR_TOTAL] = str(total)


def take_page(
    rows_plus_one: Sequence[Any],
    *,
    limit: int,
) -> tuple[list[Any], bool]:
    """对 limit+1 查询结果切页；truncated=True 表示还有后续。"""
    items = list(rows_plus_one)
    if len(items) > limit:
        return items[:limit], True
    return items, False
