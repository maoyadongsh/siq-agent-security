# 原生请求会话命名空间 v1

本增量补充 native-hermes-dispatch/v1 与 native-runtime-bootstrap/v1 的启动配置约束，兼容已有短 namespace；生命周期、签名身份与 HTTP 响应版本不变。

受保护启动器必须从实际签发的请求身份读回 `request.session_namespace`，原样传给 ImageBootstrap 和 Runtime。允许 1–191 个 ASCII 字符，格式为 `[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)*`；不截断、规范化或删除冒号，不接受空组件、空白、控制字符或 Unicode。两入口共享同一校验器。

原生会话 ID 为 `namespace + ":" + sha256(实际 Hermes session 的 UTF-8 字节).hexdigest()`，最长 256 字节，符合宿主主体限制。原始 session 校验保持不变。191 字符是边界允许值，192 字符必须拒绝。

业务请求 namespace 由现有 Go 请求身份签发器固定为 `siq:openshell:pool:{scope_id}:{request_id}:siq_analysis`。允许这种字符串格式不授予权限：子身份仍绑定父身份、批准基线、请求、执行摘要、到期时间与必需原生制品策略；服务端必须拒绝其他 namespace 的会话。根凭据仅用于宿主请求身份签发；向决策转发器提供子凭据，任何运行凭据均不进入沙箱。

验收必须使用真实管理 HTTP 开启请求签发、父凭据签发子身份及子凭据登记会话，再运行 OpenShell/Hermes 权限链路；检查错误 namespace 拒绝及父基线撤销后子身份无法继续读写。受控请求 ID/执行摘要和合成 Skill 的联验不替代业务 API、用户授权与日常启动器验收。
