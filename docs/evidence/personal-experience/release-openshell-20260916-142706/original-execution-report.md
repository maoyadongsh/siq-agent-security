# 执行报告 — 正式发行候选准备 + 真实 OpenShell 环境预检

- 批次: release-openshell-20260916-142706；执行: GLM（本机 maoyd，linux/arm64）
- 基线: `052c81617438d1eabf94a5e0166338312366c491`；分支 `glm/release-openshell-readiness-20260916-142706`
- 工作树: `/home/maoyd/siq/worktrees/siq-release-openshell-20260916-142706`
- 本批仅本地落盘，未 commit/push/merge/创建 Release/上传制品

## 1. 实际完成项

1. **冻结发行候选**: `dist/siq-agent-security-0.3.0-rc.1/` 四平台交叉编译（linux-amd64/linux-arm64/darwin-arm64/windows-amd64.exe，`-trimpath -ldflags "-s -w -X main.Version=0.3.0-rc.1"`，CGO_ENABLED=0）+ SHA256SUMS；未签名 manifest 草稿（manifest_version 3，content_hash `e69b1486c4dda3b6c8be242a80ab610ca04988a59dd5e3bb5c142e157e0a7098`，signed_by=信任根，signature 为空）。
2. **真实 OpenShell 环境预检**: 六级证据阶梯 1–5 全部以实测达成（client_expressible → documented → configured → handshake_verified → policy_readable）；endpoint_fingerprint `c4b76903a33d3ecce2c227459de8d15f61a862fca3ed7c4a22f5b5eaa864856f`。
3. **O05 真实后端行为验收**: 8 项清单实测，7 项通过、1 项负面发现如实记账（详见 §3/§4）。
4. **B2/B3 真实网关服务级实测**: 冻结协议 `scripts/personal-experience/openshell-b2b3-perf-protocol.py`（先冻结后测量），改造前(efad840) vs 候选(0.3.0-rc.1) 双腿 + B3 集成环，全部预算 pass。
5. **修复与文档**: 预检暴露的 3 个实现缺陷修复（均有负向回归）；readiness 文档（含 §3 XDG 路径实测修正）、签名指引、任务书/台账增量、证据目录落盘。

明确不做（与任务书一致）: T01–T06 团队功能；不修改 N09 阈值；不接管 sunbo (Windows)/Luke (macOS) 的未交付环境。

## 2. 验证结果（分别记账，不混计）

**构建成功**: 四平台交叉编译产物与 SHA256SUMS 重建一致；linux-arm64 为本机原生。

**测试成功**: `apps/agentshield` 全量 `go test ./...` 通过；`go vet ./...` 干净；`gofmt -l` 无输出；`go test -race ./internal/openshell/` 通过；Python 协议脚本无第三方依赖。新增强制跳过的 live driver 在普通运行下 SKIP（`o05_live_test.go:27`），仅在 `SIQ_O05_LIVE=1` 时对真实后端执行（本批已实际执行并通过）。

**真实环境验收**（非模拟、非交叉编译、非测试签名替代）:
- 预检: 真实网关 siq-openshell-dev @ 127.0.0.1:17671（mTLS），doctor 实测 policy_readable，读回稳定。
- O05: 身份绑定/下发读回/允许操作/fail-closed/CAS 负向/撤销恢复/证据关联 7 项通过；**第 4 项（行为级越权阻止）实测未达成**。
- B2/B3: 绝对预算 7/7 pass；相对预算 new/old p95 = 0.9963 (doctor_readback)、0.9977 (cli_sandbox_get)，均 ≤ 1.30；B3 apply(CAS)→读回→nil-authorizer 拒绝→授权回滚环 p95 1030.343ms（n=5）。零排除、零重跑取好、协议常数未因结果调整。

**正式发行**: 签名 leg 阻塞（官方种子未设置）——不与上述三项混计为“发行就绪”。

## 3. 发现与修复（安全修复均带负向回归）

1. **yamlkit 指示符误判**（预检暴露）: `& * ! | > { [` 等仅在节点起始具 YAML 语义，标量中部出现（真实网关 glob `path: /research/**`）曾被 fail-closed 拒绝。修复为 token-start 判定（`internal/openshell/yamlkit.go`），16 个负向 + 结构化正向回归。
2. **网络策略读回不保真**: 0.0.83 `policy get --full` 的 `protocol/enforcement/rules/allowed_ips/request_body_credential_rewrite` 旧实现不认而拒绝。忠实扩展读回（protocol=rest、enforcement=enforce、method/path、CIDR 校验），deny/未知键/畸形 CIDR 一律 fail-closed；method/path/IP 限制保留进 `NetworkRule`，不夸大有效访问。
3. **读回顺序不确定**: map 迭代顺序泄漏进 Snapshot.Network → `sortedMapKeys` 确定化。
4. **负面发现（不修代码，如实记账）**: enforcement_verified（阶梯第 6 级）在 v0.0.83 dev 网关路径未达成——`capabilities.interceptor:false`，已下发 allow 列表策略不实际阻止沙箱内环回流量（python3 与 curl 均可达非允许端口 8098，策略读回本身正确）。属网关能力限制，解锁条件：网关启用 interceptor 后重跑 O05 行为序列。

## 4. 未完成项

| 项 | 状态 | 阻塞原因 / 解除条件 |
|---|---|---|
| enforcement_verified（阶梯 6） | 未达成 | 网关 interceptor:false；网关侧启用后重跑 O05 第 4 项序列 |
| 正式签名 | blocked | `SIQ_AGENT_SECURITY_RELEASE_SEED` 未设置；维护者按 `agentshield-release-signing-instructions-20260916.md` 执行，随后 manifest-verify 信任根校验 |
| 正式 Release/上传 | 未执行 | 本批边界仅本地落盘；且依赖签名 leg |
| sunbo (Windows) / Luke (macOS) 实机预检 | external_manual | 协作者各自实机重复 §3–§4 预检并回传；本批不代做、不标记通过 |
| 跨版本真实升级验收 | 未执行 | 缺少真实旧版本发行链（规则：同一源码换版本字符串不称真实跨版本升级） |
| B07 遗留 | 维持 | diagnose_unconfigured 相对 +15.79% 超 10% 门（绝对预算全过）；本批 B2/B3 真网部分已关闭，其余同前 |

## 5. 证据与 Git 状态

证据根: `docs/evidence/personal-experience/release-openshell-20260916-142706/`
- `candidate/` — SHA256SUMS、doctor-policy-readable.json、policy-get-full-readback.txt、skill-manifest.unsigned-draft.json
- `b01-lifecycle/` — 生命周期复核 35 项 PASS
- `openshell-live/` — b2b3-results.json + b2b3-run-notes.json + o05/（脱敏行为证据 19 文件 + README-o05-verification.md）；各目录含 SHA256SUMS

文档: `docs/openshell-real-environment-readiness-20260916.md`（§3 路径修正、§6 O05、§7 B2/B3、§8–9 阻塞与解锁）、`docs/agentshield-release-signing-instructions-20260916.md`（新建）、`docs/personal-experience-lan-team-next-development-taskbook-20260915-232155.md`（§20 两行更新 + §21 增量）、`docs/personal-experience-closure-progress-20260913.md`（发行批节）、本报告。

Git: 工作树未 commit（本批边界）。修改: `internal/openshell/{policy.go,types.go,yamlkit.go,yamlkit_test.go}`；新增: `internal/openshell/o05_live_test.go`、`scripts/personal-experience/openshell-b2b3-perf-protocol.py`、上述 docs 与证据目录。原始日志仅存私有 /tmp（`/tmp/siq-relcand-o05-20260916-154423` 等），已扫描确认无凭据/配对码后脱敏入库。

## 6. 环境状态（收尾后）

- **已删除**: 批次沙箱 `siq-relcand-20260916-154423`（含其内部两个 python3 监听进程，随沙箱消亡；删除前经 create 日志复核归属）；`/tmp/b2b3-live-*` 临时编译目录。
- **未触碰**: 网关 siq-openshell-dev（siq-research-engine 归属，本批未启动/重启/修改，仅经 mTLS 调用）；canary 沙箱 `siq-analysis-canary-a01b02c91503` 保持预检时状态（rev2/digest 2373bb…）；共享 systemd manager HOME、日常 profile、全局 DNS/代理/TLS/SSRF 规则均未改动。
- **遗留私有**: /tmp 下原始证据目录与 B01 保留二进制（bin-old sha256 178c24be…，bin-new）——供复核，不入库。
- 协作者工作树未被访问/修改；未向任何协作者发送消息。
