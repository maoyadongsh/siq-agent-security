# Trusted Intent V2：CodeBuddy 原生 CLI 与隔离配置目录验收

- 时间：2026-09-07 23:11:46，Asia/Shanghai。
- 工作基线：`d860bdf`；本轮安装器修复、测试及文档为未提交增量。
- 结论：固定版本 Linux CodeBuddy CLI 的安装—准入—授权—越权拒绝—续聊—失联恢复—卸载链路已取得原生证据；完整产品与人工审批验收仍未关闭。

## 1. 本轮解决的问题

此前 CodeBuddy 证据来自直接调用 SIQ `hook codebuddy`，未让腾讯运行时真正执行命令钩子。本轮安装官方 npm 包 `@tencent-ai/codebuddy-code@2.146.0` 到独立测试前缀，使用其未修改的 `bin/codebuddy` 和 `dist/codebuddy-headless.js` 完成非交互式会话。

官方允许通过 `CODEBUDDY_CONFIG_DIR` 指定配置与数据目录；本轮据此将测试配置、会话与日志放入临时目录。安装入口与目录约定见[官方安装文档](https://www.codebuddy.ai/docs/cli/installation)，模型端点与环境变量见[官方环境变量说明](https://www.codebuddy.ai/docs/cli/env-vars)。这两份说明提供配置依据，验收结论来自本轮实际执行。

安装前缀为 `/home/maoyd/.local/share/siq-runtime-fixtures/codebuddy-2.146.0`。固定版本安装使用 `--ignore-scripts --omit=optional --no-audit --no-fund`，未修改用户全局 PATH，也未安装交互式终端的可选依赖。结果仅覆盖该版本 headless CLI，不能推广到 GUI、其他版本或其他操作系统。

## 2. 修复：安装器忽略自定义配置目录

**此前行为**：CodeBuddy 使用临时 `CODEBUDDY_CONFIG_DIR` 时，SIQ 安装器仍选择 `~/.codebuddy/settings.json`。这会造成钩子未安装到目标实例，并可能修改另一实例的配置。

**当前行为**：`adapterinstall` 的安装、状态、自动发现与卸载统一采用进程环境覆盖，CLI 和管理 API 共享同一实现。未设置或为空时保留默认目录。

- 非空覆盖必须是绝对路径；现存目录及祖先不允许符号链接或普通文件。
- 非法覆盖明确拒绝安装、卸载和状态查询；自动发现忽略该平台，不回退默认目录。
- 卸载检查最新安装记录中的配置路径；改变环境后不能借用另一目录的记录删除钩子。
- 重装保留首次原文备份，卸载只剥离本产品钩子，保留无关设置。
- 管理 API 不接受请求正文指定配置路径；decision credential 对安装端点仍得到 403，成功管理操作进入审计。

这里的祖先检查不构成对恶意并发路径替换的原子防护。多实例应配置独立 SIQ 状态目录；本轮没有扩展 inventory 的目录扫描范围。

实现：[install.go](../apps/agentshield/internal/adapterinstall/install.go)。回归：[配置目录测试](../apps/agentshield/internal/adapterinstall/codebuddy_config_test.go)、[管理 API 测试](../apps/agentshield/internal/server/codebuddy_config_test.go)。原有默认目录测试继续通过。

## 3. 原生验收如何工作

入口为 [validate-intent-v2-codebuddy.py](../scripts/validate-intent-v2-codebuddy.py)，复用既有真实 Go daemon 和可信管理会话测试框架。测试通过真实 CLI 安装钩子，扫描合成 Skill、创建并审批 Grant、签发 Intent、绑定测试会话。测试操作者是合成管理主体，不是真人审批证据。

运行时执行链：

```text
本地确定性模型服务（OpenAI SSE）
  → CodeBuddy 原生 CLI 会话与 Read/Write 工具
  → 原生 PreToolUse 命令钩子
  → 实际 Go hook 子进程 → 本地 daemon /v1/decide
  → 原生工具执行或拒绝
  → 原生 PostToolUse 命令钩子 → /v1/observe
  → HTTP 与离线签名回执链验证
```

本版本 headless CLI 会启动内部 HTTP 服务；测试显式指定其 loopback 端口。模型服务、内部服务和 SIQ daemon 各自使用限定本地端口，测试守卫拒绝其他 Node socket 连接。模型协议经实际请求确认是 `/chat/completions` 的 OpenAI SSE；首次使用 Anthropic 流的探测没有有效助手输出，未计入成功。

成功判定同时检查原生 JSON 结果中助手精确返回 `fixture-complete`、工具结果进入后续模型请求、实际文件副作用及签名回执。仅有退出码 0 或输入文本中出现完成标记不能算通过。

[Node IO 守卫](../scripts/codebuddy-fixture-guard.mjs) 是测试防误操作措施，不是 OS 沙箱；不覆盖任意子进程系统调用。测试仅提供合成 Read/Write 计划及安装器生成的 Go 钩子命令，不调用真实模型或使用真实凭据。

## 4. 原生结果

最终运行：**8 次 CLI 进程调用、19 次本地 SSE 请求、11 次原生工具调用、13 条回执**。其中 9 条在线决策、3 条 observation、1 条失联 pending 提升记录。归档保存摘要、版本和源文件指纹，不包含 token、完整签名文档、原始工具输入或文件正文。

| 场景 | 实际检查与结果 |
| --- | --- |
| 安装与重装 | 真实 CLI 两次安装到临时覆盖目录；状态显示已安装；首次原文备份不变 |
| 尚未授权 | 原生 Read 被拒绝，只有 deny 决策，无 observation 或文件内容 |
| 合法读取 | 已绑定会话读取 company-a，真实文件内容进入模型，post 与前置决策唯一关联 |
| 跨公司与路径前缀碰撞 | company-b、company-a-evil 均被 Intent 资源约束拒绝，无成功 observation |
| 未获准工具 | Write 被 Intent 工具集合拒绝，目标文件不存在 |
| 新会话 | 未绑定会话在 required 下拒绝，首次模型请求没有另一会话的工具历史 |
| 跨进程续聊 | `--resume` 恢复本会话已有工具结果；模型请求历史 ID 与既有调用对应 |
| 服务强杀 | 实际 daemon 被 kill，原生 pre hook 返回 fail-closed，生成 pending 拒绝记录 |
| 重启恢复 | 绑定与动作状态保留；读取恢复；pending 只提升一次 |
| optional 兼容路径 | 当前适配器的未绑定会话可读；已有绑定的会话仍拒绝外部公司资源 |
| 动作链 | task_seq 连续递增；parent 指向上一条 allow/redact 动作，deny 不成为授权父动作 |
| 卸载对照 | 真实 CLI 剥离钩子并保留其他设置；随后原生 company-b 读取成功且无新 SIQ 回执 |
| 完整性 | HTTP 与离线 verify 通过；原生运行时文件指纹在测试前后不变 |

[原生证据 JSON](evidence/intent-v2/native-codebuddy-cli-20260907.json) 记录每次会话、历史工具结果 ID、回执摘要和 runner/适配器/安装器源码 SHA-256。会话 ID 和模型 tool call ID 由测试显式提供，CodeBuddy 原生生命周期传递并验证一致；本轮不宣称这些 ID 来自真实模型或随机真人会话。

## 5. 复现与本地门禁

已安装固定版本运行时的环境可执行：

```bash
python3 scripts/validate-intent-v2-codebuddy.py \
  --codebuddy-root /path/to/node_modules/@tencent-ai/codebuddy-code \
  --node /path/to/node \
  --out /tmp/intent-v2-native-codebuddy.json
```

脚本要求 Go 可从 PATH 调用，构建实际产品二进制；所有测试配置、签名密钥、回执和合成文件位于自动清理的临时目录。测试会启动本地服务并强杀自己的 SIQ daemon。

本轮通过：

- `go test -race ./...`、`go vet ./...`（`apps/agentshield`）；管理 API 的新增审计断言另跑定向 race 回归。
- `linux/amd64`、`linux/arm64`、`darwin/arm64`、`windows/amd64` 四目标构建。
- 新 Python runner 的 Ruff 检查与格式检查、文档门禁和 `git diff --check`。

此前推送的 `d860bdf` 已取得 [28/28 成功 CI](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34135481421)，并归档 [CI 原始状态](evidence/intent-v2/ci-d860bdf-20260907.json)。它证明上一批 OpenClaw 改动的远端门禁，本轮 CodeBuddy 安装器增量尚未提交，不能借用该 CI 证明新代码已通过远端检查。CI 中的漏洞扫描告警策略仍以 workflow 为准，不把作业成功等同于无已知漏洞。

## 6. 对目标状态的影响与后续任务

已解除“没有 CodeBuddy 原生运行时证据”的环境缺口；固定版本 Linux CLI 的当前适配器安装、核心授权、pre/post 关联及会话恢复已验收。能力矩阵新增这组限定范围证据，整体仍为 experimental，其他平台与 GUI 状态不提升。

仍需继续：

1. **CodeBuddy 改参与审批语义**：当前适配器仍将 redact/hold 映射为 ask。官方 SDK 已说明 `updatedInput`，因此文档已纠正“平台不支持改参”的旧断言；实际 CLI 改参、审批等待与最终参数关联需要原生验证后再接入，不能把本轮 Read/Write 普通决策测试当作证明。[官方 SDK hook 输出说明](https://www.codebuddy.ai/docs/cli/sdk-hooks)
2. **旧版本兼容**：本轮 optional 测的是当前适配器；未改动历史 CodeBuddy 制品与旧 OpenClaw 不完整 post 事件仍缺完整兼容证据。
3. **其他原始目标余项**：真人审批、消息渠道、独立复核，以及已记录的 Intent 解除/并发验收项仍未全部完成。宿主检查点后的并发窗口也不属于本轮证明范围。
4. **发布验证**：提交当前增量后取得对应新 SHA 的 CI，再按发布检查执行真实环境验收。

本轮没有部署真实 SIQ 服务，没有修改既有用户 CodeBuddy/OpenClaw/Hermes 配置，没有推送新增代码。
