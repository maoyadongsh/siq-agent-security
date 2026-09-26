# 企业运行目标授权清单 v1

受控设置 SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE 指向绝对本地路径。Linux 描述符逐组件打开、禁止符号链接；末级普通文件、所有者 root 或控制面服务 UID、无 group/world 写权限、单硬链接、≤256 KiB，读取前后元数据须一致。解析拒绝重复 JSON 键、非 UTF-8、额外字段或非法标识。缺少/不支持平台/不安全/畸形/过期均失败关闭，不回显路径或内容。

schema_version=enterprise-runtime-target-authority/v1，issued_at/expires_at 必须带 UTC 时区且 expires_at>issued_at，当前时间满足 issued_at<=now<expires_at。assignments 为 0–1024 项，每项：id、tenant_id、environment_id、asset_id、agent_instance_id、endpoint_fingerprint（64 位小写 SHA-256）、gateway_name_sha256（同）、backend_target_id（1–128 位 ASCII 机器名，不能通配）。对象 ID 为 1–64 位 ASCII 字母数字及 _ . : -。

条目 ID 互异；同 endpoint_fingerprint + backend_target_id 不得重复分配，即使 tenant、环境或网关名不同也拒绝整个清单。仅匹配验证身份派生的租户与服务端绑定各字段，backend 必须 openshell-cli，不接受缺省或部分匹配。成功只返回条目 ID、清单 SHA-256 和有效期，不返回其他租户数据。

OpenShell CLI 部署准备必须在目标策略读取前精确匹配授权，预览摘要包含授权条目、清单摘要和有效期。执行前重新握手并重读，授权变化不能沿用旧预览；缺少可信连接身份返回 deployment_target_identity_unconfirmed，授权缺失/无效返回 deployment_target_authority_unverified，准备后授权变化返回 deployment_target_authority_changed。成功回执记录 target_authority、endpoint_fingerprint、gateway_name_sha256。回滚必须重验当前授权、来源引用与原回执连接；旧回执缺少连接证据时拒绝。开发模式 openshell-cli 不豁免；仅 fake 开发后端保持独立模拟语义。

基础模块不自动修改 RuntimeBinding、沙箱、策略或权限。登记仍为声明，不能据此证明实际运行角色。共享目标、真实运行身份/Skill 版本证明、外部写入并发边界和紧急撤销执行仍需独立完成。
