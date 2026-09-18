# v6 集成来源与阶段验收记录

- 主线基线：`9b8c09af742cb9df94c6d02e6f2db6ecccd68951`（`origin/main` 与本地相同）。
- 集成树：`codex/personal-v6-integration-20260917`，从上述基线建立。
- GLM 来源：`glm/local-o05-v6-20260917`，HEAD `ff310716cc4c7e045456e3f44357f2c48baf3589` 加未提交增量；原工作树未 reset、stash 或清理。
- 私有快照：本机 `/tmp/siq-v6-f00-20260917-152015/`，目录 0700，文件 0600；公开摘要见 [source-summary.json](source-summary.json)。快照前后同范围 SHA256 一致。私有快照不作为可发布制品。

## 迁移决策

| 范围 | 决策与理由 |
| --- | --- |
| `internal/openshell/client.go`、`command.go`、`internal/server/authz.go`、`server.go`、`internal/state/state.go` | 逐项移入 v6 执行入口所需的跟踪修改；保留 main 已有的策略恢复预检、授权与身份保护。 |
| v6 新增 Go 源码和测试、合同、Web 源码及测试、Python 合同测试、验收脚本 | 从私有快照按路径采纳 31 个原未跟踪文件，清单与原 SHA 见 `source-summary.json`。后续集成修复相对原 SHA 可审。 |
| `.gitignore` | main 已有 `*-private/` 忽略规则，不覆盖。 |
| `docs/agentshield-dev-spec-v1.md` | 保留 main 的 PR #70 基线恢复条款，只追加 v6 接续约束；不采用旧整块补丁。 |
| `apps/agentshield/internal/ui/embedded/` | 不拷贝 GLM 快照里的旧散列文件；在集成树通过 `npm ci`、`npm run build:local` 从已审阅源码重新生成。 |
| GLM 原工作树中未采纳的 97 个未跟踪文件 | 主要为旧批次公开证据和旧 embed 资产。原件保存在原工作树及快照，不直接移作当前候选验收。具体排除不等于判其无效；同候选复测后再单独审阅证据。 |

## 本轮修复与结果

1. 执行器新增进程内加载确认：仅同一调用配置指纹/target 的 `policy set --wait` 成功且读回匹配后记住修订、摘要和 `Loaded` 时间标记；策略写入前清除旧确认。进程重启、写入结果不确定、no-op 策略调用、只读配置匹配均不产生确认；标记缺失或变化也拒绝执行。调用配置指纹和加载时间标记都不是唯一远端网关实例身份；该剩余风险要由真实网关身份/加载协议复测解决。
2. 提交路由在消耗一次性 hold 前检查加载确认及读回的 allow 网络端点是否均在本次批准的 `network_targets` 内；执行器在目标锁内、spawn 前再次检查，并在后端 I/O 后重验授权。策略漂移、确认缺失或范围扩大时零任务启动、批准保留。并发外部写入的原子性不由进程锁保证；现有任务合同未单列网络 binary 限制。
3. 停止文案区分 SIQ 当前的本地 CLI 终止与未验证的远端单任务停止能力，避免把 `remote_stop=unsupported` 当成上游网关能力读回。界面对非零退出、超时、截断和本地停止继续显示对账指引；非零码不标作已确认的远端退出码。
4. F02 追加并发修复：相同非空执行键若已在本进程注册，第二次发起在 spawn 前拒绝，并将整条预留保守记为未知，不会让不可停止的第二条执行继续；停止在持有同一句柄锁期间先审计与持久化，再发出本地取消，失败不取消。组件与 race 回归见 `task_exec_test.go`，CLI 能力边界见 [只读复核](f02-stop-capability.md)。这不构成远端停止确认。
5. F02 持久状态补上密码学绑定：计划、发起、结果、停止证据均以 daemon 密钥签名，读时验证文档、种类与预留 ID；成功投影额外要求链上的签名 observation 与完整结果文档摘要匹配。可编辑 JSON 伪造成功、缺签名计划/发起/停止均被 503 拒绝，不重放。旧试验性无签名证据不自动升级，需保留并人工核查。新增测试见 `openshell_task_track_test.go`。

验证范围：`go vet ./...`、`go test ./...`、`go test -race ./internal/openshell ./internal/server`、Python schema 合同测试、完整 Python 测试、Web 测试与两种构建、四目标交叉构建均通过；停止竞态修复后重跑了 Go 全量、race、Python schema 合同测试和四目标构建。以上为组件与构建级验证，未声称本轮真实网关、浏览器或跨 OS 实机通过。各命令和当前构建摘要以 `checks.json` 为准。

## 剩余门槛

- F01 的真实网关身份、加载/执行次序仍需同候选专属目标复测；配置指纹及加载时间标记不能独立证明网关实例未切换。当前进程内确认重启后失效，需安全的只读重新确认协议才能改善恢复体验。在此之前 F01 仅为组件级阶段成果。
- F02 的远端单任务状态查询/停止能力尚未按实际后端协议验证。当前只能报告本地终止与远端结果未知。
- F03 仅有 Web 单测和构建，真实浏览器旅程待 F04。
- F04–F09 中 Linux 原生、企业服务、托管源、WorkBuddy 与 Windows/macOS 实机门槛各自独立，不从组件测试或旧候选证据推断通过。
