# local-o05-b3 批次最终报告（20260916-181347）

- 工作树：`/home/maoyd/siq/worktrees/siq-release-openshell-20260916-142706`（review 修复批之后，source-files.json 1137/1137 digest 零漂移）
- 候选：rc.3 linux-arm64 冻结二进制，SHA256 `4866f307cf0328caa6c9f127d0a56f8034ead6bbc511b95fae042da223e0bd5c`（与 builds-rc3.json 一致）
- 提示词：`docs/glm-local-o05-b3-next-execution-prompt-20260916-175248.md`
- 验收基线：`personal-acceptance-baseline/v2`，**N09 矩阵未改动**（本批无门槛调整）
- **本轮不提交、推送、合并、签名或发布**；提交拆分建议见文末，供维护者审阅。

## 1. L00–L07 状态总表

| 项 | 状态 | 一句话结论 |
|---|---|---|
| L00 基线保护与差距映射 | ✅（映射完成） | 零漂移基线确认；生产调用链七环节定性表落盘（决策面完整、OpenShell 面未连接） |
| L01 阻断问题定位 | ✅ | 受控实测定位根因：旧 O05 失败非策略编译缺陷，而是靶标在策略边界外（loopback 不经 egress 代理）；修正后 opt-in live 测试实跑通过 |
| L02 O05 会话执行最小闭环 | 🔶 | HTTP 合同级完成（实现 + 10 项负向测试全绿）；原生宿主真实执行未覆盖，不记 O05/B3 完成 |
| L03 候选产品旅程 | ✅ | 真二进制 + 真实 HTTP/CLI 入口 57/57 断言通过（`l03-journey.json`） |
| L04 冻结协议性能复测 | ✅ | 独占测量，全部预算阈值通过，总体比率 0.9967（对比 rc.2） |
| L05 Linux 剩余验收 | ✅* | B03 服务级补充完成（真实 daemon 四腿全过）；B04 原生采集腿、B05 均为外部阻塞 |
| L06 条件性真实源安装（B06） | ⛔ | 只读预检完成：本机 DNS 处于 fake-IP 段（198.18.0.0/15），Go 抓取路径按设计 fail-closed 拒绝；解锁条件为真实 DNS 环境，本批不放宽 SSRF 边界 |
| L07 文档/任务簿/矩阵回写 | ✅ | 进度文档回写 + 本批证据四件套（report/baseline/checks/resources）落盘 |

## 2. 诚实能力标级（不混称）

- **HTTP 单测 / 模拟 runner 级**：L02 全部实现与测试（httptest + 注入 `openshell.Options.Runner` 的有状态假网关，含 CAS 版本/摘要回读语义）；L05 B03 服务级为**真实独立 rc.3 daemon + 真实 HTTP 入口 + 真实管理员配对**（非 httptest）。
- **实机级**：L03 旅程、L04 性能、L05 up07/up05 各腿（linux-arm64 真二进制）。
- **未覆盖**：原生宿主真实采集与执行（B04 原生腿）、真实 OpenShell 网关联测（共享网关本批只读，未写 canary）、UI 入口、amd64 实跑（本机 aarch64，仅 linux-arm64 产物可执行）。

## 3. 关键发现

### 3.1 exec→hold 机制（O05）
会话执行经既有 hold 链授权：进程事实（hold 预留）通过 `ocReq["exec"]` 绑定到执行请求，`ReserveHoldExecution` 消费预留；未知/已消费预留 fail-closed 拒绝，不自动重放。详见进度文档 L02 ②⑤。

### 3.2 状态兼容边界三层语义（B03 实测，行为事实非缺陷）
`apps/agentshield/internal/state/compatibility.go` `checkUnmarkedState`：
1. 完整核心骨架无 marker → 设计上接受为 legacy（marker 不回写）；
2. 骨架不完整但 config.json 可解码（或 `keys/signing.seed` 为合法 32 字节种子）→ 仍接受为 legacy；
3. 仅"非空且不可识别"（无 marker 且无可读 config.json）→ `ErrMissingMarker` 拒绝。

`EnforceStateCompatibility` 不变更不迁移；`publishInitialStateFormat` 仅在 init 写 marker。实测另见两条行为事实：rc.3 `init` 不写 signing.seed（首次 serve 才生成）；legacy 接受的 serve 会**静默重建缺失的 `keys/signing.seed`**（新身份）。若维护者认为 (2)+(种子重建) 过宽，可作为后续收紧项——本批未改动。

### 3.3 L01 根因 + 执行平面传播滞后
- 根因：旧 O05 失败靶标在 loopback，策略边界外，与 agentshield 编译无关；跨边界默认拒绝（403）正常，allow 规则可放行。
- 新发现：gateway readback 确认新规则后，沙箱 egress 执行平面滞后 ~2–4s 才生效；enforcement_verified 级测试需 bounded settle 窗口（`o05_enforcement_live_test.go` 已内置）。

## 4. 外部阻塞

| 事项 | 状态 | 依据 |
|---|---|---|
| B05 r4 | ⛔ 外部阻塞 | openclaw 被外部降级 2026.5.12→2026.3.11，零回执；smoke.py:263 失败与 rc.2 完全一致，非本批回归（`b05-r4-blocked.md`）。通知视觉无可见桌面 → external_manual |
| B04 原生采集腿 | ⛔ | 需真实宿主原生采集环境，本机不具备；HTTP 写入合成记录不冒充原生采集 |
| B06 生产来源安装 | ⛔ | DNS fake-IP 段触发 `download.go` excludedIPv4 fail-closed（设计行为，无开关） |
| 共享网关 siq-openshell-dev | 只读预检时在线，批末 sandbox 删除时 transport refused | 沙箱 `siq-l01-o05-181930` 清单于 resources.json pending_manual；重启共享网关被禁止 |
| 生命周期 R06/R04/R07 | 无需重跑 | 本批改动（3 端点 + `RollbackAuthorized`）不触及安装生命周期状态机；`up05-*` 腿已按新候选实跑覆盖更新/移除/恢复合同 |

## 5. 验证门

- `gofmt -l` 零输出；`go vet ./...` 干净；`go test ./...` 40/40 包 ok（exit 0）；`-race`（openshell + server + receipt）ok。逐项见 `checks.json`。
- 私材料（配对码、凭据、serve 日志）仅存 `*-private/`，未写入任何公开证据或仓库文件。

## 6. 资源清单

见 `resources.json`：批内创建的接收端/临时目录/孤儿 daemon 均已清理；两项 pending manual——沙箱 `siq-l01-o05-181930`（网关拒绝连接，删除未执行）与 PID 276252（归属未确证，kill 被分类器拒绝，不重试）。

## 7. 给 sunbo/Luke 的重测清单（涉及本批改动的公共 API）

1. 新增 3 端点（`POST /v1/openshell/session-executions`、`/preview`、`/rollback`）：Windows/macOS 实机各跑 10 项负向 + happy path（合同表可从 `internal/server/openshell_session_exec_test.go` 直译）。
2. `openshell.Options.Runner` 注入点与 `policy.RollbackAuthorized`：确认与 Luke 的 runner 实现兼容（签名未变，仅新增授权函数）。
3. `Server` 结构新增字段：跨平台构建无标签冲突即可，无需行为重测。
4. B03 `up05-*` 并发合同在 amd64 实机复跑 `closure-b03-service-concurrency.py --binary <amd64 产物>`。

## 8. 提交拆分建议（供维护者审阅，本批未执行任何 git 操作）

1. `feat(agentshield): O05 session-execution closed loop` — `internal/server/openshell_session_exec.go` + `_test.go` + `server.go` 路由注册。
2. `feat(agentshield): fail-closed rollback authorization` — `internal/openshell/policy.go` `RollbackAuthorized` 及其测试。
3. `test(agentshield): O05 enforcement live test (opt-in)` — `internal/openshell/o05_enforcement_live_test.go`。
4. `chore(scripts): B03 service-level concurrency driver` — `scripts/personal-experience/closure-b03-service-concurrency.py`。
5. `docs: local-o05-b3 batch evidence + progress` — `docs/local-o05-b3-progress-…md` + `docs/evidence/personal-experience/local-o05-b3-20260916-181347/`（**建议排除** `*-private/` 与含配对码的 serve 日志，按保密策略由维护者裁决）。
