# Windows Hermes wrapper 测试适配：r1 固定候选结果

本轮候选 `59d757ae0b104f6d419a7220e64c520727d3c9a7` 只修改一个测试文件，带 DCO 本地提交；基线为 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`。原失败聚焦测试已通过，但全 adapterinstall 包仍有另一处 Windows wrapper 存在性假设失败。**本轮完整保留该失败，不将全包或 Hermes 原生安装登记为通过。**

| 阶段 | 实际退出 | 顶层测试 | 子例 | 时间（UTC） |
| --- | --- | --- | --- | --- |
| 原三项加安装入口边界，共四项聚焦测试 | 0 | 4 pass / 0 fail / 0 skip | 4 pass / 0 fail / 0 skip | 05:10:39.669522–05:11:48.916482 |
| `internal/adapterinstall` 全包 | 1 | 58 pass / 1 fail / 12 skip | 42 pass / 0 fail / 5 skip | 05:11:50.451591–05:15:18.254292 |
| `go vet -p=2 ./internal/adapterinstall` | 0 | 不适用 | 不适用 | 05:15:19.760174–05:16:12.753079 |

日期均为 2026-09-14。表格时间包含各阶段编译/工具开销，不是测试用例自身 elapsed。聚焦阶段 36 个 JSON 事件，全包 494 个事件；没有外层或 Go 包超时。不同层级和重叠阶段不累计为一个总通过数。

## 修复范围与残余失败

变更仅为 `apps/agentshield/internal/adapterinstall/install_entry_test.go`：Windows 检查预览明确没有受控安装命令、wrapper 未创建、配置诊断保持 needs_verification/unverified，登记/兼容性/运行验证均 unknown。非 Windows 原有 wrapper 内容、0700、先 admit 后原生安装的断言保留；`config.yaml` 不变断言仍覆盖两侧。没有新增 Skip，没有改变生产实现或协议。

全包唯一失败是 `TestUninstallOfOneInstanceRestoresOnlyThatInstance`，实际报错为 `backup_restore_test.go:138: sibling wrapper removed by other instance's uninstall`，该用例 elapsed 4.44 秒。失败前的兄弟配置内容、原有平台模式检查和插件保留断言已通过；最后却无条件要求 wrapper 存在。Windows 生产安装逻辑本来不生成 wrapper，源码与该原始错误一致支持“另一处测试的平台存在性假设错误”，不证明卸载删除了本来存在的 Windows wrapper。

后续针对该断言的修复和新候选必须单独记录，不能覆盖本轮源身份、日志、失败或统计。更早固定 PR45 源码 `9cc1863…` 的 2 pass / 1 fail 原证据同样保持独立。

## 测试与环境边界

执行目录为固定检出的 `apps/agentshield`，完整 argv、源状态、Go 身份和摘要见 [summary.json](summary.json)；逐事件证据为 [focused.jsonl](focused.jsonl) 和 [package.jsonl](package.jsonl)。[change.patch](change.patch) 的 SHA256 为 `3031ab3f69156902474c29e19c9b15c16933859fb55c212738a24ecff9eaa419`。

Go 1.27.1 Windows/amd64，CGO=0，工具链 exe SHA256 锁定为 `d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490`。测试子进程使用环境白名单；HOME/USERPROFILE、APPDATA、TMP/TEMP、GOTMPDIR 和 GOPATH 指向本轮新合成目录。私有根 DACL 前后核对为 protected、current-user/SYSTEM/Administrators 三类 FullControl ACE，无宽泛 ACE。只复用此前自有的 N03 编译缓存，旧日志与摘要没有更改。Go proxy/sumdb/自动工具链下载及遥测关闭；这是工具配置与测试范围控制，不是操作系统网络隔离认证。元数据 Git 和 ACL PowerShell 子进程仍使用控制器环境，只执行只读元数据操作。

testOpts、Install、Inspect 路径经源码审阅：这里的 loopback endpoint 只作为配置字符串，不发 HTTP 请求，不联系日常服务；原生宿主 opt-in 变量没有传入。全包保留原有的 12 个顶层 skip：3 个符号链接相关、5 个原生宿主 opt-in、2 个 POSIX wrapper、2 个进程死亡恢复；另有 5 个符号链接子例 skip。部分顶层在先执行普通断言后才遇到 skip，也不能把整个顶层登记为 pass。没有创建系统用户、提权或为跳过项放宽产品。

Windows 组件测试不证明 Hermes 公共 CLI、桌面、实际工具调用、跨用户 ACL 隔离或完整用户旅程。原始私有 Go 输出另存；公开 JSONL 对 Output 私有路径替换并重新序列化，原始与派生 bytes/hash 分开记录。原始日志均可严格 UTF-8 解码。没有归档临时密钥或 token。

## 核验与尚未执行的门禁

测试各阶段前后及最终复核均为同一干净候选。模块 `gofmt -l .` exit 0 且输出空，`git diff --check` 通过。最终重新核对预期聚焦集合、包终态、JSON 事件数与摘要，不能只依据 runner exit 判总验收，详见 [verification.json](verification.json)。同机独立代理只读复核了 runner、单文件 diff 及聚焦派生证据，没有发现必须修正项；没有独立重新运行测试。

所有 Go 直接子进程均已 wait 回收。2026-09-14T05:18:03.5812614Z 的只读 Win32_Process 快照中，最后记录的 Go PID 不在，私有 fixture 路径匹配的进程为 0，详见 [process-observation.json](process-observation.json)。这是时间点观察，不是历史所有后代逐个成功清理的证明。

本轮未执行全模块 `go vet ./...`、`go test ./...` 或四目标生产构建，没有生成新 SIQ 产品二进制。改动仅影响测试；这些仓库门禁仍需对最终候选实际运行或取得对应 CI 结果后记录。当前 `ci.yml` 的 Ubuntu Go 1.22 job 配置了全模块 gofmt/vet/test 和 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 构建；配置存在不等于本候选已通过。

现有 personal-experience macOS job 只测试 Python 证据工具，skills-compat macOS job 测试分发脚本，均不执行本次 Go 测试。Ubuntu Go 测试可提供其 POSIX 分支执行证据；Darwin 交叉构建不能替代 macOS 实跑，当前 macOS 仍未测。本轮不重跑无生产变更关联的真实宿主或状态生命周期。
