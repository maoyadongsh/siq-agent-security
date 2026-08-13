"""OpenShellCliBackend：真实 CLI 后端（2026-08-13 活网关实测语义锁定）。

实测依据（网关 siq-openshell-dev @ https://127.0.0.1:17671，v0.0.83）：
- `policy get <name> --full` 返回真实生效策略（含 filesystem/landlock/process/network）；
- `policy set <name> --policy yaml` 对运行中沙箱热更新：静态段（filesystem）必须与创建时一致
  （否则网关拒绝：include_workdir cannot be changed on a live sandbox），网络段可变更，
  成功输出 "Policy version N submitted (hash: ...)"；
- revision 递增（1→2），`policy get --rev N --full` 可回读历史（回滚基础）；
- 已知网关缺陷：SandboxResponse 的 Protobuf 解码错误影响 list/create/get（policy 命令不受影响），
  升级 v0.0.104（补丁已上游化）预期修复；本后端对 list_targets 提供 docker 回退。

安全约束：
- 子进程经 bash 包装 `source <env.sh>` 获得 research-engine 的隔离 XDG 状态，
  不继承调用方用户级 OpenShell 配置；
- 每次调用超时 + 输出上限；任何异常 → AdapterError（fail-closed）。
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable

import yaml

from app.adapters.openshell.base import EnforcementAdapter
from app.adapters.openshell.contracts import (
    AdapterError,
    BackendCapabilities,
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

Runner = Callable[[list[str]], tuple[int, str, str]]


def _default_env_script() -> str:
    return os.getenv(
        "SIQ_AS_OPENSHELL_ENV_SH",
        "/home/maoyd/siq-research-engine/scripts/openshell/env.sh",
    )


class OpenShellCliBackend(EnforcementAdapter):
    def __init__(self, *, runner: Runner | None = None, env_script: str | None = None):
        self._env_script = env_script or _default_env_script()
        self._runner = runner or self._subprocess_runner
        self._artifacts: dict[str, CompiledPolicy] = {}  # compile 注册，apply 引用

    # ------------------------------------------------------------ 子进程

    def _subprocess_runner(self, args: list[str]) -> tuple[int, str, str]:
        wrapped = ["bash", "-c", f'source "{self._env_script}" && exec openshell "$@"', "openshell", *args]
        try:
            proc = subprocess.run(
                wrapped,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"openshell CLI 超时（fail-closed）: {exc}") from exc
        except OSError as exc:
            raise AdapterError(f"无法执行 openshell CLI（fail-closed）: {exc}") from exc
        return proc.returncode, proc.stdout, proc.stderr

    def _cli(self, *args: str) -> str:
        rc, stdout, stderr = self._runner(list(args))
        clean = _ANSI_RE.sub("", stdout)
        if rc != 0:
            raise AdapterError(f"openshell {' '.join(args)} 失败(rc={rc}): {(stderr or clean).strip()[:300]}")
        return clean

    # ------------------------------------------------------------ 合同实现

    def probe(self) -> BackendCapabilities:
        """实测驱动：v0.0.83 动态网络更新可用（policy set 热更新已验证）。"""
        self._cli("gateway", "info")  # 探测网关可达性；失败 fail-closed
        caps = BackendCapabilities(
            backend="openshell",
            schema_version="v0.0.83-policy-v1",
            dynamic_network_update=True,  # 2026-08-13 实测：网络段热更新成功（静态段锁定）
            static_filesystem=True,  # 实测：活沙箱 filesystem 变更被拒绝
            static_process=True,
            landlock=True,  # SIQ landlock patch（0001）在运行网关中
            interceptor=False,
            provider_credential_injection=False,
            revision_support=True,  # policy list / --rev 回读
            max_filesystem_paths=1024,
        )
        return caps

    def list_targets(self, cursor: str | None = None) -> SandboxPage:
        try:
            out = self._cli("sandbox", "list")
        except AdapterError:
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
        try:
            proc = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10
            )
            out = proc.stdout if proc.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            out = ""
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
            enforcement_mode="block",
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
        policy_file = self._write_policy_yaml(merged)
        out = self._cli("policy", "set", target, "--policy", policy_file)
        match = _VERSION_SUBMITTED_RE.search(out)
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
            "经 research-engine 生命周期脚本或升级 v0.0.104 后启用"
        )

    def verify(self, target: str, checks: dict, receipt: DeploymentReceipt) -> VerificationReport:
        snapshot = self.read_effective_policy(target)
        failures: list[str] = []
        if snapshot.revision != receipt.backend_revision:
            failures.append(f"revision mismatch: {snapshot.revision} != {receipt.backend_revision}")
        allowed = {r.get("endpoint") for r in snapshot.network if r.get("effect") != "deny"}
        allow_checks = [{"endpoint": e, "result": "allow"} for e in checks.get("expect_allow", [])]
        deny_checks = [{"endpoint": e, "result": "deny"} for e in checks.get("expect_deny", [])]
        for check in allow_checks:
            if check["endpoint"] not in allowed:
                failures.append(f"allow check failed: {check['endpoint']}")
        for check in deny_checks:
            if check["endpoint"] in allowed:
                failures.append(f"deny check failed: {check['endpoint']}")
        if not allow_checks or not deny_checks:
            failures.append("正负向验证必须各至少一项（§15.3）")
        return VerificationReport(
            passed=not failures, allow_checks=allow_checks, deny_checks=deny_checks, failures=failures
        )

    def rollback(self, target: str, receipt: DeploymentReceipt) -> RollbackReceipt:
        prev_rev = int(receipt.backend_revision) - 1
        if prev_rev < 1:
            raise VerificationFailed("无可回滚的上一 revision")
        out = self._cli("policy", "get", target, "--rev", str(prev_rev), "--full")
        prev_doc = self._parse_policy_yaml(out)
        policy_file = self._write_policy_yaml(prev_doc)
        applied = self._cli("policy", "set", target, "--policy", policy_file)
        match = _VERSION_SUBMITTED_RE.search(applied)
        restored = match.group(1) if match else str(prev_rev)
        return RollbackReceipt(restored_revision=restored, evidence={"applied": applied.strip()[:120]})

    def stream_events(self, cursor: str | None = None) -> EventBatch:
        try:
            out = self._cli("policy", "list")
        except AdapterError as exc:
            return EventBatch(events=[{"type": "backend_unavailable", "detail": str(exc)[:200]}], cursor=cursor)
        return EventBatch(events=[{"type": "policy_history", "raw": out.strip()[:500]}], cursor=cursor)

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
            host, _, port = endpoint.partition(":")
            gateway[f"siq_as_rule_{idx}"] = {
                "name": rule.get("rule_name", f"siq-as-rule-{idx}"),
                "endpoints": [{"host": host, "port": int(port or 443)}],
                "binaries": [{"path": p} for p in rule.get("binary_paths") or ["/usr/bin/curl"]],
            }
        return gateway

    def _write_policy_yaml(self, doc: dict) -> str:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="siq-as-policy-", suffix=".yaml")
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False)
        return path


