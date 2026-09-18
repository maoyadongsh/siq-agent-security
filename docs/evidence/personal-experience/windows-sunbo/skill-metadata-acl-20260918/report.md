# Windows Skill 安装与更新私密元数据

源码 `6a6e47ce17801074ae5d3e3244928b417814cc08`；Windows 干净构建 SHA256 `b2a37de466b86634f36627f9bdd51347a4213ae4f135ca814228b8a761eeed19`。本批补全 Skill 安装/更新内部记录的 Windows ACL 边界，不宣称 Issue #42、FILE-22 或真实宿主验收全部完成。

## 问题与改动

旧代码在 Windows 跳过目录权限验证，安装计划使用普通文件读取；不可变记录通过普通暂存文件和硬链接发布，更新检查配置还可覆盖宽 ACL 的旧文件。仅加入测试、未改生产源码的 `654be43` 复现 4 项顶层失败：9 个子场景及独立的调度文件场景实际接受不安全权限，见 before-fix.json。

现在 Store 打开和内部记录读取复验状态根及私有根，所在目录和同一文件句柄复验 ACL。内部目录/暂存对象显式私密创建，不可变记录用共用的 Windows 不覆盖原子移动，避免成功后留下第二链接。明确授权的调度配置替换检查旧文件和父目录，不自动修复宽权限。未知失败暂存保留。

宿主侧 owner 标记继续使用签名、内容和归属验证；它可能与操作池硬链接，不能套用内部元数据单链接规则。非 Windows 保留原有发布方式。规格和模块 Windows API 限定例外已同步。

## 验证

- 开发树相关回归退出 0：14 顶层、27 子测试通过，无跳过。覆盖新 ACL 正负向、排他发布、安装/更新/移除、未知文件保护、Hermes 归属硬链接、配置重存和不兼容记录保留。明确记为 dirty 开发树验证，未改写为干净构建结果。
- 干净源码 gofmt 输出为空，go vet、Windows amd64/Linux amd64/Linux arm64/Darwin arm64 构建和 Python 合同 Schema 校验退出 0。每个产物的内嵌 SHA、dirty 标记和哈希均读回，见 clean-build-verification.json。
- Windows 原生 SIQ 服务在隔离合成 OpenClaw 配置中执行真实导入、挑战批准、计划、安装、读回和移除。独立 .NET 查询元数据根、plans、计划和操作记录的 owner、protected DACL 和允许主体；宽 ACL 注入后拒绝读取，内容和 ACL 不变，测试恢复权限后可正常读取。合计 35 条断言，实际目标内容一致，移除后目标消失。
- 原生脚本 r1 误用响应 record 字段，在导入后停止；r2 完成安装后误在顶层读取 runtime_verified。两次均收回专用进程并确认端口关闭，未隐藏失败。r2 在同一二进制、同一状态继续读回、验证操作记录拒绝及移除，没有重新安装；最终正常签名 stop、进程退出、端口关闭。完整分段事实见 native-api-verification.json 和 fixture-attempts.json。
- Skill 整包在独立干净源码树运行，见 full-package-status.json；在拿到终态前不宣称整包通过。旧 b321a5d 的完整 Go 回归已退出 1，详见同级 migration-publication-20260918/full-go-verification.json，不属于本批源码结果。

## 重放和边界

从固定源码构建并核对上述哈希，将产物与 clean-build-verification 对应的本机构建记录放在脚本指定位置。run-native-api.py 使用新的专用根 `skill-native-private-replay`，拒绝已有根，并使用同目录只读 read-fixture-acl.ps1；它已修正两个夹具字段问题并合并实测分段，做过语法检查，尚未另行重复执行合并脚本。resume-native-api.py 保留对本机 r2 已安装状态的接续逻辑，不应在已卸载状态再次运行。

测试未启动真实 OpenClaw/Hermes 进程、未调用模型，不能替代真实宿主加载或工具保护证据。更新计划/调度配置目前是组件测试证据，不能冒充原生完整更新旅程。真实第二登录身份、其他计划入口及最终候选回归仍待完成。

目标已移除，原始合成配置字节保持，测试 ACL 已还原。产品操作池的两个文件及私密签名状态按证据/恢复历史保留，未虚报全部删除；见 cleanup-audit.json。未修改日常实例、未提权、未中断系统会话。
