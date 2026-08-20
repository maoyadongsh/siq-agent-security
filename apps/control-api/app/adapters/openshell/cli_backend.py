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

安全约束：
- 仅接受显式的 CLI+网关或绝对 env.sh 路径配置，不隐式依赖相邻仓库；
- 非回环网关强制 HTTPS，拒绝 URL 凭据、路径、查询串和片段；
- 每次调用超时 + 输出上限；任何异常 → AdapterError（fail-closed）。
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
from collections.abc import Callable, Iterator
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.adapters.openshell.base import EnforcementAdapter
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
    RollbackReceipt,
    SandboxPage,
    ValidationReport,
    VerificationFailed,
    VerificationReport,
)
from app.adapters.openshell.policy_compiler import compile_policy, validate_compiled

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")

# 实测捕获的真实输出（测试夹具同源）
_VERSION_SUBMITTED_RE = re.compile(r"Policy version (\d+) submitted \(hash: ([0-9a-f]+)\)")
# 实测：内容与当前一致时网关返回 no-op（幂等重放）
_VERSION_UNCHANGED_RE = re.compile(r"Policy unchanged \(version (\d+), hash: ([0-9a-f]+)\)")

# 保守版本解析：只认 "…version…: vX.Y.Z" 或行首 "openshell … X.Y.Z" 形状，
# 不匹配任意点分三元组（避免把 gateway endpoint 的 127.0.0.1 误判成版本）。
_VERSION_LINE_RE = re.compile(r"(?im)^[^\n]*\bversion\b[^\n0-9]{0,16}v?(\d+\.\d+\.\d+)")
_CLI_VERSION_RE = re.compile(r"(?im)^\s*openshell(?:\s+version)?[\s:v-]{0,4}(\d+\.\d+\.\d+)")


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
    return {
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
        "tools_mcp": CapabilityItem(
            status="unknown", semantics="none", basis="interceptor/工具治理未经实测（不猜测）"
        ),
        "model_routing": CapabilityItem(
            status="unsupported", semantics="none", basis="provider 凭据注入未经实测（保守拒绝）"
        ),
        "secrets": CapabilityItem(
            status="unsupported", semantics="none", basis="凭据注入能力未经实测（保守拒绝，§15.2 由 Provider 侧承担）"
        ),
        "resources": CapabilityItem(
            status="unknown", semantics="none", basis="资源配额语义未经实测"
        ),
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
    ):
        self._env_script = env_script if env_script is not None else _default_env_script()
        self._runner = runner or self._subprocess_runner
        self._docker_runner = docker_runner  # None = 原始 docker 子进程
        self._artifacts: dict[str, CompiledPolicy] = {}  # compile 注册，apply 引用
        # 版本探测缓存：None = 未探测；"unknown" = 探测失败/输出不可解析
        self._detected_version: str | None = None

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
            raise AdapterError(
                "OpenShell CLI 未配置：设置 CLI_BIN + GATEWAY_ENDPOINT，或显式设置 OPENSHELL_ENV_SH"
            )
        return cmd

    def _subprocess_runner(self, args: list[str]) -> tuple[int, str, str]:
        cmd = self._build_command(args)
        # B4 环境变量白名单加固：过滤宿主敏感凭据，仅透传基础环境变量与显式配置
        safe_keys = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "TERM"}
        clean_env = {
            k: v for k, v in os.environ.items()
            if k in safe_keys or k.startswith("SIQ_AS_") or k.startswith("OPENSHELL_")
        }
        clean_env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=clean_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"openshell CLI 超时（fail-closed）: {exc}") from exc
        except OSError as exc:
            raise AdapterError(f"无法执行 openshell CLI（fail-closed）: {exc}") from exc
        return proc.returncode, proc.stdout, proc.stderr

    def _cli(self, *args: str) -> str:
        """执行 CLI；成功输出可能落在 stdout 或 stderr（实测 policy set 的 ✓ 回执在 stderr）。"""
        rc, stdout, stderr = self._runner(list(args))
        clean_out = _ANSI_RE.sub("", stdout)
        clean_err = _ANSI_RE.sub("", stderr)
        if rc != 0:
            raise AdapterError(f"openshell {' '.join(args)} 失败(rc={rc}): {(clean_err or clean_out).strip()[:300]}")
        return clean_out + "\n" + clean_err

    # ------------------------------------------------------------ 合同实现

    def probe(self) -> BackendCapabilities:
        """可达性 + 真实版本探测；能力值只反映已实测验证的语义。

        - `gateway info` 失败 → fail-closed（可达性是探测前提，保持现状）；
        - 版本探测失败仅令 schema_version 退化为 "unknown-policy-v1"，不让 probe
          整体失败（可达性已由 gateway info 证明），也绝不编造版本号；
        - 能力值不因检测到新版本而上调：布尔字段依据见下方逐行注释，
          版本化能力文档（capabilities）逐项标注 status/semantics/basis，
          未实测的能力一律 unknown 或 unsupported（P1-1，不得猜 supported）。
        """
        info_out = self._cli("gateway", "info")  # 探测网关可达性；失败 fail-closed
        version = self._detect_version(info_out)
        caps = BackendCapabilities(
            backend="openshell",
            schema_version=f"v{version}-policy-v1" if version != "unknown" else "unknown-policy-v1",
            dynamic_network_update=True,  # 2026-08-13 实测：网络段热更新成功（静态段锁定）
            static_filesystem=True,  # 实测：活沙箱 filesystem 变更被拒绝
            static_process=True,  # 实测：process 段同属静态边界（创建时锁定）
            landlock=True,  # SIQ landlock patch 在 v0.0.83 运行网关中；v0.0.104 上游已内置（ADR-009）
            interceptor=False,  # 未经任何版本实测验证（保守 False，不按新版本猜测）
            provider_credential_injection=False,  # 未经实测验证（保守 False）
            revision_support=True,  # 实测：policy list / --rev 回读可用
            max_filesystem_paths=1024,  # 合同默认值，未经网关实测上限
            capabilities=_cli_capability_document(),
        )
        return caps

    def _detect_version(self, gateway_info_output: str) -> str:
        """真实版本探测：先解析 gateway info 输出，再回退 `--version`。

        解析基于保守正则；任何一步失败都返回 "unknown" 且不抛错
        （版本缺失不掩盖可达性事实，也不编造版本号）。结果缓存供
        list_targets 的 docker 回退退役判定使用。
        """
        version = _parse_version(gateway_info_output)
        if version is None:
            try:
                version = _parse_version(self._cli("--version"))
            except AdapterError:
                version = None
        self._detected_version = version or "unknown"
        return self._detected_version

    def _detected_version_at_least(self, minimum: tuple[int, int, int]) -> bool:
        """已探测版本 >= minimum？未知/未探测一律 False（保守，不放宽行为）。"""
        if not self._detected_version or self._detected_version == "unknown":
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
            if self._detected_version_at_least((0, 0, 104)):
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
            if rc != 0:
                raise AdapterError(f"docker 目标发现失败(rc={rc}): {error.strip()[:200]}")
        else:
            try:
                proc = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10
                )
                if proc.returncode != 0:
                    raise AdapterError(
                        f"docker 目标发现失败(rc={proc.returncode}): {proc.stderr.strip()[:200]}"
                    )
                out = proc.stdout
            except subprocess.TimeoutExpired as exc:
                raise AdapterError("docker 目标发现超时（fail-closed）") from exc
            except OSError as exc:
                raise AdapterError(f"无法执行 docker 目标发现（fail-closed）: {exc}") from exc
        names = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("openshell-") and len(line) > len("openshell-") + 36:
                # 容器名 = openshell-<沙箱名>-<uuid36>；沙箱名可含 '-'
                names.append(line[len("openshell-") : -37])
        return SandboxPage(targets=[{"id": n} for n in sorted(set(names))], cursor=None)

    def read_effective_policy(self, target: str) -> PolicySnapshot:
        out = self._cli("policy", "get", target, "--full")
        doc = self._parse_policy_yaml(out)
        meta = self._parse_policy_meta(out)
        return PolicySnapshot(
            target=target,
            revision=str(meta.get("Active", meta.get("Version", "1"))),
            filesystem=doc.get("filesystem_policy") or {},
            network=self._network_rules(doc.get("network_policies") or {}),
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
        kind = "generation" if compiled.needs_generation else "dynamic"
        return ChangePlan(
            target=target,
            kind=kind,
            expected_revision=current.revision,
            artifact_hash=compiled.artifact_hash,
            steps=[f"policy set {target}（动态）" if kind == "dynamic" else f"sandbox create {target}（重建）"],
        )

    def apply_dynamic(self, target: str, plan: ChangePlan, expected_revision: str) -> DeploymentReceipt:
        """实测语义：合并当前策略（静态段必须原样）+ 替换网络段 → policy set。"""
        current = self.read_effective_policy(target)
        if current.revision != expected_revision:
            from app.adapters.openshell.contracts import RevisionConflict

            raise RevisionConflict(expected=expected_revision, actual=current.revision)
        compiled = self._artifacts.get(plan.artifact_hash)
        if compiled is None:
            raise AdapterError("未知制品哈希，拒绝发布（fail-closed）")
        merged = {
            "version": 1,
            "filesystem_policy": current.filesystem,
            "landlock": {"compatibility": "best_effort"},
            "process": current.process,
            "network_policies": self._network_rules_to_gateway(compiled.artifact.get("network_policies") or []),
        }
        with self._policy_yaml_file(merged) as policy_file:
            out = self._cli("policy", "set", target, "--policy", policy_file)
        match = _VERSION_SUBMITTED_RE.search(out) or _VERSION_UNCHANGED_RE.search(out)
        if not match:
            raise AdapterError(f"无法解析 policy set 回执（fail-closed）: {out.strip()[:200]}")
        new_revision = match.group(1)
        return DeploymentReceipt(
            backend_revision=new_revision,
            evidence={"snapshot_hash": match.group(2), "submitted": new_revision},
            applied_at=None,
        )

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
        if not allow_checks or not deny_checks:
            failures.append("正负向验证必须各至少一项（§15.3）")
        passed = not failures
        return VerificationReport(
            passed=passed,
            level=VERIFY_LEVEL_READBACK if passed else VERIFY_LEVEL_FAILED,
            allow_checks=allow_checks,
            deny_checks=deny_checks,
            failures=failures,
        )

    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        raw_rev = str(receipt.backend_revision or "").strip()
        if not raw_rev:
            raise AdapterError("回执缺少 backend_revision，无法计算回滚目标（fail-closed）")
        try:
            prev_rev = int(raw_rev) - 1
        except ValueError:
            raise AdapterError(f"backend_revision 非法（无法解析为整数，fail-closed）: {raw_rev!r}") from None
        if prev_rev < 1:
            raise VerificationFailed("无可回滚的上一 revision")
        out = self._cli("policy", "get", target, "--rev", str(prev_rev), "--full")
        prev_doc = self._parse_policy_yaml(out)
        with self._policy_yaml_file(prev_doc) as policy_file:
            applied = self._cli("policy", "set", target, "--policy", policy_file)
        match = _VERSION_SUBMITTED_RE.search(applied) or _VERSION_UNCHANGED_RE.search(applied)
        if not match:
            # 回执不可解析即失败（fail-closed），不伪造 restored_revision
            raise AdapterError(f"无法解析回滚 policy set 回执（fail-closed）: {applied.strip()[:200]}")
        return RollbackReceipt(restored_revision=match.group(1), evidence={"applied": applied.strip()[:120]})

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
        marker = out.find("---")
        body = out[marker + 3 :] if marker != -1 else out
        try:
            doc = yaml.safe_load(body) or {}
        except yaml.YAMLError as exc:
            raise AdapterError(f"策略 YAML 解析失败（fail-closed）: {exc}") from exc
        return doc

    def _parse_policy_meta(self, out: str) -> dict:
        meta: dict = {}
        for line in out.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("-"):
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        return meta

    def _network_rules(self, gateway_network: dict) -> list[dict]:
        """网关网络策略 → 产品 Permission Fact 形状的网络规则列表。"""
        rules = []
        for key, rule in (gateway_network or {}).items():
            if not isinstance(rule, dict):
                continue
            for ep in rule.get("endpoints") or []:
                rules.append(
                    {
                        "endpoint": f"{ep.get('host')}:{ep.get('port')}",
                        "effect": "allow",
                        "binary_paths": [b.get("path") for b in rule.get("binaries") or []],
                        "rule_name": rule.get("name", key),
                    }
                )
        return rules

    def _network_rules_to_gateway(self, rules: list[dict]) -> dict:
        gateway: dict = {}
        for idx, rule in enumerate(rules):
            endpoint = rule.get("endpoint", "")
            host, _, rest = endpoint.partition(":")
            port_str, _, path = rest.partition("/")
            # v0.0.83 端点模型为 host:port；"/**" 全通配等价于无路径限制可剥离，
            # 其他 path 粒度按 §15.2 "未知语义拒绝"（不静默弱化）
            if path and path != "**":
                raise AdapterError(f"path 级网络规则不被 v0.0.83 支持（拒绝编译）: {endpoint}")
            gateway[f"siq_as_rule_{idx}"] = {
                "name": rule.get("rule_name", f"siq-as-rule-{idx}"),
                "endpoints": [{"host": host, "port": int(port_str or 443)}],
                "binaries": [{"path": bp} for bp in rule.get("binary_paths") or ["/usr/bin/curl"]],
            }
        return gateway

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
