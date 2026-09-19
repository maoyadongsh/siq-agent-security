# Windows 适配器私密恢复材料

生产源码 `17763748f957606bd04f0608cc90ee917a2f2aad`，接续 PR82 的迁移/ACL 修复。Windows 干净产物 SHA256 为 `7199ffb61c80aa1e407106e5030be1cff0cd0d71d5a57755a21884d47853308b`。本批未操作日常宿主、调用模型、提权或中断系统会话。

## 问题与修复

旧生产源码 `3f40a40` 在 7 个新增负向中接受宽可读密钥/恢复文件/操作目录。仅加入测试，没有为复现改变生产代码。`adapter-backup.key` 在 Windows 不检查 DACL，包含配置原文的加密恢复计划也通过普通文件读取；三个操作目录的权限检查显式跳过 Windows。

内部密钥、密封计划及终态文件现使用私密创建、同句柄 DACL 验证后读取，并检查操作目录。既有权限变宽时拒绝，不修复 ACL、不轮换密钥、不改宿主文件。用户宿主配置继续走原有确认、备份和写入路径。

`privatefs.PublishNew` 共用不覆盖的 Windows 同句柄重命名，保留普通单链接、创建身份、DACL 和只读属性；迁移改为复用该原语。statefs 包装先检查源、目标两侧兼容屏障；未来状态下双方快照保持不变。失败私密暂存保留，不按名字删除可能已替换的对象。非 Windows 保留排他硬链接发布及原有权限语义。

## 验证结果

- 新权限测试 4 顶层、7 子测试通过；共用发布与迁移回归 9 顶层、19 子测试通过，单独 helper 跳过保留。
- statefs 整包 4 顶层、2 子测试通过；adapterinstall 整包 88 顶层、61 子测试通过，14 顶层、7 子测试跳过如实记录。这批测试从开发工作树启动，生产与后来提交的 1776374 一致，不改称干净源码测试。
- 后续移除 `TestAdapterRealProcessDeathRecovery` 过时的 Windows 跳过条件，真实原生子进程在 prepared/file:1/audited 三点异常退出，恢复与原配置还原均通过：1 顶层、3 子测试，无跳过。只改测试，生产代码未变。见 `native-process-recovery.json`，不能把先前整包计数重写成已包含这次运行。
- 干净源码 gofmt 空输出、go vet、Windows amd64/Linux amd64/Linux arm64/Darwin arm64 构建及 Python Schema 校验全部通过，逐产物身份见 `clean-build-verification.json`。
- 真实 Windows SIQ CLI 操作隔离合成 OpenClaw profile，共 9 个命令：初始化、预览、接入、5 类宽 ACL 拒绝、卸载。31 个断言通过，原始配置字节恢复，全部夹具 ACL 还原，未启动服务或宿主。
- 独立 PowerShell/.NET 描述符核查新建密钥、计划目录、密封文件和终态文件：owner 当前用户、DACL 受保护、allow 仅当前用户/SYSTEM/Administrators。逐一放宽密钥、密封计划、计划目录、操作目录、Writer 目录后，预览卸载退出 1；宿主及状态文件清单/摘要不变，ACL 未被自动修复。

证据 JSON 不包含密钥、配置原文、账号或真实用户路径。原始输出及合成私密状态保留本机。独立查询脚本只读；DACL 变更只由测试脚本作用于自己新建的隔离根。

## 重放与边界

`run-native-cli.py` 固定源码和 Windows 二进制哈希，配合同目录的 `read-fixture-acl.ps1`。在工作区根运行，先将本批自建产物和来源 JSON 放入脚本指定的 `.tmp/windows-goal-20260916/adapter-private-clean-r1/`，并准备已有私密测试父目录。脚本排他新建测试根，不删除旧根重试，不在日常状态执行。它证明 SIQ 原生配置接入链，不证明 OpenClaw 宿主实际加载、调用工具或执行 allow/deny。

本批补充 P03-FILE-22 的适配器恢复目录部分，不把完整条目改为通过：Skill 安装/更新计划的私密读写、其他剩余私密入口仍需继续覆盖。运行时 Python/TS 适配器的 token 直接读取/缓存、真实第二登录身份、#39 Windows 资源授权、#77 会话绑定及最终候选回归仍未完成。总体台账保持 73/303 通过、3 失败、5 受阻、222 未测，另排除 3 个系统中断项。

上一个集成源码 b321a5d 的全量 Go 仍由独立固定工作树收集；不能把它的结果记到本批源码，也不能用本批定向或原生配置测试宣称完整 Windows 验收通过。
