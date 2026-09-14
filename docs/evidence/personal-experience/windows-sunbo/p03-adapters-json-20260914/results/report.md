# Windows adapters JSON fixture 修复对照

同机固定基线完整包为 **4 pass / 1 fail**；固定修复候选的两项聚焦测试与完整 5 项包测试均通过，格式和模块 vet 也通过。无跳过、包超时或外层超时。各阶段单独统计，聚焦与全包不能累加成独立用例总数。

| 阶段 | 固定源码 | 命令（工作目录 `apps/agentshield`） | 结果 |
| --- | --- | --- | --- |
| baseline | `b303c6f92392f3a44c306d81ad7323c6291ef4f2` | `go test -json -count=1 -timeout=120s ./internal/adapters` | exit 1；25 events；5 顶层：4 pass / 1 fail |
| focused | `94e0d162215cb4238f0759cb96cae4a99f437b48` | `go test -json -count=1 -timeout=120s -run '^(TestPolicyExecBlocksQuarantineWarnsConditionsAllowsClean\|TestPolicyExecFailsClosed)$' ./internal/adapters` | exit 0；12 events；2 顶层 pass |
| package | 同候选 | `go test -json -count=1 -timeout=120s ./internal/adapters` | exit 0；24 events；5 顶层 pass |
| gofmt | 同候选 | `gofmt -l .` | exit 0；空输出 |
| vet | 同候选 | `go vet -p=2 ./...` | exit 0；空输出 |

三次测试均无 Go 子测试终态；循环中的 fixture 行没有作为额外子测试计数。每阶段有独立 [summary](package-summary.json)、JSONL 和输出文件，记录 UTC 起止、实际 exit、源码前后状态、工具身份及原始/派生哈希。原始日志私留，公开 JSONL 是明确标记的脱敏派生。

基线实际失败为 `TestPolicyExecBlocksQuarantineWarnsConditionsAllowsClean`：`malicious/env-webhook` 返回缺少 admission ID/verdict 的响应。源码显示动态 `stagedPath` 被直接拼入 JSON；Windows 反斜杠可导致入口解析失败，在进入 admission 前返回 block。旧 `file not dir` 只检查 block，存在被同一个解析错误满足断言的风险；这部分属于源码推断，基线日志没有单独记录该循环项的 reason。

候选仅修改 `apps/agentshield/internal/adapters/adapters_test.go`，31 行新增、9 行删除，见 [change.patch](change.patch)：两处动态请求改用 `json.Marshal`，保留原生路径和原请求字段；负向表分别核对 malformed/no-path/not-readable-directory 的既有 reason 短语，并在 file-not-directory 输入前确认 fixture 是存在的普通文件。保留三类决策 block/warn/allow、非空 admission/verdict、四类拒绝以及 plugin warn 断言，不新增 Skip，不改生产实现或共享合同。

候选聚焦通过意味着上述两项顶层测试的完整循环及断言均完成；完整包还覆盖未改的 CodeBuddy 映射、服务不可达/畸形输入/未知动作拒绝及 PostToolUse 观察逻辑。它们使用 fake decider、受控文本 fixture 和临时状态，不代表真实宿主安装、真实模型调用或原生 Hook 验收。

测试环境为 Windows 11 专业工作站版 25H2、build 26200.8875、amd64、NTFS；官方 Go `go1.27.1 windows/amd64`，CGO=0、工具链 local、telemetry off，Go EXE SHA-256 为 `d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490`。控制器使用既有 Python 3.13.7；包内未调用 Python 测试辅助工具。

在仓库外既有自有验证父目录下新建唯一私有根，各阶段使用独立新子目录及合成 HOME/USERPROFILE/APPDATA/TMP 等。根 DACL 前后受保护，仅当前用户、SYSTEM、Administrators 三个 FullControl ACE，无宽泛 ACE；只更改新根 ACL，没有更改父目录或日常配置。复用先前自有私有 Go build cache，旧原始证据未改。Go 子进程采用环境白名单，PATH 仅 Go bin 和 Windows System32，禁 Go 下载，不传宿主 opt-in 或凭据；只读 Git/ACL 控制器查询仍继承控制器环境。受测包无需网络或真实宿主，这不是 OS 网络隔离声明。

五阶段执行前后均为各自固定 clean 源码；修复前原件未因新候选更新而改写。最终独立重算验证原始与公开事件的非 Output 字段一致，expected 测试集合、包终态、分层计数与实际 exit 一致。路径脱敏从开始即兼容 Output 内嵌 JSON 的多重反斜杠。公开个人路径、用户名、SID 和常见凭据模式扫描未命中；模式检查不构成对所有秘密形式的保证。

五个直接进程均由 runner wait 回收，没有触发 taskkill。2026-09-14 06:25:41.7922847Z 的 [CIM 快照](process-observation.json) 显示记录的直接 PID 均不在场，匹配本轮私有根的可见 executable/commandline 数为 0。该时点观察不能证明每个历史后代都曾逐个回收；私有 fixture 与原始日志保留供复核。

本轮未重跑 Windows 全模块测试，也未生成新的发行 SIQ 二进制。此前 PR #48 在 `2f84d5a` 的 Windows 全模块 exit 1 属于另一固定源码的独立证据，原失败/超时保留，不移作本候选结果。全模块测试与四目标构建以独立 CI 证据为准，未计入本包；Darwin 交叉构建不等于 macOS 实机执行。

[verification.json](verification.json) 记录执行后的独立核对；[manifest.json](manifest.json) 列出除自身外全部公开文件的 bytes/SHA。全部证据为同机组件验证，不是独立 OS 复现或三宿主完整验收。
