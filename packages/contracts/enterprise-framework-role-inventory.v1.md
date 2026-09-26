# 企业框架—角色分页清单 v1

GET /api/v1/framework-role-inventory，要求 agent:read 和 env:read；租户仅从认证身份取得。支持 environment_id/device_id 精确过滤、cursor（上一页末尾资产 ID）、limit=1..100，默认 50；按资产 ID 升序，以 limit+1 判断下一页。返回 schema_version=enterprise-framework-role-inventory/v1、items、next_cursor、coverage=page_of_tenant_assets。不返回或推断组织全量计数。

每项包含 asset_id、name、reported_framework、asset_status、framework_source（完整 enterprise-framework-source-view/v1 投影）。清单保留无来源的旧资产；来源不足时不将其强行归为框架运行实例。角色名称和 assigned role 不充当实例标识。客户端仅可对 historical_reported_source 按认证上下文+环境+设备+framework+instance_key 分组；未知来源单列，不按同名混并。不同页面可能属于同一实例，当前页分组不是该实例的完整角色清单。

环境/设备过滤只命中当前租户可关联设备；不存在或外租户过滤为空，不泄漏对象。未加过滤时，本租户损坏来源的资产保留，但 foreign 设备信息不投影。请求不接受租户覆盖，不创建扫描、关系、权限或审计，no-store。来源仍是历史报告，runtime_status=unverified、技能安装关系 unresolved、有效权限 null。来源批量核对使用有界查询，不对每个角色单独请求或查询一次。

## 版本导航（2026-09-26）

本文件的 v1 语义（OpenClaw 来源、字段、分页、过滤与全部边界）保持不变，旧正文未替换。当页面投影包含 Hermes 的 `enterprise-framework-source-view/v2` 时，同一端点按页返回 `enterprise-framework-role-inventory/v2`：字段、配对与兼容限制见 [enterprise-framework-role-inventory.v2.md](enterprise-framework-role-inventory.v2.md) 与 [enterprise-framework-source.v2.md](enterprise-framework-source.v2.md)。同一分页旅程可能先 v1 后 v2，客户端须逐页核验；旧 v1 严格客户端可能拒绝 v2 页，不能视为对旧客户端完全无感兼容。
