# 运行结果解释与证据直达验收（E142）

日期：2026-09-23。接续 E141，落实 UX-11、UX-06 及部分 UX-08。总目标仍为 active，安全复核 SEC-F01–SEC-F10 保持后续顺序。

## 用户可见变化

运行详情先展示结果结论、原因和下一步：结果待核验、观测到执行失败、结果需要核查、结果核验通过、结果无法确认或未设置结果核验。它们基于服务端结果事实，不从允许调用推断整个任务成功，也不从缺少证据推断任务仍在运行。

每项要求按当前任务中的顺序编号，旁边直接查看对应证据；编号不冒充业务名称。要求 ID、原因码和证据来源标识折叠展示，安全事件另列。证据弹窗首先说明文件写入等效果类型、观测状态、来源独立性、覆盖范围及观测时间。用户可以刷新或在读取失败后重试，旧成功信息会立即撤下。

历史 hold 文案改为“需批准裁决”，明确它不表示当前仍待审批。页面注明尚未接入报告正文和文件下载，不用回执冒充业务报告。真实业务名称、成功/失败/取消生命周期、报告正文和可授权产物入口继续待办。

## 实现与边界

复用 `local-task-security-view/v1`、`completion-status/v1`、签名效果证据 GET 接口；没有新增后端权限、合同版本、执行按钮或自动批准。继续校验证据 ID 与 task_id，不把其他任务的响应当作当前结果。

`resultPresentation.ts` 集中解释结果事实，未知原因码不直接进入业务文案。`TaskSecurityViewPanel` 保持快照变化后的结果失效，`EffectEvidenceDetails` 以请求轮次区分刷新结果并取消旧请求。复用模态组件，修复其焦点清单漏掉 summary、包含折叠隐藏控件的问题；支持键盘进入技术详情、Escape 关闭和回到原按钮。

本轮修改前端及验证工具，不修改 Go 安全裁决实现、Control API 或 Hermes 0.21 基线。页面读取过程仅有 GET 与整页刷新必需的 `/v1/session/restore`，没有领域写入。

## 同一候选验证

候选：`var/flagship/ux-e142/siq-agent-security-v2`。

SHA-256：`b5797338fb808d14fe5ad9b8e1bda14ee73631ecbd6180d1847fc3b819ca1f45`。

| 验证 | 结果与实际覆盖 |
| --- | --- |
| 结果与证据浏览器 | 32 项；真实管理 API 创建隔离授权、签名意图和允许裁决；宿主文件观测产生缺证、失败、内容不符、核验通过结果；页面逐项读取、刷新、独立 API 读回一致 |
| 结果持久性 | 四种状态及对应签名证据在候选服务重启后保持一致 |
| 负向与恢复 | 决策凭据读取证据返回 403；浏览器注入 503、另一任务响应、409 后撤下旧结论，显式刷新恢复真实响应 |
| 操作与展示 | 同一任务证据引用、键盘打开技术详情、Escape/焦点恢复、375px 弹窗；未设置核验的允许调用不冒充成功；截图已人工检查 |
| 双平台旅程 | 53 项；Hermes 已安装钩子、OpenClaw 原生文件工具，以及权限编辑/批准/接入、撤销拒绝、记录详情回归 |
| 权限编辑 | 20 项；模态焦点修改后中文工具勾选、只读方案、撤回、冲突、保存和小屏回归 |
| 前端 | 43 文件 / 264 项；本地与企业构建通过，含 TypeScript 检查 |
| Go | 44 个测试包及 vet、产品源码 gofmt 通过；Linux amd64/arm64、macOS arm64、Windows amd64 构建通过 |
| 验证脚本 | 新脚本 Ruff、两个变更脚本语法检查通过 |

最终浏览器证据为 `results-v6`、`journey-v2`、`resources-v2`。同候选证据与源文件、嵌入资源、日志摘要见 [E142 证据](../evidence/flagship-optimization-20260921/ux-result-evidence-e142.json)。前端主入口仍有 500 kB 构建提示，未作为失败隐藏。

文件观测为隔离目录内的合成写入，由真实服务自行读取前后状态并签名；不是原生模型生成业务报告。故障响应与跨任务响应明确为浏览器注入，正常结果没有模拟接口。跨平台构建不等于对应操作系统的原生体验验收。Control API 未改，本轮未重复全量 Python API 测试。

## 失败记录与修正

首次误用了未安装 Playwright 的研究项目 Python，启动前失败；改用已有 Playwright 的系统 `python3`，不改依赖。初版验证把刷新页面正常恢复会话的 POST 也计作领域写入，断言失败；记录路由后确认全部为 `/v1/session/restore`，改为仅允许这个明确例外，其他写入仍会失败。没有放宽产品权限。

早期截图因关闭模态恢复按钮焦点而停在页面下方，补充回到页顶的截图；Ruff 发现脚本的 lambda 赋值，改为函数后重新完成 32 项浏览器验证。历史失败和阶段证据保留，不重复累加覆盖数。

## 复验与回滚

从仓库根运行（输出目录需为新目录）：

```bash
python3 scripts/personal-experience/result-evidence-browser-smoke.py \
  --binary var/flagship/ux-e142/siq-agent-security-v2 \
  --out-dir var/flagship/ux-e142/recheck-results
python3 scripts/personal-experience/environment-onboarding-browser-smoke.py \
  --binary var/flagship/ux-e142/siq-agent-security-v2 \
  --out-dir var/flagship/ux-e142/recheck-journey \
  --openclaw-root /home/maoyd/.nvm/versions/node/v24.21.0/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v24.21.0/bin/node
python3 scripts/personal-experience/grant-resource-browser-smoke.py \
  --binary var/flagship/ux-e142/siq-agent-security-v2 \
  --out-dir var/flagship/ux-e142/recheck-permissions
```

回滚只逆转 E142 前端展示/模态增量并重新生成嵌入 UI，不恢复整个脏工作树，不修改或删除既有授权、签名证据和真实业务配置。旧 E141 候选及本轮失败日志保留。未提交、推送、发布或更新安装版。
