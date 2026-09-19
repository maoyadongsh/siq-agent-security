# 运行时适配器：宿主调用与独立授权的连接层

适配器在原生工具调用前请求本机 SIQ 决策，在调用后提交关联观察。规则、签名、Grant、Intent、审批和效果判定由 [Go 运行时](../../apps/agentshield/README.md)持有；插件不能借模型文本、宿主弹窗或自报身份提升权限。

## 当前宿主路线

| 适配器 | 接入形式 | 当前边界 |
| --- | --- | --- |
| [Hermes](hermes-agentshield/README.md) | Python pre/post 插件、实例身份与原生会话桥接 | Linux/macOS/Windows 范围；hold 阻断后需同操作重试并取得唯一预留 |
| [OpenClaw](openclaw-agentshield/README.md) | TypeScript 插件、before/after tool hooks | 会话 key + UUID 绑定；审批后最终检查依赖宿主检查点，原版与固定补丁副本分列 |
| [WorkBuddy](workbuddy-agentshield/README.md) | 桌面 command hooks；Windows 专属受管身份 | Windows/macOS 范围，Linux 不新增接入；Windows 受管能力不外推到 macOS 旧接入 |
| [CodeBuddy](codebuddy-agentshield/README.md) | 历史 CLI command hooks | 不新增接入；保留历史协议、回执与安全卸载兼容 |

平台范围与实际通过情况分别见[范围决策](../../docs/personal-platform-scope-decision-20260917.md)、[矩阵](../../platforms/support-matrix.md)和[评测记录](../../evaluations/README.md)。底层适配代码存在不等于该 OS 当前受支持。

## 为什么需要宿主专属协议

会话、工具调用和批准窗口由宿主生成，不能用模型传入的名字替代。受管接入先以实例凭据注册真实会话，再由 daemon 绑定授权；前后置通过 action/decision/tool-call 身份关联。来源引用只有经服务端验证才可约束参数，普通工具返回值不能自称 USER。

hold 的本地批准与宿主批准是两道不同检查。受支持的恢复路径需重查当前授权与最终参数、持久化唯一签名预留，再尝试执行。响应丢失或缺少 observation 时保留 uncertain，禁止盲目重复。该协议缩小批准到执行的竞态窗口，不提供分布式 exactly-once 保证。

## 安装、排错与开发

按各模块 README 使用管理界面的“发现实例 → 权限准备 → 人工批准 → 接入预览 → 确认”。CLI 文件安装不一定提供完整身份发行流程。安装前备份、提交后读回；卸载仅移除本产品归属对象，保留其他用户配置。不要直接复制旧 profile 的凭据到新实例。

验证应依次回答：文件是否写入、宿主是否加载、身份是否有效、正常工具能否执行、越权/失联是否拒绝、观察是否关联、撤销/审批恢复是否正确。mock hook 测试、公开 CLI、网关和桌面人工旅程分别报告；allow 回执不证明实际副作用，插件已安装不证明已保护。

适配器源码与 Go 内嵌副本有一致性检查；修改实现须同步两侧，运行各宿主负向与原生验收。普通 policy 的 audit_only/warn 保留建议语义；受管身份失败及必需 Authority 无效不因模式而放行。源码目录中的 README 不是已发布安装包的支持声明。
