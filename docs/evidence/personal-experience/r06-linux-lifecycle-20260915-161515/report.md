# R06 Linux 产品生命周期实机验收报告（LC01–LC09）

- 日期：2026-09-15
- 执行批次：glm-linux r06/r04/r07 batch（交接文档 `docs/glm-linux-r06-r04-r07-execution-prompt-20260915-153142.md`）
- 工作树基线：`efad8407c84b7b8f626cb06421287e7632c83a46`（未提交、未推送）
- 证据等级标记：`[real]` 实机真实执行；`[obs]` 真实观察记录（非验收目标本身）；`[deferred]` 有因推迟。

## 环境与二进制身份

- OS：Linux 6.17.0-1014-nvidia aarch64（Ubuntu，systemd 用户管理器可用，Linger=yes 为既有配置，本批未改动）
- 候选构建：`bin/agentshield` sha256 `15d688fdd4652e9efb544ece769142b60725bc0a5d2deae233062f6b910e0701`
- 发布 v1（0.2.1-batch）linux-arm64 artifact sha256 `0cb1dcbb336c2d3384d4210b5f0f134fe4dfaf77fd9aff1475f3237083403424`
- 发布 v2（0.2.2-batch）linux-arm64 artifact sha256 `efcd5c9c49f8791398c766f7bab3500b1123bf4627a014c235d95f7f0a1dded6`
- 测试构建（Go opt-in 测试用，默认 Version）：`bin/agentshield-test` sha256 `3c0f3e82dbf4ce5ffd43154c5887dac0394b4aa16c6a5273c227fba4b09730ec`
- 签名：本地以仓库信任根（`SIQ_AGENT_SECURITY_RELEASE_SEED`，seed 内容未打印、未落盘证据）真实 Ed25519 签发 v1/v2/负例 manifest；trust root 与 `skillmanifest` 内置信任根一致（`LtEknKeT…`）。
- 关键 cwd 约束：`release-manifest`/产品命令必须在 `apps/agentshield` 目录下运行（`skillmanifest.FindModuleRoot` 自 cwd 向上找 agentshield 模块 go.mod）。

## 逐项结果

### LC01 安装预检（5 负例 + 1 正例）— PASS [real]
| 用例 | 输入 | 实际结果 | 退出码 |
|---|---|---|---|
| 签名损坏 | manifest-badsig.json | `skillmanifest: signature mismatch`，state 目录保持为空 | 1 |
| 错误平台/超大二进制 | x86_64 artifact / 超过 pin 尺寸 | `client-stage: ordinary bounded file required`（artifact pin 按 GOOS/GOARCH 选择，尺寸先于平台拒绝） | 1 |
| 未来 stateProfile | manifest-future.json（真实签名、state_profile=future-format-not-known-to-this-build） | `skillmanifest: signed client compatibility declaration missing or unsupported` | 1 |
| 缺 --confirm-install | 正常输入去掉确认 flag | 参数错误，未安装 | 1 |
| 全部负例后 | — | state 目录条目数为 0（无残留） | — |
| 正例 | manifest-v1 + v1 artifact + --confirm-install --runtime | 安装并启动用户服务，打印管理页 URL 与 pair 指引 | 0 |

### LC02 首次启动与配对 — PASS [real]
- `pair` 打印一次性配对码（5 分钟有效期；证据已脱敏，配对码未落盘）。
- `POST /v1/pair {code}` → 200，返回 `{expires_in, schema_version, scope, session}`；**token 即 session 字符串（64 字符）**，写入 state 目录 `.admin-token`（0600），证据中未打印。
- 无效码/重放码 → 401 `pairing code rejected`。
- 管理页 HTML（lc02-index.html，见 SHA256SUMS）不含任何凭据标记。
- 管理操作（service-stop/upgrade 等）均要求 Bearer token。

### LC03 路径与端口 — PASS（含一项如实失败）[real]
- 特殊字符路径实例：state dir `…/lc03/中文 目录%实例`（含中文、空格、%）安装/启动/服务注册全部成功，unit FragmentPath/ExecStart 正确引用，端口 25191。systemd 引号转义由渲染器保证（`%`→`%%`，控制字符拒绝）。
- 端口占用实例（lc03-occupied，端口 25191 被占）：**真实失败** — 服务反复启动失败，unit 进入 failed 状态，安装报错退出 1。该失败样本完整保留（lc03-occupied.out），未被删除或改记为通过。

### LC04 后台服务与重启 — PASS [real]
- unit 命名 `siq-agent-security-<instanceID[:32]>.service`（实例 ID 派生，与生产 `hermes-gateway-siq*` 无碰撞）；`Type=exec`、`Restart=no`、`UMask=0077`、`Environment=SIQ_AGENT_SECURITY_STATE_DIR=…`。
- `service-stop --confirm-stop` → 严格校验（inactive、MainPID 0、Result=success、无 lock 文件）后退出 0；`service-start` 恢复。
- 幂等：重复 service-start/service-stop 均退出 0。
- [obs] 管理会话不跨重启存活：服务重启后旧 admin token 401（重新 pair 即恢复）。这是观察记录，不影响 LC04 判定。
- [deferred] 授权撤销持久化（LC04 附属项）需要真实 admission 流量（admissions API 为 GET-only，由真实拦截生成）→ 推迟到 L2/L3 真实宿主阶段执行，有因推迟，非跳过。

### LC05 故障恢复 — PASS [real]
- 服务运行中 SIGKILL 主进程：systemd 记录失败，`service-start` 重新拉起成功，健康检查恢复；state 目录完整。
- 升级中断恢复：升级 commit 前 SIGKILL → `incomplete` 列表为空（无持久化未完成记录）；旧 staged 二进制拒绝启动（`configuration changed`）；新 staged 二进制经 `service-start` 接管成功。

### LC06 升级（真实不同版本）— PASS [real]
- v1（0.2.1-batch）→ v2（0.2.2-batch）：`service-upgrade` 停服、快照旧 CLI 到 `client-snapshots/<digest>/`、生成事务 ID（本批两次升级事务 ID 前缀 `bb0308a4…` / `ab764f4b…`）、切换 ExecStart 至新 digest 路径、健康检查通过。
- `service-rollback` 要求 `--binary` 为**精确历史源路径**（staged v1 路径）；传 release 目录 artifact 被拒：`binary path differs from historical source`。修正后回滚成功。
- 管理操作必须从**已安装 staged 二进制**运行：从 `bin/agentshield` 运行报 `state: service configuration changed; explicit migration required`。
- 未来 stateProfile 的 v2-future manifest 不参与升级（LC01 已拒于安装前）。

### LC07 未知对象保护 — PASS [real]（含边界澄清）
- unit 文件篡改：管理操作拒绝，报 `state: service configuration drift`。
- staged 程序被符号链接替换后，从任意外部真实副本运行管理操作：拒绝，退出 1（`checkServiceBinary`：`service-switch: binary content differs from recorded identity`）。
- [obs/边界] 将 staged 程序整体替换为无关程序（如 /bin/true）不在自保护边界内：此时无产品代码可执行拒绝；保护实质存在于 state 记录与信任链（证据如实记录，不计为通过项）。
- teardown 语义明示：钩子适配器**不**随 teardown 卸载，block 模式受控操作继续拒绝。

### LC08 保留数据退出 — PASS [real]
- 特殊路径实例（lc03）teardown：产品输出「当前实例后台入口已移除，服务已停止。程序、配置、身份与历史数据已保留；智能体钩子未卸载，block 模式受控操作将拒绝。」
- 验证：unit `siq-agent-security-06c30c85…` inactive；state 目录条目 45→44（保留）；端口 25191 关闭（health 000）。

### LC09 全量移除与重进 — PASS [real]（分接口卸载，不宣称一键彻底卸载）
- 分接口卸载面：`teardown`（服务层，保留数据）、`adapter uninstall`（钩子适配器独立接口）、数据目录移除（手动步骤，产品不代办）——产品**没有也不宣称**「一键彻底卸载」。
- 失败实例清理（lc03-occupied failed unit）：teardown 首次被拒 `service: normal stop not confirmed`（如实记录）；按产品指引检查后，对该批创建的身份确认 unit 执行定点 `systemctl --user stop` + `reset-failed`（Result=success、inactive）后 teardown 成功。无 pkill/killall/端口批量清理。
- 清理验证：unit 文件与 unit 记录均不存在；无关配置完好——lc01 unit 仍 active、`hermes-gateway-siq*` 7 个 unit 完好、生产 `~/.openclaw/agentshield.json` sha256 前后一致（`8df31525…`）。
- 重进：数据移除后同路径全新安装成功（新实例 `42bb762b…`，端口 25177，active）。
- [obs] `adapter status` 列出的是生产宿主适配器（~/.openclaw、~/.hermes、~/.codebuddy，均 installed）；本批**未**对生产适配器执行任何卸载。

## Opt-in 真实服务测试套件

1. `scripts/personal-experience/test_systemd_user_service.py`（`SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=<staged>`，`uv run --with pytest -- python -m pytest -v`）→ **1 passed**（1.64s），含 systemd 引号/空格路径实机演练。输出：`pytest-systemd.out`。
   - 注：首次误以 `python <file>` 直接运行（空输出 exit 0），已发现并修正为 `python -m pytest`。
2. Go `TestNativeUserServiceUpgrade` + `TestNativeUserServiceUpgradeTransientFailure`（`SIQ_TEST_UPGRADE_SYSTEMD=1 SIQ_TEST_BINARY=<test build>`）→ 首跑 FAIL `source not ready`：原因是传入了 release artifact（Version=0.2.1-batch），而该测试要求 trusted **test build**（health.Version 必须匹配测试构建）。用 `go build -o bin/agentshield-test ./cmd/agentshield` 构建后重跑 → **2 PASS**（真实 systemd 上完成旧→新二进制切换与瞬断恢复）。失败首跑输出在 `go-upgrade-tests.out` 中已被覆盖为通过轮；失败事实如实记录于此。
   - Skips 不计为实机通过；本轮两项均为真实执行（skipif 条件满足，未跳过）。

## 红线与边界遵守

- 未 reset --hard、未 git clean、未提交/推送/合并/发布。
- 未 pkill/killall/按端口批量杀进程；仅对批创建且身份确认（unit 名、FragmentPath、ExecStart→批 state 目录）的 unit 做定点 stop/reset-failed。
- 未启用 linger、未重启整机、未改生产 unit、未触碰生产 OpenClaw/Hermes/CodeBuddy 适配器与配置。
- seed/token/配对码/私人路径均已脱敏，未打印未落盘。
- 测试失败样本（端口占用、失败 unit、首跑 FAIL）全部保留并如实记录。

## 遗留与外部条件

- [deferred] 授权撤销持久化：解除条件 = L2/L3 真实 OpenClaw 宿主产生真实 admission 流量后验证。
- systemd 单元语义在真机注销/重登后的行为无法自动化：留给人工实机验收（本批未重启、未注销）。

## 创建/停止的进程、端口、unit 清单（L1 结束时点）

| 对象 | 状态 |
|---|---|
| unit `siq-agent-security-1c957b24…`（lc01 主生命周期实例，端口 25173） | active（保留供 L3 R07 使用） |
| unit `siq-agent-security-06c30c85…`（lc03 特殊路径实例，端口 25191） | 已 teardown，unit 不存在，数据保留 |
| unit `siq-agent-security-4602ee52be…`（lc03-occupied 失败实例） | 已 teardown，unit 不存在，数据已移除后重装 |
| unit `siq-agent-security-42bb762b…`（lc03-occupied 路径重进实例，端口 25177） | active（L4 清理清单项） |
| 端口 25191 | 已释放 |
| `/tmp/siq-batch-20260915/evil-bin/prog`、`realcopy`、`lc03-unit-backup` | 保留在批目录，L4 结束统一清理并列入最终清单 |
