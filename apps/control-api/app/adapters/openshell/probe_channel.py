"""行为 fixture 通道：把边界内的**原始观测**取回来（不判定、不解释）。

分工是刻意的（方案 §2 不变量 2）：

- 边界内的探针脚本 `enforcement_probe_agent.py` **只报告事实**
  （连上了 / 超时 / 拒绝 / 重置 / DNS 失败 / 自身出错 + 耗时），不做任何"是否符合预期"的判断；
- 本模块把那些事实**原样搬运**成 `ProbeObservation`，同样不判定；
- 判定只在 `enforcement_probe.validate_enforcement_probe_evidence` 里发生。

本模块不允许"夹具自述成功"混进来：探针输出必须逐字段通过结构校验，
形态必须在固定词表内，词表外的任何值一律 `probe_error`（既不算连上、也不算被拦）。

安全约束：
- 一切命令都经 `run_bounded`（超时 + 输出上限 + 白名单环境），不转发凭据；
- 命令形态是**固定模板**拼出来的（`exec` / `upload` 两类），不接受任意命令字符串；
- 本模块**自己**不判断"该不该跑"——许可与边界由调用方（工具）负责。
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.adapters.openshell.bounded_command import run_bounded
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.enforcement_probe import (
    ORIGIN_CONTROL_PLANE_HOST,
    OUTCOME_CONNECTED,
    OUTCOME_DNS,
    OUTCOME_ERROR,
    OUTCOME_REFUSED,
    OUTCOME_RESET,
    OUTCOME_TIMEOUT,
    ProbeObservation,
)

#: 探针脚本输出行的前缀（与 agent 侧合同一致）。
AGENT_REPORT_PREFIX = "SIQ_PROBE_JSON "
AGENT_REPORT_SCHEMA = "siq.openshell.enforcement-probe-agent/v1"

Runner = Callable[[list[str]], "tuple[int, str, str]"]

#: 从异常类型到固定词表的映射。**闭合映射**：未列出的异常一律 `probe_error`，
#: 绝不"猜一个像被拦的形态"——那会把探针自身的故障伪装成策略生效。
_OUTCOME_BY_EXC = (
    (TimeoutError, OUTCOME_TIMEOUT),
    (socket.gaierror, OUTCOME_DNS),
    (ConnectionRefusedError, OUTCOME_REFUSED),
    (ConnectionResetError, OUTCOME_RESET),
)


def classify_socket_error(exc: BaseException) -> str:
    """异常 → 固定词表。顺序敏感：`socket.gaierror` 是 `OSError` 的子类，先判它。"""
    for exc_type, outcome in _OUTCOME_BY_EXC:
        if isinstance(exc, exc_type):
            return outcome
    return OUTCOME_ERROR


def default_runner(argv: list[str]) -> tuple[int, str, str]:
    return run_bounded(argv, timeout=120)


# ------------------------------------------------------------ 子命令模板（固定，非自由拼接）

#: 子命令形态在**这里**固定死；二进制与网关解析交给后端的 `_build_command`
#: （单一事实源：工具与部署路径不可能对"用哪个 CLI、连哪个网关"产生分歧）。


def build_exec_args(target: str, command: list[str], *, timeout: int = 0) -> list[str]:
    """`sandbox exec` 的子命令参数（不含 CLI 二进制前缀）。"""
    return ["sandbox", "exec", "--name", target, "--no-tty",
            "--timeout", str(int(timeout)), "--", *command]


def build_upload_args(target: str, source: str, destination: str) -> list[str]:
    """`sandbox upload` 的子命令参数（不含 CLI 二进制前缀）。"""
    return ["sandbox", "upload", "--name", target, source, destination]


# ------------------------------------------------------------ 探针输出解析（严格）


def parse_agent_report(stdout: str, *, require_attempts: int, expected_endpoint: str) -> list[dict]:
    """从探针 stdout 里取出报告行并逐字段校验。

    只接受**恰好一行**带前缀的报告；attempts 条数必须够、形态必须在词表内。
    任何不合规 → `AdapterError`（fail-closed，绝不"部分采信"）。
    """
    lines = [line for line in stdout.splitlines() if line.startswith(AGENT_REPORT_PREFIX)]
    if len(lines) != 1:
        raise AdapterError("enforcement_probe_report_line_invalid")
    try:
        report = json.loads(lines[0][len(AGENT_REPORT_PREFIX):])
    except ValueError:
        raise AdapterError("enforcement_probe_report_not_json") from None
    if not isinstance(report, dict) or report.get("schema") != AGENT_REPORT_SCHEMA:
        raise AdapterError("enforcement_probe_report_schema_unsupported")
    if set(report) != {"schema", "endpoint", "attempts"} or report["endpoint"] != expected_endpoint:
        raise AdapterError("enforcement_probe_report_endpoint_invalid")
    attempts = report.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != require_attempts:
        raise AdapterError("enforcement_probe_report_attempts_insufficient")
    parsed: list[dict] = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != {"outcome", "elapsed_ms"}:
            raise AdapterError("enforcement_probe_report_attempt_invalid")
        outcome = attempt.get("outcome")
        if not isinstance(outcome, str):
            raise AdapterError("enforcement_probe_report_attempt_invalid")
        elapsed = attempt.get("elapsed_ms", 0)
        if type(elapsed) is not int or elapsed < 0:
            raise AdapterError("enforcement_probe_report_attempt_invalid")
        parsed.append({"outcome": outcome, "elapsed_ms": elapsed})
    return parsed


# ------------------------------------------------------------ 观测构造（只搬运，不判定）


def observations_from_report(
    attempts: list[dict],
    *,
    endpoint: str,
    binary_path: str,
    binary_sha256: str,
) -> list[ProbeObservation]:
    """把探针报告搬运成边界内观测。origin 固定 `sandbox_exec`（唯一可用原点）。"""
    return [
        ProbeObservation(
            origin="sandbox_exec",
            endpoint=endpoint,
            outcome=attempt["outcome"],
            binary_path=binary_path,
            binary_sha256=binary_sha256,
            elapsed_ms=attempt["elapsed_ms"],
        )
        for attempt in attempts
    ]


def reachability_control(endpoint: str, *, timeout: float = 5.0) -> ProbeObservation:
    """边界外可达性对照：**控制面主机**发起的真实 TCP 连接。

    它只回答"这个 endpoint 此刻是不是活的"。它**永不**单独构成证据——
    校验器要求它作为对照存在，同时要求边界内的拒绝臂与之矛盾（一个通、一个被拦）。
    """
    host, _, port = endpoint.rpartition(":")
    elapsed_ms = 0
    outcome = OUTCOME_ERROR
    started = _monotonic_ms()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            outcome = OUTCOME_CONNECTED
    except OSError as exc:
        outcome = classify_socket_error(exc)
    finally:
        elapsed_ms = _monotonic_ms() - started
    return ProbeObservation(
        origin=ORIGIN_CONTROL_PLANE_HOST,
        endpoint=endpoint,
        outcome=outcome,
        elapsed_ms=elapsed_ms,
    )


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


# ------------------------------------------------------------ 通道


@dataclass(frozen=True)
class ProbeCommandResult:
    """一次边界内执行的原始结果（退出码 + 两个流），供留痕，不含判定。"""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str


class SandboxExecProbeChannel:
    """通过 `sandbox exec` 在边界内取观测的通道。

    `command_builder` 由调用方注入——生产路径用后端自己的 `_build_command`
    （CLI 二进制与网关解析只有一处），合成测试用替身。
    `runner` 同样可注入（合成测试用替身；真实运行走 `run_bounded`）。
    """

    def __init__(self, command_builder: Callable[[list[str]], list[str]],
                 *, runner: Runner = default_runner):
        self._build_command = command_builder
        self._runner = runner

    def upload(self, target: str, source: Path, destination: str) -> ProbeCommandResult:
        if not source.is_file():
            raise AdapterError("enforcement_probe_source_missing")
        if not destination.startswith("/"):
            raise AdapterError("enforcement_probe_destination_must_be_absolute")
        argv = self._build_command(build_upload_args(target, str(source.resolve()), destination))
        exit_code, stdout, stderr = self._runner(argv)
        return ProbeCommandResult(argv=argv, exit_code=exit_code, stdout=stdout, stderr=stderr)

    def run_arm(
        self,
        target: str,
        *,
        endpoint: str,
        binary_path: str,
        binary_sha256: str,
        attempts: int,
        timeout_seconds: float,
    ) -> tuple[list[ProbeObservation], ProbeCommandResult]:
        """在边界内用指定二进制路径访问 endpoint。**返回原始观测，不下结论。**

        `binary_sha256` 由调用方在**上传前**用本地源文件算好并传入——通道不读边界内的文件，
        所以"两个路径下是同一份内容"这件事只能由上传方的摘要来声明，不能由通道去猜。
        """
        if attempts < 1:
            raise AdapterError("enforcement_probe_attempts_invalid")
        command = [binary_path, "--endpoint", endpoint,
                   "--attempts", str(attempts), "--timeout", str(timeout_seconds)]
        argv = self._build_command(
            build_exec_args(target, command, timeout=int(timeout_seconds * attempts) + 60)
        )
        exit_code, stdout, stderr = self._runner(argv)
        result = ProbeCommandResult(argv=argv, exit_code=exit_code, stdout=stdout, stderr=stderr)
        if exit_code != 0:
            raise AdapterError("enforcement_probe_command_failed")
        parsed = parse_agent_report(stdout, require_attempts=attempts, expected_endpoint=endpoint)
        return observations_from_report(
            parsed, endpoint=endpoint, binary_path=binary_path, binary_sha256=binary_sha256,
        ), result


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
