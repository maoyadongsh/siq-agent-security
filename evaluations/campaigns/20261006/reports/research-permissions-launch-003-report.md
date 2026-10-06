# 授权失效反馈修复的启动检查

隔离端口 18083 分别启动 protected 和 rollback 配置，两种模式各 9 项检查通过；检查实际进程、后端选项、健康、匿名业务请求拒绝、回收禁用及退出。原日常 API 在检查期间保持 PID 2814391 不变。

这是无模型、无业务执行的部署前检查。原始结果见 [launch-003](research-permissions-launch-003.json)，后续默认入口部署另见 [部署记录](research-permissions-authority-loss-message-001-deployment.json)。
