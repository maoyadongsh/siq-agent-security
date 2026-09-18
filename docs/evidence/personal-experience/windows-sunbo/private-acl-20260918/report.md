# Windows 私密状态 ACL 与缓存凭据修复

关联 Issue #42。本批源码 `82a7da5b978dbbb7c72a10a97ad77976cf84a35f`，基于迁移修复 PR #81（其基于集成 PR #80）。没有修改 main、合并 PR、操作日常实例或新增模型调用。

Windows 的 `Chmod(0600)` 不能限制 DACL，旧代码还会在凭据文件权限变宽后继续使用缓存身份或密钥。新增标准库 privatefs 边界：在创建目录/文件时直接设置当前用户 owner 和受保护 DACL，只授予当前用户、SYSTEM、Administrators；读已有私密文件时在同一普通非重解析单链接句柄上验证权限再有界读取。无法识别的 ACL、宽可读对象及查询失败拒绝，不自动修改已有对象权限。普通 Skill 扫描输入不被误当私密状态。

接入状态根、Writer 维护目录、签名 seed、decision/recovery token、runtime identity、原文加密存储及迁移读取/备份发布。生产 HTTP 入口在启动和每次请求前重查磁盘凭据；缓存密钥加解密前复验文件，删除或改写不触发替代密钥生成。其他平台维持既有访问语义，Windows 只接受普通本地磁盘路径。

## 独立原生证据

干净 Windows 产物 SHA256：`a32afce00f32c20f534885dc16a55ef62dba7f2220c22b5ee30f312f365e01c7`。

`native-daemon-verification.json` 的 41 个断言全部通过：

- 已有宽 ACL 状态根拒绝初始化，没有创建状态或修复 ACL。
- 在 Everyone 可继承读取的父目录下创建新状态。独立 .NET 安全描述符查询确认根、keys、seed、token、恢复凭据的 owner、受保护 DACL 和允许主体范围。
- 实际 Windows daemon 启动健康；运行中逐一放宽文件/目录 ACL 后，缓存凭据请求返回固定 503。秘密字节和被测 ACL 保持原样；只由测试夹具还原权限后服务恢复。
- 签名停止退出 0，进程和端口关闭。随后逐一放宽 token、恢复凭据、seed，真实 serve 启动退出 1，完整业务文件清单及摘要不变，不轮换秘密或修复 ACL。

脚本 `run-native-daemon.py` 固定上述产物哈希，并排他创建已知测试父目录下的新根；需要将该自建产物放在脚本指定的工作区相对路径。`read-fixture-acl.ps1` 只做独立读取，Python 的 DACL 修改只用于此次合成测试根。不能在日常状态执行，旧测试根存在时应拒绝而非删除重跑。原始日志含合成凭据，仅保留本机，不提交。

早期夹具失败单独记录于 `fixture-attempts.json`：模块路径和 Set-Acl 的额外审计特权请求问题均未通过提权解决。r4 为开发产物，r5/r6 为干净源码产物，身份不混用。

## 负向与回归

将同一组新增测试放在旧 `f04a31a` 生产代码上，3 个运行时身份 ACL 场景和 6 个原文存储 ACL/密钥变化场景均复现错误接受；只增加测试及合成夹具，没有修改旧生产实现。详见 `before-fix-negative-tests.json`。

开发期间 privatefs、rawcontent、signing、服务缓存检查以及选定迁移/提交崩溃恢复测试通过；signing 和迁移的显式跳过仍保留。runtimeidentity 整包保留退出 1：两个符号链接夹具无法在本机普通用户权限下创建，未抑制失败。Windows 权限正负向测试已改为实际 DACL，非 Windows 仍检查原有 POSIX 位。

干净源码 fmt、vet、Windows amd64/Linux amd64/Linux arm64/Darwin arm64 构建及 Schema 校验退出 0，每个产物的内嵌版本和哈希见 `clean-build-verification.json`。完整 Go 回归已退出 1：1210 顶层通过、67 跳过、50 失败；server/skillinstall 超时。详见 full-go-verification.json，不将选定包通过或构建通过当作全量通过。

## 台账范围与剩余工作

本批证据满足 P03-FILE-20 的私钥 ACL/继承与宽读取拒绝要求，该项由 fail 改 pass。固定台账为 **72/303 通过、3 失败、8 受阻、220 未测**，另排除 3 个系统中断项。最终集成候选尚未确定。

Issue #42 尚未整体完成：仍需审计和覆盖剩余适配器读取/缓存、计划及备份入口，验证真实第二登录身份，继续受影响宿主与最终集成回归。特别需要验证迁移在硬链接已发布、暂存链接尚未清理时真实中断的恢复边界；已有 checkpoint 测试不能替代这一窗口。P03-FILE-21/22/23 不随私钥条目自动通过。本批不提供同用户/管理员隔离，也不声称消除了历史泄漏或撤销其他进程已打开的句柄。

迁移双链接中断窗口后续已在 b321a5d 修复并复验，见同级 migration-publication-20260918；不回写为本批 82a7da5 已通过。
