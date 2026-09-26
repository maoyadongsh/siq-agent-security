# CL-08-OPERATOR-DOCS-CLOSEOUT 交接文档（操作者文档收口）

- 日期：2026-09-26
- 任务书：[cl08-glm-operator-docs-taskbook.md](cl08-glm-operator-docs-taskbook.md)
- 状态：**未提交、未部署、未宣称正式发行或整体完成**。本文只记录文档改动与待核对项。

## 1. 修改文件与章节

| 文件 | 章节 | 改动 |
| --- | --- | --- |
| README.md | 「个人用户使用路线」开头段 | 补充 `127.0.0.1` 指向浏览器所在机器（Mac 浏览器与 Linux 服务端是两台设备）、禁止以 `0.0.0.0`/关认证/放松防火墙换取访问、管理台会话确认不等于智能体业务授权 |
| README.md | 「企业用户使用路线」9-24 部署段 | 补充周期/持续采集调度仍在收口、不宣称持续扫描已完整接入；链接自动接入收口记录与生产运行手册排障 |
| README.md | 「当前产品方向」支持状态表 | 「局域网团队多设备管理」行「尚待完成」列补「持续/周期采集调度仍待验收」 |
| README.en.md | Personal route / Enterprise route / support table | 与上述三处中英文对应修改，事实一致 |
| docs/enterprise-production-runbook-v1.md | 头部 | 标注 2026-09-26 增补第 9–10 节（均 template） |
| 同上 | 新增第 9 节「常见故障排查顺序」 | 前端打不开 / 环境·设备为空 / 注册后无心跳 / 心跳正常无发现 / 采集失败或能力不匹配 / 策略未生效 / 升级与恢复，共 7 条排查顺序 + 卸载语义（停止采集 ≠ 撤销运行保护） |
| 同上 | 新增第 10 节「发行包与部署前置条件」 | 企业 unsigned candidate 不得交生产安装器；正式包须签发后 `enterprise_finalize.py` 组包 + `edge-agent verify-enterprise-release` 验证；个人包 `verify.py --release-dir --version --source-sha`；签名材料不齐列为前置条件 |

保留了 README.md / README.en.md 既有未提交改动（2026-09-24/25 状态更新、0.4.0-rc.2 候选说明、个人管理台四入口与 Skill 辅助连接等），未整体覆盖。

## 2. 修正的不准确描述

- 远程访问：原句只说“不能直接打开服务器的 127.0.0.1 链接”；现明确 `127.0.0.1` 属于浏览器所在机器，Mac↔Linux 是两台设备，并明确禁止为访问放松监听/认证/防火墙。
- 持续扫描：原企业段未区分“已有采集基础”与“周期调度”；现明确存储、确认与设备端执行在收口（Batch151–162 范围），Edge 后台周期消费与原生服务集成未验收，整体待验收。
- 支持状态表：LAN 行补持续采集待验收，避免被读成集中治理基础=持续扫描已生效。
- runbook：原为纯模板缺口清单，无排障入口；现补 7 条只用已有诊断入口的排查顺序，并写明删除库/重置身份/重复注册不是默认修复、卸载不自动删审计或放宽策略。

## 3. 关键命令/事实的源码依据

| 文档事实 | 源码依据 |
| --- | --- |
| 配对请求 5 分钟、管理会话 24 小时 | `apps/agentshield/internal/server/authz.go:26-28`（`pairingTTL = 5 * time.Minute`、`adminSessionTTL = 24 * time.Hour`） |
| 默认端口 47611 | `apps/agentshield/internal/state/state.go:147`、`apps/agentshield/internal/server/authz.go:136` |
| Edge CLI `inspect-host/register/heartbeat/serve/run-once/recover-registration/rotate-credential/verify-enterprise-release` | `edge/agent/main.go:48-80` |
| 控制面 `/health`、`/api/v1/health` | `apps/control-api/app/main.py:112-119` |
| 环境/设备/心跳/首扫诊断端点 | `apps/control-api/app/routers/environments.py:86,145,366`；`apps/control-api/app/routers/initial_scan.py:30` |
| 部署预览/提交 | `apps/control-api/app/routers/deployment_preview.py:228,239` |
| `verify.py --release-dir --version --source-sha` | `scripts/release/verify.py:224-226` |
| `enterprise_candidate.py` / `enterprise_finalize.py` / `readback.py` | `scripts/release/` 目录实际存在；candidate 产 unsigned 包（`enterprise_candidate.py:140-145`） |
| 企业 OpenShell CLI 后端仅 `block` | 既有 9-24 部署记录口径，未改 |

## 4. 文档校验命令与结果

- 本地链接检查（三个目标文件全部相对链接按所在目录解析）：**全部存在，无失效**。
- `git diff --check`：**通过**（无空白错误）。
- 中英对照：三处新增段落在 README.md 与 README.en.md 逐条对应（两机说明 / 持续扫描待验收+runbook 指引 / LAN 行）。
- 按预算未执行任何安装、注册、扫描或服务重启；未联网测试下载地址。

## 5. 正式发布或实机验收后才能填写的信息

- 0.4.0-rc.2 及后续候选的公开发布入口、下载地址与回读结果（现为本机 `.tmp/releases/0.4.0-rc.2-signed/`）。
- 持续扫描在真实设备上的生效结论（当前只能写“待验收”）。
- 企业真实组织账号、独立审批者、跨系统业务结果联验结论。
- 各平台同候选系统服务安装/升级/回滚/退出验收；macOS 公证状态。
- 正式发行后的版本号、制品摘要（runbook 第 10 节明确不预填）。

## 6. 交主开发者处理的代码问题

本次未发现需改代码的新问题。既有遗留以收口清单为准：ENT-010、ENT-022 仍为 todo；CL-02（持续调度闭环）、CL-04（拓扑与运行时绑定）、CL-05（批量权限到效果）为主要缺口。

## 7. 结论：哪些文档可接受、哪些待发布前核对

- **可接受**：README.md / README.en.md 的安装入口、使用路线、证据分级表述与当前代码及收口记录一致，可随当前工作树交付；runbook 第 9 节排查顺序只引用已存在入口，第 10 节前置条件与 scripts/release 实际工具一致。
- **发布前须核对**：所有版本号/下载地址/摘要（以正式发行回读为准）；持续扫描与设备端执行状态；企业真实身份联验结论。Qwen 名下 `scripts/release/README.md` 未改动。

## 8. 主开发者复核

核对中英文新增段落、配对/会话常量及 Edge 命令实现后，保留本次文档成果，修正 runbook 三处操作边界：`run-once` 是实际采集，必须先授权并明确范围；注册恢复与凭据轮换有不同前提且不是只读诊断；正式企业包须用独立可信 verifier 核验实际 bundle，不能只验证信封。依据为 `edge/agent/main.go` 的 cmdRunOnce、注册/轮换入口及 `edge/agent/release_verify_linux.go` 的 --bundle 分支。

主线 Batch163–164 已实现后台周期消费与服务安装前置检查，但仍缺安装交互和实机旅程，因此 README“仍在收口/待验收”的表述继续成立。不修改 Qwen 文件，不操作真实服务；本次仅文档核对与修正，不宣称 CL-08 整体完成。
