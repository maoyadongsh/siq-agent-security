# Hermes 多 Profile 发现与安全边界——原生协议验收交接（CL-03-HERMES-NATIVE）

日期：2026-09-26。任务来源：[收口清单](enterprise-auto-onboarding-closeout-20260926.md) CL-03 的 Hermes 子项，对应 ENT-008 / ENT-009 / ENT-020 的原生证据缺口。

**本交付只关闭「Hermes 原生协议验收」这一个子项。不宣称 CL-03、CL-07、ENT-009 或项目整体完成；不宣称 Hermes Skill 归属关系或运行时防护已经闭环。所有内容未提交、未推送、未部署，待主开发者复核。**

## 0. 结论速览

- 原生验收在 **Linux aarch64（本机）** 实际执行：真实编译当前未提交工作树源码 → 临时二进制 `--serve` → 真实 NDJSON stdin/stdout 交互，共 12 个新测试函数。
- **11 通过，1 失败**。失败项是本次验收发现的真实产品缺陷 **NATIVE-FINDING-01**（超大文件截断未按合同置 `truncated`，前缀摘要被当作完整 content_hash 上报），已在新测试中稳定复现，未改动既有源码、未把失败改成通过。详见 §6。
- 其余验收面（多根身份分离、身份稳定、include 范围、符号链接逃逸、.env 不读正文、不执行、语义边界、环境白名单）在真实进程边界上成立。
- 一键验收脚本如实报告失败并整体退出非零：`overall_passed=false`，`failed_checks=["go-test-race-all","go-test-race-native-focused"]`。

## 1. 实际新增文件（仅新增，未修改任何既有文件）

| 文件 | 说明 |
| --- | --- |
| `connectors/hermes/native_protocol_test.go` | 原生协议验收测试（构建真实二进制、NDJSON 会话、12 个测试函数中的 10 个平台无关项） |
| `connectors/hermes/native_protocol_linux_test.go` | Linux 专用：子进程环境白名单（/proc/<pid>/environ 实证）与 FIFO 拒绝 |
| `scripts/enterprise-experience/hermes-native-contract-check.py` | 一键验收脚本（subprocess 参数数组、拒绝覆盖证据目录、记录摘要、脱敏日志） |
| `docs/development/enterprise-hermes-native-contract-handoff.md` | 本文 |

既有 `hermes.go`、`hermes_test.go`、`consent_scope_test.go`、`profile_identity_test.go` 等为其他开发线的在途成果，本任务未触碰（`git status` 中的 `M`/`??` 状态为任务开始前已有）。

## 2. 既有函数测试 vs 新增原生协议验收

| 维度 | 既有函数测试（hermes_test.go 等 3 文件，13 个顶层测试） | 本任务原生验收（12 个测试） |
| --- | --- | --- |
| 被测对象 | 直接调用 `collectOp`/`validateScopeOp` 等包内函数 | 当前工作树 `go build` 出的真实二进制，`<bin> --serve` 子进程 |
| 协议边界 | 不经过 NDJSON/stdin/stdout | 每请求一行 NDJSON，逐行校验合法协议 JSON、id 对应、无空行 |
| 进程行为 | 无进程 | 启动/连续请求/崩溃恢复/超时杀进程/t.Cleanup 回收，无泄漏 |
| 环境隔离 | 继承测试进程环境 | 子进程最小环境白名单（HOME+SIQ_CONNECTOR_*），Linux 下经 /proc 实证 |
| 预期来源 | 部分用例调用生产 `protocol.ContentHash` 计算预期 | 独立 oracle：按合同 v2 公式用标准库 sha256 计算，不调用生产函数 |
| 覆盖互补 | 解析细节、截断边界等函数级路径 | 合同在真实进程边界上的端到端成立性 |

两者是互补关系，不是重复：函数测试锁实现细节，原生验收锁「编译产物在进程边界上的协议与安全行为」。本任务未删除、未放宽任何既有测试；全量运行时 13 个既有测试 + 11 个新测试通过，1 个新测试按合同失败（§6）。

## 3. 场景 → 合同 → 测试 → 实际结果矩阵

平台：Linux aarch64（`Linux 6.17.0-1014-nvidia`，`go1.26.5 linux/arm64`）。结果均取自证据目录日志，非记忆转述。

| # | 场景（任务书条目） | 合同依据 | 测试函数 | 实际结果 |
| --- | --- | --- | --- | --- |
| A1 | describe 合法能力声明 | connector-protocol.v1.md §2 | TestNativeDescribeSequentialAndProtocolPurity | PASS（version/objects/required_permissions/data_categories/max_output_bytes=8388608/network_access=false 逐项断言） |
| A2 | 请求/响应 ID 对应、stdout 纯 NDJSON、无日志混入 | §1/§2 | 同上 + rpc 帮助函数对每条响应强制校验 | PASS |
| A3 | 同进程连续多请求 | §2 | 同上（describe→health→checkpoint→describe） | PASS |
| A4 | 不支持操作/非法参数按现有合同失败，不崩溃不伪造 | §3 | 同上（unknown op→`unsupported`；畸形 collect 参数→`bad_request`；随后 describe 仍正常） | PASS |
| A5 | 空 scope、根 `/`、.env/secret 根、中段通配、不存在路径拒绝 | §4 | TestNativeValidateScopeRejections（9 例） | PASS |
| B1 | 双根同名 Profile 均发现；候选/locator/证据 ID 分离 | hermes-profile-origin.v2.md | TestNativeMultiRootIdentityStability | PASS（独立 sha256 oracle 逐项相等） |
| B2 | 权限事实引用正确候选与证据 | 同上 + evidence schema | 同上（3 条 declared 事实逐条绑定断言） | PASS |
| B3 | 重叠根/词法等价路径不重复 | v2「重复/词法等价位置去重」 | 同上（乱序+重复+字面量+`/.` 变体 5 根 → 仍 2 候选） | PASS |
| B4 | 重复扫描身份稳定 | v2 | 同上（fingerprint 比对，忽略时间戳） | PASS |
| B5 | 改配置内容：身份稳定、摘要变化 | v2 | 同上（ID 不变，content_hash 与 cursor 变化） | PASS |
| B6 | 复制到新路径→新来源 | v2「移动目录产生新来源」 | 同上（inst-c 产生第三候选，ID 独立） | PASS |
| B7 | 目录名相同≠同一角色 | v2「不用名称判定同一资产」 | 同上（三处 `shared-role` 互不合并） | PASS |
| C1 | 仅 include SOUL.md 时不取 config 事实 | 任务书 include 限制 | TestNativeConsentScopeEnforcement | PASS |
| C2 | 改未包含的 config.yaml 不动事实/游标 | 同上 | 同上 | PASS |
| C3 | 改包含的 SOUL.md 按合同变化 | 同上 | 同上（hash+cursor 变） | PASS |
| C4 | 非 include 文件（notes.txt）不影响任何输出 | 「不扩展用户确认范围」 | 同上 | PASS |
| C5 | 默认位置诱饵 Profile 不被显式 scope 拾取 | v2「不以第一个 root 代替全部边界」精神 + 范围边界 | 同上（fake HOME 下 ~/.hermes/profiles/decoy 未入候选） | PASS |
| C6 | 扩大 include 到 config.yaml 才解锁其事实 | include 语义 | 同上 | PASS |
| D1 | .env 仅文件名/大小元数据 | §4 + v2 | TestNativeSecretsNeverReadAndNoExecution（classification=secret_ref；hash=sha256("env-file:.env:24") 独立复算） | PASS |
| D2 | 同尺寸不同内容 .env 不引起任何内容相关输出/游标变化 | 任务书 D | 同上（24B→24B 全文替换，fingerprint 完全相等）；对照组 7B 尺寸变化→hash 按名+大小变化 | PASS |
| D3 | 响应/stdout/stderr 无秘密正文、无合成标记 | §1/§4 | 同上（.env 正文、SOUL 标记、config 未提取键、sk- 形密钥、临时目录绝对路径均断言不存在） | PASS |
| D4 | 脱敏属性实证 | siq.redaction.v1 | 同上（provider `key=sk-…` → `key=[REDACTED]`） | PASS |
| D5 | 恶意文本不执行 | §4 | 同上（SOUL 反引号/$() 与未 include 的 payload.sh 三处标记文件均不存在） | PASS |
| E1 | Profile 符号链接逃出根（第二根） | §4 + v2 | TestNativeSymlinkEscapesRejected | PASS |
| E2 | config.yaml 符号链接逃出 Profile | §4 | 同上（partial 仅 SOUL 证据，model 为空） | PASS |
| E3 | 逃逸目标内容变化不影响事实/游标 | 边界完整性 | 同上 | PASS |
| E4 | 只有 .env 的 Profile 无孤立证据 | 「每批 evidence 必须被本批 candidate 引用」 | 同上 + checkReferenceIntegrity 全批校验 | PASS |
| E5 | 超大文件不泄露、不无界处理、进程存活 | §4 | TestNativeOversizedFileStaysBounded | PASS |
| E6 | 超大文件必须截断**并告警**（truncated:true） | §3 limit_exceeded + §4 | TestNativeOversizedFileTruncationMustBeFlagged | **FAIL（NATIVE-FINDING-01，稳定复现，见 §6）** |
| E7 | 不可读文件（chmod 0000）不崩溃、不供事实 | 负向语料要求 | TestNativeUnreadableConfigSkipped | PASS（euid=1000，真实权限拒绝；root 环境会显式标注平台受限而非伪装通过） |
| E8 | FIFO 不挂起、被拒绝 | 异常文件 | TestNativeFifoConfigRefusedLinux | PASS |
| F1 | 不产生 effective 权限事实 | 安全不变量 5/8 | TestNativeSemanticBoundaries | PASS |
| F2 | 不猜测 Skill 归属/运行时实例 | 任务书 F | 同上（候选无 skills/loaded/runtime 键，事实域仅 tool） | PASS |
| F3 | 空扫描为合法线形（≠未安装/卸载） | 语义边界 | 同上（0 候选 0 证据带 cursor） | PASS |
| F4 | 候选/证据键集合 ⊂ schema（additionalProperties:false） | candidate/evidence schema | checkBatchShape（每个 collect 调用） | PASS |
| F5 | collector_id/signature 留空、payload_ref 为空 | §5 | 同上 | PASS |
| A6 | 子进程环境最小白名单 | §1 + 任务书 | TestNativeChildEnvWhitelistLinux（/proc 实证，恰为 HOME+SIQ_CONNECTOR_*，无代理/凭据族变量） | PASS |

## 4. 精确命令与退出状态

全部在仓库 `connectors/hermes` 下执行（完整输出见证据目录日志）：

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `gofmt -l native_protocol_test.go native_protocol_linux_test.go` | 0 | 无输出，两文件格式干净 |
| `go vet ./...` | 0 | 通过 |
| `go test -race -count=1 ./...` | **1** | 24 通过 / **1 失败**（仅 NATIVE-FINDING-01）/ 0 跳过；13 个既有测试全部通过 |
| `go test -race -count=1 -run TestNative -v .` | **1** | 新测试 11 通过 / 1 失败 |
| `go build -o <临时目录>/hermes-connector-native-check .` | 0 | 构建成功 |
| `<临时二进制> --serve`（stdin 关闭） | 0 | 正常 EOF 退出 |
| `git -C <repo> diff --check` | 0 | 全仓无空白错误 |
| `ruff check scripts/enterprise-experience/hermes-native-contract-check.py` | 0 | 通过 |
| 未跟踪新增文件尾随空白人工核查（`grep -nP '[ \t]+$'`） | — | 3 个新文件均干净、以换行结尾 |
| `python3 scripts/enterprise-experience/hermes-native-contract-check.py --evidence-dir /tmp/siq-cl03-hermes-native-evidence-20260926` | **1** | 如实报告 `overall_passed=false`（因上述缺陷），证据完整落盘 |

注意：两个 `go test` 退 1 是缺陷复现的诚实结果，不是测试设施问题；失败信息含完整预期/实际对比。

## 5. 平台、源码与二进制身份

- 平台：Linux aarch64（ARM64），内核 6.17.0-1014-nvidia；Go go1.26.5 linux/arm64；Python 3.13.12。
- 源码身份：**未提交脏工作树构建**（git HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0` 仅供参考，不代表被测源码；验收时工作树 567 个变更路径）。真实身份为逐文件 sha256，记录在 `summary.json.source_identity.files`（16 个文件：connectors/hermes 全部 .go+go.mod、edge/agent/protocol 全部 .go+edge/agent/go.mod、本任务脚本自身）。关键值：
  - `connectors/hermes/hermes.go` sha256 前缀 `d8cacd4e825fad52`
  - `connectors/hermes/native_protocol_test.go` sha256 前缀 `a2f39ef2b075b57a`
- 验收二进制：sha256 `1a1e5a689a6a914f0347fb799c6a4281bfb3ef51dbc42eeccd2c077520faae8f`，3806465 字节，由脚本构建进自身临时运行目录（运行结束已清理）。**未使用仓库内既有 `connectors/hermes/hermes` 二进制**（其 sha256 与来源均未采信）。脚本设 `GOPROXY=off` 实证构建/测试无网络下载。
- 手动预探独立构建过同一源码，得到相同 sha256，构建可复现（Go 确定性构建）。

## 6. 已发现缺陷与稳定复现

### NATIVE-FINDING-01（阻断项，待主开发者仲裁）

- **现象**：单个超过字节预算的配置文件被静默截断，批次不置 `truncated`，且上报的 `content_hash` 只是文件**前缀**的 sha256，却被当作完整内容摘要。
- **合同依据**：connector-protocol.v1.md §4「超大文件 / 压缩炸弹 —— 在限额内截断**并告警**」；§3 `limit_exceeded`「部分结果 + `truncated: true`，记审计」。批次级 `truncated` 是 Edge 唯一可用的结构化截断信号。
- **稳定复现**（测试内每次必现）：
  1. Profile 内写 120028 字节 `config.yaml`（有效模型行 + 注释填充）；
  2. `collect` 计划 `limits.max_bytes=1024`；
  3. **预期**：`truncated:true`；**实际**：`truncated` 缺省（false），`content_hash=6835eb5e…`（= 前 1024 字节 sha256），完整文件 sha256 为 `4b93aefcdf726b…`。
- **根因定位**（只读分析，未改动）：`connectors/hermes/hermes.go` `collectOp` 证据循环中，`readFileLimited` 用 `io.LimitReader` 静默截断到 `maxBytes`，随后 `len(data) > remaining` 判断在「单文件恰好等于剩余预算」时为假（1024 > 1024 不成立），于是前缀摘要作为完整 `content_hash` 落批且不置位。同函数对 `config.yaml` 的事实提取路径、`computeCursor`（16MB 固定上限）存在同族静默截断。
- **最小修复建议**（供仲裁，未实施）：让 `readFileLimited` 返回文件实际大小（已 stat）或截断标志；在证据循环中当 `size > len(data)`（或达到预算边界且文件更大）时置 `batch.Truncated = true`，并不把前缀摘要作为完整 `content_hash` 呈现（按合同决策：跳过该证据或保留但必须带截断信号）。修复后本任务的 `TestNativeOversizedFileTruncationMustBeFlagged` 应转绿。
- **影响面**： Edge/控制面会把截断前缀摘要当作完整文件摘要入库，且无任何截断审计信号；属于证据完整性问题，非泄露问题（读取仍有界、无正文外泄，§3 E5 已证）。

除本项外，验收范围内未发现其他合同偏差。

## 7. 证据目录与脱敏日志

- 证据目录（本任务新建，已存在则脚本拒绝覆盖）：`/tmp/siq-cl03-hermes-native-evidence-20260926/`
  - `summary.json`：平台、源码摘要、二进制摘要、各检查 argv/退出码/通过状态；
  - `logs/01..08-*.log`：每条命令的脱敏 stdout/stderr（siq.redaction.v1 同形规则；不含环境变量值与秘密正文）；
  - `git-status-porcelain.txt`：验收时工作树状态快照。
- 脚本只清理自身 `siq-hermes-native-run-*` 临时运行目录与子进程；不触碰他人 /tmp 目录。

### 证据能力边界（如实声明）

- 「.env 正文从未被读取」的证明是**功能性反证**：同尺寸不同字节替换后候选/证据摘要/游标全部不变，且 .env 证据摘要可独立复算为 `sha256("env-file:<名>:<大小>")`——若正文参与任何输出或摘要，替换必然改变结果。这与「输出中未出现秘密正文」共同构成证据；但它不证明进程地址空间内从未出现过该字节（无内存取证），也不证明未来代码路径。
- SOUL.md/config.yaml 属授权 include，正文被读取是合同行为；证明边界是「离开进程的仅有摘要与合同允许的脱敏属性」。
- 路径摘要是 sha256 摘要，**不是匿名化手段，也不是硬件/设备身份**；本任务未验证任何设备身份。
- 空扫描批次只证明「该 scope 无匹配」，不能解释为未安装或已卸载。
- declared 工具集事实是配置声明，不是技能已加载或受控执行的证据。
- 本任务不连接数据库，未验证历史资产保留/迁移行为。

## 8. 未验证范围与后续建议

- **平台**：仅 Linux ARM64 实际运行。Linux AMD64、macOS、Windows 均未验证（交叉编译成功不等于原生验收，本任务未做也未声称）。
- **未覆盖**：Edge 打包签名/新鲜度（§5 属 Edge 职责）；真实 `~/.hermes` 扫描（任务禁止）；多版本协议协商；并发多客户端（合同为单轮串行）。
- **建议**：
  1. 主开发者仲裁 NATIVE-FINDING-01：接受后按 §6 最小修复实施于 `connectors/hermes/hermes.go`（并同步检查 `computeCursor` 同族路径），修复后重跑本脚本应整体转绿；
  2. 修复进入候选基线后，在 Linux AMD64 第二原生平台复跑同一脚本；
  3. 将本脚本纳入 CL-01 整合门禁的 Connector 分组。

## 9. 状态声明

本任务所有产物**未提交、未推送、未部署**，工作树其余在途成果未受影响。验收结论：除 NATIVE-FINDING-01 这一明确阻断项外，Hermes 多 Profile 发现与安全边界在真实进程协议边界上验收通过。待主开发者复核并仲裁缺陷。

## 10. 主开发者复核与修复（2026-09-26）

以上章节保留原交付时的失败记录。本轮先独立运行
`go test -count=1 -run '^TestNativeOversizedFileTruncationMustBeFlagged$' .`，
确认相同的 120028 / 1024 字节失败，再修复实现；未删除或放宽原生测试。

- 修改 `connectors/hermes/hermes.go`：增加携带截断标志的有界读取函数，比较同一已打开文件描述符读取前后的大小与实际读取长度；事实提取和证据采集均传播到批次 `truncated`。证据截断输出固定诊断，不输出正文。原有普通文件检查、限额、脱敏和权限语义保留。
- 按 §3/§4 选择保留部分结果并明确标记，而非无界读取完整文件。`content_hash` 仍可能是已读取前缀的摘要；带截断标记的批次不能作为完整文件内容证明。本修复不新增逐证据完整性字段。
- 新增 `connectors/hermes/truncation_test.go`：0、1023、1024、1025、120028 字节五个边界，确保恰好等于限额不误报，超过限额不静默。
- 聚焦测试通过；一键原生验收脚本退出 0，`overall_passed=true`，包括全量 Hermes `go test -race -count=1 ./...`、原生聚焦测试、`go vet`、构建、脚本 Ruff 与 `git diff --check`。
- 新证据：`/tmp/siq-hermes-native-fix-review-20260926-r1/summary.json` 及同目录脱敏日志。原失败证据未覆盖。

NATIVE-FINDING-01 的批次静默截断缺陷已修复。`computeCursor` 的既有 16 MiB 有界摘要不能证明超限文件尾部未变化；本次未升级游标合同，不将其宣称为完整文件指纹。仍需按原后续清单验证其他原生平台、Edge 截断信号审计及完整链路。

本次仅确认该缺陷修复及 Hermes 隔离原生回归通过，不关闭 CL-03、CL-07、ENT-009 或项目整体。未提交、未推送、未部署。
