# Enterprise Edge credential rotation v1

ENT-021：轮换 Edge 控制面 Bearer 凭据，不轮换设备签名私钥、不改变业务权限。

## 请求

`POST /edge/v1/credential-rotation`，必须经可信 TLS 控制面传输。使用现有 X-Edge-Identity 和当前 Bearer 凭据认证，不能使用管理端身份代替设备持有证明。

严格 JSON：schema_version=`edge-credential-rotation/v1`；device_identity（ASCII 标识，1–128）；environment_id（ASCII 标识，1–64）；rotation_id（小写 UUID）；expected_secret_hash、new_secret_hash（各 64 位小写 SHA256）；signature（128 位小写 Ed25519 十六进制）。不接收 tenant、秘密明文或新公钥。

设备签名覆盖去除 signature 后全部字段，ASCII key 排序、紧凑 JSON、ensure_ascii=true，无尾换行。与注册恢复不同 schema，不能跨协议重放。设备和环境必须匹配已认证记录；租户从该环境派生。

客户端须用安全随机源生成满足现有 Edge 凭据格式的新 secret，在发送前私密、可恢复地保存旧/新凭据及同一签名请求。服务端只收到新 hash，无法证明其原像熵；可信客户端承担强随机生成要求。禁止依赖聊天、浏览器存储或模型生成凭据。

## 原子转换与恢复

设备行加锁后重验认证所见 hash 与吊销状态；expected_secret_hash 与当前记录一致才可 CAS 更新。当前及轮换历史出现过的 hash 不能作为新 hash；防止旧凭据被重新启用。轮换历史、凭据更新、审计、outbox 同事务，审计失败关闭；历史不包含明文或签名原文，不通过管理查询暴露 verifier hashes。

响应 schema_version=`edge-credential-rotation-result/v1`，edge_agent_id、environment_id、rotation_id、status=`rotated`、runtime_permissions_changed=false；Cache-Control:no-store，不返回秘密/hash/公钥。首次及精确重试响应一致。

响应丢失后旧凭据可能已拒绝；客户端只能用预先保存的新凭据和完全相同的已签名请求核对。服务端仅在 rotation_id、请求摘要及当前 hash 均符合已提交历史时返回成功，不再执行转换、不重复审计。若仍持旧凭据且原请求未提交，可对同一请求显式重试。不得生成新 secret/新请求来“恢复”未知结果。

认证/签名/设备环境不匹配或吊销返回 401；旧基线、重复 key 不同载荷、复用历史 hash、已被后续轮换取代返回 409；事务异常通用 503，先核对，不推断必然回滚。未知/多余字段返回 422。

## 边界与迁移

轮换不复活已吊销设备；后续认证拒绝旧凭据，不中断已认证在途请求。历史迁移 0026 新增 edge_credential_rotation，设备+rotation_id 唯一，设备+new_hash 唯一；降级存在历史时拒绝删除，防止丢失恢复与防重放依据。

已有任何轮换历史的设备不再允许首次注册恢复入口修改凭据，即使尚在注册恢复时间窗且未发心跳；防止该入口绕过轮换基线与历史复用限制。该检查在原设备行锁内执行。

服务端协议与原生进度以下方记录为准。真实 TLS/生命周期和 PostgreSQL 并发验证仍待交付，不冒充安装包已具备完整轮换。

## 原生协议层进度

Linux 命令约定：`rotate-credential --confirm-device DEVICE_ID [--resume]`。必须显式确认当前设备并取得与 serve 共用的排他锁；不自动停止服务。新轮换先保存日志再单次发送；恢复先用日志中的新凭据核对原请求，仅收到 401 且本地仍为原凭据时，允许对完全相同的请求进行一次旧凭据尝试。任何其他不确定结果保留日志，不自动生成新请求。核对成功后重读状态与日志以拒绝漂移，原子保存新凭据并同步目录，最后清理该次日志。成功不代表业务权限发生变化。未知版本状态字段拒绝轮换，不默默丢弃。非 Linux 命令失败关闭。

轮换专用状态、待恢复日志和日志内请求按精确 JSON 字段名解析：拒绝大小写别名、重复字段、未知字段和 null 值；日志及其请求要求字段齐全，状态保留既有可省略字段。此限制同时作用于日志准备与恢复，不依赖 Go 结构体解码的大小写宽松匹配，也不改变其他命令的兼容行为。损坏文件保留，不自动改写。

激活清理顺序：保存 state → 同步目录 → 严格读回确认新凭据及状态绑定 → 复核日志 → 删除该日志 → 再同步目录。保存或首次同步/读回失败不清理日志；删除失败保留日志。仅最后同步失败时，返回独立的 `credential_rotation_activated; cleanup_durability_unconfirmed` 提示：当前凭据已经确认激活，日志删除是否持久仍待核对，不应重新注册或丢弃当前状态。软件故障注入验证该顺序，不替代真实断电/磁盘故障测试。

Linux 私密待恢复日志现已提供内部准备/读取函数：`credential-rotation-pending.json` 独占创建为 0600，写入后同步文件和目录；准备阶段保留原 state.json，不激活新凭据。日志绑定除 secret 外的状态摘要、新 secret 和完全相同的签名请求；读取复用状态文件的祖先路径、所有者、权限、链接与重复 JSON 键检查，额外限制日志 8192 字节并验证签名。允许当前 state 使用原或该次新凭据，拒绝其他状态漂移。Linux CLI 已在锁内接入日志、网络核对、激活与清理；隔离测试不代表真实设备生命周期已交付。

Edge 已增加内存准备函数：crypto/rand 生成独立 32 字节新 secret 和 16 字节 UUID，验证本地签名 seed 与公钥一致后按合同签名；函数不写状态、不发请求。单次 HTTP 方法要求请求身份与 Client 一致，现有凭据 hash 对应原或新凭据，禁重定向/自动重试；响应限 4096 字节、精确字段、拒绝重复键/未知键/缺失键/尾随 JSON 与作用域不符，不自动激活新凭据，不输出服务器错误正文。

独立固定向量由 `scripts/enterprise-experience/generate-credential-rotation-vector.py` 生成，产物 `fixtures/credential_rotation_vector_v1.json` 使用公开测试 seed，Go/Python 两侧核对 canonical 与签名。不能用作真实部署密钥。Linux 命令仅有开发验证证据，对真实设备调用仍须部署版本匹配及实际操作授权。

原生隔离集成测试 `apps/control-api/app/tests/test_credential_rotation_native.py` 构建实际 Go CLI，使用临时合成设备状态，经仅监听回环的测试桥接调用真实 FastAPI 路由与隔离 SQLite。覆盖正常轮换和真实事务提交后丢弃响应再恢复；核对旧凭据 401、新凭据心跳成功、同一请求恢复不重复审计/outbox、状态其他字段不变及输出不含凭据。此证据不覆盖生产 TLS、真实 IAM、PostgreSQL 行锁并发、物理掉电或安装服务升级。
