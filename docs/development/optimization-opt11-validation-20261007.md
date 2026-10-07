# OPT-11 连接器可信启动组件验证（2026-10-07）

状态：**implementing**。本批完成 Edge 执行入口加固和 Linux 原生组件验证，正式签名包安装、升级和真实设备迁移尚未验收。机器可读记录及源码摘要见 [connector-execution.json](evidence/optimization-20261007/connector-execution.json)。

## 实现范围

依据 [ADR-057](../adr/0057-enterprise-connector-execution.md) 和 [启动 profile v1](../../packages/contracts/enterprise-connector-execution.v1.md)，受管 scan、安装能力探测和 Skill 采集采用同一可信启动器。服务任务先复核本地确认计划、设备环境/origin、本机架构及固定发行公钥验签的暂存包，再使用计划内程序摘要；不接受任务指定可执行文件，不回退 PATH。既有消息和签名字节格式不变。

Linux 使用 `openat`/`O_NOFOLLOW` 逐级打开目录和程序，检查目录所有权、写权限以及 ELF 的所有权、0500、单链接和大小。摘要校验和读取前后元数据复核通过后，继续持有该文件，经子进程 fd 3 启动。路径被换成另一个文件不会改变本次执行目标；同 UID 原 inode 改写、root/内核控制不属于该防线保证。

受管环境固定 PATH，保留 HOME 与三项协议变量，不继承父进程其他环境。无换行 stdout 分片累计，超过操作预算即杀停；任意 stderr 与协议错误正文不再透传给上游。开发 `run-once` 仍可使用明确绝对路径，但不属于企业制品认证。

## 验证与结果

环境为本机 Linux arm64、Go 1.26.5。真实子进程由仓库内合成 Go 协议程序构建，每个测试使用独立私有目录；不读取真实设备状态，不调用模型或控制面生产服务。

| 验证 | 结果与边界 |
| --- | --- |
| 程序环境与真实执行 | 原生 ELF 正常响应；固定 PATH、无合成设备密钥或动态加载环境；诊断正文不外泄 |
| 不可信程序 | 缺少/错误摘要、可写程序/父目录、文件/父目录符号链接、硬链接、FIFO、脚本、错误名称、相对路径均拒绝 |
| 校验后路径替换 | 已持有描述符继续运行原程序；下一次校验拒绝替换文件 |
| 合成摘要升级 | 程序字节改变后旧摘要拒绝，新摘要可运行；不等于正式签名发行升级 |
| 开发配置 | PATH 同名程序不被发现；明确程序/目录可解析；错误目录不回退 |
| 资源与生命周期 | 无换行超限及时拒绝并关闭，后续调用 closed；精确行上限及下一条 NDJSON 边界正常；既有操作期限测试通过 |
| 旧设备迁移 | 合法签名任务但无确认计划时 unsupported，提示 setup-enterprise；内存设备身份未改，失败回执进入独立执行台账 |
| 既有验签来源 | 完整 Edge 回归包含安装计划、发行签名及服务能力验证；未增加测试公钥或跳过验签的生产配置 |

执行一次批次全量：`go test -json ./...`，4 个包通过，包含子测试共 **689 passed、2 skipped、0 failed**。条件跳过为 `TestInstallPlanWireParity`、`TestSkillAncestryNativeExport`；本批未运行它们所需的外部导出条件，不把跳过计作通过。

`go vet ./...` 通过；定向竞态命令通过：

```bash
go test -race . -run 'TestVerified|TestNoPATHFallback|TestConnectorLineLimit|TestInstalledCapabilitiesSubprocess|TestSignedLegacy|TestPerOpDeadline' -count=1
```

`CGO_ENABLED=0 go build -trimpath` 的 Linux arm64/amd64、macOS arm64、Windows amd64 四目标通过。后两者仅构建验证；受管启动返回不支持，未宣称原生平台执行通过。

初次定向测试中，当前环境的测试临时叶目录为 0775，被目录权限检查拒绝。已把合成测试安装目录显式设为 0700，并保留生产拒绝条件；随后定向及批次回归通过。未降低安全断言。

## 部署与剩余验收

详见 [Edge README](../../edge/agent/README.md)。旧注册身份和心跳保留，受管扫描须经原安装流程复验签名包并确认计划；不可删除设备身份/执行台账或自动改权限绕过。修复配置后由控制面签发新任务，原失败任务不强制重放。

完成 OPT-11 还需真实可信发行候选的安装/合法升级、既有设备迁移，并按可用平台记录原生行为。缺少正式签名包时不以手工摘要子进程测试代替安装验收。本批不证明进程沙箱、网络限制、客户环境长期可用性或 Windows/macOS 受管支持。

批次日志和构建位于忽略目录 `var/optimization-20261007/opt11-*`，仅提交脱敏摘要、源码与测试。没有修改历史冻结测评或用户原始采集。
