# OPT-07 策略语义与入口一致性核查

日期：2026-10-07。状态：初始核查记录；实施结果见 [验证报告](optimization-opt07-validation-20261007.md)。下文保留当时问题定位，不作为当前未完成清单。基于 OPT-05 在线接入提交 `fa908fdf`。

## 已确认的当前行为

- `policy_compiler.py` 将 filesystem 的 `read_only` / `read_write` 缺省或假值归一为空列表；其他 filesystem 字段未映射。需要区分合法省略、非法类型及未知意图，不能因为编译产物可生成就认定完整表达了请求。
- process 对象原样进入产物；`plan_change` 仅比较请求包含的字段，因此它实际具有字段补丁语义。空对象不表示删除整个静态段。需要明确文档，并验证空值、删除意图和缩短集合不会静默变成成功。
- `apply_dynamic` 复制完整原策略，只替换网络段，保留静态与未知后端扩展字段。该既有保真行为必须保留。
- `PolicyCreate` 可接收可选字段 null，数据库输出与编译输入有归一层；公共 DesiredPolicy schema 的静态段则是对象。需要追踪 `_desired_from_policy`、前端生产者及所有编译消费者后确定兼容处理，不能直接将所有 null 改成删除。
- 旧 `/api/v1/deployments` 仍存在；preview submit 与 submission 复用 `prepare_deployment` / `execute_deployment`。批量调度还需沿 service/worker 继续追踪，不以路由共用函数替代入口负向验收。

## 开发与验收安排

1. 先形成版本化语义合同：省略、null、空对象、空数组、字段替换与显式删除，分别说明 API 输入归一与后端策略合成。
2. 为未知 filesystem 意图、非法静态值、allow 集缩短、静态重建拒绝和纯网络更新保留静态段补充负向与兼容向量；复用共享 policy compile vectors，检查 Go 等消费者。
3. 列举旧部署、preview submit、submission、批量执行、CLI/Edge 的实际支持边界，逐入口检查租户、权限、审批失效、binding 吊销、目标漂移与重复执行。
4. 保留支持中的旧入口并说明是否需要预览摘要；前端未使用函数清理不作为安全修复证据。
5. 按影响运行定向测试、合同验证、API 全量和 PostgreSQL 门禁；若变更共享规则或 Go 语义则增加相应消费者验证。

本任务尚未完成语义合同或行为改动；不据此宣称已修复或通过。
