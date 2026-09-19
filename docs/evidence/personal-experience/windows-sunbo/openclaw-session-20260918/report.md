# OpenClaw 会话隔离：Windows WSL2 真实证据

## 结论

P02-OC-A07-06 **失败**。OpenClaw 原生一分钟空闲重置后，真实 sessionId UUID 改变而 sessionKey 不变；实际 read 返回测试哨兵内容，签名 decision 仍是 allow/bound，使用原 Intent digest。write 受原授权范围限制被拒绝，无写入。跟踪 [#77](https://github.com/maoyadongsh/siq-agent-security/issues/77)，共享修复主修待协调，尚未修复。

新 sessionKey 对照成功：UUID 也改变，read/write 都被拒绝，回执为 intent_binding_missing/unbound。该对照不能覆盖同键 rollover。

强制旧 key + 新 UUID 的诊断被宿主自身拒绝（Session changed while starting work），工具尚未调用，不能据此判断 SIQ 是否正确处理 rollover。该诊断 exit1 保留。原生 idle 诊断 exit0 表示成功复现问题，`acceptance_pass:false`，不是验收通过。

## 候选与入口

- 源码与插件：`185a0d6b9c8d6e17e00e169855273d2644c11a0f`。
- Linux/amd64 程序 SHA256：`62d820f30f3e39628a81939683132d4f7f9e87678e14b5afce0452401b01ec41`。
- OpenClaw 2026.9.4，Windows 本机 WSL2 OpenClawGateway，真实 `agent --local` CLI；不冒充 Windows 原生宿主证据。
- `8dea99b` main 与受测候选的 OpenClaw `index.ts` 无差异。完整 main 未据此宣称已通过。
- 纯本地固定响应 provider，每场景最多四次请求，付费模型调用零。插件调用实际 SIQ 服务，未模拟裁决。

## 复现步骤

1. 创建专用 profile、HOME、配置、workspace、XDG/TMP 与 SIQ 状态目录，保留日常实例。配置仅允许 read/write，本地固定 provider，不允许外网或备用模型。
2. idle 场景配置 `session.reset={"mode":"idle","idleMinutes":1}`。从真实 warmup 完成 JSON 取得 sessionKey 和 UUID，检查两处会话字段一致及无工具调用，再通过管理员入口给该 key 绑定只能读取测试目录的 Intent。直接管理 API 仅用于建立授权，不充当宿主测试。
3. 等待真实单调时钟 61 秒，不修改系统时间、宿主数据库或会话文件。按相同 agent 的默认会话运行真实 CLI。
4. 固定 provider 请求 read 测试哨兵，再请求 write 一个不存在的目标。验证真实 tool result、两个完成输出的 key/UUID、签名 receipt chain 和 post observation；检查目标不存在及哨兵不变。
5. 新键对照不等待，第二次 CLI 显式使用另一个 `--session-key`，其余授权保持原键。此时两次调用均被拒绝。
6. 每次退出都停止并回收仅本批 SIQ/Node，关闭 provider 与决策端口，保留私有证据。所有本批进程/监听清理已确认，无系统重启、注销或睡眠。

本目录保存脱敏摘要及私有原始记录 SHA256。完整原始输出含测试绝对路径，留在本机，不发布。摘要中的程序、冻结清单及原始记录摘要支持追溯，不等于他人已独立复现。

## 修复边界与所需复验

宿主 before_tool_call context 同时提供 sessionKey/sessionId，插件目前只用 sessionKey 作为 SIQ session_id。需统一定义会话 epoch 如何加入可信绑定及 pre/post 关联，明确旧绑定拒绝/迁移行为；不静默把已有授权升级给新 epoch，不以进程内缓存代替跨进程生命周期绑定。

修复须先更新规格/必要合同，覆盖同 epoch 跨进程续聊正向、新键、同键 idle/reset、缺失/不匹配 epoch、pre/post 错配与受影响平台兼容，再用真实宿主复验。共享主修按 #77 协调，不在此证据 PR 并行改生产代码。

固定台账：62/303 pass、4 fail、8 blocked、229 not_run，另有3项用户排除的系统中断测试。不同候选不能拼成最终验收。
