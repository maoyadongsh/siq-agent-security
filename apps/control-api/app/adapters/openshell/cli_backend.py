"""OpenShellCliBackend：真实 CLI 后端（2026-08-13 活网关实测语义锁定）。

实测依据（网关 siq-openshell-dev @ https://127.0.0.1:17671，v0.0.83）：
- `policy get <name> --full` 返回真实生效策略（含 filesystem/landlock/process/network）；
- `policy set <name> --policy yaml` 对运行中沙箱热更新：静态段（filesystem）必须与创建时一致
  （否则网关拒绝：include_workdir cannot be changed on a live sandbox），网络段可变更，
  成功输出 "Policy version N submitted (hash: ...)"；
- revision 递增（1→2），`policy get --rev N --full` 可回读历史（回滚基础）；
- 已知网关缺陷：SandboxResponse 的 Protobuf 解码错误影响 v0.0.83 的 list/create/get
  （policy 命令不受影响）；v0.0.104 已实测确认修复（docs/compatibility.md 2026-08-13
  隔离网关验证）。list_targets 在探测版本 >= v0.0.104 时如实抛出 CLI 错误
  （docker 回退退役），版本未知或低于 v0.0.104 保持 docker 兜底。
- probe 版本探测：从 `gateway info` 输出 / `--version` 真实解析版本（保守正则，
  解析不到记为 unknown，绝不编造）；schema_version 由探测结果组成，
  不再硬编码 v0.0.83 假设。
- probe 身份握手（O04）：`gateway info` 只是本地配置打印，成功不证明后端在线；
  probe 必须真实调用 `status` 并通过结构校验（"Server Status" 标题行 + 非空
  "Gateway:" 名）。空输出/无关输出/异构协议 rc=0 一律 fail-closed；
  gateway_version 只来自 live status 输出，CLI 版本不再上调 schema_version。
  版本/握手缓存绑定调用指纹（CLI+endpoint 或 env.sh 路径+size+mtime），配置
  一变即失效。

安全约束：
- 仅接受显式的 CLI+网关或绝对 env.sh 路径配置，不隐式依赖相邻仓库；
- 非回环网关强制 HTTPS，拒绝 URL 凭据、路径、查询串和片段；
- 每次调用超时 + 输出上限；任何异常 → AdapterError（fail-closed）。
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.adapters.openshell.base import EnforcementAdapter
from app.adapters.openshell.bounded_command import MAX_OUTPUT, run_bounded
from app.adapters.openshell.contracts import (
    VERIFY_LEVEL_FAILED,
    VERIFY_LEVEL_READBACK,
    AdapterError,
    BackendCapabilities,
    CapabilityItem,
    ChangePlan,
    CompiledPolicy,
    DeploymentReceipt,
    EventBatch,
    PolicySnapshot,
    RollbackAuthorization,
    RollbackAuthorizer,
    RollbackReceipt,
    SandboxPage,
    ValidationReport,
    VerificationFailed,
    VerificationReport,
)
from app.adapters.openshell.operation_registry import (
    PROCESS_POLICY_OPERATIONS,
    PolicyOperation,
    PolicyOperationRegistry,
)
from app.adapters.openshell.policy_compiler import compile_policy, validate_compiled
from app.adapters.openshell.policy_safety import (
    clone_policy,
    gateway_network_to_rules,
    network_rules_to_gateway,
    parse_policy_output,
    policy_digest,
    static_policy_digest,
    validate_revision,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")

# 实测捕获的真实输出（测试夹具同源）
_VERSION_SUBMITTED_RE = re.compile(r"Policy version (\d+) submitted \(hash: ([0-9a-f]+)\)")
# 实测：内容与当前一致时网关返回 no-op（幂等重放）
_VERSION_UNCHANGED_RE = re.compile(r"Policy unchanged \(version (\d+), hash: ([0-9a-f]+)\)")

# 保守版本解析：只认 "…version…: vX.Y.Z" 或行首 "openshell … X.Y.Z" 形状，
# 不匹配任意点分三元组（避免把 gateway endpoint 的 127.0.0.1 误判成版本）。
_VERSION_LINE_RE = re.compile(r"(?im)^[^\n]*\bversion\b[^\n0-9]{0,16}v?(\d+\.\d+\.\d+)")
_CLI_VERSION_RE = re.compile(r"(?im)^\s*openshell(?:\s+version)?[\s:v-]{0,4}(\d+\.\d+\.\d+)")

# ---- O04 身份握手（与 Go 侧 internal/openshell 同一判定语义）----
# status 结构校验：首个非空行必须是 "Server Status"，且存在 "Gateway:" 行、
# 网关名非空且不含控制字符。空输出/无关输出/异构协议 rc=0 全部拒绝。
_ERR_IDENTITY_UNCONFIRMED = (
    "endpoint 有响应，但 status 输出无法识别为 OpenShell 服务端（身份/协议未确认）"
)
_STATUS_HEADING = "Server Status"
_GATEWAY_LINE_RE = re.compile(r"^Gateway:\s*(\S.*)$")
_GATEWAY_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_GATEWAY_VERSION_RE = re.compile(r"(?im)^\s*Gateway version:\s*v?(\d+\.\d+\.\d+)\s*$")
_STATUS_VERSION_RE = re.compile(r"(?im)^\s*Version:\s*v?(\d+\.\d+\.\d+)\s*$")

# 版本/握手缓存 TTL：与调用指纹共同构成证据作用域（配置一变即失效）。
_VERSION_CACHE_TTL_SECONDS = 300.0
_CLI_TIMEOUT_SECONDS = 30


def _looks_like_openshell_status(text: str) -> bool:
    """status 输出结构校验（fail-closed）：空/无关/异构协议输出一律 False。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != _STATUS_HEADING:
        return False
    names = [line.removeprefix("Gateway:").strip() for line in lines[1:]
             if line.startswith("Gateway:")]
    return len(names) == 1 and bool(_GATEWAY_NAME_RE.fullmatch(names[0]))


def _parse_gateway_name(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[1:]:
        match = _GATEWAY_LINE_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


def _parse_gateway_version(text: str) -> str | None:
    versions = _GATEWAY_VERSION_RE.findall(text)
    if _looks_like_openshell_status(text):
        versions += _STATUS_VERSION_RE.findall(text)
    return versions[0] if len(versions) == 1 else None


def _parse_version(text: str) -> str | None:
    """从 CLI 输出中保守解析 OpenShell 版本号；无法确定时返回 None（绝不编造）。"""
    for pattern in (_VERSION_LINE_RE, _CLI_VERSION_RE):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _cli_capability_document() -> dict[str, CapabilityItem]:
    """openshell-cli 路径的版本化能力文档（P1-1/P1-11）。

    每一项的 status 只反映已实测结论；未实测一律 unknown/unsupported 并在
    basis 注明依据，不得猜 supported。与上方布尔字段保持一致（布尔字段是
    同一实测结论的便捷视图）。
    """
    items = {
        # 实测：v0.0.83 网关 SandboxResponse 解码缺陷致 create/list 经 CLI 不可用
        # （v0.0.104 已确认修复但本探测路径未对 create 实测，保守 unsupported）
        "sandbox_lifecycle": CapabilityItem(
            status="unsupported",
            semantics="none",
            basis="实测：SandboxResponse 解码缺陷，create_generation 经 CLI 拒绝（v0.0.104 修复未在本路径实测）",
        ),
        # 实测：静态段创建时锁定，活沙箱变更被网关拒绝（include_workdir cannot be changed）
        "filesystem": CapabilityItem(
            status="supported", semantics="enforce", basis="实测：静态边界，创建时锁定，网关强制"
        ),
        "process": CapabilityItem(
            status="supported", semantics="enforce", basis="实测：process 段同属静态边界，创建时锁定"
        ),
        # 2026-08-13 实测：policy set 对运行中沙箱热更新网络段成功（host:port 粒度）
        "network_l34": CapabilityItem(
            status="supported", semantics="enforce", basis="2026-08-13 实测：host:port 网络段热更新成功"
        ),
        # 实测：端点模型仅 host:port；path 级规则编译期拒绝（_network_rules_to_gateway）
        "network_l7": CapabilityItem(
            status="unsupported", semantics="none", basis="实测：端点模型仅 host:port，path 级规则编译拒绝"
        ),
        # interceptor 未经任何版本实测 → unknown（fail-closed，不猜测）
        "tools_mcp": CapabilityItem(status="unknown", semantics="none", basis="interceptor/工具治理未经实测（不猜测）"),
        "model_routing": CapabilityItem(
            status="unsupported", semantics="none", basis="provider 凭据注入未经实测（保守拒绝）"
        ),
        "secrets": CapabilityItem(
            status="unsupported", semantics="none", basis="凭据注入能力未经实测（保守拒绝，§15.2 由 Provider 侧承担）"
        ),
        "resources": CapabilityItem(status="unknown", semantics="none", basis="资源配额语义未经实测"),
        # 网关无已实测行为事件流；stream_events 仅能回读 policy list 文本（非行为事件）
        "audit_events": CapabilityItem(
            status="unknown", semantics="none", basis="无已实测事件流；stream_events 仅 policy list 回读（非行为事件）"
        ),
        # P1-11：openshell-cli 当前只支持 block；warn/audit_only 无实测执行语义
        "enforcement_mode.block": CapabilityItem(
            status="supported", semantics="enforce", basis="网关策略默认拦截语义（部署路径实测）"
        ),
        "enforcement_mode.warn": CapabilityItem(
            status="unsupported", semantics="none", basis="CLI 路径无 warn 执行语义的实测依据"
        ),
        "enforcement_mode.audit_only": CapabilityItem(
            status="unsupported", semantics="none", basis="CLI 路径无 audit_only 执行语义的实测依据"
        ),
    }


    return {key: replace(item, evidence_level="documented",
                         scope="historical_adapter_observations_2026-08-13; not_current_target")
            for key, item in items.items()}


Runner = Callable[[list[str]], tuple[int, str, str]]


def _default_env_script() -> str | None:
    return os.getenv("SIQ_AS_OPENSHELL_ENV_SH") or None


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class OpenShellCliBackend(EnforcementAdapter):
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        env_script: str | None = None,
        docker_runner: Runner | None = None,
        operation_registry: PolicyOperationRegistry | None = None,
    ):
        self._env_script = env_script if env_script is not None else _default_env_script()
        self._runner = runner or self._subprocess_runner
        self._docker_runner = docker_runner  # None = 原始 docker 子进程
        self._artifacts: dict[str, CompiledPolicy] = {}  # compile 注册，apply 引用
        # 版本探测缓存：None = 未探测；"unknown" = 探测失败/输出不可解析。
        # O04：缓存绑定调用指纹 + TTL，配置变更或过期后一律重新解析（不复活旧结论）。
        self._detected_version: str | None = None
        self._detected_fingerprint: str = ""
        self._detected_at: float = 0.0
        self._operations = operation_registry or PROCESS_POLICY_OPERATIONS

    # ------------------------------------------------------------ 子进程

    def _build_command(self, args: list[str]) -> list[str]:
        """目标网关选择（§15.1 能力协商/多网关）。

        - SIQ_AS_OPENSHELL_CLI_BIN 指定 CLI 二进制（如 v0.0.104 构建产物）
          + SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT/INSECURE → 直连指定网关（不经 env.sh）；
        - SIQ_AS_OPENSHELL_ENV_SH → 显式 source 指定的绝对路径脚本；
        - 两种方式均未完整配置时 fail-closed。
        """
        cli_bin = os.getenv("SIQ_AS_OPENSHELL_CLI_BIN")
        endpoint = os.getenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT")
        insecure = os.getenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "0") == "1"
        if bool(cli_bin) != bool(endpoint):
            raise AdapterError("SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 必须同时配置")
        if cli_bin and endpoint:
            parsed = urlparse(endpoint)
            try:
                _ = parsed.port  # 显式触发端口解析校验（非法端口抛 ValueError）
            except ValueError as exc:
                raise AdapterError("OpenShell gateway endpoint 端口无效") from exc
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise AdapterError("OpenShell gateway endpoint 无效")
            loopback = _is_loopback(parsed.hostname)
            if parsed.scheme != "https" and not loopback:
                raise AdapterError("非回环 OpenShell gateway 必须使用 HTTPS")
            if insecure and not loopback:
                raise AdapterError("--gateway-insecure 仅允许回环开发网关")
            cmd = [cli_bin, "--gateway-endpoint", endpoint]
            if insecure:
                cmd.append("--gateway-insecure")
            cmd.extend(args)
        elif self._env_script:
            env_path = Path(self._env_script)
            if not env_path.is_absolute():
                raise AdapterError("SIQ_AS_OPENSHELL_ENV_SH 必须是绝对路径")
            # 脚本路径通过位置参数传入，不拼接到 shell 程序文本。
            cmd = [
                "bash",
                "-c",
                'source "$1" && shift && exec openshell "$@"',
                "openshell-env",
                str(env_path),
                *args,
            ]
        else:
            raise AdapterError("OpenShell CLI 未配置：设置 CLI_BIN + GATEWAY_ENDPOINT，或显式设置 OPENSHELL_ENV_SH")
        return cmd

    def _subprocess_runner(self, args: list[str]) -> tuple[int, str, str]:
        cmd = self._build_command(args)
        return run_bounded(cmd, timeout=_CLI_TIMEOUT_SECONDS)

    def _cli(self, *args: str) -> str:
        """执行 CLI；成功输出可能落在 stdout 或 stderr（实测 policy set 的 ✓ 回执在 stderr）。"""
        rc, stdout, stderr = self._runner(list(args))
        if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > MAX_OUTPUT:
            raise AdapterError("openshell_output_limit")
        clean_out = _ANSI_RE.sub("", stdout)
        clean_err = _ANSI_RE.sub("", stderr)
        if rc != 0:
            raise AdapterError("openshell_command_failed")
        return clean_out + "\n" + clean_err

    def _set_policy_and_wait(self, target: str, policy_file: str) -> str:
        # Submission/readback does not confirm the sandbox loaded the policy.
        # A failed acknowledgement may follow a committed write: never retry
        # without --wait or issue a successful deployment receipt.
        return self._cli(
            "policy", "set", target, "--policy", policy_file,
            "--wait", "--timeout", str(max(1, _CLI_TIMEOUT_SECONDS - 2)),
        )

    # ------------------------------------------------------------ 合同实现

    def _invocation_fingerprint(self) -> str:
        """调用指纹（O04）：探测/缓存证据的作用域。

        - CLI_BIN + GATEWAY_ENDPOINT 直连 → 绑定 (cli, endpoint)；
        - 显式配置包含 TLS 模式、CLI 文件身份和实际配置/证书目录上下文；
        - env.sh 可间接切换目标，返回空指纹，禁止复用缓存。
        """
        cli_bin = os.getenv("SIQ_AS_OPENSHELL_CLI_BIN") or ""
        endpoint = os.getenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT") or ""
        env_sh = self._env_script or ""
        if cli_bin and endpoint:
            try:
                stat = os.stat(cli_bin)
                identity = f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"
            except OSError:
                identity = "unavailable"
            parts: tuple[str, ...] = (
                "env_pair", cli_bin, endpoint,
                os.getenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "0"), identity,
            )
            # These inputs survive clean_env() and select CLI registration and
            # TLS state. A changed project context must invalidate old evidence.
            context_keys = (
                "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME",
                "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
            )
            parts += tuple(f"{key}={os.getenv(key, '')}" for key in context_keys)
        elif env_sh:
            # A script can source other files or select a different gateway.
            # No stable destination identity exists without running it.
            return ""
        else:
            parts = ("none",)
        digest = hashlib.sha256()
        for part in parts:
            digest.update(part.encode("utf-8", "replace"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def probe(self) -> BackendCapabilities:
        try:
            return self._probe_current()
        except AdapterError:
            self._detected_version = None
            self._detected_fingerprint = ""
            self._detected_at = 0.0
            raise

    def _probe_current(self) -> BackendCapabilities:
        """协议响应 + 版本观察；历史能力字段不代表当前目标已执行验证。

        O04 语义修正：
        - `gateway info` 只是本地配置打印，成功 ≠ 后端在线；probe 必须真实
          调用 `status` 并通过结构校验，空输出/无关输出/异构协议 rc=0 一律
          fail-closed（身份/协议未确认），绝不伪装成可达；
        - cli_version 来自 `gateway info` / `--version`；gateway_version 只来自
          live `status` 输出；schema_version 由 gateway_version 组成（CLI 版本
          不再上调 schema，与 Go 侧一致）；
        - 旧布尔/能力文档保留历史出处；编译只使用本适配器显式声明的配置能力。
          配置表达能力不代表执行权限，不因版本或握手而上调执行证据。
        """
        before = self._invocation_fingerprint()
        info_out = self._cli("gateway", "info")  # CLI 可用性前提；失败 fail-closed
        status_out = self._cli("status")  # 身份握手前提；rc!=0 fail-closed
        if not _looks_like_openshell_status(status_out):
            raise AdapterError(_ERR_IDENTITY_UNCONFIRMED)
        fingerprint = self._invocation_fingerprint()
        if before != fingerprint:
            raise AdapterError("openshell_configuration_changed")
        cli_version = self._detect_version(info_out)
        if before != self._invocation_fingerprint():
            raise AdapterError("openshell_configuration_changed")
        gateway_version = _parse_gateway_version(status_out) or "unknown"
        caps = BackendCapabilities(
            backend="openshell",
            schema_version=(
                f"v{gateway_version}-policy-v1" if gateway_version != "unknown" else "unknown-policy-v1"
            ),
            dynamic_network_update=True,  # 2026-08-13 实测：网络段热更新成功（静态段锁定）
            static_filesystem=True,  # 实测：活沙箱 filesystem 变更被拒绝
            static_process=True,  # 实测：process 段同属静态边界（创建时锁定）
            landlock=True,  # SIQ landlock patch 在 v0.0.83 运行网关中；v0.0.104 上游已内置（ADR-009）
            interceptor=False,  # 未经任何版本实测验证（保守 False，不按新版本猜测）
            provider_credential_injection=False,  # 未经实测验证（保守 False）
            revision_support=True,  # 实测：policy list / --rev 回读可用
            max_filesystem_paths=1024,  # 合同默认值，未经网关实测上限
            capabilities=_cli_capability_document(),
            # ---- O04 证据字段（增量）：只声明 status 握手能证明的事实 ----
            evidence_level="handshake_verified",
            handshake_verified=True,
            handshake_gateway=_parse_gateway_name(status_out),
            observed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            endpoint_fingerprint=fingerprint,
            cli_version=cli_version,
            gateway_version=gateway_version,
            max_filesystem_paths_measured=False,
            configuration_capabilities={"network.dynamic_update": True, "enforcement_mode.block": True},
        )
        return caps

    def _detect_version(self, gateway_info_output: str) -> str:
        """真实版本探测：先解析 gateway info 输出，再回退 `--version`。

        解析基于保守正则；任何一步失败都返回 "unknown" 且不抛错
        （版本缺失不掩盖握手事实，也不编造版本号）。结果缓存绑定调用
        指纹 + TTL，供 list_targets 的 docker 回退退役判定使用。
        """
        fingerprint = self._invocation_fingerprint()
        now = time.monotonic()
        if (
            self._detected_version is not None
            and bool(fingerprint)
            and self._detected_fingerprint == fingerprint
            and now - self._detected_at <= _VERSION_CACHE_TTL_SECONDS
        ):
            return self._detected_version
        version = _parse_version(gateway_info_output)
        if version is None:
            try:
                version = _parse_version(self._cli("--version"))
            except AdapterError:
                version = None
        self._detected_version = version or "unknown"
        if version and tuple(int(p) for p in version.split(".")) >= (0, 0, 104):
            self._docker_fallback_retired = True
        self._detected_fingerprint = fingerprint
        self._detected_at = now
        return self._detected_version

    def _detected_version_at_least(self, minimum: tuple[int, int, int]) -> bool:
        """已探测版本 >= minimum？未知/未探测/指纹变化/过期一律 False（保守，不放宽行为）。"""
        if (
            not self._detected_version
            or self._detected_version == "unknown"
            or not self._detected_fingerprint
            or self._detected_fingerprint != self._invocation_fingerprint()
            or time.monotonic() - self._detected_at > _VERSION_CACHE_TTL_SECONDS
        ):
            return False
        try:
            parts = tuple(int(p) for p in self._detected_version.split("."))
        except ValueError:
            return False
        return parts >= minimum

    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        try:
            out = self._cli("sandbox", "list")
        except AdapterError:
            # SandboxResponse 解码缺陷在 v0.0.104 已实测确认修复（docs/compatibility.md
            # 2026-08-13 隔离网关验证）：探测版本 >= v0.0.104 时 CLI 报错是真实故障，
            # 如实抛出而非静默走 docker 回退；版本未知或低于 v0.0.104 保持兜底。
            # A one-way fallback retirement never becomes a version/capability fact.
            if getattr(self, "_docker_fallback_retired", False) or self._detected_version_at_least((0, 0, 104)):
                raise
            return self._list_targets_docker_fallback()
        targets = []
        for line in out.splitlines()[1:]:
            name = line.strip().split()[0] if line.strip() else ""
            if name and name != "No":
                targets.append({"id": name})
        return SandboxPage(targets=targets, cursor=None)

    def _list_targets_docker_fallback(self) -> SandboxPage:
        """网关 SandboxResponse 解码缺陷的兜底：容器名 openshell-<name>-<uuid>。

        注意：docker 命令不能走 openshell 包装壳（_subprocess_runner 固定 exec openshell）。
        """
        if self._docker_runner is not None:
            rc, out, error = self._docker_runner(["docker", "ps", "--format", "{{.Names}}"])
        else:
            rc, out, error = run_bounded(["docker", "ps", "--format", "{{.Names}}"], timeout=10)
        if len(out.encode("utf-8")) + len(error.encode("utf-8")) > MAX_OUTPUT:
            raise AdapterError("openshell_output_limit")
        if rc != 0:
            raise AdapterError("openshell_command_failed")
        names = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("openshell-") and len(line) > len("openshell-") + 36:
                # 容器名 = openshell-<沙箱名>-<uuid36>；沙箱名可含 '-'
                names.append(line[len("openshell-") : -37])
        return SandboxPage(targets=[{"id": n} for n in sorted(set(names))], cursor=None)

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        out = self._cli("policy", "get", target, "--full")
        doc, revision = parse_policy_output(out)
        return PolicySnapshot(
            target=target,
            revision=revision,
            policy=clone_policy(doc),
            policy_digest=policy_digest(doc),
            static_digest=static_policy_digest(doc),
            filesystem=doc.get("filesystem_policy") or {},
            network=gateway_network_to_rules(doc.get("network_policies")),
            process=doc.get("process") or {},
            # P1-11：`policy get --full` 输出不含执行模式字段，无法从后端输出确定
            # 模式时如实填 "unknown"，不得无条件硬编码 "block"
            enforcement_mode="unknown",
            observed_at=None,
        )

    def compile(self, desired_policy: dict, capabilities: BackendCapabilities | None = None) -> CompiledPolicy:
        compiled = compile_policy(desired_policy, capabilities or self.probe())
        self._artifacts[compiled.artifact_hash] = compiled
        return compiled

    def validate(self, compiled: CompiledPolicy) -> ValidationReport:
        return validate_compiled(compiled)

    def plan_change(self, target: str, compiled: CompiledPolicy) -> ChangePlan:
        current = self.read_effective_policy(target)
        static_changed = any(
            key in compiled.artifact
            and (
                not isinstance(current.policy.get(key), dict)
                or any(current.policy[key].get(field) != value for field, value in compiled.artifact[key].items())
            )
            for key in ("filesystem_policy", "process")
        )
        kind = "generation" if static_changed else "dynamic"
        return ChangePlan(
            target=target,
            kind=kind,
            expected_revision=current.revision,
            artifact_hash=compiled.artifact_hash,
            base_policy_digest=current.policy_digest,
            base_static_digest=current.static_digest,
            steps=[f"policy set {target}（动态）" if kind == "dynamic" else f"sandbox create {target}（重建）"],
        )

    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        """Patch only network_policies under a process-local target lock."""
        validate_revision(expected_revision)
        if plan.target != target or plan.expected_revision != expected_revision or plan.kind != "dynamic":
            raise AdapterError("openshell_change_plan_mismatch")
        with self._operations.target_lock(target):
            current = self.read_effective_policy(target)
            if current.revision != expected_revision:
                from app.adapters.openshell.contracts import RevisionConflict

                raise RevisionConflict(expected=expected_revision, actual=current.revision)
            if current.policy_digest != plan.base_policy_digest or current.static_digest != plan.base_static_digest:
                raise AdapterError("openshell_prewrite_policy_drift")
            compiled = self._artifacts.get(plan.artifact_hash)
            if compiled is None:
                raise AdapterError("openshell_unknown_compiled_artifact")
            if "network_policies" not in compiled.artifact:
                raise AdapterError("openshell_network_intent_missing")
            merged = clone_policy(current.policy)
            network = network_rules_to_gateway(compiled.artifact["network_policies"])
            if network:
                merged["network_policies"] = network
            elif merged.get("network_policies") != {}:
                # Preserve an already-empty document as a no-op. On actual
                # revocation match gateway omission, keeping the full digest.
                merged.pop("network_policies", None)
            expected_digest = policy_digest(merged)
            operation_id = f"opo-{secrets.token_hex(24)}"
            if expected_digest == current.policy_digest:
                receipt = self._deployment_receipt(
                    operation_id=operation_id,
                    target=target,
                    base=current,
                    applied_revision=current.revision,
                    applied_digest=current.policy_digest,
                    result="no_op",
                )
                self._operations.remember(
                    PolicyOperation(
                        operation_id=operation_id,
                        target=target,
                        base=current,
                        applied_revision=current.revision,
                        applied_digest=current.policy_digest,
                        no_op=True,
                    )
                )
                return receipt
            prewrite = self.read_effective_policy(target)
            if prewrite.revision != current.revision or prewrite.policy_digest != current.policy_digest:
                raise AdapterError("openshell_prewrite_policy_drift")
            with self._policy_yaml_file(merged) as policy_file:
                out = self._set_policy_and_wait(target, policy_file)
            new_revision, gateway_hash = self._parse_set_receipt(out)
            readback = self._read_after_write(prewrite, new_revision, expected_digest)
            receipt = self._deployment_receipt(
                operation_id=operation_id,
                target=target,
                base=current,
                applied_revision=new_revision,
                applied_digest=expected_digest,
                result="applied",
                gateway_hash=gateway_hash,
            )
            self._operations.remember(
                PolicyOperation(
                    operation_id=operation_id,
                    target=target,
                    base=current,
                    applied_revision=new_revision,
                    applied_digest=readback.policy_digest,
                    no_op=False,
                )
            )
            return receipt

    def _deployment_receipt(
        self,
        *,
        operation_id: str,
        target: str,
        base: PolicySnapshot,
        applied_revision: str,
        applied_digest: str,
        result: str,
        gateway_hash: str = "",
    ) -> DeploymentReceipt:
        return DeploymentReceipt(
            backend_revision=applied_revision,
            operation_id=operation_id,
            target=target,
            base_revision=base.revision,
            base_policy_digest=base.policy_digest,
            applied_policy_digest=applied_digest,
            result=result,
            evidence={
                "snapshot_hash": gateway_hash,
                "gateway_policy_hash": gateway_hash,
                "full_policy_digest": applied_digest,
            },
            applied_at=None,
        )

    def _parse_set_receipt(self, out: str) -> tuple[str, str]:
        match = _VERSION_SUBMITTED_RE.search(out) or _VERSION_UNCHANGED_RE.search(out)
        if not match:
            raise AdapterError("openshell_policy_set_receipt_invalid")
        revision = validate_revision(match.group(1))
        return revision, match.group(2)

    def _read_after_write(
        self,
        base: PolicySnapshot,
        expected_revision: str,
        expected_digest: str,
    ) -> PolicySnapshot:
        import time

        last = base
        for attempt in range(10):
            snapshot = self.read_effective_policy(base.target)
            last = snapshot
            if snapshot.revision == expected_revision and snapshot.policy_digest == expected_digest:
                return snapshot
            if snapshot.revision not in {base.revision, expected_revision}:
                raise VerificationFailed("openshell_postwrite_revision_drift")
            if snapshot.revision == expected_revision:
                raise VerificationFailed("openshell_postwrite_policy_digest_mismatch")
            if attempt < 9:
                time.sleep(1)
        if last.revision == expected_revision:
            raise VerificationFailed("openshell_postwrite_policy_digest_mismatch")
        raise VerificationFailed("openshell_postwrite_revision_not_active")

    def _validate_receipt_binding(
        self,
        target: str,
        receipt: DeploymentReceipt,
        operation: PolicyOperation,
    ) -> None:
        expected_result = "no_op" if operation.no_op else "applied"
        if (
            not receipt.operation_id
            or receipt.operation_id != operation.operation_id
            or receipt.target != target
            or operation.target != target
            or receipt.base_revision != operation.base.revision
            or receipt.base_policy_digest != operation.base.policy_digest
            or receipt.backend_revision != operation.applied_revision
            or receipt.applied_policy_digest != operation.applied_digest
            or receipt.result != expected_result
        ):
            raise VerificationFailed("openshell_rollback_receipt_mismatch")

    def create_generation(self, target: str, compiled: CompiledPolicy) -> DeploymentReceipt:
        raise AdapterError(
            "sandbox create 经 CLI 受网关 SandboxResponse 解码缺陷影响；"
            "请通过受控生命周期创建，或升级到已修复的 OpenShell 版本后启用"
        )

    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        """配置读回验证（readback）：Active 会短暂滞后于提交（实测 Loaded→Active
        异步传播），以 1s 间隔轮询至多 10 次；最终不一致才判失败（§21.1 不变量 #5）。

        P1-2 分级语义：本方法只比对读回配置（revision + 网络允许集），没有任何
        行为 fixture 通道，因此通过时 level 只能是 readback_verified，
        绝不产出 enforcement_verified；任一失败 → failed。
        """
        import time

        snapshot = self.read_effective_policy(target)
        for _ in range(10):
            if snapshot.revision == receipt.backend_revision:
                break
            time.sleep(1)
            snapshot = self.read_effective_policy(target)
        failures: list[str] = []
        if snapshot.revision != receipt.backend_revision:
            failures.append(f"revision mismatch: {snapshot.revision} != {receipt.backend_revision}")
        if not receipt.applied_policy_digest or snapshot.policy_digest != receipt.applied_policy_digest:
            failures.append("full policy digest mismatch")
        allowed = {r.get("endpoint") for r in snapshot.network if r.get("effect") != "deny"}
        allow_checks = [
            {
                "endpoint": e,
                "request": "config_readback",
                "expected": "allow",
                "actual": "allow" if e in allowed else "not_in_allow_set",
                "result": "allow",
                "revision": snapshot.revision,
            }
            for e in checks.get("expect_allow", [])
        ]
        deny_checks = [
            {
                "endpoint": e,
                "request": "config_readback",
                "expected": "deny",
                "actual": "deny" if e not in allowed else "in_allow_set",
                "result": "deny",
                "revision": snapshot.revision,
            }
            for e in checks.get("expect_deny", [])
        ]
        for check in allow_checks:
            if check["endpoint"] not in allowed:
                failures.append(f"allow check failed: {check['endpoint']}")
        for check in deny_checks:
            if check["endpoint"] in allowed:
                failures.append(f"deny check failed: {check['endpoint']}")
        passed = not failures
        return VerificationReport(
            passed=passed,
            level=VERIFY_LEVEL_READBACK if passed else VERIFY_LEVEL_FAILED,
            allow_checks=allow_checks,
            deny_checks=deny_checks,
            failures=failures,
        )

    def rollback(
        self,
        target: str,
        receipt: DeploymentReceipt,
        authorizer: RollbackAuthorizer | None = None,
    ) -> RollbackReceipt:
        with self._operations.target_lock(target):
            operation = self._operations.get(receipt.operation_id)
            if operation is None:
                raise VerificationFailed("openshell_rollback_operation_unknown")
            self._validate_receipt_binding(target, receipt, operation)
            current = self.read_effective_policy(target)
            if current.revision != operation.applied_revision or current.policy_digest != operation.applied_digest:
                raise VerificationFailed("openshell_rollback_external_drift")
            if operation.no_op:
                self._operations.consume(operation.operation_id)
                return RollbackReceipt(
                    restored_revision=current.revision,
                    restored_digest=current.policy_digest,
                    result="no_op",
                    evidence={"operation_id": operation.operation_id},
                )
            if authorizer is None:
                raise VerificationFailed("openshell_rollback_authorizer_required")
            try:
                authorized = authorizer(
                    RollbackAuthorization(
                        operation_id=operation.operation_id,
                        target=target,
                        current=current,
                        restore=operation.base,
                    )
                )
            except Exception:
                raise VerificationFailed("openshell_rollback_authorization_failed") from None
            if authorized is not True:
                raise VerificationFailed("openshell_rollback_authorization_failed")
            prewrite = self.read_effective_policy(target)
            if prewrite.revision != operation.applied_revision or prewrite.policy_digest != operation.applied_digest:
                raise VerificationFailed("openshell_rollback_prewrite_drift")
            with self._policy_yaml_file(operation.base.policy) as policy_file:
                applied = self._set_policy_and_wait(target, policy_file)
            restored_revision, gateway_hash = self._parse_set_receipt(applied)
            readback = self._read_after_write(
                prewrite,
                restored_revision,
                operation.base.policy_digest,
            )
            self._operations.consume(operation.operation_id)
            return RollbackReceipt(
                restored_revision=restored_revision,
                restored_digest=readback.policy_digest,
                result="restored",
                evidence={
                    "operation_id": operation.operation_id,
                    "gateway_policy_hash": gateway_hash,
                },
            )

    def stream_events(self, cursor: str | None = None) -> EventBatch:
        """注意：这不是行为事件流（P1-2）。

        openshell CLI 没有行为事件通道；这里只能回读 `policy list` 文本，
        事件 type 如实标注为 backend_unavailable/policy_history，source 标注为
        cli_policy_list_readback。消费方不得将其当作策略被执行的行为证据。
        """
        try:
            out = self._cli("policy", "list")
        except AdapterError as exc:
            return EventBatch(
                events=[{"type": "backend_unavailable", "detail": str(exc)[:200]}],
                cursor=cursor,
                source="cli_policy_list_readback",
            )
        return EventBatch(
            events=[{"type": "policy_history", "raw": out.strip()[:500]}],
            cursor=cursor,
            source="cli_policy_list_readback",
        )

    # ------------------------------------------------------------ 解析

    def _parse_policy_yaml(self, out: str) -> dict:
        """`policy get --full` 输出 = 元信息块 + '---' + YAML 策略体。"""
        return parse_policy_output(out)[0]

    def _parse_policy_meta(self, out: str) -> dict:
        return {"Active": parse_policy_output(out)[1]}

    def _network_rules(self, gateway_network: dict) -> list[dict]:
        """网关网络策略 → 产品 Permission Fact 形状的网络规则列表。"""
        return gateway_network_to_rules(gateway_network)

    def _network_rules_to_gateway(self, rules: list[dict]) -> dict:
        return network_rules_to_gateway(rules)

    @contextlib.contextmanager
    def _policy_yaml_file(self, doc: dict) -> Iterator[str]:
        """策略 YAML 临时文件上下文：CLI 子进程读取后立即删除（生命周期限定在本上下文内）。

        文件必须存活到 policy set 子进程读取完成（跨进程消费），故不能用 delete=True 的
        关闭即删语义；mkstemp（0600）+ try/finally 删除，正常/异常路径均不泄漏。
        """
        import tempfile

        fd, path = tempfile.mkstemp(prefix="siq-as-policy-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as fh:
                yaml.safe_dump(doc, fh, sort_keys=False)
            yield path
        finally:
            os.unlink(path)
