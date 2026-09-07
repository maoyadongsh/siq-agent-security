# AgentShield 性能观察基线（DEV16-D）

本目录存放**实测**本地回执链 / 导出耗时观察结果。数字仅供同硬件、同版本对照；**不预填**毫秒 SLA，也不把单次 smoke 跑数当作 1 万 / 10 万验收通过。

## 规格

- 报告 `format`: `agentshield.perf_baseline.v1`
- 字段 `thresholds`: 恒为 `null`（本骨架不做 pass/fail）
- `notes`: 固定诚实声明（Observations only…）

## 规模

| 名称 | 默认回执数 | 用途 |
| --- | ---: | --- |
| `smoke` | 200 | CI / 聚焦验证 |
| `medium` | 10_000 | 计划中的 1 万档，需人工记录硬件后归档 |
| `large` | 100_000 | 计划中的 10 万档，需人工记录硬件后归档 |

## 命令

```bash
cd apps/agentshield
go test -count=1 ./internal/perfbaseline/
go run ./cmd/perfbaseline -scale smoke -out /tmp/perf-smoke.json
# 完整档（勿在无资源声明时当验收）：
# go run ./cmd/perfbaseline -scale medium -out ../../docs/evidence/perf/local-medium-$(date -u +%Y%m%d).json
```

门禁：`python3 scripts/check_perf_baseline_harness.py`（源码诚实检查 + smoke 实测）。

## 未宣称

- 决策路径 p95&lt;200ms（规格另节）不等于本导出/扫盘基线
- 空闲无污点会话过期（另切片）
- 整任务 DEV16 验收

## Intent V2 本地查找基线

```bash
cd apps/agentshield
go run ./cmd/perfbaseline -intent -intent-bindings 1024 -intent-samples 200 -out /tmp/intent-perf.json
```

`intent-bindings` 范围为 1–4096，`intent-samples` 为 1–10000，默认 1 / 200。报告的 `lookup_ms`、`missing_lookup_ms`、`matcher_ms` 均含 p50/p95/p99；不包含初始化、HTTP、回执 fsync 或真实工具执行。

2026-09-07 对照数据在 [`../intent-v2/`](../intent-v2/)：`local-20260907-164340-bindings-*.json` 为目录扫描方案，`local-20260907-164553-direct-bindings-*.json` 为确定性 ID 直接读取方案。每次目标查找仍执行签名与时效检查，未用缓存替代授权。
