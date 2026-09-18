# B07 闭环证据：OpenShell O00/O04 真实 B0/B1 同协议对照

## 1. 范围
- B0 = `b303c6f`（TRUE B0：O01–O03 与 O04 之前），B1 = `dafb4cd`（当前候选）。
- 同一冻结协议（Rounds=3、固定预热/样本/轮次交错、最近邻秩百分位、不剔除失败、完整留样），
  同机顺序单独运行（§15.5），无并行负载。
- B2/B3（真实网关/驱动环境）blocked：本机无可用真实后端，登记缺口。

## 2. 关键事实（p95，ms）
| 场景/指标 | B0 p95 | B1 p95 | Δ(B1−B0) | 判定 |
| --- | --- | --- | --- | --- |
| A/decide_allow_ms | 7.726 | 11.911 | +54.17% | over_budget |
| A/diagnose_unconfigured_ms | 0.019 | 0.022 | +15.79% | over_budget |
| B/decide_allow_auth_ms | 8.238 | 11.597 | +40.77% | over_budget |
| B/decide_deny_revoked_ms | 8.441 | 11.98 | +41.93% | over_budget |
| C/probe_cold_ms | 4.327 | 4.553 | +5.22% | within_budget |
| C/probe_repeat_ms | 4.084 | 3.994 | -2.20% | within_budget |
| D/timeout_fail_ms | 30003.426 | 200.808 | -99.33% | improved |
| E/apply_rollback_cycle_ms | not_measured | 0.585 | — | not_measured |

- 相对预算：A/B/C 场景 B1 p95 增幅 ≤10%；D 预期为改进方向（B1 有界排水 vs B0 无界）。
- budget_misses：A decide_allow_ms: p95 +54.2% > 10%；A diagnose_unconfigured_ms: p95 +15.8% > 10%；B decide_allow_auth_ms: p95 +40.8% > 10%；B decide_deny_revoked_ms: p95 +41.9% > 10%
- 未启用时零后端进程/请求：协议在隔离环境运行，scenario A diagnose_unconfigured 证明未配置路径不产生后端请求。
- 运行过程披露（双跑事故）：B0 完成后曾有两次 B1 运行几乎完全重叠（预排自动链
  `/tmp/siq-b07-review-b1-20260916` 02:13:33–02:14:51 与 compaction 后手动重启的
  `openshell-o04-perf-20260916-021336` 02:13:36–02:14:54 UTC），互相污染、违反 §15.5；
  两份运行与其派生对照 `closure-b07-20260916-021548` 均已加 INVALID 标记，不用于本对照。
  本对照使用其后的单独干净 B1 运行 `openshell-o04-perf-20260916-022051`。
- 一致性佐证：被污染运行的 A/B 数值（12.283/12.638/12.289ms）与干净运行（11.911/11.597/11.980ms）
  接近，表明 A/B 相对预算未中在当前环境下可复现，非双跑伪影。
- 噪声底披露：同一 B1 提交 `dafb4cd` 的早前非正式运行（`openshell-o04-perf-20260915-224205`，
  已加 NOT-OFFICIAL 标记）测得 A decide_allow p95=7.855ms，与本次 11.911ms 相差约 −34%——
  同提交运行间波动与测得的回归量级相当。因此 over_budget 判定不能归因于
  `b303c6f→dafb4cd` 的具体产品改动；按冻结协议（不剔除、不重跑挑选）如实记录，不作归因结论。
  A/diagnose_unconfigured 的 +15.8% 为亚毫秒级（0.019→0.022ms），绝对噪声主导。

## 3. 覆盖与遗漏
- 覆盖：A（诊断+决策）、B（授权/撤销决策）、C（冷/热探针）、D（超时故障注入 fail-return）。
- not_measured：场景 E（B0 无 RollbackAuthorized——O01–O03 新增能力，无可对照历史，可证明的对照范围即 A–D）；
  B2/B3 真网性能与能力证据。
- B0 harness 适配披露（不触及被测计时操作）：见 comparison.json disclosure。

## 4. 隔离与安全
- 测量在各自独立 checkout/工作区运行；未触碰真实 ~/.openclaw、~/.config/siq-agent-security/；
  未改系统时钟、全局网络、生产服务；无付费模型或生产端点调用。

## 5. 复现
```
git worktree add --detach /tmp/siq-b07-b0 b303c6f   # B0 checkout（harness 移植见 disclosure）
cd /tmp/siq-b07-b0 && python3 scripts/personal-experience/openshell-o04-perf-protocol.py   # 单独运行
cd <b1-worktree> && python3 scripts/personal-experience/openshell-o04-perf-protocol.py     # 单独运行
python3 /tmp/assemble-b07-evidence.py <b0-dir> <b1-dir>
```

## 6. 证据文件
- b0-report.json / b0-samples.json / b0-protocol.md / b0-source-hashes.json / b0-SHA256SUMS
- b1-report.json / b1-samples.json / b1-protocol.md / b1-source-hashes.json / b1-SHA256SUMS
- comparison.json —— 逐指标对照与披露
- environment.json / SHA256SUMS
