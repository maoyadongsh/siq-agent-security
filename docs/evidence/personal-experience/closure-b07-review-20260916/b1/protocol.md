# O04-D 冻结测量协议（B1：改造后 native 组件）

本协议在测量前冻结；不得因结果调整。冻结项：

- 轮数：3；A/B 交错顺序：[['A', 'B', 'B', 'A'], ['B', 'A', 'A', 'B'], ['A', 'B', 'B', 'A']]；C/D/E 每轮各测一次
- 预热（丢弃）：{"A": {"decide_allow": 5}, "B": {"decide_allow_auth": 5, "decide_deny_revoked": 3}, "C": {"probe_repeat": 3, "probe_cold": 0}, "D": {"timeout_fail": 3}, "E": {"apply_rollback_cycle": 5}}
- 每轮样本量：{"A": {"decide_allow_ms": 200, "diagnose_unconfigured_ms": 200}, "B": {"decide_allow_auth_ms": 200, "decide_deny_revoked_ms": 200}, "C": {"probe_cold_ms": 1, "probe_repeat_ms": 200}, "D": {"timeout_fail_ms": 60}, "E": {"apply_rollback_cycle_ms": 200}}（D 故障注入路径冻结为 60，非热路径）
- 百分位算法：nearest-rank on sorted samples (ceil(p/100*n))
- 剔除规则：none: any failed operation aborts the run; in D the timeout failure IS the measured event
- 冻结预算（ms）：{"A": {"decide_allow_ms": {"p95": 25.0}, "diagnose_unconfigured_ms": {"p95": 25.0}}, "B": {"decide_allow_auth_ms": {"p95": 25.0}, "decide_deny_revoked_ms": {"p95": 25.0}}, "C": {"probe_cold_ms": {"p95": 200.0}, "probe_repeat_ms": {"p95": 50.0}}, "D": {"timeout_fail_ms": {"p95": 300.0, "max": 500.0}}, "E": {"apply_rollback_cycle_ms": {"p95": 100.0}}}
- 预算依据：frozen before measuring: p95 budgets sized at multiples of pre-study component magnitudes; B1-B0 relative budget is P95 increase <=10% but the B0 pre-change baseline requires a separate checkout and is not produced here
- B1−B0 相对预算：P95 增幅 ≤10%（B0 对照本轮不可测，见 report.json not_measured）
- B2/B3：blocked，缺真实后端

## 证据分级

- 场景 A：component_in_process
- 场景 B：component_in_process
- 场景 C：component_real_subprocess_fixture
- 场景 D：component_real_subprocess_fault_injection
- 场景 E：component_in_process_fixture_cli

全部为组件级证据：无真实网关、无主机端到端。测量期间不运行全量测试或构建负载。
