# apps/agentshield 工作约定

siq-agent-security 本地二进制（Go；模块路径仍为 `apps/agentshield`）。上层约束见仓库根 `AGENTS.md`；本文只写本模块的就近规则。实现规格是 `docs/agentshield-dev-spec-v1.md`——**先读它，再改代码；规格与代码冲突时先改规格。** W7 本地台账计划见 `docs/agentshield-local-ledger-dev-plan-v1.md`（新 API / 状态文件须先回写规格）。

## 模块与职责

| 包 | 职责 | 状态 |
| --- | --- | --- |
| `internal/canon` | 与 CPython `json.dumps(sort_keys=True, separators=(",",":"))` 逐字节一致的规范化 JSON | 完成 |
| `internal/rulepack` | 内嵌规则包、外部包 Ed25519 验签、防降级、fail-closed 回退 | 完成 |
| `internal/threat` | 静态分析器（Python `threat_analysis.py` 移植，AST 层缺席） | 完成 |
| `internal/signing` | 本地 Ed25519 身份、文档/字节签名与验签 | 完成 |
| `internal/inventory` | 只读盘点：平台配置、Skill、Hermes profiles、OpenClaw agents.list、MCP 客户端配置（`mcp_server`）；可选 `--connectors-dir` **exec** 子进程（不 import `connectors/*`） | 规格 §3.5 |
| `internal/export` | 脱敏导出包 `agentshield.export.v1`（无私钥/token/参数原文） | 规格 §3.8.1.3 |
| `internal/controlsync` | `sync --control-api` → Edge `POST /edge/v1/batches`；缺凭据跳过；失败不改本地决策 | 规格 §2.4 |
| `internal/admission` | frontmatter、哈希、限额、决策表、Skill Card | 完成（决策表变更需同步规格 §3.6.4 与 `dispositions.go`）|
| `internal/grant` | declared → allowlist / DesiredPolicy；状态机；`PatchDesired`；读回 effective | 完成（`CompilePolicy` 与 Python `artifact_hash` 对等）|
| `internal/receipt` | 决策引擎、污点/trifecta、哈希链、Verify；block 下无 host 的出网 exec deny；hold 审批后签名预留与不确定恢复 | N06/R02 组件批次 |
| `internal/state` | 状态目录、token、admission/grant/policy/assets/findings/audit 文件态存储 | 完成 |
| `internal/ledger` | 台账投影 + 资产生命周期 refresh（G7）；confirm/dismiss/drift/accept | 完成 |
| `internal/server` | `/v1/*` HTTP（loopback + Host 允许列表 + 决策/管理分权 + 配对）+ 无 secret 的 `/ui-config.json` + embed UI | DEV02-A |
| `internal/adapterinstall` | `adapter install/uninstall/status`：写主机钩子，先备份可还原 | 完成 |
| `internal/openshell` | probe / 网络 `policy set` / 读回；不调 `create_generation` | 完成 |
| `internal/ui` | embed `apps/web` 本地模式构建产物（`npm run build:local`） | 完成 |
| `cmd/agentshield` | 子命令入口（含 `admit`/`grant`/`adapter`/`openshell`/`serve`/`export`/`sync`/`release-manifest`/`manifest-verify`） | 完成 |
| `internal/skillmanifest` | 发布清单构建、Ed25519 验签、诚实 support_matrix | 完成 |
| `internal/skillcontext` | Skill 执行上下文（SEC，`skill-execution-context/v1`）签发/验证/撤销；verified 归属唯一路径；决策时全量重验实例、会话 binding、grant digest、安装与目标内容 | N05/R01 组件批次 |

## 硬性规则

1. **仅标准库。** 需要第三方依赖（如 tree-sitter）先立 ADR。交叉编译 `linux/{amd64,arm64}`、`darwin/arm64`、`windows/amd64` 必须始终通过；不得引入 `fcntl`/`syscall` 平台专属调用，文件/锁独占用 `O_EXCL`。不可变版本允许按 ADR-012 用标准库 `os.Link` 将已写完的同目录暂存文件排他发布；文件系统不支持时显式失败，不回退覆盖或暴露半写文件。
2. **规则包是共享文件。** `internal/rulepack/data/threat_rules.v1.json` 必须与 `apps/control-api/app/data/threat_rules.v1.json` 逐字节一致（`TestEmbeddedPackMatchesControlPlaneCopy` 锁定）。改模式：RE2 可编译、CPython 语义等价、附边界用例、两侧测试都跑。
3. **对等优先于"更好"。** `threat` 的输出（sha256 / rule_id / line / excerpt_sha256 / excerpt）必须与 Python 相同；想改行为先在 Python 侧改并同步语料，再移植。
4. **签名只签规范化字节。** 所有文档签名 = `Ed25519(canon.Marshal(doc 去掉 signature))`，十六进制 128 位；回执链签 `hash` 字符串字节。任何新文档类型都走 `signing`，不得自建序列化。
5. **状态目录之外不写。** 路径由 `state` 包解析（`SIQ_AGENT_SECURITY_STATE_DIR` 覆盖，兼容旧名 `AGENTSHIELD_STATE_DIR`）；目录 0700、文件 0600；只追加或新建，禁止原地改写准入/签发/回执文件。 本用户个人体验开发周期按 ADR-039/ADR-044/ADR-047 增加限定例外：经明确确认并复验的安装、移除或更新操作可写对应 Skill 目标及同 profile 私有操作目录，采用排他发布、权限失效与归属校验恢复；不得执行候选内容或覆盖/删除未知用户对象。
6. **不执行被分析内容。** 不 `import` Skill、不解压嵌套压缩包、不跟随符号链接；git 来源用 `--depth 1` 并禁用 hooks。可选 `--connectors-dir` 仅 **exec** connector 二进制（规格 §3.5），禁止 import `connectors/*`。
7. **模型不是权威。** 任何未来的 LLM 语义层只能产生 `inferred` 事实或 `info` finding，不能改 verdict / action / status。
8. **fail-closed 表是合同。** `block` 模式下服务不可达、超时、401、非法响应 = 拒绝；普通 policy 的 `audit_only`/`warn` 保留 allow + `advisory_action`。按当前用户开发目标（ADR-0015），无效 Authority 在所有模式下 hard deny，不得被 advisory 放宽。每个适配器必须有对应负向测试。
9. **日志只记类别。** 拒绝原因、异常消息不得包含规则内容、参数、文件内容或密钥。
10. **批准不等于执行。** hold 通过后必须先追加唯一 `hold_reservation` 才能允许外部工具；重复/并发预留拒绝。已预留且无 observation 时只能报告 `uncertain`，不得因超时或权限撤销掩盖可能发生的副作用。管理员人工结案只追加 `hold_reconciliation`，不能再执行旧预留或宣称 exactly-once。

## 测试要求

Windows 资源事实按 `docs/windows-resource-profile-spec-v1.md` 的限定例外，允许 `internal/runtimepath/*_windows.go` 使用标准库 syscall/unsafe 只读查询盘符映射、文件/目录句柄、卷和目录大小写属性；不更改资源、盘符或 ACL，不提权，不把路径事实本身当作 Authority。测试可在临时目录内建立并清理 junction，不修改用户对象。

Windows 私密状态按 dev-spec §2 的限定例外，允许 `internal/privatefs/*_windows.go` 使用标准库 `syscall`/`unsafe` 查询文件句柄安全描述符、构造受限 DACL 并在新对象创建时传入。禁止改已有对象 ACL、提权、调用外部权限工具或让其他平台直接引用 Windows API；保留兼容屏障和仅标准库约束。

ACL 负向测试允许仅由 `_test.go` 引用的 `internal/acltest` 辅助包使用同类标准库 API 修改本次测试临时根内的合成对象 DACL，并在结束时还原测试夹具；不得用于产品代码或真实用户对象。

Windows Writer 恢复按 dev-spec §2.3 的限定例外，允许在 `_windows.go` 中使用标准库 `syscall`/`unsafe` 调用进程只读查询和文件句柄重命名 API；独占创建仍用 `O_EXCL`，不引入第三方依赖、进程终止、提权或新的平台服务。跨平台文件不得直接引用这些 API，其他平台构建保持通过。

N01 Windows 迁移暂存清理按 `docs/n01-state-protocol-design-20260913.md` 的限定例外，允许同样通过标准库 Win32 句柄删除本次创建且身份复验一致的暂存链接；禁止通过清除只读位删除硬链接，禁止清理未知对象。

N01 Windows 私密单链接发布同样允许在普通文件、DACL、创建身份和目标父目录验证后，通过现有 FileRenameInfo 不覆盖地原子移动本次暂存文件；不允许覆盖目标、清除只读属性或退回暴露双链接窗口的发布方式。其他平台保持 ADR-012 原有排他发布。

同一限定例外允许 privatefs.PublishNew 共用不覆盖的 FileRenameInfo 发布原语，供 N01 迁移、适配器内部私密恢复材料、Skill 安装/更新内部私密元数据及 Intent 内部授权/绑定/撤销/上下文记录使用；statefs 调用必须先执行兼容屏障，不改变宿主配置文件的授权写入语义。

```bash
gofmt -l . && go vet ./... && go test ./...
for t in linux/amd64 linux/arm64 darwin/arm64 windows/amd64; do GOOS=${t%/*} GOARCH=${t#*/} go build ./cmd/agentshield || exit 1; done
```

- 每个内置检查、每条决策表行、每个 fail-closed 场景：**一正一负**。
- 边界值：限额恰好等于上限通过，+1 拒绝。
- 与 Python 对等的部分用**共用语料/固定向量**（`../control-api/app/tests/fixtures/threat/corpus.json`、CPython 生成的 canon/signing 向量），不得各写各的样例。
- 输出样例写入 `testdata/contracts/*.json` 并由 `apps/control-api/app/tests/test_schema_contracts.py` 用 schema 校验；Go 测试断言运行时输出与样例一致。
- 不写变更探测器：不要断言规则条数、版本号字面量等预期会变的数据；断言关系（如「每条规则至少一个语料命中」）。

## 提交

`agentshield: <主题>`；规则包改动用 `rulepack:`；涉及合同同时改 `packages/contracts/` 并用 `contracts:` 单独提交。安全修复必须带证明旧行为被拒绝的负向测试。


## Linux 用户服务注册增量（2026-09-12）

按当前个人客户端生命周期开发授权及规格 §3.11.6，`service-register` 可通过 `systemctl --user link` 写入当前用户的服务搜索路径链接；签名配置仍仅写状态目录。限定实例专属名称、归属读回、无 force/sudo、无隐式自启，不得修改未知单位/覆盖配置。测试只注册隔离状态实例的 runtime 链接并复验后清理；不能修改用户生产服务。

M44 按规格 §3.11.8 增加服务注销：仅在已停止、双 Writer 与签名/manager 归属复验后删除实际加载的同名用户服务符号链接；不得广泛 disable 或删除源配置、密钥与历史。此为用户已授权生命周期开发的受限系统链接写入例外。

M54 按规格 §3.11.16 增加明确 --restore-missing-binary 的受限恢复：仅恢复签名原 source unit 指向的缺失程序，快照须同时匹配历史摘要与发行清单。允许原路径同目录临时文件及排他发布，不覆盖已有对象或创建外部目录。

M59 按规格 §3.11.21 允许经签名/manager 归属复验后，创建或移除当前注册目录 default.target.wants 下的精确实例链接；不广泛 enable/disable、不改其他依赖。隔离实测仍仅 runtime 注册范围。

M63 按规格 §3.11.25 允许 macOS launch-agent-register 向当前用户 Library/LaunchAgents 发布实例专属的精确签名源链接；只创建缺失目录/链接，不覆盖未知对象，不加载或启动任务。无 macOS 时仅在隔离临时 home 测试文件层，不修改真实系统目录。

M66 按规格 §3.11.28 允许明确 launch-agent-load --confirm-load 后在当前 GUI 用户域 bootstrap 已签名且精确注册的单个实例。当前域/同标签状态与源链接必须复验，未知配置拒绝；不 enable/kickstart/bootout，不操作其他任务。无 macOS 时只测试临时目录和模拟控制器，不执行真实系统加载。

M67 按规格 §3.11.29 允许 launch-agent-start --confirm-start 经归属复验后 kickstart 当前 GUI 实例，不带强制重启参数；释放主 Writer 后启动，健康失败保留现场。仅模拟控制器验证，不宣称 macOS 原生通过。

M68 按规格 §3.11.30 允许 launch-agent-stop --confirm-stop 在当前 GUI 域和完整归属复验后 stop 精确实例，读回退出状态并确认 Writer 可用；不 bootout/disable/删配置，不对 PID 直接发信号。无 macOS 实机时仅测试模拟控制器。

M69 按规格 §3.11.31 允许明确 launch-agent-unregister 后，持双锁复验已停止实例并 bootout 精确 GUI 任务；完整枚举确认缺席后仅删除精确归属注册链接并同步目录。未知文件/其他任务不得删除，源配置、密钥、历史保留；无 macOS 时仅模拟验证。

M78 按规格 §3.11.40 允许 `task-register --confirm-register` 在当前用户本机 Task Scheduler 根目录，以 TASK_CREATE 排他创建签名绑定的单个实例任务；双锁与完整归属复验，不覆盖、不启动、不自动清理失败现场。无 Windows 时只测试模拟控制器，不操作真实系统任务。

M79 按规格 §3.11.41 允许 `task-start --confirm-start` 在生命周期锁、完整签名/系统配置核对后按需 Run 当前用户已注册实例；主 Writer 检查后先释放再启动，不传动作参数，不强制重启、改配置或自动删除。无 Windows 宿主只测试模拟控制器。

M88 按规格 §3.11.50 允许明确 task-unregister --confirm-unregister 在双 Writer、签名/完整配置与空闲状态复验后，删除当前用户精确实例任务并读回缺席；保留本地源配置、密钥和历史。无 Windows 宿主只测试模拟控制器，不执行真实系统删除。


按 docs/windows-task-upgrade-spec-v1.md 的 Windows 升级增量，明确确认后允许在主 Writer 与 service-control Writer 保护下，以签名事务复验并替换本实例的任务 XML/windows-task.json；只删除与记录精确匹配且空闲的当前用户系统任务，并以 TASK_CREATE 排他注册同名目标。未知对象不覆盖，业务授权和撤销历史不回放。故障只保留可恢复事务，不重启/注销 Windows、不更改信任根或系统防护。
