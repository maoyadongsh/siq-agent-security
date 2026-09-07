# Trusted Intent V2：CodeBuddy 钩子启动失败时的执行绕过修复

- 时间：2026-09-07 23:25:51，Asia/Shanghai。
- 基线：`d860bdf` 加此前 CodeBuddy 配置目录增量；本轮修改未提交。
- 结论：原生复现了初始化错误导致的非阻断退出，并修复为结构化 pre/post 结果。10 个原生场景及此前完整 CLI 回归通过；不能据此宣称任意钩子进程故障均 fail-closed。

## 1. 问题与证据

CodeBuddy 的命令钩子协议将退出码 2 用于阻断，其他非零退出属于非阻断错误。[官方权限文档](https://www.codebuddy.ai/docs/cli/permissions)说明了这一行为。本轮在未修改的腾讯 `@tencent-ai/codebuddy-code@2.146.0` 上，用实际 CLI、原生命令钩子、合成 Read 工具请求和本地 SSE 模型完成复现。

此前 `cmdHook` 在读取状态、配置或 token 出错时直接返回 error；`main` 随后打印错误并退出 1。结果是 SIQ 自己未给出授权决策，CodeBuddy 却按其他权限规则执行了工具。

[修复前归档](evidence/intent-v2/native-codebuddy-bootstrap-before-20260907.json) 为 `passed=false`：

| 故障 | 修复前原生结果 | 缺口 |
| --- | --- | --- |
| 畸形配置 | Read 执行 | 应拒绝，没有在线决策/observation |
| 配置含 warn 但端口非法 | Read 执行 | 部分解析的配置不能授权降级 |
| block 模式短 token | Read 执行 | 应拒绝，没有在线决策/observation |
| warn / audit_only 模式短 token | Read 执行 | 允许符合档位，但缺少 pending advisory 记录 |
| 状态路径实际为文件 | Read 执行 | 应拒绝 |

正常调用和恢复后的对照调用各产生 decision/observation 一对，失败基线共四条回执。工具返回中确实包含合成文件标记，因此这不是只检查退出码的静态推断。

## 2. 修复行为

[main.go](../apps/agentshield/cmd/agentshield/main.go) 将客户端初始化与钩子事件映射分开。初始化无法建立客户端时，仍交给 [CodeBuddyHook](../apps/agentshield/internal/adapters/adapters.go) 生成平台识别的 JSON。

- 完整配置无法读取或验证：使用 block，不采信伴随错误返回的部分配置字段。
- 完整 warn/audit_only 配置已验证，但 token 不可用：保留该档位的 allow，并记录固定类别原因及 unsigned pending。
- PreToolUse 无客户端：结构化 deny 或 advisory allow，不以退出码 1 代替决策。
- PostToolUse 无客户端：只输出该事件结果，不制造 observation，也不增加前置决策。
- 钩子只读取 daemon 已有 token；缺失、过短、不可读或路径为目录均作为不可用处理，不在钩子里创建新凭据。
- 状态目录可用时写既有 pending；状态目录不可用时仍拒绝，但不能声称记录已经持久化。
- 对外原因只使用 `local hook initialization unavailable` 等固定类别，不含底层路径、配置值或 token。

没有添加规则、签名密钥、审批权或新 HTTP 合同到适配器。有效请求仍调用原有决定/观测服务。

## 3. 原生复验

[validate-codebuddy-hook-failures.py](../scripts/validate-codebuddy-hook-failures.py) 通过真实安装器注册命令钩子，建立可信 Grant 和 Intent，再逐项注入临时配置或凭据故障。每个故障后恢复原始文件，测试不修改用户配置。

[修复后归档](evidence/intent-v2/native-codebuddy-bootstrap-fixed-20260907.json) 为 `passed=true`：

| 场景 | 结果 |
| --- | --- |
| 正常与恢复后读取 | 均执行，前置决策和 observation 正确关联 |
| 畸形配置、非法端口、短 token、状态路径为文件 | block 下均不执行，原生工具结果含 fail-closed 原因 |
| 新增：token 缺失、token 路径为目录 | 均不执行，钩子未生成替代凭据 |
| warn / audit_only 短 token | 均执行，各记录一条 pending allow |
| pending 提升 | 七条：五条 deny、两条 allow；状态路径不可用的场景没有伪造落盘证据 |
| 再次重启 | 所有回执 ID 保持一致，pending 不重复提升 |
| 回执完整性 | 共 11 条，HTTP 与离线 verify 通过 |

修复后共 **10 次原生 CLI 调用、20 次本地 SSE 请求**。修复前运行包含八个场景；缺失 token 和目录 token 是修复后的额外覆盖，不能把这些额外场景伪称为已有修复前原生证据。两个归档分别保留当次源码与运行时指纹。

此外用当前二进制重跑[上一轮完整 CLI 验收](trusted-intent-v2-codebuddy-validation-20260907-231146.md)，[新增回归归档](evidence/intent-v2/native-codebuddy-cli-bootstrap-fixed-20260907.json) 仍为 8 次 CLI、19 次 SSE、13 条回执通过，确认普通安装、授权、跨公司拒绝、续聊、optional 与卸载行为未退化。该回归与故障复验使用独立临时状态，回执数量不混为同一条链。

## 4. 回归与运行方法

[Go 启动故障测试](../apps/agentshield/cmd/agentshield/codebuddy_hook_test.go) 覆盖结构化决策、完整/部分配置的信任区别、敏感诊断不外泄、pending outcome、post 不制造决策，以及缺 token 时不创建新凭据。

已通过：

```bash
# apps/agentshield
go test -race ./...
go vet ./...
```

同时通过 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建，新 runner 的 Ruff 和文档检查。真实 CLI 故障测试需固定版本原生运行时：

```bash
python3 scripts/validate-codebuddy-hook-failures.py \
  --codebuddy-root /path/to/node_modules/@tencent-ai/codebuddy-code \
  --node /path/to/node \
  --out /tmp/codebuddy-hook-failures.json
```

脚本仅使用 loopback 模型、合成文件和操作者；Node IO 守卫仍不等同于 OS 沙箱。上一提交 `d860bdf` 的 28/28 CI 成功保留为历史基线，本轮源码尚无对应远端 CI。

## 5. 剩余边界与下一步

本修复依赖钩子进程能够启动并输出 JSON。二进制不存在、被强杀、宿主超时或 stdout 失败仍需另外验证宿主的阻断机制，不以本轮结果覆盖这些故障。

改参调查也发现官方 CLI hook 文档示例使用 `modifiedInput`，当前 2.146.0 实现读取 `updatedInput`。后续接入须以固定版本的实际工具副作用与 post 事件验证字段，不能只复制文档示例。[官方 hook 文档](https://www.codebuddy.ai/docs/cli/hooks)是协议调查来源；本轮没有实现或声称完成 redact/hold 流程。

回到原始 Trusted Intent V2 要求，后续优先核对并完成：

1. §42 明列的 `binding revoke while decide` 并发项，与受信解除生命周期一起设计和验证，不能将未实现的解除填为通过。
2. DoD 13 的旧 Adapter optional 兼容，尤其旧 OpenClaw 不完整 post 事件和未改动的历史 CodeBuddy 制品。
3. 当前增量对应新 SHA 的全仓 CI，以及所有原始 DoD 的逐项完成审计。

GUI、真人部署审批、真实消息渠道及独立生产复核继续作为范围明确的额外验收，不用本地合成证明替代。完整工程目标仍保持进行中。
