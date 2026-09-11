# ADR-020：个人发现流程与 Skill 安装身份

- 日期：2026-09-10。
- 状态：实施中；对应 UX-002、UX-005、UX-012。

## 问题

`GET /v1/assets` 读取投影缓存，前端“重新盘点”没有可靠触发扫描。Skill ID 包含平台、名称及摘要，导致不同目录的同名内容相撞，版本变化也会更换安装身份。一层目录扫描遗漏分类目录、profile Skills；共享目录去重后没有消费者关系。

## 身份与关系

- 安装 ID 采用 `skill-installation:<脱敏规范化目录 SHA-256 前 32 位>`，不含名称和内容。原路径修改内容仍是同一安装，复制到另一目录则是另一安装。
- `artifact_digest` 表示内容版本；版本文字仅是声明，不替代摘要。发现身份不能直接授予运行权限。
- Skill locator 统一为 `local://skills/<脱敏路径>`。旧 locator 在台账稳定键中归一化，旧记录保持不可变。相同路径和摘要的 ID 迁移不自动撤权；实际内容变化继续复核和撤权。
- 关系包括 source_id、skill_id、basis、state:inferred 和证据，仅表示目录/配置关联，不证明平台已加载、任务实际使用或权限生效。
- 一个共享安装可关联多个已发现消费者。缺少证据时显示使用者未知，不通过同名文本猜测。
- Hermes default 和各 profile 分别关联本身目录；OpenClaw 共享根关联配置中的实例，明确 workspace 根关联对应实例。允许列表、覆盖优先级及会话快照仍需运行时验证。

## 发现与扫描

- 配置只读已知字段、限制大小；不读取认证文件，不执行内容，不跟随用户目录符号链接。
- 有界递归寻找 SKILL.md，找到后不把其引用目录继续算作其他 Skill。读取失败、无结果和扫描达到上限分别显示。
- 扫描前展示已知范围与可选项目/Skill 目录；显式扫描提供运行、完成、部分完成和失败状态，不把缓存读取当作重新发现。
- 手动目录在状态目录独立版本化保存，后续刷新与重启继续采用，不混入权限配置。范围扩大保留已登记范围，不修改平台配置。
- 复用 inventory、ledger 和生命周期逻辑，不自动确认纳管或启用钩子。新增管理接口只接受 admin 会话。

## 兼容和验证

沿用 Candidate 合同；新增关系合同为 local-discovery.v1。旧记录按归一化定位映射到新 ID，新投影不重复展示旧 ID；历史 Grant/回执不改写。

验证覆盖重复扫描、同名不同目录、内容变化身份稳定、共享多消费者、profile 隔离、嵌套分类目录、符号链接/超大配置拒绝、内容不执行、显式重扫、手动范围持久化、旧 ID 迁移和实际变化撤权。

目录规则参考 [OpenClaw Skills](https://docs.openclaw.ai/tools/skills)、[Hermes Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) 与 [Hermes Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/)，检索日期 2026-09-10。解析测试不能代替真实版本运行验收；WorkBuddy 不以 CodeBuddy 结果替代。
