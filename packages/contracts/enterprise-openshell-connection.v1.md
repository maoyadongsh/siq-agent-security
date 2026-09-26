# 企业 OpenShell 只读连接诊断 v1

GET /api/v1/environments/{environment_id}/openshell-connection：环境租户定位 404，env:manage 与 policy:read 权限 403，然后诊断。无请求配置输入，无数据库变更，no-store。

响应 schema_version=enterprise-openshell-connection/v1，scope=control_plane_connection；status 为 not_configured / configuration_rejected / probe_failed / identity_unverified / version_unknown / handshake_verified。ready_for_deployment=false，version_compatibility=unverified，credential_scope=unverified，execution_evidence=none；这些结果不能证明网关/沙箱属于该环境。

仅显式绝对普通可执行 CLI 文件、非 group/world writable、HTTPS endpoint、无 userinfo/query/fragment/path、无 env.sh、insecure 为 0/未设置；缺配置与非法配置在执行前返回固定状态。不读取证书/配置秘密，不暴露 endpoint、路径、环境、stderr 或网关名称。子进程上下文冻结且白名单过滤，复用有界命令执行器，每次诊断总预算 10 秒。只允许 gateway info/status/--version。

握手成功返回 endpoint_fingerprint、gateway_name_sha256、cli_version/gateway_version（缺失为 unknown），configuration_capabilities 只投影 network.dynamic_update/enforcement_mode.block 的适配器表达能力。版本信息不表示已通过兼容矩阵；失败不复用以前的成功结果。诊断可读本地 CLI 配置以握手，但不扫描用户资产、创建沙箱或写策略。
