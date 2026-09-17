# B07 组件对照复核

仅组件级；B07 总体保持 partial。

| 场景 | 指标 | B0 p95 ms | B1 p95 ms | 相对变化 % | 比较边界 |
| --- | --- | --- | --- | --- | --- |
| A | decide_allow_ms | 7.726 | 7.604 | -1.5790836137716813 | same_external_component_operation |
| A | diagnose_unconfigured_ms | 0.019 | 0.022 | 15.789473684210531 | same_external_component_operation |
| B | decide_allow_auth_ms | 8.238 | 8.583 | 4.187909686817193 | same_external_component_operation |
| B | decide_deny_revoked_ms | 8.441 | 8.7 | 3.0683568297595 | same_external_component_operation |
| C | probe_cold_ms | 4.327 | 4.752 | 9.822047608042528 | changed_probe_workload |
| C | probe_repeat_ms | 4.084 | 4.526 | 10.822722820763953 | changed_probe_workload |
| D | timeout_fail_ms | 30003.426 | 200.969 | -99.33017982679712 | same_external_component_operation |
| E | apply_rollback_cycle_ms | 未测量 | 0.555 | None | no_b0_implementation |

## 必须保留的边界

- B0 D inherited notes mention bounded pipe drainage; b303c6f has no such bound. Raw notes are preserved, this correction supersedes them.
- B0 C does not detect the CLI version; B1 cold probe does. C numbers are observations with changed work, not equivalent-workload acceptance.
- D total fixture wait is 3 * (3 warmups + 60 samples) * 30 seconds = 94.5 minutes, excluding overhead.
- Hash validity attests file integrity, not native/backend verification or absence of background host load.
