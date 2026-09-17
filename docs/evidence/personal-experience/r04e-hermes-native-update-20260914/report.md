# R04-E Linux/Hermes 原生 Skill 更新验收

日期：2026-09-15。结论：本机隔离环境 15/15 检查通过；R04 的 Linux/Hermes 原生 V1→V2 更新门槛完成。候选为当前未提交工作树构建，未发布。

## 实际链路

测试使用公开 `hermes chat --oneshot`、真实 Hermes 插件钩子和文件工具、SIQ 管理 API、隔离 HOME/profile/state，以及仅监听本机的确定性模型夹具。没有调用外部或付费模型。

1. 经产品入口导入、批准、安装并激活 V1，签发实例身份并安装适配器。
2. 用 `--skills intent-fixture` 明确预载 V1；测试只在宿主生成的 system/developer/tool 材料中确认 Skill，随后真实读取文件，回执为 `controlled_task`。
3. 导入 V2，先以 pending Grant 比较内容差异。该阶段模拟用户取消，确认 V1 文件、旧 Grant revision 和候选 Grant revision 均不变。
4. 人工测试身份批准 V2，重新比较并生成签名更新计划；明确确认后发布 V2，旧 Grant 撤销，旧运行身份变为 `grant_unavailable`。
5. 明确停用旧身份，激活 V2、签发新身份、更新适配器并签发绑定新安装的 SEC。Hermes 以 `--skills intent-fixture-v2` 重新加载 V2，真实读取成功；回执内容摘要与 V1 不同。
6. 明确移除 V2，验证目标目录消失、新 Grant 撤销、新身份不可用、回执链可验，并保留原 profile 设置及另一 profile。

## 修复的验收缺陷

原 R01 runner 曾在完整模型请求中搜索 Skill 名称，用户提示词本身也可能满足条件。当前实现把检查范围收紧为宿主拥有的 system/developer 消息和工具声明，并通过 Hermes `--skills` 明确预载安装项。收紧后 R01 11/11 与本批 R04 15/15 均重新通过。

## 身份与边界

- 候选二进制 SHA256：`b6e7650f9ab35f6b259cbd64fe9be5a19347b3689ed3dab0be38874d4bda6708`
- Hermes CLI SHA256：`4e623fce245c1fe6e70ae0edd3248b376ceaf94d560d63f5881cc7a3415ec609`
- Runner SHA256：`cec6433aeca1a3acd2dc351175a23621c89562330e320197737f7a72486e7cc2`
- 机器范围：Linux/aarch64；Hermes 真实进程，本机合成模型与自动测试操作者。
- V2 来源是用户明确导入的本地目录。公网调度取数因当前网络前置条件仍 blocked，不能由本证据代替。
- 测试观察器只上报 Hermes 生成的 session/task ID，不持有 SIQ 凭据或签名权限；完成后禁用并删除文件。
- Windows、macOS、OpenClaw、WorkBuddy 的更新链仍需各自实机验收。
- 本地预留、状态事务和外部副作用不能组成跨系统 exactly-once 事务。

机器可读结果见 [report.json](report.json)，文件摘要见 [SHA256SUMS](SHA256SUMS)。
