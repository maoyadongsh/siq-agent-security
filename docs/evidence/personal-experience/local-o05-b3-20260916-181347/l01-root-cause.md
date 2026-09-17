# L01 阻断问题定位 — 受控实测结论（2026-09-16）

实验环境：专用临时沙箱 `siq-l01-o05-181930`（Id c27b9276-44e1-4809-8160-6d258b7a264b，本批创建并归属，创建证据 `l01-private/sandbox-create2.log`），网关 siq-openshell-dev v0.0.83，镜像 siq/hermes-openshell-siq-analysis:f470321d2fb2b2cda14b7c3b（本地缓存，与 canary 同源）。受控接收端均带 correlation ID；宿主侧接收端为本批自有用户进程（18444/18445）。

## 对照矩阵（全部有 corr_id 与接收端到达日志/空日志佐证）

| # | 目标 | 策略 | 客户端结果 | 接收端到达 | 证据 |
|---|---|---|---|---|---|
| 1 | loopback 127.0.0.1:18443 | 无 network policy（rev1） | 200 | 到达 | baseline-reachability.log |
| 2 | loopback 127.0.0.1:18098（违规） | 无 network policy（rev1） | 200 | 到达 | baseline-reachability.log |
| 3 | loopback 18443（放行） | A: agentshield 形状（无 protocol/enforcement），rev2 | 200 | 到达 | polA-loopback-test.log |
| 4 | **loopback 18098（违规）** | A（rev2） | **200，未阻断** | **到达** | polA-loopback-test.log |
| 5 | **loopback 18098（违规）** | B: +`enforcement: enforce`+`protocol: rest`+rules，rev4 | **200，未阻断** | **到达** | polB-loopback-test.log |
| 6 | 跨边界 172.23.0.1:18444 | 无 network policy（rev1） | 403（egress 代理产生） | **未到达**（宿主日志空） | baseline-reachability.log |
| 7 | 跨边界 172.23.0.1:18444（放行） | C: A+B+agentshield 形状 xb 规则（无 protocol/enforcement），rev5 | 200 | **到达**（corr_id 匹配，源 172.23.0.4） | 会话记录+hostrecv.log |
| 8 | **跨边界 172.23.0.1:18445（违规）** | C（rev5） | **403** | **未到达**（宿主 18445 日志空） | 会话记录 |

403 由沙箱内 egress 代理（supervisor 监听 10.200.0.1:3128，见容器日志 `OCSF NET:LISTEN 10.200.0.1:3128`）产生；请求从未到达宿主接收端。

## 根因结论

1. **旧 O05 "阻断失败" 的直接根因是测试靶标选错边界**：沙箱内 loopback（127.0.0.1）流量不经过 egress 代理，完全不被 network policy 拦截——即使显式 `enforcement: enforce` 也无法阻断 loopback（矩阵 #4/#5）。历史证据 `exec-behavior-abc.log` 中 8098 接收端收到请求，正是这一机制，而非 agentshield 策略编译缺陷。
2. **跨边界（非 loopback）egress 默认拒绝且策略生效**：无条目 → 403（#6）；agentshield 形状的 allow 条目即可放行（#7）；未放行目标 403 且请求不达（#8）。
3. **`networkRulesToGateway` 缺 `protocol`/`enforcement` 字段不是阻断失效根因**（对照 #7 vs #8：缺省字段的 allow 规则放行生效、违规目标仍被拒）。网关对该形状按 allow 条目处理，跨边界执行 enforce 语义。
4. 附带发现：`protocol: rest` 必须配 `rules` 或 `access`，否则网关拒绝加载（"protocol requires rules or access to define allowed traffic"）——agentshield 若未来要带 protocol 字段，必须同时生成 rules。
5. **执行平面传播滞后（本日补充实测）**：`policy set` 网关回读已确认新 revision 后，沙箱 egress 执行平面仍滞后数秒才生效——带时间戳实测：set 完成 +1ms 发起请求 → 403；+2.3s → 200（diag2-t1/t2，诊断接收端 18447）。行为级验证若在 readback 通过后立即发起，会把"传播未完成"误判为"策略未生效"。任何 enforcement_verified 级别测试必须在放行路径上带 bounded settle 窗口并记录观察到的传播耗时。

## 对 SIQ 侧的含义

- enforcement_verified（level 6）此前未达成的部分原因：O05 实测把靶标放在了策略边界之外的 loopback。**O05 live 测试须用跨边界受控接收端**（本批宿主接收端模式可复用），并把 loopback 与跨边界分开记账（本批矩阵即模板）。
- agentshield 策略编译本身无需为"阻断失效"打补丁；但 O05 测试装置（接收端位置、可达性前置证明、correlation ID）需要按上述结论修正。
- **修正后的行为级 live 测试已落盘**：`apps/agentshield/internal/openshell/o05_enforcement_live_test.go`（`TestO05LiveCrossBoundaryEnforcement`，opt-in：SIQ_O05_ENFORCE_LIVE/TARGET/CONFIRM_TARGET + SIQ_AS_OPENSHELL_ENV_SH + SIQ_O05_ENFORCE_EGRESS_HOST，默认跳过）。它实现：loopback 零声明、测试自有 correlation-ID 双接收端（放行端口=阳性对照、违规端口）、基线默认拒绝前置证明、agentshield 形状 allow 规则经 ApplyNetwork CAS 应用 + readback 验证、放行路径 bounded settle 窗口（30s，结论 #5）、违规目标 403 且接收端 0 到达、策略基线恢复（成功路径与失败清理双路）。已于本沙箱实跑通过：baseline_deny=ok，rev13→14，放行到达、违规 0 到达（`l01-private/o05-enforcement-live-test.log`）。
- 接收端必须绑定可跨边界到达的地址（0.0.0.0 / 桥接网关 IP）；loopback-only bind 会被误读为"阻断成功"。

## 私有文件

`l01-private/`：sandbox-create2.log（创建+删除记录）、new-sandbox-get.txt、ssh-config-redacted.log（已脱敏）、baseline-reachability.log、polA/polB/polC 测试日志、policyC-effective-readback.txt。原始合并策略 YAML 在 /tmp/l01-exp/（临时）。

## 沙箱处置

`siq-l01-o05-181930` 为本批专用临时资源，L01 证据采集完成后将按精确 ID 清理；宿主接收端进程（18444/18445）随批终止。
