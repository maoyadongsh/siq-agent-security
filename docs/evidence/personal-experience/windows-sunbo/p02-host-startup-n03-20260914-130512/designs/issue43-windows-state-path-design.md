# Issue #43：Windows 状态根路径最小拒绝方案（只读设计）

## 结论

可以按 Windows 专属状态根输入校验修复，不需要改 JSON Schema、状态格式版本、目录摘要算法、签名内容或 Intent/receipt 决策引擎。实现前在规格 §2.1 补明“不支持实际路径组件以 ASCII 空格或点结尾；在路径归一化和文件访问前拒绝；不自动 trim、迁移或重绑实例”。不要把 Windows Task Scheduler 的完整路径规则套到所有状态路径。

本次只读源码基线为干净 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`，没有执行新 state 命令、修改源码或访问远端。已有实机复现仍绑定 runtime candidate `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`、二进制 SHA256 `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74`；它不是新补丁验证。

## 已有事实与源码定位

- 已归档 P03 `evidence/paths/report.md:15–16`：尾点和尾空格输入的 init 都成功，实际为去尾字符的 target；扩展路径复核证实精确请求对象不存在，且普通输入与 target 的原生文件身份相同。未证明目录逃逸或权限绕过。
- 新的只读源码发现：`internal/state/state.go:34–37` 通过 `product.Env` 取状态目录；`internal/product/product.go:44–54` 对主、旧环境变量执行 `strings.TrimSpace`。所以尾空格在进入 state 检查前会被产品通用环境读取器删除；**只修 `checkStateParents` 或 `statefs` 会漏掉尾空格复现**。这条是本次源码解释，不回写旧报告为当时已取得的过程证据。
- `state/compatibility.go:177–198` 的 `checkStateParents` 在 `filepath.Abs` 后 Lstat；没有检查原始组件尾字符。`CheckStateCompatibility:68`、`state.Open:102` 和 `writer.go:52` 的写锁前置链都能复用此入口。
- `cmd/agentshield/serve_state_directory.go:9–27` 是显式 `serve --state-dir` 的独立入口；它绕过 DefaultDir。要在 Clean/Lstat/EvalSymlinks 前检查原始拼写，不能假定 canonical 检查已覆盖 Windows 尾字符。
- `stateformat.RequirePath:273` 扫描的是通用文件路径，包括状态外输入；全局在此拒绝所有文件尾字符会超出 #43 范围。`fileopen.Regular` 也不是状态根专用入口。
- `cmd/agentshield/windows_task.go:19–34` 有尾字符检查，但同时限制本地盘符、260 UTF-16 单元、百分号等。既有 P03 已观察普通长路径与显式扩展路径可正确初始化；复用整个 task validator 会引入不必要的支持回退。

## 建议最小改动点

| 路径 | 拟改动与理由 |
|---|---|
| `internal/state/state.go` + 新 `directory_input_windows.go` / `directory_input_other.go` | DefaultDir 改用状态专用环境读取 helper。Windows 对原始主变量、旧变量先检查再选择，保留非空主变量优先；非法主变量明确拒绝，不能偷偷回退旧变量。非 Windows 分支继续原 `product.Env` 行为。**不改全局 product.Env。** |
| 同一 Windows helper | 只检查原始路径实际组件的尾 ASCII `0x20` 和 `.`；支持两种分隔符，检查中间组件和末组件（包括后接目录分隔符），在任何 Clean/Abs/Join 前运行。返回类别错误、不含用户原路径，不返回“修剪后的替代路径”。默认目录来源 LOCALAPPDATA 也须在 Join 之前检查其原始组件。 |
| `internal/state/compatibility.go:checkStateParents` | 在现有 Abs/Lstat 前调用同一词法 helper，以覆盖直接 Open、兼容诊断与 Writer 路径。非 Windows 为 no-op，现有 N01 格式/屏障/权限复验顺序继续保留。 |
| `cmd/agentshield/serve_state_directory.go` | 对显式原始目录调用导出的同一状态根校验函数，之后仍走既有 canonical、目录及 symlink 检查；不改变环境覆盖和显式参数的优先级。 |

词法实现必须区分 `.` / `..` 导航组件和真实名称，不能因为本修复禁止所有相对路径。不能用 `TrimSpace` 判非法：其 Unicode/前导空白语义比本缺口更宽；不能去掉 `\\?\` 后静默改写路径。对扩展前缀中的**实际名称**尾点/尾空格同样明确拒绝即可，不把已存在的这类特殊目录迁移为普通名称。盘符大小写、正常中文/内部空格、非尾部点、正常长路径/扩展路径应保持原行为。设备名、ADS、UNC、ACL、reparse 与不同卷继续各自既有规则，不顺手扩大此补丁。

若 PR 要声称“所有 state 包直接调用在任何读取前均拒绝”，还需逐个检查 `Store.DirectoryID`、`Store.MigrateState` 等绕过 DefaultDir 的 API：前者先 Abs/EvalSymlinks；后者第一次兼容检查错误后可能继续读取 migration plan。可以在这些**状态根 API**首行复用 helper；否则 PR 应限定为公共 CLI、Open、Writer 入口防护，不能宣称通用文件 I/O 已全面硬化。不要为了覆盖这些直接调用而改整个 statefs 的状态外路径规则。

CLI 应给出不含原路径的明确输入错误，不建议用户删除状态或迁移格式。`state-status` 经 DefaultDir 拒绝非法输入时可使用其既有解析失败返回非零路径；有效目录上的 `compatible=false` 诊断仍可退出 0，不新增 schema status 值。`hook` 继续绕过顶层 exit-1 检查，`main.go:419–426` 的 DefaultDir/Open 失败要继续进入 nil decider + block 的结构化拒绝，不能退化成宿主可能忽略的退出 1。

## 拟复验（本轮未执行）

1. Windows 原生负向：主变量与旧变量分别提供 `target.`、`target `；新增多尾字符、中间 `parent.\\child` / `parent \\child`、尾分隔符及正斜杠变体。先保证字面目标与 trimmed alias 均不存在，init 必须明确拒绝且两者均未创建。
2. 已存在 alias 负向：用新二进制先在独立正常 target 建立合成状态，再用尾字符输入调用 init、state-status、`state-migrate --confirm`。要求拒绝，既有树的字节摘要、命名流、属性/DACL、实例/Grant revision 均不变；不把普通名称的现有实例自动当作用户请求的尾字符实例。
3. 覆盖变量优先级：非法主变量 + 合法旧变量仍拒绝；空主变量 + 合法旧变量按原意选择旧变量；非空合法主变量优先。空白-only 主变量作为 Windows 非空非法路径明确拒绝，不静默选择另一状态。
4. 显式 `serve --state-dir` 的尾字符必须在监听端口、创建/隔离 Writer 或读 token 前拒绝；用 CLI 子进程及端口/目录观察，不注册 Task Scheduler、不启动真实宿主。
5. 直接包级负向：Open、CheckStateCompatibility、AcquireWriter、AcquireScopedWriter 在无目录和已有别名上都拒绝，特别证明旧实现会产生 alias、补丁拒绝且没有新锁/状态。若包含 DirectoryID/MigrateState 的前置 guard，为对应 API 增加同类测试。
6. 正向：正常中文/内部空格、点位于名称中间、盘符大小写、正常长路径与显式扩展前缀、受支持相对路径/导航拼写；真实句柄读回路径正确，重复 init 维持同一实例、有效 state-status 语义不变。只需重放受影响初始化/诊断，不扩大成全生命周期声明。
7. Hook 负向：合成 pre-tool 输入 + 非法状态根，断言既有结构化 block 被输出、不会联系决策端口/创建状态；不能仅断言退出码。有效根原有 hook 组件用例照常通过。
8. 每例使用新私有根和固定 candidate/binary SHA。拒绝前后目录快照只能证明**无持久变化**；要声称“瞬时零写入”还需额外可审计观测或代码级前置调用证明，不把 state-status 自身未加锁当整个 init 过程零写的证据。不要调用会生成密钥的 pubkey 作为只读探针。

单元测试后最低聚焦回归为 `go test ./internal/state ./internal/stateformat ./internal/statefs ./cmd/agentshield`，再按仓库要求 gofmt/vet/Go 全量、四目标构建及受影响合同样例校验；非 Windows 需运行正常与字面尾空格/点仍由原 OS 语义处理的回归，确认 Windows 规则未扩散。没有改 Schema 时不升级合同版本。原 P03 失败材料不可覆盖，应追加新候选的真实复验。

## 归属与已知冲突

共享协作规则 §3 明确 `internal/state*` 是高冲突路径，GLM 负责共享状态核心；Windows 平台负责人可修 OS 独有问题，但公共问题沿同一个编号指定主修人。因此建议 #43 作为一个 Windows 专属校验 PR，由 sunbo 实施时让 GLM/维护者确认这几个 shared call-site 的单一 owner，避免另起三系统分叉。

本地 Issue #43 快照仅含 body/comments/number/state/title，记录 OPEN，但没有 assignees/更新时间；无法据此声称当前无人认领或没有远端并行补丁。已知相邻问题是 #39（Intent/runtime filesystem resource 规范化）和 #42（宽 DACL）；它们不能由本补丁顺带关闭。准备实施前应由主任务核对最新主线、#43 和相关 PR 的 owner/变更路径；本次未发远端消息、未重复创建 Issue。
