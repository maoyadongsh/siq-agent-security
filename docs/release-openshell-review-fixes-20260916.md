# OpenShell 发行批复核修复报告（2026-09-16）

本次已修复可在本机确定的代码与工具问题；原“ O05 7/8 通过、B2/B3 全通过”
结论已撤回。修复成果仅本地落盘，未提交、推送、合并、正式签名或发布。

工作树：`siq-release-openshell-20260916-142706`；
分支：`glm/release-openshell-readiness-20260916-142706`；
基线：`052c81617438d1eabf94a5e0166338312366c491`。
保留 GLM 原有实现与原始证据，在其上增量修复。

## 1. 实际修复

| 问题 | 处理与边界 |
| --- | --- |
| 读回的 method/path/IP 限制在再次 Apply 时丢失，可能放宽访问 | 保留 protocol/enforcement/凭据重写布尔值的存在性；当前 host:port writer 对任何只读限制字段写前拒绝，后端零写；完整原策略仍可经受控精确回滚恢复 |
| Verify 只看 endpoint，把限制规则当作无条件允许 | 限制端点标记 restricted，端点级 allow 和 deny 检查均不通过，不把配置验证升级为行为执行验证 |
| doctor 返回 0 即被算作性能成功样本 | 严格校验 JSON、state、probe/identity、target、revision/digest、证据有效期；不可达场景要求精确状态与 false 标志 |
| 绝对预算漏入退出码 | 绝对与相对任一 MISS 均非零退出；p50/p95/p99 均为 nearest-rank；不根据旧结果放宽预算 |
| 同 CLI 对照冒充候选对比；测试驱动冒充 B3 | 移除同 CLI 的候选相对判定，Go driver 明确命名为辅助控制面验证；候选 B3 仍 not_measured |
| 驱动 no-op / skip 也可成功；授权回调报错后仍返回 nil | 必须产生变更且实际执行负向与恢复；授权绑定不匹配返回错误；确认精确自有一次性目标；失败时按精确回执与当前授权尝试恢复，漂移拒绝，不强制覆盖 |
| 性能失败后丢证据/覆盖旧文件、输入未绑定 | 独占领取输出路径，测量前冻结协议；源文件与三二进制哈希、辅助驱动摘要绑定；逐条保存样本，异常落 invalid，结束复查漂移；临时测试二进制自动清理 |
| 签名示例目录和格式错误 | 明确标准 base64 的 32 字节种子；用原生候选二进制；静默读取种子、清除环境；暂存完整 Skill 内容与清单后独立内嵌信任根验签，不覆盖仓库清单 |
| 5 个哈希清单引用的 .out 被全局规则忽略 | 对这 5 个具体脱敏文件设置窄例外；未放开其他运行时输出 |

安全回归在 `readback_restrictions_test.go`；
驱动授权回归在 `o05_live_test.go`；
工具负向测试在 `test_openshell_b2b3_perf_protocol.py`。
规格及安全合同同步，Python 的严格读取子集未被放宽。

## 2. 实际验证

| 检查 | 结果 |
| --- | --- |
| Go gofmt（修改包）/ go vet ./... / go test ./... | 通过 |
| go test -race ./internal/openshell ./internal/server | 通过；真实驱动默认 SKIP，不算真实后端通过 |
| Python 脚本 unittest | 8 项通过，包括绝对失败但相对通过、错误诊断、skip/no-op、错误输出不回显敏感内容 |
| Ruff（两个性能脚本文件） | 通过 |
| Python policy safety vectors + schema contracts | 231 项通过（存在依赖弃用提示，无测试失败） |
| CGO=0 四目标构建 | linux/amd64、linux/arm64、darwin/arm64、windows/amd64 全部通过 |
| 隔离目录从源码快照重建 linux/arm64 | 与 rc.2 字节摘要完全一致 |
| 新候选只读实网 doctor | exit 0，结构化验证 policy_readable、revision=2、digest 2373bb…；一次诊断，不是性能采样或行为验收 |
| 新候选 unsigned manifest 验签 | 预期 exit 1 / missing signature |
| 两个 seed 环境变量均缺席时签名 | 预期 exit 1 / refusing to sign，零输出文件 |
| 签名示例 bash -n | 通过；未执行正式签名 |
| 原证据 SHA256SUMS | 60 条全部匹配，原始证据未改写 |
| source-delta 基线应用检查 / git diff --check | 通过 |

本次没有再次执行会修改共享沙箱的 live driver，没有启动/停止网关或调整其策略。
只读诊断证据有效期属于观测当时，不作为当前永不过期的在线状态。
诊断不能证明密码学会话身份，也不能证明实际拦截。

## 3. 新候选和证据

候选：`dist/siq-agent-security-0.3.0-rc.2/`。
原 rc.1 目录不变，不继承其验收结论。
构建参数：CGO_ENABLED=0，
`-trimpath -buildvcs=false -ldflags "-s -w -X main.Version=0.3.0-rc.2"`。

证据：[release-openshell-review-20260916](evidence/personal-experience/release-openshell-review-20260916/)：

- `source-files.json`：1137 个源/资源/Skill/测试文件摘要；
- `source-delta.patch`：含新增 Go 文件的差异，可应用于记录基线；
- `builds.json`：Go 工具链、构建参数、四制品大小/摘要与源码归属；
- `reproduce-linux-arm64.json`：独立源码快照重建一致性；
- `skill-manifest.unsigned-draft.json`：由原模板更新版本、实际 Skill 哈希及实际四目标摘要的**未签名草稿**；URL 为计划值，尚未上传；
- `rc2-doctor-readonly.json`：脱敏后的单次只读观测；
- `integrity-review.json`、`signing-negative-checks.json`、`checks.json`、`SHA256SUMS`。

源码快照 `source-snapshot.tar.gz` 留在忽略的 dist 下；
发布到其他环境需携带快照，或从基线应用差异并按 source-files.json 复核。
Skill content_hash 只绑定 Skill 内容，不代替生产源码或二进制摘要。
本机原生二进制 SHA256：
`5b52109a43355168fb04bd5101f5d6b4cce8f3ea35bc3ff492c4401823c1bc70`。

## 4. 原报告纠正

1. doctor 只证明协议响应和策略读取，不能证明会话/调用身份绑定。
2. 回滚授权回调不能代替 SEC/Authority 撤销、会话失效与恢复。
3. deployment operation/evidence ID 不能代替执行调用及结果的全链关联。
4. `client.go` 的 `Interceptor:false` 是静态兼容字段，不能据此认定网关能力。
   环回 8098 可达负例保留；网络路径、命名空间及规则适用范围仍需定位。
5. B2 旧样本缺少每次真实状态证明，不能追补成新协议通过；B3 旧驱动不是候选二进制。
6. b01-lifecycle 使用旧/新测试信任构建，不能算 rc.1 或 rc.2 正式发行验收。
7. 旧原稿以 historical/superseded 保留，不删除失败结果，不改旧哈希清单。

## 5. 下一步与解除条件

- **B2**：在无并行构建/测试的独占环境，确认自有一次性靶标后运行 v2 协议。
  必填 B2B3_OLD_BIN、B2B3_NEW_BIN、B2B3_CLI_BIN（绝对路径）、
  B2B3_SANDBOX、B2B3_CONFIRM_OWNED_TARGET（值等于 sandbox）、
  B2B3_OUT（全新路径）；显式配置 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 与需要的私有 XDG 环境。
  不复用旧已删除沙箱；失败保留输出，不能重跑取最好值。
- **B3**：开发/验收必须经过候选产品实际入口，不能用工作树 Go 测试二进制替代。
- **O05**：真实会话/调用身份 → 当前权限/Authority → required 失联拒绝 →
  撤销/失效 → 执行结果关联；确认隔离层可覆盖的流量类别，
  在自有靶标完成允许与越权双腿后才可提升 enforcement 证据。
- **发行**：完成剩余门禁后由维护者使用正式种子签名；本轮不生成或借用正式种子。
- **跨平台**：sunbo/Luke 的原任务不变，不用交叉编译结果替代 Windows/macOS 实机证据。
- **团队功能**：仍遵守 N09 前置条件，不因此批修复提前关闭个人验收。

## 6. 环境与 Git

仅修改本工作树；无子代理、无协作者消息、未访问协作者工作树。
新建的临时 Git index、源码重建目录已清理；新增 control-api .venv 为忽略的本机测试环境。
未创建后台服务/沙箱/监听端口；共享网关仅接受一次只读诊断。
用户已有修改与私有原始日志保留。本轮所有更改未提交、未推送、未合并、未发布。
