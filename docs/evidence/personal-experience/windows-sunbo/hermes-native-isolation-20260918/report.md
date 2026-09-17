# Hermes 原生双 profile 配置隔离及漂移拒绝

受测测试源码 e05a37d297182dd0834abc77f8034cfd8d4b5bae；产品代码仍为 de5de5f 的 Windows 启动预算修复。真实安装 Hermes CLI 入口 SHA256 与启动修复批一致，见 verification.json。通过产品 adapterinstall 库与该实际 CLI 的配置命令执行，不使用模拟 Hermes；testOpts 的 SIQ Binary 是未执行的占位文件，本批没有测试 runtime hook、SIQ CLI 安装入口或实际工具保护链。

两个独占 profile（含中文及空格路径）真实启用 SIQ 插件。每次预览前后目标树相同，安装后有 NativeOriginal 归属备份。对第一个 profile 预览卸载后追加用户字段，旧计划返回 ErrPlanChanged；两个 profile 的目录及全部文件摘要均不变。重新预览并卸载第一个后，第二个 profile 的整个树仍逐字节不变。

实际 Hermes 配置读取确认第一个实例恢复原 SIQ disabled/enabled/override 登记；用户新增字段、自定义设置及另一个 enabled 插件保留，产品插件目录移除。最后卸载第二个，比较所有 nativeUnowned 配置和 NativeRegistration 与原始完整解析对象相同，允许宿主规范化 YAML 格式。未操作实例树摘要比较始终严格保持。

r1 最后错误要求第二个 YAML 恢复后的字节完全相同，exit1；此要求不符合既定“宿主会规范化配置格式”规格。保留原始失败，只把末尾改为完整配置语义比较后，新根 r2 通过，测试234.29秒/控制器239.59秒，exit0，无跳过。fmt/vet通过，测试临时目录空，配置查询子进程已退出，模型调用0。

本批覆盖 P02-HM-A03-03（配置漂移拒绝）、04（保留其他配置）、06（还原卸载归属）。不覆盖权限预览完整性、实际加载自检、宿主重启后工具链或审批/允许写入。当前固定台账71/303通过、4失败、8受阻、220未测，另3系统中断项排除；最终候选仍未确定。

复现：在普通Windows用户的专用私有TEMP/TMP，SIQ_HERMES_NATIVE_CLI指向已验证的安装CLI，执行 go test -json -count=1 -timeout=10m -run ^TestHermesNativeCLIProfileIsolationAndDrift$ ./internal/adapterinstall。测试文件保留所有配置与副作用断言；真实配置命令按产品30秒单命令上限执行，输出只记录固定结论，不记录账号或密钥。
