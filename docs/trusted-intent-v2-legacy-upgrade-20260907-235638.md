# Trusted Intent V2：旧适配器兼容性、升级恢复与进度核对

> 后续口径核对：本报告记录旧 post 完整兼容失败；原文 T15 要求的是 optional Grant/unbound 授权兼容。三平台该项已验证，详见 [最终工程验收](trusted-intent-v2-final-audit-20260908-000506.md)。下文 94% 为重新核对原文之前的阶段估计，历史失败事实保持不变。

- 核对时间：2026-09-07 23:56，Asia/Shanghai。
- 当前产品代码：`2305979dd2d6b3d58390d888756a6ffb45b86a98`。
- 结论：按原始 17 项 DoD 等权粗计，当前 V2 专项约 **94%（16/17 项已有核心证据）**。DoD 13 的完整旧适配器兼容仍未满足；这不是工作量加权进度、整个项目进度或生产就绪度。
- 本轮增加复测脚本和证据，不修改产品授权规则或用户实际安装。

## 1. 新提交的 CI 已通过

[运行 34140323805](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34140323805) 的 head SHA 精确等于上述产品代码，状态为 `completed/success`，28 个 job 全部成功。见 [原始 CI 元数据](evidence/intent-v2/ci-2305979-20260907.json)。覆盖内容以运行步骤和仓库工作流为准，不能将 CI 解释为三平台全部原生运行路径的证明。

该提交已包含 CodeBuddy 配置/启动错误修复及签名绑定撤销。提交前的 Go 全模块 race/vet、四目标构建、Python 120 项合同测试和相关 Ruff 检查已通过。本轮新增兼容性脚本及报告不属于该已通过的提交，单独记录本地验证。

## 2. 历史适配器到底兼容到什么程度

从原始基线 `0caacd3bd678051f80efb2737ea26a0c76f96a97` 提取真实旧实现，避免把“当前代码切到 optional”误当成旧版兼容。新增 [复测脚本](../scripts/validate-intent-v2-legacy-platforms.py)。

| 平台 | 历史实现与运行方式 | 7 个旧版场景 | 观察回执结论 |
| --- | --- | --- | --- |
| OpenClaw 2026.5.12 | 未修改的旧 `index.ts`，实际插件加载器、before wrapper、Pi 文件工具和 after relay | 授前拒绝、optional 首读/重复读/另一资源读取、绑定越权拒绝、required 缺绑定拒绝、强杀恢复后 optional 重复读 | 允许的文件读取确实执行；旧 post 无调用 ID、无原参数，未产生 observation |
| CodeBuddy 2.146.0 | 整个历史 Go 模块原样构建，只将原生 pre/post 命令指向旧二进制；daemon 为当前版本；真实 CLI 与本地确定性模型 | 同上；真实 CLI 保留同一会话历史并执行文件工具 | 允许的文件读取确实执行；旧 HTTP Observe 客户端清空参数且不传调用 ID，未产生 observation |

两平台各有 7 条旧版 decision，允许/拒绝符合预期，观察回执为零。旧 CodeBuddy 的 Go hook DTO 虽保留 `ToolInput`，历史 `httpDecider.Observe` 实际发送的是空 `params`；必须核对完整发送链，不能只凭 DTO 判定可关联。

原始记录：[OpenClaw](evidence/intent-v2/legacy-openclaw-upgrade-20260907.json)、[CodeBuddy](evidence/intent-v2/legacy-codebuddy-upgrade-20260907.json)。两份报告均明确 `passed=false`、`full_observation_compatibility=false`，脚本正常完成这项不兼容复现后退出码为 **1**。其中 `authorization_checks_passed=true` 只表示执行授权测试通过，不能覆盖整体失败。

旧 Hermes 已有独立历史源码原生验证，见 [原有报告](trusted-intent-v2-soak-and-compatibility-20260907-194732.md)；其稳定 `tool_call_id` 与上述两个旧客户端不同。该历史证据不扩展为所有旧版本保证。

## 3. 升级恢复路径已验证

在相同测试实例上保留 daemon 状态、Intent/Binding、历史决策、平台会话及用户合成设置，仅更换适配器入口为当前实现：OpenClaw 替换临时插件入口，CodeBuddy 将两个 hook 命令切回当前二进制。

两平台各新增 4 个升级场景：

1. 在旧 optional 会话中继续读同一文件，生成关联正确的 observation。
2. 再读同一文件，新的调用 ID 对应新的 decision/observation，没有和旧无 ID 决策混淆。
3. 原已绑定会话读取另一企业目录仍拒绝，升级没有移除既有权限约束。
4. 强杀并重启 daemon 后继续读取，关联回执仍正确。

每个平台最终 **11 条 decision + 3 条 observation = 14 条回执**，CLI 离线验签通过；报告 `upgrade_recovery_passed=true`。这证明指定基线的升级恢复路径，不能把旧版本缺失的观察补写为已发生的可信观察，也不代表旧代码无需升级便完全兼容。

运维迁移时，应暂停工具调用，备份原平台配置及 SIQ 状态，通过当前 `adapter install <platform>` 安装/更新适配器，并让平台重新加载；CodeBuddy 的 hook 必须实际指向当前二进制。随后验证允许动作同时出现 decision/observation、拒绝动作没有成功 observation，并检查原绑定仍生效。原安装器的备份/卸载测试及当前原生安装报告另有证据；本节原生迁移测试只替换临时入口，不冒充真实用户安装验收。

## 4. 隔离与证据限制

- OpenClaw 的旧代码只认 home 下的配置，不识别 `OPENCLAW_STATE_DIR`。夹具通过 Node preload 将两个固定配置文件读取替换为临时配置字节；不更改 `HOME`，不更改旧适配器源码、HTTP 内容或 hook 判定逻辑。此配置桥接是测试前提，不属于对任意旧安装的支持承诺。
- OpenClaw 用真实工具组件，但 after relay 由夹具调用，不是本次执行了完整 Agent 会话；既有完整会话证据在其他报告中。
- CodeBuddy 本次为 11 次原生 CLI、22 次本地模型请求，无真实模型供应商调用。Node I/O guard 不是 OS 沙箱。
- 历史 Go 模块从指定 Git 提交提取并在临时目录编译；当前 daemon 始终使用当前构建。归档包含源码、历史制品、当前二进制和运行时摘要。
- 本轮没有接收无法证明来源的观察，没有按时间、同名工具或“最近一次调用”猜测关联，也没有修改实际平台安装。

## 5. 进度与剩余决策

| 范围 | 当前状态 |
| --- | --- |
| DoD 1–12、14–16 | 核心实现与正负测试已有证据，详见工程报告与逐项验收表；不扩展成所有宿主路径的无限保证 |
| DoD 17 | `2305979` 精确 SHA 的全仓 CI 已通过 |
| DoD 13 | 部分满足：旧版 pre 决策兼容；旧 OpenClaw/CodeBuddy post 完整兼容失败；升级后关联恢复已验证 |
| §42 撤销并发 | 已实现签名撤销并有原生/HTTP 并发与重启证据，不再列为待开发 |
| 生产发布、真人审批、独立安全复核、跨 OS 实机 | 另外的发布/平台验收范围，不纳入上述 17 项等权百分比 |
| Provenance DAG、委派图、强 OS 隔离 | 原文排除的后续阶段；不应算成本轮偷偷漏掉的实现，也不能宣称已实现 |

剩余核心问题是如何满足“旧 Adapter 完整兼容”与“Observe 必须证明合法前置动作”这两项要求。缺失关联信息不能由服务端安全还原。当前已提供保留状态的升级路径；在原始验收口径未明确接受升级作为迁移条件前，仍保留 DoD 13 未关闭，V2 不标为 100%。

复测示例（仓库根目录，两个平台分别执行；完整旧版兼容未达成时预期退出 1）：

```bash
python3 scripts/validate-intent-v2-legacy-platforms.py \
  --platform codebuddy --runtime-root /path/to/codebuddy-package \
  --node /path/to/node --out /tmp/legacy-codebuddy.json

python3 scripts/validate-intent-v2-legacy-platforms.py \
  --platform openclaw --runtime-root /path/to/openclaw-package \
  --node /path/to/node --out /tmp/legacy-openclaw.json
```
