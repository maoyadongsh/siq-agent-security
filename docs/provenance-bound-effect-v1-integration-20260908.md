# Provenance-Bound Effect V1 集成核验（2026-09-08）

本地源码：`95e425c`；分支`codex/provenance-bound-effect-v1`，运行前工作树干净。完整目标仍进行中，本报告不是最终Engineering Report或45项DoD全部通过声明。

## 运行结果

- `python3 benchmarks/runtime-security/run.py --out /tmp/siq-integration-current.json`：21对/42场景/20类别通过。
- `apps/control-api/.venv/bin/python benchmarks/runtime-security/evidence.py /tmp/siq-integration-current.json`：51条回执/11个效果封套验证通过。
- `python3 benchmarks/runtime-security/recovery_fixture.py --out /tmp/siq-integration-recovery.json`：两次真实SIGKILL与恢复通过。
- `apps/control-api/.venv/bin/python benchmarks/runtime-security/recovery_evidence.py /tmp/siq-integration-recovery.json`：2pending/2接管/1撤销/1决定/1单文件Completion验证通过。
- `python3 benchmarks/runtime-security/performance.py --out /tmp/siq-integration-performance.json`：八阶段实际样本及百分位导出成功。
- scenario合同检查、17项benchmark单测、Ruff全部通过。

## 实际阶段分母

D2表示动作尝试，D3表示执行，D4表示效果观测，D5表示独立核实的目标效果发生；positive不统一等价为“攻击成功”。deny后故意绕过的受控写入也会出现D5 positive，并必须作为incident呈现。D0/D1无模型观测，保持未评估。

| 样本类别 | 阶段 | positive | negative | 未评估 | 已评估分母 |
| --- | --- | --- | --- | --- | --- |
| attack | D0 | 0 | 0 | 21 | 0 |
| attack | D1 | 0 | 0 | 21 | 0 |
| attack | D2 | 21 | 0 | 0 | 21 |
| attack | D3 | 4 | 4 | 13 | 8 |
| attack | D4 | 3 | 2 | 16 | 5 |
| attack | D5 | 3 | 2 | 16 | 5 |
| benign | D0 | 0 | 0 | 21 | 0 |
| benign | D1 | 0 | 0 | 21 | 0 |
| benign | D2 | 21 | 0 | 0 | 21 |
| benign | D3 | 8 | 0 | 13 | 8 |
| benign | D4 | 6 | 0 | 15 | 6 |
| benign | D5 | 6 | 0 | 15 | 6 |

D5总计只评估11个样本，31个未评估；不得宣称42个样本都有独立效果证据。未评估包括未执行目标工具或没有适用oracle的场景，不能自动当作失败或成功。

## 性能和证据摘要

性能报告见下方归档摘要，原始样本保留在本地/tmp报告。性能fixture使用实际计时，测量期间并行运行其他独立验证任务，可能有CPU/磁盘竞争；该结果是本机组件基线，不能作为生产SLA或端到端延迟。

| 产物 | SHA256 |
| --- | --- |
| siq-integration-current.json | `89731ec60e5deacecaa408c67b62fea5729d7ab27eaf3f63a60d9bf93214b67a` |
| siq-integration-recovery.json | `61f1d7b7c2b2ba941dba7d8a3db36a97c14bdf09af5cfae6b7964c91472777c8` |
| siq-integration-performance.json | `4d53d9e5dbae95bcad8c04e6d265bacf80d0a900747a3e5f6870f5f5c2ebbdcd` |

## 远端状态与剩余事项

实际查询PR #4：远端`30c7656`全部可见必跑检查成功，nightly依触发条件跳过。后续本地`95e425c`仍需推送后的对应CI，不能沿用旧提交绿灯。

后续继续原生V3来源传播、通用证据语义重放、逐项DoD/INV及完整最终报告；能力矩阵不因此升级为production supported。
