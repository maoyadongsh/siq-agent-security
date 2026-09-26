# 主线分支整合记录

日期：2026-09-26。目标：汇总当前开发成果，形成可审计提交并合并到本地 `main`。

## 1. 基线与处理原则

- 合并前同步 `origin`；`origin/main` 为 `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`。
- 唯一尚未被 `origin/main` 包含的本地分支是
  `deepseek/enterprise-mainline-closeout-20260926`，原有 31 个提交。
- 不读取或提交密码、私钥、`.env`、种子、备份、运行数据库、`var/`、`.tmp/` 或构建缓存。
- 不用 squash 抹掉已有审阅历史；新增工作按核心、界面、交付材料分组提交，再用显式非快进合并。
- 合并开发源码不等于签名发行、生产部署或关闭综合验收记录中的产品缺口。

仓库未安装 `gitleaks`，因此本次不虚报完整凭据扫描。实际门禁包括敏感路径核对、
忽略规则、仓库公开材料检查、`git diff --check`、提交态导入闭包及各技术栈全量回归。

## 2. 新增提交与合并

| 提交 | 内容 |
| --- | --- |
| `77db7cd` | 控制面、迁移、Edge、Connector、版本化合同及直接测试 |
| `645821d` | 企业 Web、个人管理端、嵌入式前端产物及直接测试 |
| `b737551` | README、运维/交接文档、公开证据、验收及发行工具 |
| `67bcf06` | 清除两个历史公开证据文件中的四处尾随空格，使全分支差异检查通过 |
| `c7cfbd4` | `main` 的非快进整合提交，保留上述分支历史 |

合并后 `main` 与来源分支的 tree 均为
`006898acad11119742054ce6a2604fb877c1e365`，不存在合并时内容改写。
所有本地分支均已成为 `main` 祖先；原分支未删除，仍可用于审计。

## 3. 远端遗留分支裁决

最终检查发现 7 条旧远端追踪分支的尖端不是 `main` 祖先。未机械合并它们：

| 分支集合 | 处理 | 依据 |
| --- | --- | --- |
| `origin/codex/windows-client-install-20260918`、`windows-filesystem-evidence-20260914`、`windows-migration-done-barrier-20260918`、`windows-openclaw-session-evidence-20260918` | 已吸收，不重复合并 | `git cherry main <branch>` 的全部补丁均为等价补丁；重复合并只增加陈旧历史边 |
| `origin/codex/windows-resource-binding-20260916` | 已由后续主线演进取代 | 运行实现补丁等价；早期合同提交因后续修改不再 patch-identical，但九条文件均已存在于 `main` 并通过当前测试 |
| `origin/codex/windows-task-upgrade-20260918` | 已由后续主线演进取代 | 后续七个补丁等价；初始合同提交的四条新增文件均已存在，当前合同/实现已继续演进并通过回归 |
| `origin/cursor/setup-dev-environment-fdee` | 淘汰，不引入当前树 | 仅含旧 `.cursor` 环境脚本，使用未校验的远程 `curl | sh`、旧工具链假设及重复开发启动入口；引入会降低当前供应链与启动边界 |

这些远端引用未删除或改写；“不作内容合并”是显式裁决，不是遗漏。若未来需要清理远端分支，
应另行授权并在托管平台确认保护规则，本次不执行删除或推送。

## 4. 合并后验证

- 提交态导入闭包：`import_closure_closed_at_ref`，`grafted_count=0`；此前依赖 39 个工作树文件的阻断已消失。
- 合同导航：未建档版本 0、坏链接 0；`documented_but_unemitted=89` 保留为静态观察，不冒充 89 个缺陷或完成项。
- 后端：2250 passed、1 skipped、1 个既有 Starlette/httpx 弃用警告。
- 前端：112 个测试文件、1012 项通过；`VITE_DEV_MODE=false` 标准构建成功，输出位于独立 `/tmp` 目录。
- Go：`edge/agent`、全部 Connector、`apps/agentshield` 均以 `GOPROXY=off` 完成 race 测试与 vet。
- `git diff --check origin/main...main` 通过；工作树干净。

截至合并后验证完成时尚未推送 `main`，也没有签名、发包或部署；当时本地 `main`
在远端基线上领先 36 个提交。用户随后另行授权普通非强制推送，本记录随后的提交与推送结果
应以 Git 历史和远端引用核对为准；该授权仍不包含签名、发包、部署或删除旧远端分支。
