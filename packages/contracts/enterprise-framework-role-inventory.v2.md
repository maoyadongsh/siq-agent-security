# 企业框架—角色分页清单 v2（Hermes/混合页扩展）

本文记录已实现的清单 v2 行为，供 Hermes 与混合页消费使用；不设计新 API，不改变 v1 的既有语义（见 [enterprise-framework-role-inventory.v1.md](enterprise-framework-role-inventory.v1.md)）。清单仍是分页来源投影，不证明进程运行、技能已加载或权限生效。

## 端点与权限（与 v1 相同）

GET `/api/v1/framework-role-inventory`：先 `agent:read`、`env:read` 双读；租户仅取自认证身份，不接受请求中的租户覆盖；响应 `Cache-Control: no-store`；不新增任何业务写请求。

## 顶层字段与分页（与 v1 相同）

顶层精确字段为 `schema_version`、`coverage`、`items`、`next_cursor`，无额外字段。分页规则不变：`environment_id` / `device_id` 精确过滤（1..64 字符）；`cursor` 为上一页末尾资产 ID（格式 `agt_` + 1..60 位字母数字下划线连字符）；`limit` 1..100，默认 50；按资产 ID 严格升序，取 `limit+1` 判断下一页，`next_cursor` 为本页最后一项资产 ID 或 `null`。`coverage` 恒为 `page_of_tenant_assets`，不是组织全量，不返回或推断全量计数。

## 条目字段与嵌套版本

条目字段与 v1 完全一致：`asset_id`、`name`、`reported_framework`、`asset_status`、`framework_source`（完整来源投影）。嵌套来源只接受明确的 `enterprise-framework-source-view/v1` 或 `/v2`，精确字段、精确键，不接受任意版本号。清单 v1 页仅含 view/v1；清单 v2 页可混合 view/v1 与 view/v2 条目。

## 来源与框架配对

来源投影与框架严格配对：view/v1 的成功来源配 `framework=openclaw`；view/v2 的成功来源配 `framework=hermes`。仅 Hermes 要求投影的实例键等于资产 locator 的末段 profile 键；不要将此等值规则套用到 OpenClaw 的配置实例键与角色定位键。缺失声明为 `status=no_recorded_source`；声明存在但证据/设备/租户归属不可核对为 `status=source_unavailable`；两者 `source=null`，不得为无法核对的来源造节点或补造框架名。

## 按页选择版本

服务端按**页面投影内容**选择清单版本：页内任一 `enterprise-framework-source-view/v2` 投影（包括 Hermes 资产无来源或来源不可核对时返回的 view/v2 占位）则整页为 `enterprise-framework-role-inventory/v2`，否则为 v1。因此同一分页旅程可能先返回 v1 页后返回 v2 页，客户端必须逐页验证 `schema_version` 与每个条目的视图版本，不能假定整段旅程恒为 v2 或恒为 v1。

## 兼容限制

旧 v1 严格客户端遇到 v2 页可能拒绝，**不能称为对旧客户端完全无感的兼容**；生产者与消费者应配套交付。不得为绕过校验把 Hermes 映射为 OpenClaw、删除版本校验或自动降级；当前 Web 解析器同时接受两个清单版本并逐页、逐条严格核验，异常响应直接报错，不回退为空列表。

## 分组边界（与 v1 相同）

分组仍以认证上下文 + 环境 + 设备 + framework + instance_key 为准；OpenClaw 与 Hermes 即使摘要相同也不能合并。同名角色或相同角色名称不表示同一实体。

## 保留的历史与未知边界

`coverage=page_of_tenant_assets` 不是全量；来源是历史报告，`runtime_status=unverified`、`skill_relationship_status=unresolved`、`effective_permissions=null`。Hermes profile 来源（config.yaml manifest 证据）不证明技能安装/加载、进程存活、共享沙箱或任何保护生效。

## 最小合成响应示例

以下为纯合成数据，不代表任何真实资产、设备、证据或摘要取值；字段、标识格式与时间格式满足当前解析器：

```json
{
  "schema_version": "enterprise-framework-role-inventory/v2",
  "coverage": "page_of_tenant_assets",
  "items": [
    {
      "asset_id": "agt_synthetic_example_01",
      "name": "synthetic-hermes-asset",
      "reported_framework": "hermes",
      "asset_status": "candidate",
      "framework_source": {
        "schema_version": "enterprise-framework-source-view/v2",
        "asset_id": "agt_synthetic_example_01",
        "status": "historical_reported_source",
        "source": {
          "framework": "hermes",
          "instance_key": "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",
          "environment_id": "env_synthetic_01",
          "device_id": "edge_synthetic_01",
          "device_revoked": false,
          "config_sha256": "9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a9a",
          "evidence_id": "evd_synthetic_01",
          "observation_id": "obs_synthetic_01",
          "observed_at": "2026-09-26T00:00:00Z"
        },
        "runtime_status": "unverified",
        "skill_relationship_status": "unresolved",
        "effective_permissions": null
      }
    }
  ],
  "next_cursor": null
}
```
