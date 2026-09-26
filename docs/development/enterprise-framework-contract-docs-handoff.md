# CL-03-FRAMEWORK-CONTRACT-DOCS 交接记录（框架来源协议兼容文档收口）

- 日期：2026-09-26
- 任务书：CL-03-FRAMEWORK-CONTRACT-DOCS
- 状态：**未提交、未部署；仅文档收口完成，不代表 CL-03 或整体项目完成。**

## 1. 实际文件

| 文件 | 改动 |
| --- | --- |
| `packages/contracts/enterprise-framework-role-inventory.v2.md` | 新增：清单 v2 独立合同说明（端点/权限、顶层字段与分页、条目字段、来源-框架配对、按页选版本、兼容限制、分组边界、保留边界、最小合成示例） |
| `packages/contracts/enterprise-framework-role-inventory.v1.md` | 末尾追加「版本导航」一节，v1 正文未改动 |
| `packages/contracts/enterprise-framework-source.v1.md` | 末尾追加「版本导航」一节，v1 正文未改动 |
| `docs/development/enterprise-framework-contract-docs-handoff.md` | 新增本记录 |

未修改 source.v2 合同、任何代码、前端、README、台账或其他交接文件。

## 2. 源码对应位置（版本映射）

| 文档事实 | 代码依据 |
| --- | --- |
| GET URL、agent:read+env:read 双读、租户仅来自认证身份、no-store、只读 | `apps/control-api/app/routers/framework_inventory.py:14-39` |
| 顶层精确四字段；cursor 格式 `agt_…`（1..60）、limit 1..100 默认 50、资产 ID 升序、limit+1 判下一页、next_cursor=本页末项或 null、coverage=page_of_tenant_assets | 同上 `:15-44` |
| 条目五字段 v1/v2 一致 | 同上 `:42-43`；`apps/web/src/api/frameworkRoleInventory.ts`（exact 校验） |
| 来源投影仅 view/v1 或 view/v2；配对 view/v1↔openclaw、view/v2↔hermes；不可核对 source=null（no_recorded_source / source_unavailable） | `apps/control-api/app/framework_source_view.py:19-23,33-41,59-66`；`apps/web/src/api/frameworkSource.ts`（framework 配对断言） |
| 按页选版本：页内任一 view/v2（含 Hermes 无来源/不可核对的 view/v2 占位）→ 整页 inventory/v2，否则 v1；v2 页可混合两种视图 | `framework_source_view.py:20`（逐资产按 framework 定投影版本）+ `framework_inventory.py:40`（任一 /v2 即整页 v2） |
| 入库侧仅接受 (source/v1,openclaw) 与 (source/v2,hermes) 配对，Hermes 证据须 manifest / KEY/config.yaml | `apps/control-api/app/framework_source.py:26-31,46-63` |
| 前端逐页逐条严格核验，异常抛错不回退空列表；v1 页内出现 view/v2 即拒绝 | `apps/web/src/api/frameworkRoleInventory.ts`（parseFrameworkRoleInventory/parseItem） |
| 入库可用=Batch172、读取与树消费者接通=Batch173；浏览器/原生跨语言旅程证据缺失 | `docs/development/enterprise-auto-onboarding-closeout-20260926.md:79-81` |

## 3. 兼容限制（文档已明确）

- 同一分页旅程可能先 v1 后 v2，客户端须逐页核验；不写"所有请求恒 v2"。
- 旧 v1 严格客户端可能拒绝 v2 页，不称"对旧客户端完全无感兼容"；生产者/消费者配套交付。
- 不把 Hermes 映射为 OpenClaw、不删版本校验、不自动降级。
- 分组仍为认证上下文+环境+设备+framework+instance_key；跨框架同摘要不合并；同名角色非同一实体。
- 保留边界：page_of_tenant_assets 非全量；runtime_status=unverified、skill_relationship_status=unresolved、effective_permissions=null；Hermes profile 来源不证明技能安装/加载、进程存活、共享沙箱或保护。

## 4. 示例核验

`enterprise-framework-role-inventory.v2.md` 的最小合成响应逐字段对照前端解析器：`asset_id` 匹配 `agt_[A-Za-z0-9_-]{1,60}`；`instance_key`/`config_sha256` 为 64 位小写 hex；`environment_id`/`device_id`/`observation_id` 匹配 identifier 正则；`observed_at` 满足 `^\d{4}-\d\d-\d\dT.*Z$` 且可解析；顶层/来源精确键、coverage、升序、next_cursor=null 均满足。数据全部为合成占位。

## 5. 检查命令与结果

```
三个合同文件相对链接检查：全部存在
新文件行尾空白检查（grep -P '[ \t]+$'）：无
git diff --check：通过
```

未运行 npm test / pytest / Go 测试 / 浏览器或构建，未安装依赖，未操作真实设备或服务（按任务书预算；示例为人工对照，未跑解析器进程）。

## 6. 未完成项与证据边界

- 本任务仅核对文档与当前源码；不证明部署、浏览器验收、跨语言原生旅程或正式发行。
- 不将 Batch172/173 的历史测试数量计入本任务通过项。
- 精确角色—Skill 关系仍未解决（Batch173 口径），清单 v2 不关闭 CL-03。
- 未发现实现与本说明的冲突；若后续实现变更，以实际代码与已接受合同为准更新文档。

## 7. 主开发者复核（2026-09-26）

核对清单路由、来源投影与前端解析器后，收紧一处表述：instance_key 等于资产 locator 末段是 Hermes 专属规则，不适用于 OpenClaw 的配置实例键与角色定位键。已直接修正文档，无协议或代码变更。

本交付的 Batch173 浏览器证据缺失为当时状态。后续主线 Batch174 已完成隔离模拟浏览器 16 项检查，并修复树标题误标；不计为本 GLM 文档任务执行的测试。原生跨语言全链路、真实设备、正式发行仍未验证。未提交、未部署。
