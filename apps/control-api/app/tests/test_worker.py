"""worker 循环退避测试：失败指数退避（封顶）+ 成功复位；注入 sleep_fn 不依赖真实时钟。

退避状态只影响下一次尝试时间：outbox 发布等子任务仍由每周期 once() 全量执行（保活语义），
退避不改变 outbox 原子语义（发布仍按事件级幂等标记）。
"""

from __future__ import annotations

import pytest

import app.worker as worker_mod


def _drive_loop(monkeypatch, script: list, stop_after_sleeps: int) -> tuple[list[float], int]:
    """按 script 顺序驱动 loop 的 once()（值为返回值，Exception 为抛出）；sleep_fn 记录退避并终止。

    返回 (每次 sleep 的秒数, once() 被调用的次数)。
    """
    sleeps: list[float] = []
    calls = {"n": 0}

    def fake_once():
        step = script[calls["n"] % len(script)]
        calls["n"] += 1
        if isinstance(step, BaseException):
            raise step
        return step

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= stop_after_sleeps:
            raise KeyboardInterrupt  # 终止无限循环（KeyboardInterrupt 不落入 except Exception）

    monkeypatch.setattr(worker_mod, "once", fake_once)
    with pytest.raises(KeyboardInterrupt):
        worker_mod.loop(60, max_backoff_seconds=300, sleep_fn=sleep_fn)
    return sleeps, calls["n"]


def test_loop_backoff_grows_exponentially_and_caps(monkeypatch):
    """连续失败：60 → 120 → 240 → 300（封顶）→ 300；循环不退出（保活）。"""
    err = RuntimeError("boom")
    sleeps, calls = _drive_loop(monkeypatch, [err] * 5, stop_after_sleeps=5)
    assert sleeps == [60.0, 120.0, 240.0, 300.0, 300.0]
    assert calls == 5  # 失败后仍继续下一周期


def test_loop_backoff_resets_after_success(monkeypatch):
    """成功即复位：fail,fail,ok,fail → 60,120,60,60。"""
    err = RuntimeError("boom")
    sleeps, _ = _drive_loop(monkeypatch, [err, err, {"ok": True}, err], stop_after_sleeps=4)
    assert sleeps == [60.0, 120.0, 60.0, 60.0]


def test_loop_success_keeps_base_interval(monkeypatch):
    """无失败：始终基础间隔。"""
    sleeps, calls = _drive_loop(monkeypatch, [{"ok": True}] * 3, stop_after_sleeps=3)
    assert sleeps == [60.0, 60.0, 60.0]
    assert calls == 3


def test_loop_backoff_cap_respects_configuration(monkeypatch):
    """封顶可配置：max_backoff_seconds=90 → 60 → 90 → 90。"""
    sleeps: list[float] = []
    err = RuntimeError("boom")

    def fake_once():
        raise err

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker_mod, "once", fake_once)
    with pytest.raises(KeyboardInterrupt):
        worker_mod.loop(60, max_backoff_seconds=90, sleep_fn=sleep_fn)
    assert sleeps == [60.0, 90.0, 90.0]
