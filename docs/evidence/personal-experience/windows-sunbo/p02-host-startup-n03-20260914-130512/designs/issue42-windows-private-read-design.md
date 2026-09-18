# Issue #42：Windows 私密文件读取拒绝检查方案（待协调、未实现）

日期：2026-09-14。关联：[Issue #42 / WIN-ACL-001](https://github.com/maoyadongsh/siq-agent-security/issues/42)。

建议先实施显式的 Windows 私密文件读取检查，拒绝权限不符合约定的既有 signing seed 和全局 token；再单独补齐新秘密的原子安全创建、备份和适配器凭据读取。第一批只能修复指定读取入口，不能据此关闭整个 Issue #42 或宣称 Windows 状态已完成跨用户隔离。

本文是只读源码审阅及既有证据基础上的设计，没有实现修复、运行新状态命令、调整 ACL 或复验候选。公开材料不包含个人 SID、私有状态路径、凭据或原始命令日志。

## 1. 身份与协作状态

| 项目 | 固定事实 |
| --- | --- |
| 本次源码审阅 | `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`，本地工作树审阅前后干净；这是固定源码身份，不宣称当前远端 main |
| 原生 ACL 复现实现候选 | `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` |
| 原生 ACL 复现证据工作树 | `973541733ccdb25d4578e56033901e4829ff257c`，`source_dirty=false` |
| 原生受测二进制 SHA256 | `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74` |
| 已核对的源码关系 | 本文涉及的 `signing/signing.go`、`state/state.go`、`statefs/fs.go`、`runtimeidentity/files.go` 以及 Hermes/OpenClaw 适配器入口，在原受测候选与本次审阅源码之间无差异 |
| 远端协作快照 | 本轮主任务新鲜核对：#42 为 OPEN，无 assignee、无评论；未见相关 OPEN 修复 PR，相关 OPEN PR #44 为证据 Draft。此行是查询时状态，不代表后续状态不会变化 |
| 主修归属 | 共享状态主修 owner 仍需维护者确认；Windows 负责人可承担约定接口下的 Windows 后端与原生负向测试，本文不代替维护者分配共享文件归属 |

复现来源为[固定证据报告](https://github.com/maoyadongsh/siq-agent-security/blob/3cbbd1dcec7eae5691de465de0ea6fbc459243ae/docs/evidence/personal-experience/windows-sunbo/p03-filesystem-20260914-104819/evidence/acl/report.md)。证据与设计分开保留；本方案不改写原始结果。

## 2. 已实测缺陷与证据限制

既有 Windows 11、NTFS 原生复现直接证明：

- 合成状态父目录额外继承 Everyone ReadAndExecute 时，`init` 返回成功；新状态、`keys`、`backups` 与初始化元数据保留宽 DACL。该命令没有生成 seed 或 token。
- 在宽 DACL 状态中预置公开固定测试 seed 后，`pubkey` 返回成功；文件内容及 DACL 不变。静态权限 API 的 Everyone mask 含 FILE_READ_DATA。这证明既有宽权限 seed 被实际加载。
- 事先设置安全私有继承的另一分支可以初始化并生成 seed。这证明该 fixture 的继承结果安全，不能证明产品主动创建了私密 DACL。
- 当前用户被明确拒绝创建子对象时，初始化失败且空目录不变；Windows ReadOnly 属性不等同于 DACL。

宽 DACL 分支没有随机真实秘密，只有公开固定 seed、公开 marker 和初始化元数据。没有执行另一登录身份读取，没有证明日常密钥曾泄漏，没有实测宽 DACL 下随机 seed/token 首次生成，也没有完成真实备份或迁移验收。外层目录私有不构成宽权限叶文件安全的证明：Windows 目录遍历与文件访问检查不同，具备遍历特权的访问者可能跳过部分父目录检查。[Microsoft 文件安全说明](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)

## 3. 静态新增发现及入口清单

以下路径相对 `apps/agentshield/`，行号针对固定审阅源码。它们是静态定位，不是新运行结果。

| 入口 | 现有行为 | 第一批需要处理的内容 |
| --- | --- | --- |
| `internal/signing/signing.go:50`，`Load` | 先允许环境 seed 分支；磁盘分支创建 `keys` 后直接读取 seed；任何读取错误均继续首次创建尝试 | 磁盘私密读取接入检查；仅明确 `NotExist` 才进入生成/创建；其他错误直接返回 |
| `internal/signing/signing.go:166`，`LoadExisting` | 检查文件形态、大小后打开并有界读取；不会首次创建 | 同一打开句柄检查 DACL，检查通过才读取、解码或构造私钥 |
| `internal/state/state.go:183`，`Token` | 读错后生成随机内容并尝试 `O_EXCL`；遇到 `EEXIST` 递归调用 `Token()` | 先修非 `NotExist` 错误传播；并发创建重读也必须使用相同私密检查，避免无限递归 |
| `cmd/agentshield/main.go:434`，CodeBuddy 客户端 | 独立直接读取全局 token，不通过 `Token()` 生成 | 同步接入私密读取；保留既有客户端和服务端授权语义 |
| `internal/runtimeidentity/files.go:34,74` | 私有目录及 JSON 权限检查明确跳过 Windows；已有祖先、文件形态、有界读取与严格 JSON 检查 | 列入共享权限合同后续覆盖范围，不能将当前 Unix mode 判断冒充 DACL 检查 |
| `internal/runtimeidentity/store.go:155` | `CredentialPath` 只返回路径，不读取明文 token；另有凭据发布流程 | 需单独覆盖创建和发布，不把路径函数计为已保护的读取入口 |

**新增静态风险：`Token()` 当前的读错误处理必须与拒读检查一起修改。** 若已有 token 的 DACL 被新检查拒绝，而原代码仍吞掉该错误，则创建会遇到 EEXIST 并递归进入同一分支，可能无限重试至栈耗尽。现有代码对其他持续读取失败也有相同控制流风险。本轮未执行该场景；不能将它写成已实测崩溃。`signing.Load` 没有同样的递归，但也应停止把任意读错误当作首次创建条件。

此外，`adapters/runtime/hermes-agentshield/__init__.py:125` 与 `adapters/runtime/openclaw-agentshield/index.ts:128` 各自直接读取并缓存凭据。Go 读取接口的修复不会自动保护这些入口或清除已缓存 token。适配器凭据读取与缓存期限应由共享 owner 和适配器负责人另行协调，不能复制授权引擎或宣称 Go 修复已覆盖所有宿主。

## 4. 拟议最小接口与权限合同

本节是待维护者确认的设计选择，尚未成为既有规格或实现承诺。建议先回写本地规格中 Windows 对 0700/0600 的实际含义；如不改变 API/持久化合同，不因内部 Win32 校验自行新增协议版本。

### 4.1 接口与读取顺序

新增显式的私密读取能力，例如私密读取 helper 加 `_windows.go` 权限后端；可用已经打开的 `*os.File` 作为后端输入。具体包名由共享 owner 决定。接口必须保持：

1. 先经过现有状态格式兼容屏障；保留未来/损坏状态、迁移例外及拒写的原有分类和顺序。
2. 打开目标并检查普通文件、大小及文件身份；在**将秘密内容读入内存之前**，对同一文件句柄查询并验证安全描述符。
3. 检查通过后才有界读取、解码和使用；每次新打开重新检查，不缓存 ACL 通过结论；所有分支关闭句柄并释放 Win32 分配。
4. 返回稳定的“不安全私密权限”或“无法验证权限”错误，避免将其降级为文件缺失。错误不包含原始安全描述符、个人 SID 或秘密内容。

不要给通用 `statefs.Open/ReadFile` 全部强制私密 ACL：该层也服务于普通扫描输入，批量改变它会误拒绝公共 Skill/源文件，并扩大共享行为变化。也不应依赖文件名猜测是否敏感。

### 4.2 一个可审阅的保守接受集合

建议的第一版合同是：文件 owner 为当前进程用户；只接受当前用户、SYSTEM、Builtin Administrators 的授权 ACE，并接受这些可信主体的安全继承。按 SID 比较，不能按本地化账户名称匹配。这些主体及 owner 限制必须由共享 owner 明确批准，不能在实现中悄然扩大或缩小。

- 不要求恰好三条 ACE，也不要求 `SE_DACL_PROTECTED=true`。已有“安全父目录继承”的正例应能通过；实际 DACL 必须包含本次可见的显式与继承规则。
- 缺失/null DACL 拒绝。empty DACL 授权语义不同，不得当成 null；无法以所需权限打开或读取描述符仍应明确失败。[Microsoft null/empty DACL 说明](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)
- 第一版宜采用小而明确的 ACE 接受集合。未知、条件、callback、无法可靠解析的 ACE 及无效 SID/ACL 拒绝，不依靠忽略未知项来通过。
- 对不可信主体的 allow 采用保守拒绝，不自行计算“宽 allow 被 deny 抵消”后放行。此选择会拒绝部分实际有效权限可能安全的复杂企业 ACL，必须作为兼容限制明示。
- 根目录、`keys`、secret/backup 目录及其可继承规则需要自己的对象类型合同；不能把叶文件规则机械套到全部系统祖先目录，也不能只检查状态根而漏过宽权限叶文件。

该设计验证的是本次打开时对象的私密权限是否落在产品接受集合，不是对每个潜在登录 token 进行完整授权推导，更不是同用户/管理员攻击沙箱。

### 4.3 可复用设施与禁止的捷径

当前仓库没有生产级 Go DACL 读取/校验器。可复用 stdlib `syscall` 的进程 token/SID 能力，用 Windows build tag 封装少量 Win32 API；保持项目 stdlib 约束和 Go 最低版本兼容。现有通用文件包装和格式屏障继续复用，避免另建文件安全引擎。

`GetSecurityInfo` 可以查询已打开的文件句柄，获取 owner/DACL 需要 `READ_CONTROL`；返回的描述符必须按 API 约定释放。要严格校验描述符、ACL、ACE 长度与类型及 SID 边界，避免未经验证的指针遍历。该 API 不保证安全描述符并发变化时的原子性，不能仅凭 handle 查询声称消除了所有竞争。[Microsoft GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)

既有 PowerShell/C# fixture 中的 `GetEffectiveRightsFromAclW` 可复用为观察手段，但不能直接成为“所有其他用户都无法读取”的产品证明；该 API 不完整考虑 owner 隐式权限、特权及登录 session group 等因素，也不能只检查 Everyone 就接受其他主体授权。[Microsoft API 限制](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-geteffectiverightsfromaclw)

安全读取路径不应启动 PowerShell/icacls，不修改用户目录权限，不自动修复 ACL，不用 Go Chmod 成功替代 NTFS 权限认证。本文 Microsoft 资料核对日期为 2026-09-14。

## 5. 兼容风险与第一批不能承诺的内容

- 安全但复杂的企业组 ACL、条件 ACE 或管理员所有的旧状态可能被保守合同拒绝。应给明确诊断与可审阅迁移设计，不能自动收紧或迁移日常目录。
- 环境 seed 分支是内存输入，不受磁盘 ACL 检查；保持当前语义，证据必须明确分支，不能用环境输入成功替代文件验收。
- 权限检查是每次打开时的快照。并发改 ACL、已有打开句柄、同用户或管理员修改与适配器已缓存凭据仍有限制；不得承诺持续监控或绝对无竞争。
- 第一批只做既有文件读取拒绝，无法保证新 seed/token 在宽继承父目录下的原子私密创建。生成前检查父目录虽有帮助，也不能替代创建时指定受限 DACL。
- 初始化本身、runtime identity secret 发布、备份权限/继承保存、安装计划目录、适配器读取以及另一真实普通登录身份访问仍需后续覆盖。Issue #42 全量关闭条件由维护者与共享 owner 明确。

## 6. 修复后的真实正负例计划（全部未运行）

| 场景 | 要求的结果与证据 |
| --- | --- |
| 安全显式 ACL、安全继承 ACL | 既有公开合成 seed/token 在对应读取入口通过；记录 handle 安全描述符观察及内容/DACL 不变。继承规则不能被误当作不安全 |
| Everyone、Users、Authenticated Users 或其他用户 SID 获得读取 allow | 加载明确拒绝；外层私有目录不能豁免宽权限叶文件。宽分支只放公开确定性测试材料 |
| null DACL、owner 不符合合同、未知 ACE、描述符不可读 | 有限时间内拒绝，不生成替代 seed/token；empty DACL 与 null DACL 分开记录，避免伪造不可构造的 fixture |
| 既存 token 持续读取失败 | 证明有界返回、无递归重试/栈耗尽、无随机创建尝试；与真正 NotExist 的正常首次创建分支区分 |
| 两次打开间将 ACL 放宽 | 第二次拒绝，证明没有缓存通过结论；不把此顺序用例扩大成并发竞争证明 |
| 文件替换/reparse、大小或内容非法 | 保留原文件身份、有界读取与严格解码约束；不因增加 ACL 校验放宽既有拒绝 |
| 未来或损坏状态、环境 seed 输入 | 保留既有兼容分类、拒写行为及分支语义；不将非文件分支登记为 DACL 通过 |
| 拒绝前后副作用 | 清单、摘要、DACL、业务权限与 Grant revision 不变；日志不存在公开合成秘密 canary，不归档真实秘密 |

只有已实测的 Windows 原生结果才能登记通过。不会为本方案创建系统用户或提权；实际第二登录身份访问需后续受控验证。安全创建与真实备份另需负向测试，不能用上述既有读取测试代替。

发生实现改动后，按仓库要求运行相关正负向与本机 Go 检查（gofmt、vet、test、三 OS 交叉编译），并验证当前支持的 Go 版本。本文没有执行这些未来检查，也不提供虚构通过数。

## 7. 协作拆分与可承担工作

维护者首先确认一个共享状态主修 owner，负责私密主体/ACE 合同、错误语义、规格以及 `signing.Load/LoadExisting`、`state.Token`、CodeBuddy 直接读取等共享调用点；先统一接口，再并行修改，避免多处复制权限判定。

Windows 负责人可以独立承担约定接口下的 `_windows.go` 实现、Win32 结构边界测试及原生正负向证据。完整补丁仍需共享调用点和创建分支同步，不能只新增 Windows 文件就声称完成。适配器、备份与新秘密创建按同一 owner 协调后续批次。

当前完成状态：设计与 Issue 评论草稿已准备；修复未实现，新候选未生成，本计划用例未复验，远端未发布。
