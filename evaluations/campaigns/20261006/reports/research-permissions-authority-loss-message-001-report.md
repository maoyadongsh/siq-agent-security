# 执行后授权失效反馈修复

已运行任务在结果收集后失去权限或运行所有权时，此前错误返回“会话已有请求”，普通响应还保留成功 terminal_result，流式响应建议重试。现在两个路径都明确记录 failed / active_run_lease_lost，返回权限或运行状态变化、结果无法确认的消息；该终态 retryable=false。真正的准入冲突保留原行为，授权检查、租约检查、原收容和 finalizer 均未放宽。

修改仅位于 Research 项目 `apps/api/services/agent_chat_runtime_impl.py`，新增正反向场景在 `test_agent_runtime_authority_loss.py`。相关 85 项测试通过（392 条既有弃用警告）；隔离端口上的 protected / rollback 启动各 9 项检查通过，见 [launch-003](research-permissions-launch-003.json)。新默认启动清单冻结 1,647 个源文件。

在确认没有未过期运行租约后，仅重启原 API 服务；一个 7 月过期历史行保留未改。日常前端 15173 和 API 18081 的健康、恢复状态及 qwen38 路由正常，新 PID 2952550；详见 [部署记录](research-permissions-authority-loss-message-001-deployment.json)。原受保护版本的源码和服务覆盖文件已备份，可回退到上一受保护版本。没有切换回 legacy Host。

阶段限制：启动和单测不替代真实任务复验；接续批次为 drift-containment-002。历史 replacement-003 曾返回相同“会话已有请求”文字，但缺少当时的底层原因记录，不能把这次复现直接当成该历史失败的唯一根因。
