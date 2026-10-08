# 原生业务身份消费者 v1

业务仓库的显式原生 profile 使用现有 SIQ HTTP 合同：self/v2、request-identity-issued/v2、session-enrolled/v3。旧插件消费者保持原有严格版本，不隐式升级或降级。

消费者配置绑定 loopback 端口、根 identity/instance、Grant ID、scope_id、固定 runtime_artifact_sha256 与宿主私有 credential_path。配置由已授权的业务部署入口提供，不能由模型、请求正文或沙箱改写。客户端不创建管理审批、不注册 issuer；既有管理员批准和 issuer 配置是前置条件。每次操作按磁盘对象身份复验 0600、单链接、当前用户拥有的凭据，禁止重定向、代理、重试或响应回显 token。

签发前读回父 self/v2，严格校验必需原生策略、Grant 与身份。request_id、execution_sha256 和 expires_at 必须来自业务已有授权和执行租约；消费者限制有效期最多一小时，不自行延长。子身份 ID 按既有域分离 SHA-256 推导；签发响应必须精确匹配父身份、业务 scope、请求/执行摘要、到期时间、session namespace、Grant 与制品策略。只有验证完响应，才能读取父凭据同目录中固定 `{child_id}.token`，不得读取响应任意指定路径；再以子凭据读回 self/v2，确认内容一致。

会话登记仅接受实际原生 session，经固定 namespace 与 SHA-256 派生，核对 v3 响应主体/策略/时间。撤销沿既有 parent request cancellation 接口，即使父身份或 Grant 已失效仍尝试精确取消，不先要求 active self 读回；必须确认响应，失败不得伪称已清理。所有异常对外只给固定类别。

此消费者仅证明安全协议衔接。业务用户权限、对象范围、执行租约、取消/回收、实际 PID 与制品核验仍由所属业务和原生宿主负责。它不向沙箱传递 SIQ 运行凭据，也不把 self/enroll 的 unverified 状态提升为已验证运行。
