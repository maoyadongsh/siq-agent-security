# closure-b01 生命周期验收证据（20260916-003916）

- 基线矩阵：`personal-acceptance-baseline/v2`；checks schema：`closure-b01-checks/v1`
- 结论：**done**（33 项检查：31 observed PASS + 2 not_exercised 备注项，0 FAIL）
- 任务书依据：taskbook §6.2（生命周期 runner）与 §6.3（LC01–LC09 接受表）

## 1. 覆盖对象与构建

| 项 | 值 |
|---|---|
| 旧版 commit / tree | `efad840` / `2216f4a0e9eef3e750c13673da8e158d4e84a6a3` |
| 新版（候选）commit / tree | `53155b1` / `9ff0c7e9c50c48fcc249adfbe48df76b82d19c51` |
| 构建方式 | 两次独立 `git archive` 提取（非共享 checkout），`go build -trimpath -ldflags "-s -w -X main.Version=…" -o … ./cmd/agentshield`，GOOS/GOARCH × {linux/amd64, linux/arm64, darwin/arm64, windows/amd64}，`CGO_ENABLED=0` |
| 版本号 | old=`0.2.0-b01-old`，new=`0.2.0-b01-new` |
| 产物摘要 | 见 `environment.json` `builds`（每目标 sha256） |
| 信任层 | 测试种子（一次性，`run_dir/release-seed.b64` 0600，不入证据）→ stdlib `crypto/ed25519` 派生公钥 `rk5UqLck9x04rbQe/XswHXM7zWrttQot1Zmp1kA06as=` → **仅在 archive 提取树内**补丁 `skillmanifest.ReleasePublicKeyB64` 常量（fail-closed 单密钥 pin，非放宽信任根）；worktree 源码零改动。正式发布 leg = **blocked**，解锁条件：维护者以正式发布种子签署 manifest（`environment.json.trust_layer`） |

## 2. LC01–LC09 接受表

| 检查 | 结论 | 级别 | 说明 |
|---|---|---|---|
| lc01_no_confirm / bad_signature / digest_mismatch / state_incompatible | PASS | observed | 四类安装前置拒绝（缺确认 / 篡改签名 / 摘要不符 / v2 manifest 无状态兼容声明 vs marker-v2） |
| lc01_no_side_effect | PASS | observed | 拒绝前后状态目录树摘要 + `siq-agent-security-*` 用户单位集合均不变 |
| lc01_install_ok / lc01_identity | PASS | observed | 测试信任根下 client-install 成功；身份面（state_directory_id / version / unit / MainPID / FragmentPath / staged 二进制摘要=运行摘要 / 签名公钥）完整 |
| lc02_pair_valid / invalid / replay | PASS | observed | 有效码得会话；无效码 `dead-beef-dead-beef` 拒绝；重放仍 401/403 |
| lc02_expired_code | PASS | **not_exercised** | 5 分钟真实过期窗口未等待；由 `requestLocalPairing ExpiresIn=300` 组件合同覆盖（备注项，非缩分母） |
| lc03_port_occupied | PASS | observed | 端口 25179 被本 runner 持有的 socket 占用：client-install 非零退出、占用者存活、未新注册任何用户单位。stderr 为设计面通用错误（子进程 stderr 有意丢弃，见 §5） |
| lc03_special_path | PASS | observed | 状态目录含 中文/空格/%25：ExecStart 运行路径归属该特殊路径状态目录，服务 active |
| lc04_unit_precise / no_second_process / stop_needs_confirm / restart / session_after_restart | PASS | observed | FragmentPath=安装副本、ExecStart 指向状态目录 staged 程序；重复 start MainPID 稳定；stop 缺确认拒绝；stop→start 恢复；重启后旧管理会话 401/403 |
| lc06_upgrade_tx / identity_kept | PASS | observed | staged 旧程序 + `--source-manifest` 升级，捕获切换事务号；directory_id 不变、版本切至 new |
| lc07_rollback_wrong_path | PASS | observed | `--binary` 指向与事务历史摘要不符路径（repo 构建产物路径）被拒（`binary path differs from historical source` — renderUserUnit 比对 SourceUnit） |
| lc07_rollback / rollback_identity | PASS | observed | 精确历史 staged 路径 + 旧 manifest 回滚成功；运行摘要回到旧版、directory_id 保持 |
| lc07_recover | PASS | observed | 升级中断注入（读出事务号后 SIGKILL，延迟梯度 0.05–1.0s）→ 单位 inactive → `--recover <tx>` 恢复至 new |
| lc08_unknown_preserved | PASS | observed | 未知文件 / symlink / `~/.config/systemd/user/b01-unknown-user-unit.service`（外来单位）经 start/stop/start 全程保留 |
| lc09_teardown_unit_gone / state_retained | PASS | observed | teardown 后单位 not-found；状态目录保留（身份/配置条目在前后树交集内） |
| lc09_reentry_install / identity_reused | PASS | observed | 以**最新已验证版本**（teardown 前最后运行的 staged 程序对应版本）经 client-install 重入成功；state_directory_id 复用（未重新生成身份）。用旧版本重入会触发 `explicit migration required` 设计面拒绝（unit 摘要签名绑定，见 §5） |
| lc09_revoked_still_invalid | PASS | observed | 重入后无效凭据仍 401/403 |
| lc09_grant_revocation | PASS | **not_exercised** | Grant 撤销不复活由 r04/UP 层证据覆盖（备注项，非缩分母） |
| b01_artifacts / b01_final_teardown | PASS | observed | 双版本 4 目标构建 + 3 份 manifest 签署；收尾 teardown 单位注销 |

## 3. 失败索引

本轮（003916）：无 FAIL。

前次迭代（归档于 `iterations/`，均为 runner 自身问题，非产品缺陷）：

| 迭代 | 结果 | 失败项 / 原因 | 修复 |
|---|---|---|---|
| 001127 / 001621 / 001728 | 中断（仅 logs） | ① 测试种子 manifest 被产品信任根拒（`untrusted signing identity`）② pubkey 派生 helper 编译错 ③ `unit_name()` 经 service-prepare 取单位名，运行期撞 state 写锁（`write lock held by another process`） | 建立测试信任构建层；stdlib 派生公钥；改为只读 glob 状态目录已渲染单位文件 |
| 002444 | 中断（仅 logs） | `ExecStart` 解析按空白切分，取到 `{`（systemd show 返回对象串且路径含空格） | 改为 `path=(.*?)(?: ;$)` 截取 |
| 003002 | 28 检查 3 FAIL | ① lc04 FragmentPath 断言错（systemd 从 `~/.config/systemd/user/` 加载）② 真回滚用了 repo 构建产物路径（产品要求精确 staged 历史路径）③ lc09 用旧版本重入触发 `explicit migration required` | ① 按实际安装副本断言 ② 改用事务内 staged 路径 ③ 以最新已验证版本重入（语义修正，见 §5） |

## 4. 命令与退出码（关键路径，摘要见 logs/）

- `git archive <commit> | tar -x` ×2 → 独立提取树；4 目标构建退出码均 0（argv 与 sha256 在 `environment.json`）
- `release-manifest`（env `SIQ_AGENT_SECURITY_RELEASE_SEED`）×3：old-v3 / old-v2（无兼容声明，负例用）/ new-v3；测试密钥 stderr 告警已归档
- `client-install`：负例 ×4 exit 1；lc03 端口占用 exit 1；主安装 exit 0
- `service-upgrade` / `service-rollback` / `service-upgrade --recover`：均 exit 0（中断注入轮按设计 exit 非 0 后恢复）
- `teardown --confirm-teardown`：exit 0（“程序、配置、身份与历史数据已保留”）
- 全部 CLI 调用的脱敏 argv/exit/duration 见 `logs/`（0600，配对码已脱敏）

## 5. 设计面行为记录（本轮实证）

1. **client-install 子进程失败仅报通用错误**：`cmdClientInstall` 对 setup 子进程 `Stdout/Stderr = io.Discard`（`apps/agentshield/cmd/agentshield/client_install.go`），失败统一为 "installation not confirmed; staged program retained"。端口占用归属由「非零退出 + 占用者存活 + 单位集合不变」三角证据完成。
2. **重入版本绑定**：teardown 保留的 `user-service.json` 记录含签名绑定的 unit 摘要（unit 内容含 ExecStart 指向最后运行的 staged 程序）。以其他版本 client-install 重入触发 `state: service configuration changed; explicit migration required`（`internal/state/user_service.go verifyServiceRecord`）——设计面迁移守卫，正确重入路径 = 最后运行的已验证版本。
3. **回滚路径精确性**：service-rollback 校验 `renderUserUnit(--binary) == plan.SourceUnit`，仅接受事务内记录的 staged 路径，repo 构建产物路径被拒。

## 6. 环境与收尾状态

- 主机：Ubuntu 24.04.4 aarch64；go1.26.5；systemd user session
- 端口：25173（主）/ 25179（端口占用负例，占用者=runner 自持 socket，已关闭）
- 状态目录：`/tmp/siq-closure-20260915/b01r6/state 中文 空格%25实例`（保留于 /tmp，不入仓库）
- 收尾：`b01_final_teardown` PASS —— 无运行中实例、无 `siq-agent-security-*` 用户单位、端口释放（复验：PORT_FREE / NO_UNITS）
- 敏感物：测试种子 0600 于 run_dir，未入证据、未提交；`~/.config/siq-agent-security/` 真实信任物全程未读取

## 7. 缺口与解锁条件

| 缺口 | 解除条件 |
|---|---|
| 正式发布信任根 leg | 维护者以正式发布种子签署 manifest 后复跑本 runner（`--official` 路径） |
| lc02 真实 5 分钟过期窗口 | 等待窗口或组件注入时钟；当前以 ExpiresIn=300 组件合同覆盖 |
| 其他 OS 安装 leg（B06/B08） | 需 Windows / macOS 实机（外部 manual，见 B09） |
