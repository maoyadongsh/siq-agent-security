# Windows N03 更新检查组件复验

固定 PR #45 源码 `9cc18630be584692905e1ce612b91a9ba5aee610`，在 Windows 11 amd64、Go 1.27.1、CGO=0 下运行三个定向测试。复验结果为 **3 个顶层测试通过，其中 10 个子例通过；0 fail、0 skip，包退出码 0**。这些是 Windows 本机执行的组件测试，不是三个真实宿主的安装更新验收。

两次运行前后源码均为相同 SHA 且 clean。PR #45 已于 `2026-09-14T03:19:44Z` 合并为 `4464dfbc8e66c8ec1fb2590b286351595fcd9667`；本批仍明确测试其固定源提交 9cc，没有把它重新标注为 merge commit 或旧 Windows SIQ 二进制身份。

## 两次运行分别保留

| 运行 | 时间（UTC）与结果 | 解释 |
| --- | --- | --- |
| 首轮全新缓存 | 04:01:13.886680–04:04:15.008664；外层 180 秒超时；Go 退出码 1 | 原始 JSONL 为 0 字节，0 个测试事件；三项测试均未执行。作为冷缓存准备阶段超时保留，不计测试语义失败。 |
| 复用自有私有缓存复验 | 04:06:52.662261–04:08:36.161510；退出码 0 | 新建独立私有运行根，复用首轮自己的 GOCACHE；完整运行 103.499249 秒，包报告 66.533 秒。`-count=1` 强制重新执行测试。 |

两次包测试上限均为 90 秒；第二次外层上限为 300 秒，未触发超时。首轮不存在测试事件，无法从该空日志定位具体编译子阶段或将退出码 1 归因于某个断言。原始超时日志与汇总没有因第二次通过而改写。

首轮 `taskkill /T /F` 返回 255：输出含两条成功、一条失败，失败报告“操作不被支持”；其更底层原因未知，不能称所有后代逐个终止成功。Go 主进程已回收，随后按首轮私有根查询可见进程为 0。复验后 `04:08:41.6526743Z` 的 CIM 快照中，记录的自有 Go PID 及递归后代为 0。快照发生在运行结束后，没有取得活跃编译阶段的定时观测，也不宣称持续跟踪了全部进程。

## 实际断言与边界

| 测试 | 结果 | 本批证明的范围 |
| --- | --- | --- |
| `TestLateUpdateOutcomeCannotOverwriteUserReconfiguration` | pass，26.44 秒；4 个子例通过 | 手动/自动检查期间禁用或重新保存更新配置；通过合成上游回调构造确定性交错。迟到结果被拒绝，用户保存的配置字节不被覆盖。 |
| `TestScheduledCheckNewVersionDoesNotConfirm` | pass，6.18 秒 | 合成上游显示新版本时，结果仍要求确认；新增状态路径限于更新源目录，Grant revision 不变。 |
| `TestSaveUpdateSourcePreservesIncompatibleRecords` | pass，32.88 秒；6 个子例通过 | future schema、未知字段、坏签名、非法状态、错误安装 ID、畸形 JSON 均拒读；再次启用或禁用都拒写，原记录字节和状态目录路径集合保持不变。 |

10 个子例属于上表两个顶层测试，不能将两层计数相加当作 13 个互相独立的顶层测试。完整子例名称、耗时见 [summary.json](summary.json)，原始逐事件副本见 [tests.jsonl](tests.jsonl)。

公共 fixture 经 `t.TempDir()` 创建合成状态、Skill 源和安装目标，使用固定合成签名种子及测试审批对象；上游读取替换为内存快照，不启动 Hermes、OpenClaw、WorkBuddy、Git 或模型服务。两个新运行根均在写入前核验为 protected DACL，只有当前用户、SYSTEM、Administrators 三条 FullControl ACE，未调整父目录或日常用户目录 ACL。

这些结果补充 P04/N03/A08 的 Windows 组件正负向证据。确定性交错测试不是 Go `-race` 或真实并发压力测试；兼容测试只锁定指定记录字节和路径集合，不证明整树内容摘要、ACL 或其他登录身份不可访问。没有测试真实 HTTPS/Git 下载、真实宿主加载与重启、更新安装确认 UI、后台常驻调度、服务失联恢复，也没有完成 A10 旧状态迁移或 A12 升级恢复。Issue #39/#42/#43、已有 adapterinstall 的 Windows wrapper 缺席，以及三宿主平台矩阵均不因此提升。

## 工具身份与复现

- Go：`go version go1.27.1 windows/amd64`；`GOHOSTOS=GOOS=windows`、`GOHOSTARCH=GOARCH=amd64`、`CGO_ENABLED=0`。
- `go.exe` SHA256：`d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490`。工具链 build 信息见 [go-toolchain-build.txt](go-toolchain-build.txt)，仅替换首行程序绝对路径；原始与展示摘要在汇总中分别记录。
- 环境在 runner 子进程内指定：`GOENV=off`、`GOWORK=off`、`GOFLAGS` 为空、`GOPROXY=off`、`GOSUMDB=off`、`GOTOOLCHAIN=local`、`GOCACHEPROG` 为空。`TMP/TEMP/GOTMPDIR/GOCACHE/GOPATH/APPDATA/LOCALAPPDATA` 使用自有私有目录；工具链实读 `GOTELEMETRY=off`。没有修改调用者或全局环境。
- 模块为 `apps/agentshield`，本候选 `go.mod` 无第三方模块依赖。测试参数如下，未运行整个包的其他测试：

```text
go test ./internal/skillinstall -run ^(TestLateUpdateOutcomeCannotOverwriteUserReconfiguration|TestSaveUpdateSourcePreservesIncompatibleRecords|TestScheduledCheckNewVersionDoesNotConfirm)$ -count=1 -p=1 -parallel=1 -timeout=90s -json
```

复现时先准备干净的上述固定源码检出、同版 Go 和一个全新空 NTFS 私有目录，设置其 DACL 为仅当前用户、SYSTEM、Administrators 的 protected 三条可继承 FullControl。脚本会验证 ACL 后才创建数据，不替操作者修改目录 ACL。以下 PowerShell 变量由复现者在本机指定：检出目录 `$SiqCheckout`、Go 可执行文件 `$SiqGo`、全新私有根 `$SiqNewPrivateRoot`、前一次自有 Go 缓存 `$SiqPriorPrivateCache`。这些变量仅用于指定复现者本机位置。

```powershell
# 首次使用全新缓存，保留准备超时的可能性：
python .\run-n03-cold.py --checkout $SiqCheckout --go $SiqGo --private-root $SiqNewPrivateRoot

# 使用另一个全新私有根，复用前一次自有缓存：
python .\run-n03.py --checkout $SiqCheckout --go $SiqGo --private-root $SiqNewPrivateRoot --cache-root $SiqPriorPrivateCache --outer-timeout 300
```

两份脚本各自的 SHA256 已记录在相应运行汇总。脚本只写指定私有目录，原始输出不可直接上传；公开前仍需检查个人路径与日志内容。缓存可以继续使用，首轮原始日志、汇总和脚本保留原字节。

## 证据完整性

- [summary.json](summary.json)、[tests.jsonl](tests.jsonl)：成功复验 56 个事件，原始与公开 JSONL 字节相同，14,331 字节，SHA256 `75ae97a26e1a359ecc5a3f5587e0fcf13e9c112036b2b1e35298e53c22503f86`。成功输出没有个人路径、SID、凭据或任务原文。
- [cold-cache-summary.json](cold-cache-summary.json)、[cold-cache-tests.jsonl](cold-cache-tests.jsonl)：首轮独立原样结果；空 JSONL SHA256 为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
- [cold-cleanup-observation.json](cold-cleanup-observation.json)、[process-observation.json](process-observation.json)：清理限制与只读进程快照；不公开 PID、SID 或私有绝对路径。
- 原始任务清理输出及 Go 路径留在私有根；本批没有读取或导出日常宿主配置、私钥或聊天内容。清单 [manifest.json](manifest.json) 记录公开文件长度和摘要。

本目录是提交前的公开派生材料，不表示已经创建新的 PR、合并或发布。
