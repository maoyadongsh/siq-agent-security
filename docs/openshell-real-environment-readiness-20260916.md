# OpenShell 真实环境就绪预检 — release-openshell-20260916-142706

- 批次: 正式发行候选准备 + 真实 OpenShell 环境预检
- 源提交: `052c81617438d1eabf94a5e0166338312366c491`（origin/main 同步点）
- 工作树: `/home/maoyd/siq/worktrees/siq-release-openshell-20260916-142706`
- 日期: 2026-09-16；主机 spark-1319 (linux/arm64)
- 范围: 仅本机（maoyd）；sunbo (Windows) / Luke (macOS) 环境未覆盖，不为其标记通过

## 1. 证据阶梯（evidence ladder）六级与 B2/B3/O05 当前状态

| 级别 | 含义 | 本批状态 |
|---|---|---|
| 1. client_expressible | 客户端可表达 OpenShell 环境契约 | ✅ 已达（env_pair 双变量契约，见 §3） |
| 2. documented | 有书面执行条件与来源 | ✅ 已达（本文档 + baseline/environment.json） |
| 3. configured | 指向真实网关的环境已配置且可判定 | ✅ 已达（siq-openshell-dev @ 127.0.0.1:17671，mTLS） |
| 4. handshake_verified | 匹配 status 协议响应（非会话身份绑定） | ✅ 已达（identity_ok=true，endpoint_fingerprint 见 §4） |
| 5. policy_readable | 目标策略只读读回成功 | ✅ 已达（doctor state=policy_readable，revision=2） |
| 6. enforcement_verified | 行为级执行限制验证 | ❌ 未达成（旧候选环回负例未阻断；原因未确认，见 §6） |

结论：旧候选曾读回策略；O05 仍 partial，B2 需按修复协议重跑，候选 B3 尚未测量。详见 [修复报告](release-openshell-review-fixes-20260916.md)。

## 2. 历史被测对象（rc.1；不代表修复后的 rc.2）

- `dist/siq-agent-security-0.3.0-rc.1/` 四平台交叉编译产物（linux-amd64 / linux-arm64 / darwin-arm64 / windows-amd64.exe），`-trimpath -ldflags "-s -w -X main.Version=0.3.0-rc.1"`，CGO_ENABLED=0
- SHA256SUMS 见同目录；本次预检使用本机原生 linux-arm64 二进制
- 签名输入草稿 `candidate/skill-manifest.unsigned-draft.json`：
  - manifest_version 3（client-compatible）、skill.content_hash `e69b1486c4dda3b6c8be242a80ab610ca04988a59dd5e3bb5c142e157e0a7098`（与上一版一致，skill 目录未变更）
  - 四个 artifact sha256/bytes 与重建产物一致；signed_by 固定为发行信任根 `LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=`；signature 为空（未签名草稿）

## 3. 预检环境契约（只读，全程未触碰被测项目状态）

```
SIQ_AS_OPENSHELL_CLI_BIN=<siq-research-engine>/var/openshell/toolchains/v0.0.83/bin/openshell
SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17671
OPENSHELL_GATEWAY=siq-openshell-dev
XDG_DATA_HOME   → <siq-research-engine>/var/openshell/xdg/data
XDG_CONFIG_HOME → <siq-research-engine>/var/openshell/xdg/config
XDG_STATE_HOME  → <siq-research-engine>/var/openshell/xdg/state
XDG_CACHE_HOME  → <siq-research-engine>/var/openshell/xdg/cache
OPENSHELL_LOCAL_TLS_DIR     → <siq-research-engine>/var/openshell/xdg/state/openshell/tls
OPENSHELL_SYSTEM_GATEWAY_DIR → <siq-research-engine>/var/openshell/gateway
```

> 2026-09-16 修正：本文档初版把 XDG_* 概括为 `<siq-research-engine>/xdg/...`，实测网关注册元数据
> 位于 `<siq-research-engine>/var/openshell/xdg/config/openshell/gateways/siq-openshell-dev`，
> 指向错误路径时 CLI 报 "Unknown gateway"。上表为实测校正后的精确路径。

- 契约形式: env_pair（CLI_BIN + GATEWAY_ENDPOINT，endpoint 进入稳定指纹）
- 环境变量指纹: `SIQ_AS_OPENSHELL_*` 前缀绑定到 `agentshield openshell` 子树；`env_sh`（无 env_pair）指纹为空串 → fail-closed `identity_unconfirmed`
- 网关归属: siq-research-engine 项目，2026-09-15 经用户授权启动（provenance: docs/evidence/personal-experience/openshell-o01-o02-20260915/report.md）；本批未启动、未重启、未修改任何既有服务

## 4. 预检实测结果（候选二进制，2026-09-16）

命令: `agentshield openshell doctor --target siq-analysis-canary-a01b02c91503`

- exit=0；`state: "policy_readable"`（tier L3）；`probe_ok: true`，`identity_ok: true`
- `handshake_gateway: siq-openshell-dev`；`cli_version: 0.0.83`；`endpoint_fingerprint: c4b76903a33d3ecce2c227459de8d15f61a862fca3ed7c4a22f5b5eaa864856f`
- 目标策略读回: `revision: 2`，`policy_digest: 2373bb131a84765119bbc62b61b16d744cca198d4b3d816b8a262d80d038a746`（两次运行一致，读回稳定；expires_at 为 15s 快照窗口）
- 原始证据（无凭据、无配对码，已核验）: `candidate/doctor-policy-readable.json`、`candidate/policy-get-full-readback.txt`

预检过程暴露并已修复的实现缺陷（均有负向回归）：

1. yamlkit 指标符误判: `& * ! | > { [` 等指示符仅在节点起始位置才具 YAML 语义；标量中部出现（如真实网关的 glob `path: /research/**`）必须接受。修复为 token-start 判定（`internal/openshell/yamlkit.go`），16 个负向 + 结构化正向用例回归。
2. 网络策略读回不保真: 0.0.83 `policy get --full` 含 `protocol/enforcement/rules/allowed_ips/request_body_credential_rewrite`，旧实现只认 `{host,port}` 而 fail-closed 拒绝。已忠实扩展（protocol=rest、enforcement=enforce、allow 规则 method/path、allowed_ips CIDR 校验；deny/未知 enforcement/未知键/畸形 CIDR 一律 fail-closed），method/path/IP 限制保留进 `NetworkRule`，不夸大有效访问。
3. 读回顺序不确定: map 迭代顺序泄漏进 Snapshot.Network → `sortedMapKeys` 确定化。

## 6. O05 复核：控制面观察不能代替会话执行验收

| 原清单 | 复核结论 |
|---|---|
| 会话及调用身份绑定 | unverified：doctor 仅匹配网关协议与读回目标策略 |
| 策略下发与后端读回 | 原候选已观察；新候选需独立证据 |
| 允许操作真实发生 | 已观察部分环回 HTTP；不足以证明完整任务授权链 |
| 越权操作真实阻止 | failed：环回负例实际到达，根因待查 |
| 服务不可达 fail-closed | 控制面 apply 拒绝已观察；required 会话执行拒绝未由此证明 |
| CAS 负向 | expected revision 冲突拒绝已观察 |
| 撤销/会话失效与恢复 | unverified：策略回滚不是会话撤销/失效 |
| 执行与结果关联 | unverified：deployment operation/evidence ID 不是 SEC/调用/执行结果全链 |

`capabilities.interceptor:false` 来自客户端硬编码兼容字段，不是网关现场探测结论。
不再将环回未拦截归因为“网关未启用 interceptor”，也不排除适配或测例问题。

## 7. B2/B3 复核

旧测量数据和冻结参数保留，原“全部通过”验收结论撤回：
doctor rc=0 可处于失败诊断态，旧脚本没有逐次检查 readback；
cli_sandbox_get 两腿使用同一 CLI，是环境控制项；
apply_rollback_service 执行工作树 Go 测试二进制，不是候选应用二进制。
旧绝对门槛失败也未进入退出码，现已修复。

v2 脚本执行前冻结协议/源码/二进制绑定，独占输出目录，逐样本验证并留证，
失败保留已收集样本，绝对或相对超限返回非零。
辅助回滚驱动禁止 no-op/skip 冒充覆盖，要求精确确认自有一次性靶标。
新候选 B2 正式测量尚待重跑；候选 B3 为 not_measured。
门槛未按旧结果调整，不将 30% 服务预算替代原组件 10% 预算。

## 8. 解除条件

- O05：补真实会话/调用/权限/执行结果关联，验证 required 失联、撤销失效与恢复，
  定位环回测例适用范围后完成外部目标允许/禁止双腿；不得从配置读回提升 enforcement。
- B2：空闲独占环境、已确认归属的专用靶标、两二进制与相同 CLI/网关绑定，按 v2 重测。
- B3：从候选产品实际入口跑完整应用路径；辅助测试驱动不能代替。
- 正式签名：先完成候选验收，维护者按修订签名指引执行内嵌信任根验签；
  本轮不签名、不上传。
- Windows/macOS：sunbo/Luke 原职责不变，不因本机交叉编译标记实机通过。

## 附: 证据清单与校验

见 `docs/evidence/personal-experience/release-openshell-20260916-142706/candidate/SHA256SUMS`（doctor JSON / policy 读回原文 / 未签名草稿）与
`docs/evidence/personal-experience/release-openshell-20260916-142706/openshell-live/`（B2/B3 结果 + O05 脱敏证据，各带 SHA256SUMS）。原始日志仅存于私有 /tmp 路径，未复制进 docs（已扫描确认无凭据/配对码）。
