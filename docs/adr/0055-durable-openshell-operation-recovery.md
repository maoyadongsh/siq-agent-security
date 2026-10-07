# ADR-055：部署后端来源与持久 OpenShell 操作恢复

日期：2026-10-07。状态：实施中；对应 OPT-05，关联 OPT-07/09。

## 已确认的问题

- 回滚分支曾由当前 `SIQ_AS_ENFORCEMENT_BACKEND` 选择；配置变化可能使 OpenShell 部署走账面回滚。
- `PolicyOperationRegistry` 仅进程内保留最多 256 个前置快照。重启、跨 worker 或淘汰后无法安全回滚。
- 外部写入与数据库提交不是同一个事务；不能因本地提交失败就再执行外部写入。

## 分阶段实施

### A：原后端来源

迁移 0029 给 Deployment 增加可空 `execution_backend`。新建部署、单项与批量 reservation 从已验证的服务端准备结果写入；客户端无该字段。回滚只按原来源选择分支，当前配置必须一致。历史空值只接受同租户/环境/目标的原 RuntimeBinding 作为兼容来源，不能猜测。仍执行当前管理权限、活体授权链与网关身份检查。记录过来源后禁止通过降级丢弃它。

### B：持久操作事实源（继续实施前的约束）

1. 操作记录至少绑定 tenant、environment、binding、deployment、backend、target、网关 fingerprint/hash、原 revision/digest、期望应用 digest、实际应用 revision、状态及并发版本。缓存可保留，但不能成为恢复权威。
2. 精确前置策略按敏感配置处理，加密保存，并以不可变来源字段作 AEAD 关联数据。数据表、审计、日志和 HTTP 不含明文 provider 凭据；解密密钥不落操作表。密钥需有 ID 和轮换/保留说明，缺少旧密钥时拒绝猜测恢复。
3. 先提交带审计的执行 reservation，再提交操作意图，最后才进行外部写入。不能在一个未提交的 SQLite 写事务内，通过另一连接“提交恢复记录”。旧部署入口也必须满足该顺序，不靠删除 UI 入口解决问题。
4. 操作状态区分 prepared、applying、applied、unknown、rollback_pending、rolled_back。应用后本地提交失败保持可恢复/未知，不自动再次 apply。失败记录不能当作从未发生外部效果。
5. PostgreSQL 采用目标作用域的跨进程互斥；锁需绑定网关身份和 target。开发 SQLite 若采用文件锁，应限于已验证数据库专属私密目录。锁只约束协作的 SIQ 写者，不能声称后端具备原子 CAS 或能阻止外部管理员竞争。
6. 回滚先读持久记录并复核其完整性，再检查当前授权、binding、网关身份与当前 revision/digest。记录只提供恢复材料，不能替代新一次授权。
7. 重复请求不得再次写后端；已回滚结果的读取与新执行区分。历史缺少持久记录时拒绝自动恢复，调用者提供的快照不能重建可信记录。
8. applying/rollback_pending 的恢复先精确读回；状态相符只能证明当前观测符合预期，不等同于证明该操作的因果归属。无法可靠判定时保持 unknown，不能通过盲目重试“修复”。
9. 外部操作完成、本地 API 返回前失败，仍应保留操作 ID、恢复分类与脱敏错误摘要；不得用一个普通错误对象覆盖唯一恢复线索。
10. 增量迁移不得丢弃尚用于恢复的加密快照或操作历史。降级保护逐层验证，较新迁移提前拒绝时，较老守卫应使用独立直接测试保留覆盖。

## 必须验证

原后端切换拒绝、跨租户与未授权拒绝；空库/有历史数据升级；重启及不同 worker 接续；超过 256 条仍可恢复；外部写入前/后、回执提交前/后故障；重复/并发回滚；策略漂移、网关切换、密文/关联数据篡改与密钥不可用；相应审计与业务状态一致。

A 批完成不能标记整个 OPT-05 完成。B 批的实现选择及证据须继续回写本 ADR 和任务台账。

## B1：内部快照封装

恢复快照采用已有 cryptography 依赖的 AES-256-GCM，随机 96-bit nonce；每个封装包含固定版本、key_id、nonce 和 ciphertext。关联数据为带域分隔的规范 JSON，覆盖操作 ID、tenant、environment、binding、deployment、backend、target、网关指纹/名称摘要、base revision/digest、expected digest，以及版本和 key_id。修改来源字段或密文必须认证失败。完整策略只存在密文及短生命周期进程内对象，不进入 HTTP、审计、日志或 repr。

内部 codec 接受调用方显式注入的独立 32-byte 密钥环及活动 key_id，不自动生成临时密钥、不复用签名密钥、不从数据库读取密钥。轮换时新写使用活动密钥，旧密钥仅解密历史；尚有恢复记录时应保留旧密钥。未知 ID、缺失密钥、格式不符、超过 1 MiB 明文上限、策略摘要不匹配一律失败，错误只含固定类别。服务部署的密钥供应及跨 worker 注入在 B2 接入时另行明确；codec 通过不代表持久恢复已接入。

## B2：持久操作台账

迁移 0030 新增私有 `openshell_operation`，每个 deployment 最多一个 operation，保存不可变来源 JSON、加密快照、状态、epoch、应用/恢复 revision 和 digest，以及时间戳。无明文策略列。外键不级联删除恢复材料；任何非空台账均禁止自动降级丢弃。

内部台账方法使用独立短事务；调用者必须先提交 deployment reservation 并结束任何冲突写事务。prepare 同时校验已提交部署的 tenant/environment/binding/backend/target，并在同一事务追加审计。读取始终限定 tenant 和 deployment，认证封装后才返回进程内恢复对象。

状态迁移采用状态与 epoch 双条件 CAS，与审计同事务提交。合法边为 prepared→applying→applied→rollback_pending→rolled_back，以及 applying/rollback_pending→unknown；完全无变更的 prepared→applied 仅允许原摘要、revision 一致。unknown 没有自动重试写入边。applied 必须匹配期望摘要，rolled_back 必须匹配原摘要。台账不授予管理权限，也不替代目标级跨进程互斥；这些检查仍由在线接入负责。只有把独立台账接入真实写入前后并验证故障窗口后，才可宣称持久恢复成立。

## B3：密钥供应约束

服务接入使用 `SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE` 指向宿主或 Secret Manager 挂载的独立密钥文件。文件为普通文件、绝对路径、非最终符号链接，属当前服务用户或 root，权限只允许属主读写（0400/0600）。JSON 结构为 `{"active_key_id":"<id>","keys":{"<id>":"<32-byte key in base64>"}}`，只允许这两个字段，拒绝重复 JSON 键、超出 8 KiB、非法 base64、非法 key ID、错误长度与缺失活动密钥。读取过程中元数据变化同样拒绝。不得在代码或示例中携带实际密钥。

加载失败不生成新密钥，不回退到签名密钥或内存缓存。轮换通过原子替换文件，保留所有尚需解密的旧 key ID；每个操作使用一次加载的一致快照。此接口仅为密钥供应组件，在线入口接入完成前不会改变现有部署行为。文件属主检查不是对同 UID 恶意进程的隔离保证。

## B4：目标互斥

锁键由固定域、网关指纹和目标名计算，与 tenant 无关，避免相同外部目标被不同绑定并发写入。PostgreSQL 使用独立连接的 session advisory lock；有界等待失败后返回 busy，不写外部后端。退出时显式解锁；连接/解锁异常时使连接失效，不能把仍持锁的会话放回池。此锁只协调同数据库且遵守本协议的 SIQ 写者，不能阻止外部管理员或其他控制面。

显式开发 SQLite 仅支持磁盘数据库和 POSIX 文件锁。锁文件位于数据库旁、服务用户拥有的 0700 私有目录，文件 0600、拒绝符号链接/多硬链接，释放后保留文件以免 inode 切换导致两个锁域。内存 SQLite 不提供伪跨进程互斥。所有写入前后身份和 revision/digest 检查仍须保留，锁不是后端原子 CAS。
