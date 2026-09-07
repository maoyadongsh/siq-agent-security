# Trusted Intent V2：原生网关重置与提交后验收

- 整理时间：2026-09-07 21:51，Asia/Shanghai。
- 已推送代码：`87fd1ce3b6b7967c94846a798b4fca868aedd857`；合同提交：`0e357ce`。
- 网关测试执行时间：2026-09-07 21:43；当时基线为 `78e740a` 加工作树改动。测试代码及证据现已进入 `87fd1ce`，本轮重新核对源文件指纹一致。
- 结论：原生网关 `sessions.reset` 与后续本地 CLI 的连续路径通过；对应新提交的远端 CI 全部成功。V2 整体验收仍未关闭。

## 1. 网关重置验证范围

使用本机 OpenClaw 2026.5.12、Node v22.22.1、linux/arm64，在临时配置、临时 SIQ 状态与合成模型服务中运行。实际启动原生网关，通过原生 WebSocket 客户端调用 `sessions.reset`，随后使用实际 `agent --local` 入口续聊。没有直接调用 reset 实现来代替 RPC，也没有修改本机 OpenClaw 安装、实际用户配置或会话。

入口为 [Python 验收脚本](../scripts/validate-intent-v2-openclaw-gateway-reset.py) 和 [原生网关 worker](../scripts/openclaw-gateway-reset-worker.mjs)。完整摘要与指纹见 [原始测试归档](evidence/intent-v2/native-openclaw-gateway-reset-20260907.json)。归档内 `baseline_conversation` 的限制只描述前置 CLI 子测试，顶层字段描述新增网关场景。

| 检查 | 直接证据 | 结果 |
| --- | --- | --- |
| 只读客户端不能重置 | `operator.read` 调用被拒绝，错误包含缺失 scope；调用前后 Session Store 全文件 SHA-256 相同 | 通过 |
| 管理客户端执行重置 | `operator.admin` 调用返回成功，Store 中 UUID 与 RPC 返回值一致且不同于旧 UUID | 通过 |
| 重置后的活动文件不含旧消息 | 立即检查文件仅有一行 Session header，header UUID 与新 UUID 一致 | 通过 |
| 旧历史保留为归档 | 恰好新增一个 `.reset.` 归档，其 SHA-256 与重置前完整 transcript 相同 | 通过 |
| 下一次模型请求清空旧工具历史 | 旧工具结果数量为 0，旧合成 PII 标记不在请求中；使用 RPC 创建的新 UUID | 通过 |
| 固定授权不随 UUID 变化消失 | 同一 routing key 的 Intent、Task、digest 保持，跨资源读取仍被拒绝 | 通过 |
| 动作链延续 | 后续 `task_seq` 为 6、7、8，父动作关系延续 | 通过 |
| 重置不清空 SIQ 污点 | 新的敏感读取发生之前，拒绝回执仍带既有 PII 污点 | 通过 |
| 回执恢复与验签 | 合计 13 条回执，HTTP 分页读取验签与离线 CLI `verify` 均通过 | 通过 |

前置完整会话包含四次 CLI 调用、十次 SSE completion、六次工具调用及八条回执；重置阶段额外产生五次 completion 请求。脚本最终退出码为 0，`passed=true`、`siq_invariants_passed=true`、`native_transcript_cleared=true`。

## 2. 路径复用与空闲重置故障的区别

这次测试的 `session_file_unchanged=true` 表示**文件路径字符串相同**。网关已将原内容归档，并在活动路径写入新 UUID 的空 Session header；下一次模型请求也确实没有旧工具结果。不能只检查路径是否变化来判断重置成败。

原版的 [空闲重置失败](trusted-intent-v2-openclaw-idle-reset-20260907-203600.md) 是另一条路径：UUID 轮换后仍把六条旧工具结果送给模型。这份失败归档保持有效；[临时副本候选补丁](trusted-intent-v2-openclaw-reset-patch-20260907-204200.md) 仍只证明被修补副本通过。手动 RPC 成功不代表空闲路径已修复，也不代表实际安装已应用补丁。

旧 transcript 被完整归档，因此这里只证明活动上下文重置，**不证明磁盘上的历史数据被删除**。同一 routing key 继续承载原 SIQ 授权与污点是本场景预期；创建独立新会话的权限隔离另由完整 CLI 会话测试覆盖。

## 3. 复现与证据核对

从仓库根目录运行，要求 Go 可用，路径参数指向兼容的真实 OpenClaw 安装及 Node：

```bash
python3 scripts/validate-intent-v2-openclaw-gateway-reset.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/native-openclaw-gateway-reset.json
```

脚本使用实际运行时内部入口；其他版本必须重新验证，不能沿用当前版本结果。本轮重新比对七个相关项目文件、24 个原生运行时文件与归档 SHA-256，全部一致；审批修复归档的十二个项目源文件指纹也与当前提交一致。没有重复运行未发生变化且已通过的原生场景。

合成模型、合成管理员和测试 I/O guard 不构成真实用户在场或 OS 隔离证明。消息渠道命令触发 reset、网关中的完整 Agent 对话，以及渠道身份到 routing key 的映射仍需单独验收。

## 4. 当前 SHA 的远端 CI

[GitHub Actions 34129436564](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34129436564) 的 `headSha` 精确为 `87fd1ce3b6b7967c94846a798b4fca868aedd857`，状态 `completed/success`，28 个 job 全部成功。逐 job、逐 step 元数据保存于 [ci-87fd1ce-20260907.json](evidence/intent-v2/ci-87fd1ce-20260907.json)。

提交前本地 Go race/vet、117 项 Python 合同与 Schema 测试、OpenClaw 适配器测试和脚本静态检查通过。CI 通过仅覆盖其实际配置的门禁，不代表三平台原生验收已完成，也不能据此宣称依赖扫描没有任何漏洞发现。此次报告和 CI 元数据归档属于提交后的文档增量。

## 5. 尚未关闭的事项与下一步

| 事项 | 当前证据与下一步 |
| --- | --- |
| OpenClaw 完整审批 | 六个原生合成场景已通过；仍需验证平台审批等待期间 Grant/Intent/污点变化，以及真人双重审批操作流程 |
| OpenClaw 生命周期 | 手动 RPC → 本地 CLI 路径已通过；消息渠道 reset 尚未验证，原版空闲重置故障仍存在 |
| Hermes 本地 hold | 源码显示 `grant.Build` 和 `PatchDesired` 只为 OpenClaw 生成 `require_approval`；receipt 的逐次审批集合来自该字段。Hermes 的 `hold → block` 映射单测不能证明正常 Grant 流程会产生 hold。现有规格 §4.2 只承诺 hold 退化为 block，原始 V2 §31 要求可靠 pre/post 关联，并未要求新增 Hermes 原生审批通道。若后续扩展为逐次审批流程，需先设计合同和受信批准后的执行关联；不能向夹具塞入非正常生成的 Grant 来宣称现有产品流程完整 |
| CodeBuddy 原生环境 | `codebuddy` 命令仍未找到。缓存 VSIX `codebuddyai.codebuddy-ai-1.7.0` 的 README 链接指向 `www.codebuddy.ca`，不能据同名认定为本项目腾讯 CodeBuddy 适配目标；未执行或安装该扩展。仍需目标运行时的安装路径、版本和隔离入口 |
| 旧 OpenClaw 兼容 | 缺 ID/参数的旧 post 无法安全关联；需实际运行时桥接证据或明确升级迁移流程，不能猜测动作来源 |
| 独立复核 | 仍需独立审查者核对原始 T1–T16、签名恢复与分权，开发者自查不充当独立验收 |
| 解除绑定/撤销并发 | 当前固定绑定没有解除 API；原文可选扩展及其并发测试未实现，沿用原验收台账的未完成标记 |

本轮关闭新 SHA 的 CI 待确认项，补齐已执行网关场景的解释和复现入口，并识别 Hermes 审批验收的合同前提。上述未完成项没有因局部验证通过而被移出目标。
