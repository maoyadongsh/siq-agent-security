# 2026-10-07 测评目录完整迁移

[测评总览](../../README.md) · [批次入口](../../campaigns/20261006/README.md) · [报告入口](../../reports/README.md)

唯一现行测评根目录为 `evaluations/`。原 `third-party-evaluation/` 已撤除，不保留同名目录、软链接或跳转占位。

| 原位置 | 现行位置 |
| --- | --- |
| `third-party-evaluation/20261006/` | `evaluations/campaigns/20261006/`，内部结构保留 |
| 旧综合报告兼容入口 | `evaluations/reports/comprehensive-20261006/`，旧跳转文件撤除 |
| 旧离线 ZIP 副本 | 归并到综合报告目录，核对字节一致 |
| 原批次 README 与复现说明 | 原文保存在批次内 `*.archived.md`；现行同名文档更新导航与命令 |

## 证据保护

[迁移清单](manifest.json)逐项登记 2,118 个原有 Git 文件的源路径、目标路径、摘要和处理方式，来源固定为 `d80879cbbddb05abaaaa42c69fd7f82e30bf3bc4`。冻结协议、数据、报告、源码快照及归档导航均保留原始字节；不重签历史回执、不改变统计分母、不把搬迁算作新实验。撤除的仅是旧根目录说明、忽略文件与已失去作用的报告兼容入口，其原文仍可从固定 Git 提交复核。

当前导航、测试夹具入口和新运行输出采用新路径。冻结记录里的旧路径描述原执行环境；其中的链接和历史命令应结合本页映射阅读，不要求旧根目录继续存在。综合 HTML、证据索引及固定版本 GitHub 引用保持原样，构建器从固定 Git 来源重建。

仓库检查同时验证清单覆盖完整、源 Git 对象身份、目标字节、路径安全及旧根目录缺席。历史归档 Markdown 用原始字节校验，现行 README 和方案继续做导航检查。旧的冻结证据保护规则继续有效。

## 核验与复现

```bash
python3 scripts/repository/evaluation_archive.py
python3 scripts/repository/check.py --base origin/main
python3 -m unittest discover -s scripts/repository -p 'test_*.py'
python3 evaluations/reports/comprehensive-20261006/build_report.py
```

需要复核历史原文中的路径布局时，可在仓库外创建一个**不存在的新目录**：

```bash
python3 scripts/repository/evaluation_archive.py --materialize /tmp/siq-evaluation-original-20261007
```

该命令只从固定 Git 提交导出当时公开归档，不执行其中脚本、不调用模型、不恢复密钥或私有状态。它用于历史路径与摘要复核，不是完整业务重跑环境；真实重跑仍需原协议要求的候选、模型、宿主和独立状态。现行只读证据校验器通过 `--campaign evaluations/campaigns/20261006` 使用新布局；历史绝对路径不能直接视为当前可执行命令。

本机私有候选、原始状态及未发表材料只做本地迁移和备份，不纳入本公开清单或 Git 提交。本地差异的备份与处理清单位于维护者的 `var/evaluation-full-migration-20261007/`，不作为公开实验成绩。

## 本轮核验结果

- 2,118 项来源映射完整；2,112 个目标文件逐字节保留，6 个过时兼容文件仅在固定 Git 原文中保留。
- 仓库迁移守卫及负向测试通过；两份 HTML 与证据索引重建逐字节一致；仓库外历史布局恢复全部摘要一致。
- 新路径下的本机权限证据复核通过：10 批、67 条签名，以及本次审计器实际覆盖的 7 项当前文件检查；这不替代原报告其他文件检查，也不算新实验。
- 使用本机未公开补充材料运行的 440 项历史校验中，431 项通过，9 项因系统 inotify 监视配额耗尽报错；原始失败记录保存在本机迁移工作目录，未计为通过。该套测试依赖本机材料和固定宿主依赖，不能在纯公开克隆上直接声称全量复现。
- 密钥扫描使用仓库既有精确值、字段、路径例外；仅增加一一对应的新路径，并校准旧路径和新路径下的负向样本，未放宽为目录级忽略。
