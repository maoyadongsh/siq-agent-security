# Edge 能力心跳更新 v1

POST /edge/v1/heartbeat 增量支持可选 capabilities：

```json
{"inventory_schema":"enterprise-installed-capabilities/v1","protocol_version":"connector-protocol.v1","connectors":["hermes"],"connector_versions":{"hermes":"0.1.0"},"data_categories":["config_names"]}
```

该对象字段严格校验，不允许组织/环境/路径/任意诊断字段。ID 采用安装计划的 12 项枚举，至多 12 个且不可重复；版本键必须与 connectors 完全一致，类别为至多 64 个有界机器标签。空数组和空版本表表示设备当前未确认任何可用采集器，不代表环境没有资产。省略或 null 兼容旧客户端，保留原记录。

服务端只从在线校验的设备凭据确定设备、环境与租户。能力更新替换而非合并，变化时写 edge.capabilities.update 审计（仅计数、协议版本），与心跳和能力保存同事务；相同值心跳不重复写变更审计。失效/吊销凭据拒绝更新。申报能力不是可信执行证明，不更改资产、策略、业务权限或审批。

Linux serve 对已保存确认计划的设备，在每次心跳前核对计划摘要/环境/origin/架构及 SIQ_CONNECTOR_BIN_DIR 对应的可信暂存布局，读取发行清单并以固定发行公钥复核制品，然后调用 describe/validate_scope。持久确认不因最初 15 分钟安装期限过期而失效。任一核验失败时发送明确空能力集合并输出固定的 unverified 日志；这表示未确认可用，不是资产为空或确认卸载。取消服务不发送空集合。没有本机确认计划的旧设备仍省略该字段。

当前快照采用整批保守失败，不提供每采集器失败原因；UI 证据状态展示、旧 register 和独立 heartbeat 的迁移仍须配套完成。重新验签为周期时点检查，不是防御同用户恶意进程替换文件的完整隔离证明。
