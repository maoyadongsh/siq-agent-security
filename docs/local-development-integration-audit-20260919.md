# 本地开发成果与 main 整合核查（2026-09-19）

用户要求先确认本地开发已提交并整合到 main，形成一版提交，再进行仓库架构优化。本轮以 `main@56fd525ef869acb8d5aea86f0c994f77751102f9` 为基线；核查 49 个本地分支、34 个登记工作树（33 个目录存在）和 1 个 stash。逐树状态及分支 HEAD 见[机器可读清单](local-development-integration-audit-20260919.json)。范围不包含其他 SIQ 仓库、未登记的仓外目录或未推送到本机的协作者内容；忽略的运行状态、凭据、私有材料和构建缓存不是待提交开发代码。

结论：近期开发分支的功能提交已进入 main；主要“未提交”提示来自刻意保留的早期来源工作树。它们不能再次整树覆盖主线。唯一尚未纳入主线祖先关系的本地分支是 `codex/windows-stage-review-20260918`，余下 3 个提交均为历史整合节点。本轮补齐其合并关系，并将本核查与更新后的架构方案作为可追溯基线提交；产品源码、合同、锁文件和构建产物不变。

## 本地残留逐项处置

| 来源 | 本轮核对 | 处置 |
| --- | --- | --- |
| 常用目录 `siq-agent-security`，`codex/personal-macos-stop-recovery@274ed979` | 展开未跟踪文件后共 470 项：344 个文件与 main 相同，120 个文件的完整 Git blob 可在 main 历史到达，6 个删除也已被主线吸收 | 没有发现这批内容中遗漏提交的独有文件；保留原工作区，不重复提交旧实现 |
| `siq-personal-next-20260913-193405` | 262/262 项与已提交的[来源清单](evidence/personal-experience/glm-stage-review-20260914/source-inventory.json)一致，未发现该清单之后新增开发 | 沿用[独立复核结论](evidence/personal-experience/glm-stage-review-20260914/report.md)：采纳并修复的 N02/N03/N04/N08 已进入主线；旧 N05/N06、安全审查未通过的脚本、旧锁文件与证据不重新导入 |
| `siq-local-o05-v6-20260917` | 跟踪差异 SHA 与已提交记录相同；私有来源 manifest SHA 与公开记录相同；128/128 个未跟踪文件匹配原 manifest，其中已选取 31/31 项匹配公开清单 | 沿用[v6 整合映射](evidence/personal-experience/v6-integration-20260917-153208/integration-map.md)：可采纳源码/合同/工具已合入并加强；97 项原留存材料及旧 embed 保留，不能替换当前候选 |
| `siq-release-openshell-20260916-142706` | 2 个未跟踪文档：执行提示与 main 相同；任务书仅缺 main 后补的复核更正段 | 主线已包含较完整版本，原件保留 |
| `/tmp/siq-b07-final-review-20260916` | 5 个未跟踪文档均与 main 字节一致 | 已吸收，原件保留 |
| `stash@{0}`，`6ac5b073` | 仅把 Control API 锁文件项目来源从 `virtual` 改为 `editable`；main 已为 `editable` | 不重复 apply，不删除 stash |
| `codex/windows-stage-review-20260918@0597811` | `git cherry` 无独有非等价补丁；`git merge-tree --write-tree` 无冲突且结果 tree 与 main 完全相同 | 普通 merge 补齐祖先关系，不恢复旧代码 |
| 其他存在的工作树 | 除本轮 main 文档变更外干净；其 HEAD 已属于 main 历史 | 不重复合并、不重建产品 |
| 已不存在的 `/tmp/siq-b07-review-b1-20260916` | 登记 HEAD 已在 main 历史 | 只记录，不据此清理登记或声称检查了已消失的文件 |

常用目录的 313 个“未跟踪条目”是默认折叠目录的状态计数；展开为 375 个文件，所以总数为 89 修改 + 6 删除 + 375 未跟踪 = 470。不能把折叠计数与逐文件比较数直接相加。

## 为什么旧草稿不能再次整体合入

旧 N05 把安装/授权关联当成调用来源证明；旧 N06 放宽跨任务审批消费。两项问题及排除原因已在 2026-09-14 主线复核报告逐项记载。后续主线通过可信 SEC 和一次性预留推进相应能力；“旧文件仍未提交”不表示应恢复旧设计。

v6 来源也经过选择性整合，随后补了加载前置、执行授权、持久记录签名及停止能力边界。直接导入旧来源会撤回这些修复。当前核查证明来源现场没有出现未核查的新一轮开发，不把旧实现存在解读为漏合并，也不把排除材料重新标为当前通过。

本次保留所有原工作树、未跟踪文件和 stash。**main 的集成提交完成不意味着每个历史工作树的 `git status` 都变干净。** 清理历史现场是后续独立任务；无需为消除提示而提交已拒绝实现、重复 bundle 或运行秘密。

## 合并与验证口径

历史复核分支的试合并 tree 和基线 tree 均为 `90dafeb51bacac9294067654ba66871806da4010`。最终提交只增加本报告、机器清单并修订架构方案；既有开发源码不变。提交后的分支祖先检查应使所有 49 个当时本地分支均可从 main 到达，并确认 main 工作树干净。

已执行检查：

- 全部分支/工作树状态、HEAD、Git blob 可达性及旧来源 SHA-256 对比；提交前复查其他窗口未改变对应 HEAD/状态。
- `git merge-tree --write-tree main codex/windows-stage-review-20260918`：无冲突、产品内容零差异。
- `python3 scripts/check_research_task_ledger.py`：通过。
- `python3 scripts/research/check_metadata.py`：通过。
- `python3 scripts/check_capability_honesty.py`：通过。
- 新增/修订文档的 29 个本地链接、JSON 格式、`git diff --check` 和 gitleaks 提交内容秘密扫描：通过。

未重跑 Go/Python/Web 全量或跨平台原生验收：本轮没有产品代码变化，不能把历史验收改写为本次新验收。本次仅本地提交/合并，不推送、不签名、不发布、不改远端治理。

## 架构优化启动条件

以承载本报告的 main 提交作为后续整理起点，重新确认工作树状态后执行[更新方案](repository-architecture-reorganization-proposal-20260918-095230.md)的 RA-00/RA-01。当前只完成方案与整合核查，不移动目录，不重构运行时，不修改冻结证据。后续若其他窗口继续提交，先记录新的 main 差异，再选择具体路径批次。
