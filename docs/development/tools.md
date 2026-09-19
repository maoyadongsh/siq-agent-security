# 工具职责与稳定入口

RA-05 本轮选择原位归类，未移动执行器或改 CLI。消费者跨 CI、相对模块路径、旧报告和宿主脚本，导航已经解决发现问题；目前无证据表明批量搬迁能抵消兼容成本。责任角色沿用[当前任务](current.md)，精确整理路径见[资产地图](repository-map.json)。以下命令均从仓库根运行。

| 工具组 / 责任角色 | 稳定路径与消费者 | 运行与验证边界 |
| --- | --- | --- |
| 客户端发行 / 发行维护者 | [release](../../scripts/release/README.md)；安装维护与 CI 工具测试 | 固定源码导出、签发、离线验包、只读回读分开；默认不启动服务 |
| 研究发布 / 研究维护者 | [研究工具](../../scripts/research/)、[操作记录](../research/operations-20260908.md)；研究 CI | 源码包/研究资产/元数据验证独立于客户端八资产流程 |
| 仓库守卫 / 主线维护者 | [check.py](../../scripts/repository/check.py)、[目录校验](../../scripts/repository/catalogs.py)；既有 CI | `python3 scripts/repository/check.py --base origin/main`；路径、证据冻结、文献与结果清单 |
| 固定研究基准 / 研究维护者 | [hackathon](../../benchmarks/hackathon/)、[复现路线](../../REPRODUCIBILITY.md)；原 A/B 入口 | `run.py` 与 `verify.py` 配对；全新私有输出，不覆写旧语料/分母 |
| 运行时工程套件 / 运行时维护者 | [runtime-security](../../benchmarks/runtime-security/README.md)；runtime CI | smoke/full/performance 按原 README；不要仅运行 `--help` 就记实测通过 |
| 历史演示与封包 / 历史材料维护者 | [hackathon 脚本](../../scripts/hackathon/)；冻结比赛说明/复现 | 稳定保留；旧封包不是当前正式发行入口；真实模型模式仍需环境与预算 |
| 平台批次验收 / 各 OS 维护者 | [personal-experience](../../scripts/personal-experience/)、[平台导航](../../platforms/README.md) | 由对应候选/任务书选择驱动，不能整目录执行或把组件测试算原生验收 |
| UI 构建 / Web 维护者 | [build_ui.sh](../../scripts/build_ui.sh)、[Web](../../apps/web/)；CI/Go embed | 保留企业/本机两个构建入口，产品资源相对路径不动 |
| 通用约束 / 主线维护者 | [能力声明](../../scripts/check_capability_honesty.py)、[研究台账](../../scripts/check_research_task_ledger.py)、[Action 固定引用](../../scripts/check_ci_action_pins.py)；CI | `python3` 调用原文件；不复制一套检查框架 |
| 宿主联调 / 宿主维护者 | [scripts 根](../../scripts/)、[adapters](../../adapters/runtime/)；对应宿主任务 | 保留现有 `validate-*`、`test-*`、worker 路径；本轮无宿主行为改动 |

后续确需移动时按方案登记每个消费者、源 blob、兼容方式及退役条件，验证新旧命令和干净含空格路径，再做小批 PR。冻结批次执行器继续服务历史复现；原位保留不是“当前所有脚本都适用于任意宿主”的声明。
