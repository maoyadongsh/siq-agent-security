# F04 / D05：E09q「start↔outcome 间真实崩溃点」收口批次（2026-09-17）

本批固定 Linux/arm64 二进制 SHA256 `0b16e5e09e6d807b5be732e390c373e6a4354d096b272eba827bddb84a6c8177`，源绑定 `ba8d266ef5ba861282f23a8576be8744d6023118f3f42efd8e1054632ffe06fc`（931 文件，本批复算一致；本批只改 Python 驱动与 docs，未改任何 Go 源、go.mod 或 embed）。候选私有副本在 `d05-private/bin/`（0700）重新校验 sha256 一致。真实 OpenShell 0.0.83 gateway（共享，未重启）、本批独占沙箱 `siq-v6-f04-e09-crash-20260917` 执行了扩展后的 `openshell-o05v6-d05-acceptance.py` **全矩阵**（不带 --only）：[机器可读矩阵](d05-acceptance-matrix.json)373 步：**365 pass / 7 partial / 1 blocked / 0 fail**。E01–E13 汇总 **10 pass / 3 partial**（E06、E08、E11），**不等于全部验收通过**。

## 本批新增真实腿：leg_e09_crash（E09x 系列步）

紧跟 leg_e09 之后、在同一主 daemon 与同一 state 目录上第二次崩溃周期：

- **崩溃点命中**：批准一个「启动即写 1 字节启动计数器 → sleep 30 → 写 token 文件」的任务，异步 submit；轮询确认 `<state>/evidence/ostart-*.json` 已出现（ostart ID 按 Go 同源公式复算，离线守卫测试钉死）且直连 CLI 读回启动计数器 == 1（远端已真实启动），且 outcome 文档 `ost-*.json` 在 kill 时不存在（`outcome_present_at_kill=false`）。
- **真实 SIGKILL**（本批自有 daemon 进程）：客户端线程只见 `RemoteDisconnected`；ps 快照实测执行器 CLI 子进程在 kill 前 `ppid=<daemon>`、kill 后 `ppid=1`（孤儿化），窗口结束后消失（观察记录，未断言远端终止）。
- **同 state 目录重启**：token 不变（`daemon_token_unchanged=true`）。
- **链签名验证通过**（E09x7）。
- **已消费批准不可再执行**：重启后重提同一 body → 409 `hold_execution_already_reserved`（E09x8），拒绝来自持久链而非进程内存。
- **状态投影如实**：该预留的投影报 `state=uncertain` + `reason_code=openshell_task_result_uncertain`，绝不报成功（E09x9b；对应 taskStatusProjection case 5）。
- **不重放**：重启后窗口内启动计数器始终保持 1（E09x9，`launch_counter_after_restart=1`）；远端 sleep 30 的迟发效果文件在约 5 次读回后观察到（`remote_effect_observed=true`）——只证明远端命令活过了本地 daemon，不证明它被终止。
- **daemon 恢复**：probe ok + 重启后新任务真实执行成功（E09xd）。

## E09q 判据口径（保持 partial 的理由）

E09q note 仍记 **partial**（`crash_leg=pass`）：真实注入现有三类——daemon-kill 重启（E09a–E09i）、start↔outcome 间 SIGKILL（E09x，本批）、存储写盘 EACCES（E11m/n/o）；仍明确未覆盖的子项：时钟注入（**禁止项**，不改系统时间）与 plan↔start 窄窗（不打补丁无法稳定命中，仍由不可变按事实分条记录结构性覆盖）。按驱动保守口径，有具名未覆盖子项即不升 pass。

## 与上一批的修正关系

- 矩阵从 344 步（337 pass）增到 373 步（365 pass）；E09 行保持 pass 并新增 `crash_between_start_and_outcome=pass` 字段。
- E06 行本批复为 **partial**：并发守卫强化新增了 E06u4 判据——本机唯一可用的旧 CLI v0.0.13 实测**支持** `--wait`（上一批已如实记录），「不支持 --wait 的 CLI」子情形无法真实构造，按保守口径记 `not_run`，E06 汇总因存在 not_run 子项而不升 pass。E06 其余子项（加载窗口 409、窗口内撤权 403、`--wait --timeout 1` 124+写入已落+旧批准被拒、旧 CLI 执行前读回拒绝）全部 pass。
- E11 保持 partial（E11i 超时观测为 CLI 124 模糊归属，非已证远端超时）；E08 保持 partial / E08h blocked（v0.0.83 无单任务远端停止协议）。E05g、E10c、E13d 原判据不变。
- 迭代期 `--only e09` 单独验证过新腿；本目录证据来自一次不带 --only 的完整运行，无删改选优。

## 资源与清理

沙箱 `siq-v6-f04-e09-crash-20260917` 为本批独占创建（本地固定镜像 `siq/hermes-openshell-siq-analysis:f470321d2fb2b2cda14b7c3b`，create 尾随 `/bin/true` 使 CLI 正常退出），用毕按精确名称删除并只读复查不存在；其余沙箱与共享 gateway 未动。批属 daemon 进程（主 daemon 两次重启周期 + K80/E04/E06 侧 daemon）全部退出；本批 /tmp 临时目录已删。明细见 [resources.json](resources.json)。私有材料（原始流量、候选副本）在 0700 的 `d05-private/`，公开区无配对码/私钥。
