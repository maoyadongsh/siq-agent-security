"""`scripts/openshell_compat_check.py --live` 的合成回归守卫。

被测脚本在 `scripts/`（不在本目录），但它属于"本轮工具"，其测试按本轮既有约定
放在 `scripts/enterprise-experience/`，以便被同一条命令收走：

    pytest scripts/enterprise-experience

**本测试不接触任何网关、不发任何真实 CLI、不产生任何 `policy set`。** 它用一个
鸭类型假后端替换 `OpenShellCliBackend`，只钉住三件事：

1. `_live_check` **必须**把 authorizer 传给 `rollback`——早期版本不传，后端必抛
   `openshell_rollback_authorizer_required`，结果就是"写成功但回不去"；
2. authorizer **只认这一次操作**（operation_id + target），换一个操作 id 必须为假；
3. 写入后**无论成功失败都必须尝试回滚**，且回滚后读回与 BEFORE 不一致时必须判红。

另钉一条：`plan.kind != "dynamic"` 时**一个字节都不许写**（既无 apply 也无 rollback）。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "openshell_compat_check.py"
sys.path.insert(0, str(ROOT / "apps" / "control-api"))

_SPEC = importlib.util.spec_from_file_location("openshell_compat_check", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

from app.adapters.openshell.contracts import RollbackAuthorization  # noqa: E402


@dataclass(frozen=True)
class FakeSnapshot:
    revision: str
    policy_digest: str
    network: list = field(default_factory=list)


class FakeReceipt:
    def __init__(self, operation_id: str, backend_revision: str):
        self.operation_id = operation_id
        self.backend_revision = backend_revision
        self.applied_policy_digest = "d-applied"


class FakeRollbackReceipt:
    def __init__(self, restored_revision: str):
        self.restored_revision = restored_revision
        self.result = "restored"


class FakeCompiled:
    unsupported_by_backend: list = []


class FakePlan:
    def __init__(self, kind: str):
        self.kind = kind
        self.expected_revision = "rev-1"


class FakeReport:
    def __init__(self, passed: bool, failures: list | None = None):
        self.passed = passed
        self.level = "readback_verified" if passed else "failed"
        self.failures = failures or []


class FakeBackend:
    """只实现 `_live_check` 用到的方法；记录调用次序，供断言检查。"""

    def __init__(self, *, plan_kind="dynamic", verify_raises=False, verify_passed=True,
                 after_digest=None):
        self.calls: list[str] = []
        self.rollback_authorizer = "not_called"
        self.rollback_authorization = None
        self._plan_kind = plan_kind
        self._verify_raises = verify_raises
        self._verify_passed = verify_passed
        self._after_digest = after_digest
        self._before = FakeSnapshot("rev-1", "d-before", [{"endpoint": "api.kimi.com:443"}])
        self._wrote = False

    def read_effective_policy(self, target):
        self.calls.append("read")
        # 首次读 = BEFORE；写入后读 = AFTER（可由用例指定为漂移值）
        if self._wrote and self._after_digest is not None:
            return FakeSnapshot("rev-9", self._after_digest, [])
        return self._before

    def compile(self, desired):  # noqa: A003 - 与后端接口同名
        self.calls.append("compile")
        self.compiled_desired = desired
        return FakeCompiled()

    def plan_change(self, target, compiled):
        self.calls.append("plan")
        return FakePlan(self._plan_kind)

    def apply_dynamic(self, target, plan, expected_revision):
        self.calls.append("apply")
        self._wrote = True
        return FakeReceipt("opo-synthetic-1", "rev-2")

    def verify(self, target, checks, receipt):
        self.calls.append("verify")
        if self._verify_raises:
            raise RuntimeError("synthetic verify failure")
        return FakeReport(self._verify_passed, [] if self._verify_passed else ["synthetic"])

    def rollback(self, target, receipt, authorizer=None):
        self.calls.append("rollback")
        self.rollback_authorizer = authorizer
        if authorizer is None:
            # 复刻真实后端：无作者即拒，且 refusal 发生在写入之前
            raise RuntimeError("openshell_rollback_authorizer_required")
        authorization = RollbackAuthorization(
            operation_id=receipt.operation_id,
            target=target,
            current=self._before,
            restore=self._before,
        )
        self.rollback_authorization = authorization
        if not authorizer(authorization):
            raise RuntimeError("openshell_rollback_authorization_failed")
        return FakeRollbackReceipt("rev-3")


def test_happy_path_passes_and_records_receipt():
    backend = FakeBackend()
    out: dict = {}
    assert tool._live_check(backend, "sandbox-synthetic", out) is True  # noqa: SLF001
    assert backend.calls == ["read", "compile", "plan", "apply", "verify", "rollback", "read"]
    assert out["before_revision"] == "rev-1"
    assert out["applied_revision"] == "rev-2"
    assert out["restored_revision"] == "rev-3"
    assert out["restored_digest_matches_before"] is True
    assert out["rollback_attempted"] is True


def test_rollback_is_always_given_an_authorizer():
    """⚠️ 核心回归：不传 authorizer 时真实后端必然拒绝回滚 —— 这正是缺陷本身。"""
    backend = FakeBackend()
    tool._live_check(backend, "sandbox-synthetic")  # noqa: SLF001
    assert backend.rollback_authorizer not in (None, "not_called")


def test_authorizer_only_accepts_this_operation():
    backend = FakeBackend()
    tool._live_check(backend, "sandbox-synthetic")  # noqa: SLF001
    authorize = backend.rollback_authorizer
    good = backend.rollback_authorization
    assert authorize(good) is True
    # 换一个操作 id / 换一个目标都必须为假
    assert authorize(RollbackAuthorization(good.operation_id + "x", good.target, good.current, good.restore)) is False
    assert authorize(RollbackAuthorization(good.operation_id, "other-sandbox", good.current, good.restore)) is False


def test_rollback_attempted_even_when_verify_raises():
    backend = FakeBackend(verify_raises=True)
    try:
        tool._live_check(backend, "sandbox-synthetic")  # noqa: SLF001
    except RuntimeError:
        pass  # 异常该往外抛，但回滚必须先发生
    assert "rollback" in backend.calls, "verify 抛异常时仍必须尝试回滚"


def test_failed_verify_returns_false_but_still_rolls_back():
    backend = FakeBackend(verify_passed=False)
    assert tool._live_check(backend, "sandbox-synthetic") is False  # noqa: SLF001
    assert "rollback" in backend.calls


def test_rollback_that_does_not_restore_before_digest_is_red():
    """回滚"成功"但读回内容与 BEFORE 不同 → 必须判红，不许只看 rollback 没抛异常。"""
    backend = FakeBackend(after_digest="d-still-wrong")
    assert tool._live_check(backend, "sandbox-synthetic") is False  # noqa: SLF001


def test_live_fixture_network_rules_carry_absolute_binary_paths():
    """缺 `binary_paths` 会在 `compile()` 阶段抛 `openshell_network_binary_required`。

    早期版本的 fixture 缺这一段，`--live` 其实**从未真正写入过**——它永远在这一步
    就失败，因此"写后回不去"的缺陷也一直没被发现。这条用例把它钉住。
    """
    backend = FakeBackend()
    tool._live_check(backend, "sandbox-synthetic")  # noqa: SLF001
    rules = backend.compiled_desired["network"]
    assert rules, "fixture 必须至少含一条网络规则"
    for rule in rules:
        binaries = rule.get("binary_paths")
        assert isinstance(binaries, list) and binaries, f"规则缺 binary_paths: {rule}"
        assert all(isinstance(p, str) and p.startswith("/") for p in binaries), rule


def test_non_dynamic_plan_writes_nothing():
    backend = FakeBackend(plan_kind="generation")
    assert tool._live_check(backend, "sandbox-synthetic") is False  # noqa: SLF001
    assert backend.calls == ["read", "compile", "plan"]
    assert "apply" not in backend.calls and "rollback" not in backend.calls
