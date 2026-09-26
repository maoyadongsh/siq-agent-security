# CL-03-OPENCLAW-NATIVE-CLOSEOUT 交付记录：OpenClaw Connector 原生合同验收

日期：2026-09-26。范围：仅“函数单测通过，但原生协议与来源身份尚需核对”的缺口。未提交、未推送、未部署。仅声明 OpenClaw Connector 原生采集子项，不关闭 CL-03/CL-07 整体。

## 1. 实际文件

新增：

- `connectors/openclaw/native_contract_test.go` — 原生 NDJSON 旅程（8 个测试中的 6 个跨平台 + 夹具/预言机）。
- `connectors/openclaw/native_contract_linux_test.go` — Linux 特有 2 项（/proc 环境白名单、FIFO 拒绝）。
- `docs/development/enterprise-openclaw-native-closeout-handoff.md`（本文件）。

修改（白名单内，唯一生产代码改动）：

- `connectors/openclaw/openclaw.go`：`dispatch` 的 `OpValidateScope` 分支一处（+5/-1，见 §4）。既有在途修改（+89/-24）全部保留。

未触碰：Go 模块依赖与锁文件、共享 `edge/agent/protocol`、Hermes/Directory Connector、后端、前端、安装器、发行工具、公共台账、公共合同语义。

**基线保护**：仓库登记的 `connectors/openclaw/openclaw` 二进制在基线核对时被一条探查性 `go build ./...` 意外覆盖；已用 `git show HEAD:connectors/openclaw/openclaw` 恢复原字节，`git status` 确认该文件回到未修改状态。原生测试只构建到独立临时目录，从不使用或触碰登记二进制（`nativeBinary` 的 `-o` 指向 `os.MkdirTemp` 产物）。

## 2. 基线

- 任务起点 `git status`：`connectors/openclaw/openclaw.go` 既有修改（+89/-24）+ 14 个未跟踪文件（既有函数级测试与实现拆分）。这些属当前基线，全部保留。
- 既有函数级测试基线：`GOPROXY=off go test -race -count=1 ./...` → ok（修复前已验证全绿）。
- 既有原生验收：openclaw 无；复用 `connectors/hermes/native_protocol_test.go` 的原生子进程模式（临时构建、最小环境白名单、RPC 超时、清理回收、合同公式独立预言机），未修改 Hermes。
- 环境：go1.26.5 linux/arm64（aarch64），/tmp 无符号链接；构建仅本地 replace + 标准库，GOPROXY=off 离线可用。

## 3. 复现（原生证据先行）

先写原生测试，对当前工作树真实构建运行。首轮 `GOPROXY=off go test -race -count=1 -run TestNative -v ./...`：

- **缺陷复现（真实）**：`TestNativeScopeEscapeAndMissingBoundaries` —— 8 类非法 scope（null、空 roots、`/`、含 `.env`、含 `secret`、中段通配符、exclude、include 不含 openclaw.json）经 `validate_scope` 全部返回 `valid=true` 且携带 errors，响应自相矛盾；合同 §4 要求这些被拒绝，共享类型 `ValidationResult.Valid` 的语义（及 hermes 既有实现 `Valid: len(errs)==0`）要求 valid=false。Edge/调用方按 valid 判定时会把未授权/空范围当作有效。
- **测试侧越界断言（我的测试错误，非被测缺陷，已修正）**：
  - entries 顺序：合同要求“以键为身份并按键排序”，candidate_id 是位置摘要，不承载顺序语义；原断言误按 candidate_id 字典序，改为按合同键序核对预言机顺序（omega→zeta）。
  - “内容变更必须移动 cursor”：openclaw 合同只承诺同位置身份稳定 + 新证据（cursor 公式只覆盖候选身份集，且 j2-05 已核对 checkpoint 与公式一致）；删除该越界断言。内容摘要变化由 evidence 断言覆盖。
  - J6 临时目录名含 "Secret" 被 `ValidateScopeSafety` 正确拒绝（安全行为，非缺陷）；测试改名 `TestNativeHostileTextAndRedaction` 避开路径词。

## 4. 最小修复

`connectors/openclaw/openclaw.go`（dispatch 内一处）：

```go
errs := validateScope(p.Scope)
// valid 必须与 errors 一致（合同 §4：空 scope 等必须表现为拒绝），
// 不能恒真——Edge/调用方按 valid 判定，errors 只是原因说明。
result = protocol.ValidationResult{Valid: len(errs) == 0, Errors: errs}
```

- 修复前复现证据：§3 首轮原生运行 8 个非法 scope 全部 `valid=true`（相当于删除修复的变异体验证）。
- 修复后同一命令全部通过；`plan_scan`/`collect` 路径另行检查 errors，行为不变；既有函数级测试（含 consent_scope）不依赖旧行为，全量回归通过。
- 未放宽断言、未吞错、未扩大扫描范围、未降低安全级别。

## 5. 原生旅程覆盖（8 项，全部真实子进程 NDJSON）

- `TestNativeProtocolAndRoleDiscovery`：describe/health/checkpoint/plan_scan 形状与默认 include/limits；未知 op 与畸形参数失败关闭且进程存活；list 与 entries 两种 roster 布局的身份/证据/framework_source 预言机核对；无 roster → 默认 main（config_default，继承 defaults）；显式 main ↔ 默认 main 同一位置身份；大小写别名/重复键/$include/null roster/双布局/坏 JSON 全部整次拒绝且错误无路径泄漏；显式空 roster → 空清单非错误；`~/.openclaw` 诱饵默认位置零贡献。
- `TestNativeMultiRootSameNameIdentityAndDrift`：两根同名角色身份不混同（预言机 id 互异）；词法等价/重复根去重；同输入重复采集身份与证据稳定；内容变更保持 candidate_id/位置、evidence id 与配置摘要更新；checkpoint cursor 与合同公式逐位一致；每根 auth-profiles 元数据按根摘要隔离引用、只记 `size:N`。
- `TestNativeSkillSelectionAndSourceRoots`：agent/defaults/显式空/畸形/秘密形状/未配置六种 skill_selection 形态；skill_source_roots 只含预言机摘要定位（无原始路径）；非绝对 workspace → unresolved；agentDir 为声明字符串；属性键不超出声明合同集；无技能安装/加载或 effective 事实。
- `TestNativeScopeEscapeAndMissingBoundaries`：validate_scope 全部拒绝形态（修复后 valid=false）；缺失 → `openclaw_config_missing`；符号链接逃逸 fail-closed 且零逃逸内容；多根任一失败整次拒绝不提交部分候选；逃逸目标内容/路径零泄漏。
- `TestNativeBudgetNeverAttestsPrefix`：恰好等于预算的完整文件（含 JSON5 注释与尾部空白）摘要按原始字节核对；预算差一字节 → truncated=true 且零候选/证据/事实；合法 JSON 前缀不冒充完整配置；混合根保留已完成根结果 + truncated（未扫描到与不完整扫描明确区分）。
- `TestNativeHostileTextAndRedaction`：shell 文本仅作数据（marker 文件未创建、进程存活续答）；workspace 中 token 形状 canary 被 [REDACTED]；auth-profiles canary 内容零泄漏；全部事实 state=declared。
- `TestNativeChildEnvWhitelistLinux`（Linux）：/proc 实测子进程环境恰好为 HOME + SIQ_CONNECTOR_* 四变量，无代理/凭据族。
- `TestNativeFifoConfigRefusedLinux`（Linux）：FIFO 配置不阻塞、拒绝为 `openclaw_config_unavailable`、无路径泄漏。

预言机独立性：candidate/evidence/auth/framework_source/skill-root 定位与 cursor 均按 `packages/contracts/enterprise-openclaw-*.md` 公式用 crypto/sha256 + encoding/json 独立计算，未调用 `protocol.ContentHash`、`collectOp` 等被测函数，未从响应反推预期。

## 6. 命令与结果

```
cd connectors/openclaw
GOPROXY=off go test -race -count=1 ./...      # ok 2.889s（既有函数级 + 8 项原生）
GOPROXY=off go test -race -count=1 -run TestNative -v ./...
  # 8/8 PASS（见 §5 清单）
go vet ./...                                   # 通过
gofmt -l .                                     # 无输出
cd ../../.. && git diff --check                # 通过
```

记录用二进制（从当前工作树构建，linux/arm64；测试每次在临时目录重新构建同源代码）：

```
GOPROXY=off go build -o /tmp/cl03-openclaw-native-record .
sha256sum = c2780735dc38f388a665b3e541f8fab1f0e046704bb01a4e9f4abcd1cc4a4acf
```

（记录后已删除该临时文件；仓库登记二进制保持原状。）

## 7. 合成输入与真实环境边界

- 全部输入为测试临时目录内的合成 openclaw.json / auth-profiles.json / canary 文本；子进程 HOME 重定向至临时目录（内置永不读取的诱饵 ~/.openclaw）；环境为四变量白名单（Linux /proc 实测）。未扫描任何真实用户配置，未联网。
- 实际验证平台仅为 **Linux ARM64**；不声称 AMD64/macOS/Windows 已验证（`open_regular_other.go` 的非 unix 回退未做原生验证）。
- 原生进程约束：每 RPC 30s 超时，关闭 stdin → 5s 宽限 → Kill 回收，stderr 捕获上限 1 MiB。

## 8. 观察项（非本次修复对象，供主开发者裁决）

- `collect` 结果不携带 `cursor` 字段（仅 checkpoint 返回）；hermes 两者都有。合同 §2 示例含 cursor 但共享类型为 omitempty，openclaw 合同未承诺——记录为差异，不擅自改 wire。
- 畸形参数错误码：openclaw 用 `scope_invalid`，hermes 用 `bad_request`（合同 §3 表均未列）；两 Connector 语义不一致，需合同层面统一，本次未改。
- evidence.source_locator 含经脱敏的绝对配置路径（hermes 为摘要定位）；identity.v2 未禁止，变更超出最小范围，记录待裁决。
- 上述三项如需改动均属公共语义，不在本任务边界内。

## 9. 未完成项

- 真实 OpenClaw 版本配置兼容性与安装验收（合同 enterprise-openclaw-json5.v1 明确另行记录）。
- AMD64/macOS/Windows 原生验证；非 unix 平台的符号链接拒绝强度（best-effort）未实测。
- 角色—Skill 精确安装/加载关联、控制面投影消费：仍属 CL-03 后续，不由声明推导。

本记录仅声明 OpenClaw Connector 原生采集子项；CL-03、CL-07 整体不关闭。

## 10. 主开发者验收与夹具修复（2026-09-26）

`validate_scope.valid` 与错误集合不一致的修复成立。未新增采集器产品代码修改；该缺陷是协议判定错误，不直接等同已经绕过 collect 的范围门禁（plan/collect 仍各自拒绝非法范围）。三项公共语义观察暂不改动、不另行扩展功能。

发现并修复原生验收夹具的证据完整性缺口：

- stdout 原 `ReadString` 无行长度上限；改为分段读取，单响应最多 8 MiB，超限即失败，而非可能持续分配内存。
- stderr 单次写入跨过 1 MiB 时未正确设置 overflow，且 overflow 未用于测试判定；现正确记录并在子进程回收后令测试失败，不能对被静默截断的输出声称泄漏检查完整。
- 临时构建增加 60 秒超时、有界输出，并在构建子进程明确设置 `GOPROXY=off`、`GOTOOLCHAIN=local`。不是仓库内构建，不覆盖登记二进制。

新增一个夹具边界测试，检查单次 stderr 截断、无换行 stdout 超限及恰好边界合法行。该测试不是第九个原生产品旅程；原八项原生旅程和既有函数测试均保留。

实际验证：

```bash
cd connectors/openclaw
GOPROXY=off go test -race -count=1 ./...
# ok siq-agent-security/connectors/openclaw 2.945s
GOPROXY=off go vet ./...
gofmt -l native_contract_test.go native_contract_linux_test.go openclaw.go
```

上述检查及仓库 `git diff --check` 通过。测试用二进制每次测试进程构建一次，由八项旅程共享，不是每个测试重新编译；每项实际启动独立原生进程。

二进制保护核对：本次 `git hash-object connectors/openclaw/openclaw` 与
`git rev-parse HEAD:connectors/openclaw/openclaw` 均为
`639204032432e3ea63110260bdc20639ba955d4e`，当前登记二进制无差异。
这仅确认当前字节与 HEAD 相同，不能追溯证明误覆盖前没有他人未提交字节。
后续所有 Go 构建必须显式指定仓库外 `-o`，不得再次以共享工作树覆盖/还原方式做基线。

本次只增补本任务测试夹具及交接记录，未改其他开发线。Linux ARM64、临时合成配置证据，不是生产安装或多平台验收。未提交、未推送、未部署，仅接受本采集子项，不关闭 CL-03/CL-07。
