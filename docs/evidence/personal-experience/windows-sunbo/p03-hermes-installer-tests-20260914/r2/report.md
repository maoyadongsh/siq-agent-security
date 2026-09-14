# Windows Hermes wrapper 测试适配：r2 固定候选结果

候选 `2f84d5af6934f3cc17354107f66beae6dc8e1b59` 在 Windows 原生 Go 环境中通过五项聚焦测试、adapterinstall 全包与聚焦 vet。相对主线基线 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`，只有两个测试文件改变；两个本地提交均带 DCO。没有修改生产实现、协议或宿主配置逻辑。

| 阶段 | 退出码 | 顶层测试 | 子例 | 时间（UTC，2026-09-14） |
| --- | --- | --- | --- | --- |
| 五项聚焦测试 | 0 | 5 pass / 0 fail / 0 skip | 4 pass / 0 fail / 0 skip | 05:24:18.973691–05:24:46.685293 |
| `internal/adapterinstall` 全包 | 0 | 59 pass / 0 fail / 12 skip | 42 pass / 0 fail / 5 skip | 05:24:48.113874–05:28:15.857246 |
| `go vet -p=2 ./internal/adapterinstall` | 0 | 不适用 | 不适用 | 05:28:17.451056–05:28:25.247397 |

时间包含阶段编译/工具开销，不是单个测试 elapsed。聚焦记录为 40 个 JSON 事件，全包为 493 个；没有外层或 Go 包超时。重叠阶段与不同层级不累计为一个总通过数。

## 变更与证据范围

`install_entry_test.go` 在 Windows 上验证预览明确暂无受控安装命令、wrapper 不存在、诊断仍为 needs_verification/unverified，原生登记/兼容性/运行验证均 unknown。非 Windows 的 0700、wrapper 内容与 admit 顺序断言完整保留，`config.yaml` 不变断言仍覆盖两侧。

`backup_restore_test.go` 在 Windows 上分别于安装后、卸载第二实例后以 Lstat/IsNotExist 验证两个实例没有生成不受支持的 wrapper；POSIX 兄弟实例 wrapper 存在断言保留。两类系统的兄弟配置字节、原有模式检查、插件保留及卸载断言均未放宽，没有新增 Skip。

r1 候选 `59d757ae0b104f6d419a7220e64c520727d3c9a7` 的全包真实失败保持独立：其最后一个 sibling wrapper 存在性断言在 Windows 失败，不能改写为通过。更早 PR45 固定源码 `9cc1863…` 的原三项 2 pass / 1 fail 同样不变。r2 的两个测试修复没有增加 Windows 受控安装能力，**本次通过仅是组件行为与诚实诊断符合现有平台边界，不是 Hermes 原生安装、真实调用或宿主完整验收。**

完整 argv 与身份见 [summary.json](summary.json)，逐事件证据见 [focused.jsonl](focused.jsonl)、[package.jsonl](package.jsonl)。[change.patch](change.patch) SHA256 为 `d7fcad2bd7e496998898648fc8b7621c4c3dd9b2e0ea97e20b22a908ec1883cd`。

## 环境、跳过及核验

Windows 11、NTFS，Go 1.27.1 Windows/amd64、CGO=0。Go exe SHA256 为 `d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490`。新私有测试根 DACL 前后均为 protected，current-user/SYSTEM/Administrators 三类 FullControl ACE；HOME/USERPROFILE、APPDATA 与临时目录为新合成路径。只复用自有 N03 编译缓存，r1 日志与 runner 未覆盖。

测试 Go 进程使用环境白名单，关闭 Go 下载与遥测，不传原生宿主 opt-in 或凭据。Install/Inspect 中的 loopback 地址只作为配置字符串；本包测试没有联系日常服务。元数据 Git 和 ACL PowerShell 子进程使用控制器环境进行只读元数据操作。此环境安排不是操作系统网络隔离证明。

全包的 12 个顶层 skip 原因是：3 个符号链接能力不足、5 个原生宿主 opt-in 缺席、2 个 POSIX wrapper、2 个进程死亡恢复限制；另有 5 个符号链接子例 skip。完整理由保留在 package.jsonl。部分顶层先执行其他断言后才跳过，也不能将整个顶层登记为 pass。不提权、不创建系统用户、不为跳过项修改产品门禁。

各阶段与最终复核保持同一干净候选。模块 `gofmt -l .` exit 0 且输出空，diff check 通过。[verification.json](verification.json) 独立核对预期五项集合、源码前后、事件/hash/count、包终态和 timeout；不只使用 runner exit。主任务另行独立核对 r1/r2 六阶段的原始日志、公开 JSONL、集合、终态和源码状态。增量静态审阅也确认 r1 manifest 所列 16 文件、209,961 bytes 未改；这些是同机证据审阅，没有独立重跑。

Go 直接子进程均已 wait 回收；[收尾快照](process-observation.json) 中最后 Go PID 不在、r2 私有根路径匹配进程为 0。这是时间点观察，不是所有历史后代逐个回收的证明。

公开 JSONL 对私有路径脱敏并重新序列化；原始日志私留，原始与派生长度/hash 分开记录。没有归档合成密钥/token。模块级 Windows vet/test 使用另一新根另行记录，不能把本包结果替代全模块门禁；PR #48 的 Ubuntu CI 与四目标生产构建由主任务另行归档，Darwin 交叉构建不等于 macOS 实跑。
