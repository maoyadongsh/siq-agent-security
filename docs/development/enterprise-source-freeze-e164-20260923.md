# E164 企业控制端现有代码收尾

签发入口待提供期间，对既有企业控制端实现做独立源码交付核对，没有新增业务功能。现已保存为本地候选提交 `4a4bcd0b3695dfa56e73c24d8f42a547fe94be31`，分支 `codex/flagship-enterprise-freeze-e164`，工作树干净。

本候选以客户端冻结提交 `fd02384d6de5f96a849f9d04bbfbfaff38cf6148` 为父提交，追加 52 项文件变更：Control API、迁移 0017、Edge、SIQ Connector 及既有企业验收脚本。客户端签发仍使用 E163 的固定提交，不因企业候选而重新改变发行身份。主工作树、原分支和其他已有改动保留。

## 本次验证

| 项目 | 结果 |
| --- | --- |
| API 独立环境 | `uv sync --frozen --dev`、`uv run ruff check app` 通过；`uv run pytest` **1071 passed**，保留 1 条 Starlette/httpx 弃用提示 |
| Edge / SIQ Connector | 两模块全量 Go 测试与 vet 通过；两模块各自 Linux ARM64/AMD64、macOS ARM64、Windows AMD64 编译通过 |
| 隔离 PostgreSQL | **11 项通过**：0001→0017 空库迁移、空表降级/再升级、部署幂等及审计、真实行锁争用、响应未知/审计失败下不重复执行、已有请求记录禁止破坏性降级 |
| 企业前端 | 在本候选工作树安装锁定依赖并执行 `npm run build`，TypeScript 和企业构建通过；构建环境排除了外部 VITE 配置，未启用开发身份构建。原有大包提示保留 |
| 验收脚本 | 按脚本所属仓库配置 Ruff 通过；修正执行权限、显式 `check=False` 和导入顺序，PostgreSQL 驱动修正后重跑通过 |

首次从 API 子目录对外部验收脚本运行 Ruff，继承 API 专属行长/导入配置，记录 179 条长行与 4 条导入排序问题。随后按仓库根对脚本应用其所属规则，修正发现的 11 处 shebang 执行位、4 处显式子进程返回码配置及 3 个文件的导入排序；没有大规模重排脚本长行，也不声称这些脚本满足 API 的全部排版规则。API 自身严格 lint 始终通过。

## 交付与运维边界

API 测试使用隔离 SQLite 和开发身份；PostgreSQL 专项使用本轮临时容器和合成身份，验证数据库事务与锁，执行适配器有明确替身。它们不替代生产 IAM、真实审批人或真实 OpenShell 行为；E151 等历史原生行为证据仍保留各自范围。本轮未重新执行企业浏览器全旅程，也不增加新的浏览器通过数字。

PostgreSQL 测试仅使用本机已有镜像、随机回环端口、512 MiB 内存/1 CPU 限制和临时数据。测试退出后自有容器删除；pytest 的临时数据库/签名文件放在本轮临时父目录中并清理。未迁移用户业务数据库、替换在线 API/Web、部署 Edge 或改变 Hermes/OpenClaw 配置。

真实部署前仍须按 Control API README 应用迁移 0017、核对生产 PostgreSQL 与 IAM，并协调 API/Web 更新。已有部署请求时禁止删除 0017 表回退；需要回退旧代码时先关闭部署写入口、保留表和审计、核对未决请求。此源代码冻结不代表这些上线步骤已执行。

客户端正式签发仍等待用户提供受控入口。原标杆目标的业务部署、生产身份、运行故障恢复、原生 CI 与后续安全清单保持未完成；本地候选未合并、推送或发布。

[证据](../evidence/flagship-optimization-20260921/enterprise-source-freeze-e164.json) · 候选清单（本机私有路径：`var/flagship/enterprise-freeze-e164/candidate.json`） · [客户端签发交接](client-signing-handoff-e163.md)
