# Windows P03：状态 ACL、继承与只读边界

**已复现 WIN-ACL-001：Windows 状态初始化和已存在签名 seed 的加载没有拒绝宽泛读取 DACL。建议按 P1 交共享状态负责人主修。** 本报告是同一实现候选上的原生最小复现，没有修改产品代码、测试门禁、系统用户或用户目录权限；不关闭 A10/P03 总体验收。

| 身份 | 记录 |
| --- | --- |
| 日期 / 最终观察 | 2026-09-14；02:24:50.061892 UTC |
| 实现候选 | `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0` |
| 当前工作树 HEAD | `973541733ccdb25d4578e56033901e4829ff257c`，执行前后相同，`source_dirty=false` |
| Windows amd64 二进制 SHA256 | `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74` |
| 受审代码与候选的关系 | `signing/signing.go`、`state/state.go`、`statefs/fs.go`、CLI `initialize.go` 在实现候选与当前 HEAD 之间无差异 |
| 宿主 | Windows 11 专业工作站版 25H2，build 26200.8875，amd64，NTFS；PowerShell 7.6.5 |
| 方法 | 候选原生 `init` / `pubkey`；NTFS DACL 读回；`GetEffectiveRightsFromAclW` 的 Everyone trustee 计算；公开 marker 的 ReadOnly 属性实验 |
| 执行脚本 | [acl-native-probe.ps1](acl-native-probe.ps1)，SHA256 `76819188e139066d84736d1ffb92bf16db80e5a840088da52e0c3c3cba7624a2` |
| 原始脱敏结果 | [acl-native-diagnostics.json](acl-native-diagnostics.json)，SHA256 `67d262d228f67c8c14b8ca713257a4a0c1b8fa8174b9ab81cdfabcdfc609c199` |

## 实际结果

本批共执行 6 次原生 CLI，无超时。**5 次退出 0、1 次退出 1 不是安全通过分数**：其中两次退出 0 正是下面的宽 DACL 缺口。初始化不生成 signing seed 或 bearer token；宽权限下的随机私钥首次生成没有执行。

| 场景 | 实际命令/结果 | ACL 与副作用证据 | 结论 |
| --- | --- | --- | --- |
| 受控私有父根正常初始化 | `init` 退出 0，`initialized` | 新状态、`keys`、`backups` 仅继承 current_user、SYSTEM、Administrators 的 FullControl | 本 fixture 的创建结果符合已设置的私有继承；不是产品主动设置私有 DACL 的证明 |
| 上述私有根首次生成私钥 | `pubkey` 退出 0，输出可解码为 32 字节公钥 | 生成的 seed 是普通文件，保留相同三类继承 ACE；Everyone 有效 mask 为 `0x00000000`。没有读取或归档 seed 内容 | 随机秘密仅在事先核验过的私有 ACL 分支生成；未进行其他登录身份访问测试 |
| 合成父目录额外允许 Everyone 继承 ReadAndExecute | `init` 退出 0，`initialized` | 新状态、`keys`、`backups`、`config.json` 与 `state-format.json` 均保留 Everyone 继承。API 计算成功，mask 为 `0x001200a9`，包含 FILE_READ_DATA、不包含 FILE_WRITE_DATA；init 后 seed/token 都不存在 | **未拒绝宽泛读取的状态父目录，也未收紧新状态与敏感子目录的 DACL** |
| 宽继承状态中预置公开固定 seed | `pubkey` 退出 0，公钥可解码为 32 字节 | seed 明确为公开的确定性测试输入；其 DACL 同样对 Everyone 授予 FILE_READ_DATA。命令前后文件字节与 DACL 摘要不变 | **加载签名身份没有拒绝已存在 seed 的宽 DACL**；未启动服务、未签发业务材料，不等于已证明其他账号读取真实私钥 |
| 当前操作者在空合成状态目录被明确 Deny CreateFiles/CreateDirectories | `init` 退出 1，AccessDenied | 执行后仍为空目录，DACL 摘要不变 | 内核权限拒绝有效，产品没有通过提权、改 ACL 或回退位置继续初始化 |
| 仅设置目录 ReadOnly 属性 | 子目录上的 `init` 退出 0 | 父目录的 ReadOnly 属性仍在，DACL 摘要不变 | Windows 目录 ReadOnly 属性不是创建子对象的访问控制边界，不能据此认定产品绕过了真实只读 DACL |

另对私有目录中的公开 marker 做文件 ReadOnly 实验：设置属性后追加被拒，HRESULT 为 `0x80070005`；清除该属性后追加成功；全程 DACL 摘要相同。此实验直接调用 .NET 文件属性 API，**没有把它冒充实际 Go `Chmod` 调用**。本机 Go 1.27.1 的 `syscall_windows.go:759–773` 源码单独确认 `Chmod` 按写位设置或清除 `FILE_ATTRIBUTE_READONLY`，不修改 DACL。

在宽继承 `backups` 目录中只创建了公开 marker；它也继承 Everyone ReadAndExecute。此证据说明该目录的默认继承行为，**没有实际迁移备份、密钥备份或 ACL 保存认证**。

## 源码定位与影响边界

以下路径相对 `apps/agentshield/`：

- `internal/state/state.go:102–114` 的 `Open` 使用 `MkdirAll(...,0700)` 创建状态与子目录；兼容性检查没有代替 Windows 权限检查。
- `internal/statefs/fs.go:16–20,40–44` 在格式屏障之后直接调用 `os.OpenFile` / `os.MkdirAll`，未建立 NTFS DACL。
- `internal/signing/signing.go:62–67` 创建 `keys` 后直接读取既有 seed；`decodeSeedFile` 校验编码和长度，没有 Windows DACL 检查。原生 `pubkey` 在 `cmd/agentshield/main.go:860–869` 经过这条实际加载路径。
- `internal/signing/signing.go:69–94` 在首次生成时用 `O_EXCL` 与 `0600` 写 seed；`internal/state/state.go:183–215` 对 bearer token 也采用 `0600` 文件创建。Go 1.27.1 的 Windows `syscall.Open` 将 mode 写位映射到 ReadOnly 属性，未将 `0600` 转成只允许当前用户的 DACL。

因此，**新随机 seed/token 在宽继承父目录下继承读取权限是有源码与原生继承观察支持的风险推断，本批未直接执行该秘密生成场景**。本批已直接证明的是宽目录初始化被接受、宽 DACL 的公开 seed 被加载，以及安全父目录下生成的 seed 依赖父权限继承。没有测试用户真实默认状态目录是否宽泛，也没有证据证明用户日常密钥已泄漏。

建议共享状态负责人先定义 Windows 私钥/token、状态根及备份的有效权限合同：安全创建时原子指定受限 DACL；既有状态读写前验证实际所有者、可继承规则与有效访问主体；拒绝不可信读取/写入权限并提供明确、可审阅的修复路径。不能只对用户任意目录递归执行 `icacls`，不能忽略未知 ACE，也不能把 `chmod` 成功作为 Windows 隔离认证。应保持实例目录身份、不可变发布、未知对象保留和未来状态拒写不变量。

下一候选由 Windows 负责人复验：安全继承、宽允许、显式拒绝、继承变更、创建失败无秘密残留、既有 seed/token 加载拒绝、真实备份 ACL 保持；实际另一普通登录身份访问需要后续受控验证。本批不创建用户、不提权、不模拟其他用户已登录，也不扩大该复现为跨用户攻击成功声明。

## 隔离、保留现场与证据限制

全部修改限于新建 ACL fixture 根与其子目录。外层私有根保持继承保护开启和三条明确 FullControl ACE，前后 DACL 摘要相同。脚本不修改父目录 ACL；随机生成的唯一 signing seed 始终位于已核验私有分支。宽 ACL 分支只有普通初始化元数据、公开固定测试 seed 和公开 marker。没有给真实随机密钥或 bearer token 添加 Everyone 权限。

外层目录私有不是“子文件宽权限仍安全”的依据。Windows 的目录遍历检查与文件本身访问检查分开，具备遍历特权的访问者可以越过某些父目录检查；因此本批没有依靠隐蔽路径来保护宽 ACL 下的秘密。[Microsoft 文件安全与访问权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)。

`GetEffectiveRightsFromAclW` 只计算指定 DACL 对 trustee 的权限，不完整模拟实际登录 token、权限特权或 session group，也不等于第二用户实际打开文件。本批使用其成功返回的 Everyone FILE_READ_DATA 作为静态权限事实，未将 API 成功当作跨用户登录实测。[Microsoft API 定义与限制](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-geteffectiverightsfromaclw)。两份官方资料核对于 2026-09-14。

六个 CLI 子进程均已等待退出；没有启动服务、模型、浏览器或计划任务。所有状态与失败现场留存，未删除 Writer 锁或未知文件；显式创建拒绝 fixture 保留其 DACL，便于核对。原始命令输出可能含私有路径/合成实例 ID，仅本机私有日志保留。归档 JSON 将个人 SID 映射为 current_user，仅记录角色、规则、权限 mask、摘要与命令退出码。

本批未完成第二用户访问、迁移备份 ACL/继承保存、安装计划目录 ACL、硬链接/reparse 逃逸、Windows 默认 profile 安全性以及整体生命周期验收。对应项目继续保持未测或待修。
