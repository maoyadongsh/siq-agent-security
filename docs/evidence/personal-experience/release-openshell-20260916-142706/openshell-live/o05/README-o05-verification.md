# O05 真实后端验收证据（2026-09-16）

原始日志产生于 /tmp/siq-relcand-o05-20260916-154423（私有目录，含完整环境上下文，不入库）。
本目录为脱敏后副本，已扫描无配对码/凭据/私钥。

## 靶标
- 网关：siq-openshell-dev @ https://127.0.0.1:17671（真实运行中服务，非 mock）
- 沙箱：siq-relcand-20260916-154423（本批自建，镜像 siq/hermes-openshell-siq-analysis:f470321d2fb2b2cda14b7c3b）
- 二进制：候选 dist siq-agent-security-linux-arm64 (sha256 e93b70ba0dd0d11d4df4dd9d9f1ad2d170d1dc96fd7bfd5f07adc1652d700537)

## 逐项结果（对应 O05 清单）
1. 会话及调用身份绑定 — doctor-baseline.json: probe_ok=true, identity_ok=true, source=env_pair → 通过
2. 策略下发与后端读回 — apply-ok.out（rev1→2, readback_verified, evidence_id ev-9fa7b8197745dd20）→ 通过
3. 允许操作真实发生 — exec-behavior-abc.log / exec-start-listeners.log：沙箱内 8099/8098 监听与 HTTP 请求到达 → 通过
4. 越权操作被真实阻止 — **行为级未达成（负面发现）**：allow 列表仅含 python3 且仅允许 127.0.0.1:8097，但 python3 与 curl 对 8098 的请求均到达
   （exec-behavior-a2b2.log；与网关 capabilities interceptor:false 一致）。策略读回正确（apply-deny.out），
   证据阶梯第 6 级 enforcement_verified 在本网关路径未达成，如实记账，不升级。
5. 服务不可达时 fail-closed — apply-unreachable.out（exit 1 openshell_command_failed）+ doctor-unreachable.out
   （configured_unreachable, probe_ok=false, identity_ok=false）+ doctor-after-failclosed.json（策略未变：rev2, digest 15a91620…）→ 通过
6. CAS 负向 — apply-cas-negative.out（expected-revision 999 → exit 1 revision conflict）→ 通过
7. 撤销/会话失效与恢复 — go-live-rollback-test.log：TestO05LiveRollbackRestore PASS
   （nil authorizer 回滚拒绝（fail-closed）→ 授权回滚恢复 base digest 15a91620…，读回证实 rev4）→ 通过
8. 执行与结果证据准确关联 — operation_id opo-63eeb153… 与 evidence_id 关联（apply-ok.out / go-live-rollback-test.log）→ 通过

## 结论
O05 8 项中 7 项通过；第 4 项（行为级越权阻止）在 v0.0.83 dev 网关上未达成，
属网关能力限制（interceptor:false），非 agentshield 缺陷；第 6 级证据（enforcement_verified）如实记录为未达成。
