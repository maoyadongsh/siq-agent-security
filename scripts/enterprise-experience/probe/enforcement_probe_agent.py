#!/usr/bin/env python3
"""边界内行为探针：**只报告事实，不做判定**。

它被上传进沙箱、由 `sandbox exec` 在**策略真正治理的那个边界内**运行，
对给定 `host:port` 做 N 次真实 TCP 连接，把每次的形态与耗时如实打出来：

    SIQ_PROBE_JSON {"schema": "...", "endpoint": "h:p", "attempts": [{"outcome": "...", "elapsed_ms": 0}, ...]}

**它刻意不知道"预期是什么"**：没有 `--expect`，也不会因为结果"看起来像被拦"就改变输出。
判定由我方仓库侧的工具按差分结构做（允许臂必须连上 / 拒绝臂必须被拦 /
边界外对照必须连上）。夹具自己说"我被拦住了"**不是证据**。

形态词表（与 `app/adapters/openshell/enforcement_probe.py` 逐字对齐）：
`connected` / `timeout` / `connection_refused` / `connection_reset` / `dns_failure` / `probe_error`。
词表外的任何异常一律 `probe_error`——绝不错猜成"像被拦"的形态。

退出码：0 = 完成全部尝试并打印了报告；2 = 参数非法；3 = 未能打印报告。
**退出码不表示"被拦"或"没被拦"**。
"""

import argparse
import json
import socket
import sys
import time

SCHEMA = "siq.openshell.enforcement-probe-agent/v1"
REPORT_PREFIX = "SIQ_PROBE_JSON "

# 与仓库侧词表逐字对齐（顺序敏感：gaierror 是 OSError 的子类，先判它）
_OUTCOME_BY_EXC = (
    (TimeoutError, "timeout"),
    (socket.gaierror, "dns_failure"),
    (ConnectionRefusedError, "connection_refused"),
    (ConnectionResetError, "connection_reset"),
)


def classify(exc):
    for exc_type, outcome in _OUTCOME_BY_EXC:
        if isinstance(exc, exc_type):
            return outcome
    return "probe_error"


def attempt(host, port, timeout):
    started = time.monotonic()
    outcome = "probe_error"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            outcome = "connected"
    except OSError as exc:
        outcome = classify(exc)
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
    return {"outcome": outcome, "elapsed_ms": elapsed_ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument('--endpoint', required=True, help='目标 host:port')
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=5.0)
    args = parser.parse_args()
    if args.attempts < 1 or args.timeout <= 0:
        return 2
    host, sep, port = args.endpoint.rpartition(':')
    if not sep or not host or not port.isdigit():
        return 2
    results = [attempt(host, int(port), args.timeout) for _ in range(args.attempts)]
    report = {"schema": SCHEMA, "endpoint": args.endpoint, "attempts": results}
    sys.stdout.write(REPORT_PREFIX + json.dumps(report, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
