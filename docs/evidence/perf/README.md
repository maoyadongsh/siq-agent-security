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
