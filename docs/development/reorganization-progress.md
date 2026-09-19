# 仓库架构调整进度

依据[方案 v1.2](../repository-architecture-reorganization-proposal-20260918-095230.md)持续实施。启动基线 `1173042275ae994faa4ed1c99cee58f7d541cb1c`（2026-09-19）；在独立整理分支实施，各批经验证后合入 main。当前记录只描述仓库整理，平台验收与研究任务保留各自台账。

| 阶段 | 状态 | 已交付 / 下一步 |
| --- | --- | --- |
| RA-00 资产与依赖 | 已完成首批 | [资产与冻结清单](repository-map.json)，21 类资产覆盖跟踪树，明确首批路径；新文件与后续迁移继续登记 |
| RA-01 入口收口 | 待实施 | docs/current 导航、旧操作入口修正及路径检查覆盖 |
| RA-02 文献/研究 | 待实施 | 原位文献索引、研究唯一正文与关联；不强制搬迁全文 |
| RA-03 测评/发行 | 待实施 | 候选绑定目录、外部模板、可复用发行验证工具 |
| RA-04 平台导航 | 待实施 | 三 OS、宿主、架构与真实验证范围 |
| RA-05 工具整理 | 待判断 | 优先注册现有工具；仅在消费者清单与收益明确后移动 |
| RA-06 历史导航 | 待实施 | 历史索引；旧 worktree 清理不属于本轮删除范围 |
| RA-07 收口演练 | 待实施 | 干净检出、相关检查与回退检查 |

## RA-00：分类与冻结检查

新增 [路径守卫](../../scripts/repository/check.py) 与[负向测试](../../scripts/repository/test_check.py)，接入既有 CI 的 gitleaks job，不改 required check 名称。冻结范围含历史 evidence、比赛材料、归档、签名 fixture 与研究主张/任务书的已绑定文件。

检查同时对照固定启动基线和 PR base（push 使用 before SHA），防止删除保护、移动冻结基线或修改后续新增的已归档文件。允许新路径追加证据，不修改旧摘要。导航支持空格、Unicode、尖括号、URL 编码、HTML 链接、引用式链接及标题锚点；拒绝越出仓库、错误大小写和符号链接路径。外部网页可达性不在离线检查范围。

本批验证：`python3 -m unittest discover -s scripts/repository -p 'test_*.py' -v` 九项通过；`python3 scripts/repository/check.py --base 1173042275ae994faa4ed1c99cee58f7d541cb1c` 通过。新增公开目录的私有状态忽略规则。未迁移运行代码、证据、论文或工作树；回退本批提交即可移除新守卫与索引，历史材料不变。
