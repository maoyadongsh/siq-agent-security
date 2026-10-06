# Skill 异常收尾诊断增量

历史 drift-002 与 replacement-003 的对应 supervisor invocation 日志均只有
`supervisor_failed_closed`。持久记录显示已收容、最终释放，但不能由最终状态反推
最早失败阶段，也不能把收容直接计为下一次工具调用的签名拒绝。
只读复核见 [原始运行分类读回](../inventory/research-rg05-historical-runtime-review-001.json)。

Research 监督器新增固定类别日志 `supervisor_failure stage=… category=…`，覆盖
授权加载、owner 检查、续期、运行身份、relay/forward/broker 与清理等阶段。不输出
异常文本、身份、凭据或业务正文。原错误处理、拒绝、访问切断、沙箱回收及状态
schema 保持原有行为；日志写入失败也不跳过收容。

143 项监督器、服务、请求监督及身份回归通过，其中包括私密错误不进入日志、
日志处理器自身异常仍执行原收容的负向测试。随后独立端口的两种启动配置再次
通过，见 [launch-002](research-permissions-launch-002.json)。

日常 API 在无存活业务租约和请求 sandbox 占用时刷新源码绑定并重启，保留
qwen38 保护路由。PID 从 2716725 变为 2814391，恢复与前端健康检查通过。
此次只变更两个已冻结源文件；备份了上个受保护版本的对应源码和覆盖文件，失败
时恢复受保护版本，而非自动回退到旧 Host 路由。
见 [冻结部署协议](../protocols/research-permissions-supervisor-diagnostics-001.json)与
[部署记录](research-permissions-supervisor-diagnostics-001-deployment.json)。

此增量是观测能力修复，尚不能据此关闭 RG05。新增 Skill 漂移批次保留原要求：
真正的第二次同文件写入必须出现签名拒绝、原文件保持、任务完成且清理通过。
诊断包装器的第一次准备失败（缺少父场景需要的 task 默认值）发生在业务/API/模型
创建前，已独立保留为 [drift-003 准备失败](research-permissions-skill-drift-003-preparation-failure.json)。
修复与命令行构造测试完成后改用新批次 drift-004，不重写 drift-003。
