# 企业绑定证据就绪度 v2（内部只读检查）

本版继承 [v1](enterprise-binding-evidence-readiness.v1.md) 的全部结构与安全边界，
仅以本节覆盖下列判定。不是 HTTP 合同，不接入任何路由或执行链。

- `schema_version` 改为 `enterprise-binding-evidence-readiness/v2`。
- 原固定原因码集合增加 `declaration_record_invalid`。没有新增状态或执行开关。
- `declared_selection` 在输出引用前复用 `RoleSkillSelection.model_validate` 校验持久声明。
  该声明记录只适用于 `openclaw` / `openclaw_agent` 资产，不得套用于 Hermes。
  非对象、缺字段、非法状态/来源、非法名称及结构不一致，返回
  `records_inconsistent` / `declaration_record_invalid`，不返回损坏内容及校验异常。
  校验通过只证明声明结构符合已有合同，不重新认证历史签名，不证明运行归属。
- `directory_candidate` 除结构解析外，复用 `validate_role_skill_roots` 校验资产框架、
  来源类型与 framework_source 的版本配对；失败仍使用 `layout_candidate_invalid`。
  本子事实不证明设备当前可用，也不证明安装或加载。

五个维度、其余原因码、输出白名单、查询租户边界、只读与不得推导要求均沿用 v1。
安装观察仅为该设备范围的历史观察，不是该角色的安装集合；设备当前已吊销与历史记录
是否存在是独立事实。记录校验不等于历史签名重新验证或完整数据库抗篡改核验。
`execution_confirmation_supported` 恒为 false；不得据此开放执行按钮。
调用方仍负责传入经认证的 Identity 并检查入口权限；非空 tenant_id 不是身份认证。
本层非原子快照，不设 TTL，不改变预览、影响、执行和审批链的任何判据。

当前模块尚无既有消费者；未来消费者须显式识别 v2，不得将其当作 v1 静默接受。
