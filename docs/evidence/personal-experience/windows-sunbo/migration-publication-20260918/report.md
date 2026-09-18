# Windows 迁移发布中断恢复与真实备份 ACL

源码 `b321a5d807e05c6b2d002a856a357711b9202203`，集成上游 `bb364015f745316497f0d654ee9746b5287035c0` 及 PR80/81/82 已有修复。Windows 二进制 SHA256：`4706efe37bb939eb1e51a34a88a22e9d37b56ccc4ae22c16e4c40baa7974401e`；内嵌源码身份一致，工作树干净。没有修改 main、合并远端 PR、使用模型额度或中断系统会话。

## 问题和修复

迁移原先先创建目标硬链接，再清理暂存名。Windows 私密读取要求单链接；真实子进程在两步之间退出后，普通与只读输出都会留下两个链接，恢复返回 `state-migrate: unsafe output`。发布前中断仍可恢复。旧代码失败证据见 `before-fix.json`，生产实现未为复现改变，仅加入内部测试故障点。

Windows 改为对本次暂存文件获取不共享的 READ + DELETE 句柄，复核创建身份、普通单链接和 DACL，通过同句柄 FileRenameInfo 不覆盖地原子移动。保留只读属性和私密 ACL；不清除只读位、不覆盖目标、不退回复制或硬链接。非 Windows 保留原发布方式。规格与模块平台 API 例外随实现更新。

新测试真实终止自己创建的测试子进程，验证 0600/0400 文件在发布前、发布后均可恢复；前者保留未知暂存，后者不残留目标别名。另验证来源被替换、已有只读目标、多硬链接、宽 ACL 和来源被占用时拒绝，原对象内容、属性及 ACL 不被修复或覆盖。

## 验证

- 干净源码迁移及 Windows Writer 回归退出 0：14 顶层、58 子测试通过。测试 helper 顶层仅由子进程运行，正常枚举跳过；一个 symlink-backup 子测试因本机无符号链接权限跳过，未记为通过。
- gofmt 输出为空、go vet、Windows amd64/Linux amd64/Linux arm64/Darwin arm64 构建及 Python Schema 校验均退出 0。逐个产物源码与哈希见 `clean-verification.json`。
- 真实历史未标记源码 `ff99317450784c9563f5b6a2308c98e8262df98d` 的原始二进制创建业务状态，完成准入、pending_approval 授权及撤销；新版执行状态诊断、迁移、重复迁移、诊断和已撤销再撤销拒绝，共 10 次 CLI 调用。9 次退出 0，最后一次按预期退出 1，全部进程自然结束。
- 历史文件及完整备份逐字节比较，摘要、模式、计划清单、实例/目录绑定、完成 checkpoint 均核对；重复迁移及诊断的状态快照不变。旧版本没有在迁移开始后再次运行。没有手写版本标记伪装历史版本。
- 独立 PowerShell/.NET 查询新建迁移 journal、plan、checkpoint 和备份共 43 个对象（其中 39 个备份对象）：owner 为当前用户、DACL 受保护，allow 主体仅当前用户、SYSTEM、Administrators。查询脚本只读，不用 Chmod 或测试根 ACL 冒充产品结果。

`native-journey.json`、`native-acl-verification.json` 和 `independent-acl-descriptors.json` 是脱敏结果；原始业务输出及私密合成状态保留本机。测试根继承此前私密测试父目录，这是历史 CLI 的测试条件；新建迁移对象自身的 protected DACL 是独立检查的产品结果。

## 复现与限制

先构建上述两个真实源码候选，核对固定摘要。`run-unmarked-journey.py` 接收 `--private-root`、`--old-binary`、`--old-sha256`、`--new-binary`、`--new-sha256`；根必须是新建空私密目录，两个二进制位于其父目录下独立 build 目录。脚本拒绝重解析点、多链接、身份变化和已有测试根内容；不能在日常状态运行。`read-migration-acl.ps1` 只查询本批隔离目录，复现时须选择该脚本限定的专用根名。不要删除旧根来重复执行；另建批次并保留身份记录。

本批证明无标记历史迁移及新发布流程，不证明受保护 v1 历史版本、旧候选已残留的未知硬链接自动修复、真实第二登录身份或所有计划目录。未知旧别名继续拒绝并保留，不按文件名前缀删除。迁移 plan ACL 不能代替安装/更新等其他 plan 的验证。

旧 ACL 源码 `82a7da5` 完整 Go 回归已退出 1：1210 顶层通过、67 跳过、50 失败，server/skillinstall 超时，结果在同级 `private-acl-20260918/full-go-verification.json`。这些不是本批源码的结果，也不宣称全量回归通过。当前集成候选仍需完整回归及其余 Windows 修复；最终验收候选尚未固定，Issue #42 保持未完成。
