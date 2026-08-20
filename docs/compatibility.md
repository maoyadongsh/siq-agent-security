# 兼容矩阵（Phase 0 基线）

> 设计文档 §15.1/§16 要求：固定版本、能力协商、不按版本号假设。D1 spike 完成后用实测数据替换本文"待探测"项。

## OpenShell 兼容矩阵（首个 Enforcement Adapter）

| 能力 | v0.0.83（SIQ 冻结） | v0.0.104（2026-08-13 实测） |
| --- | --- | --- |
| Gateway 控制面 / Sandbox 生命周期 | ✅ 已实现（research-engine） | ✅ 实测：sandbox list/create/delete 解码正常（Protobuf 解码缺陷已修复） |
| filesystem_policy 静态边界 | ✅ 编译期锁定，重建生效 | ✅ 静态段创建时锁定（部署闭环未触发重建） |
| Landlock | ✅ 带本地 patch（mask-file-access） | ✅ 上游已内置（ADR-009） |
| process / seccomp 静态边界 | ✅ | ✅ 静态边界（创建时锁定） |
| **network_policies 动态更新** | ✅ **实测支持**（2026-08-13：活沙箱 `policy set` 网络段 → version 2 提交成功并读回生效；静态段修改被拒绝）。SIQ 自研编译器的固定规则限制 ≠ 网关能力限制 | ✅ 实测：审批部署闭环 `effective`（真实 policy set + 读回验证） |
| Provider 凭据隔离 | ✅ credential placeholder + 网关注入 | ❓ 未实测（Providers v2 动态能力） |
| Gateway Interceptor | ❓ v0.0.83 上未使用/未验证 | ❓ 未实测 |
| revision / 有效策略回读 | ✅ | ✅ 实测：policy set version 递增 + `policy get --full` 读回验证 |

**MVP 影响（实测修正）**：动态网络策略发布**在 v0.0.83 上即可实现**（policy set + revision 读回）；§29.1 降级条款保留为风险预案。

### v0.0.104 解码缺陷验证（2026-08-13 实测，本机原生构建 + 隔离网关）

- 本机 cargo 原生构建 v0.0.104 三二进制（CLI 20MB / gateway 72MB / sandbox 22MB；gateway 需 `--features bundled-z3` + cmake）；
- 隔离网关（端口 17673、独立 XDG/DB/命名空间、自建 supervisor 镜像 alpine+二进制）实测：
  - `sandbox list` → 干净表格输出（NAME/CREATED/PHASE），**无 Protobuf 解码错误**；
  - `sandbox create` → 进度流完整解析（allocated → image → container → supervisor relay），**响应完全可解码**；
  - `sandbox delete` → 正常；
- **结论：v0.0.83 的 SandboxResponse Protobuf 解码缺陷在 v0.0.104 已修复**；升级后 CLI 后端的 docker 兜底路径可退役；
- 遗留：测试用沙箱容器因旧基础镜像+新 supervisor 组合不匹配而 restart（与解码无关），正式升级时需用 v0.0.104 配套 supervisor/基础镜像。
- **产品闭环实测（同日）**：官方 base 镜像 + 自建 supervisor 镜像 → 沙箱 `Ready`；产品 sync 拉取 52 条 effective 事实；审批部署闭环 `effective`（真实 policy set + 读回验证）——v0.0.104 作为产品执行后端完全可用。迁移 runbook 见 [openshell-v083-to-v0104-migration.md](openshell-v083-to-v0104-migration.md)。

## 本地 patch 清单（ADR-005）

| patch | 目标 | 上游状态 |
| --- | --- | --- |
| 0001-landlock-mask-file-access | OpenShell v0.0.83 | 待上游化评估 |
| 0002-siq-strict-bind-mount-contract | OpenShell v0.0.83 | 待上游化评估 |
| 0001-runtime-auth-file-override | Hermes 0.13.0 | 待上游化评估 |
| 0002-runtime-state-home-override | Hermes 0.13.0 | 待上游化评估 |
| 0003-api-run-stop-quiescence | Hermes 0.13.0 | 待上游化评估 |

## Hermes 现实边界（L1-L3 评级依据，ADR 结论同步自设计文档 v0.2 §16.3）

| 项 | 现实 | 评级影响 |
| --- | --- | --- |
| Profile | 数据目录（config.yaml/SOUL.md + 状态），无权限声明 | L1 发现合同按"profile 目录 + 全局 platform_toolsets + Hub sandbox 字段"三源合一设计 |
| Runs API | 内存态（60s TTL），无持久台账 | L2 可观测性按 Hub RunLedger 现状下调 |
| 审批门 | cooperative-mode 启发式，非安全边界 | 只作为 observed 证据 |
| 运行形态 | SIQ 生产中为 hub 容器内子进程 | Agent Instance 模型含 embedded 运行时 |

## OpenShell Enforcement Adapter 合同状态（Phase 3 前置，2026-08-13）

- 合同类型与十方法（§15.3）：`apps/control-api/app/adapters/openshell/`（contracts/base/policy_compiler/fake_backend/client）
- FakeBackend 契约测试 9 项：能力探测/revision 冲突/静态 generation/正负验证/回滚/unsupported 显式标记
- 真实 client fail-closed 占位：D1（版本路径）+ D2（SIQ 基座部署）后接入
- 部署流已接线：`SIQ_AS_ENFORCEMENT_BACKEND=fake` 时编译制品入任务 payload，未知语义 422 拒绝

## Connector 兼容

> 下表为 2026-08-20 实测状态（`go vet ./...` + `go test ./...` 全量跑过一遍，11 个已交付
> Connector 模块全绿；`connectors/siq` 尚未开工，不计入本表）。发现层级：应用级（读取该
> 框架自己的配置文件/目录布局）vs 运行级（通过操作系统/容器运行时枚举正在跑的进程/容器/
> pod/service unit）。

| Connector | 发现层级 | 状态 | 负向测试要点 |
| --- | --- | --- | --- |
| hermes（Go） | 应用级 | 已实现（build/vet/test 全绿） | scope 校验/符号链接逃逸/.env 拒绝/截断 |
| openclaw（Go） | 应用级 | 已实现（L1/L2 只读，build/vet/test 全绿） | 发现 agents.list + declared model/workspace 权限事实；auth-profiles 永不读（只记大小）；不写 OpenClaw 配置 |
| directory（Go） | 应用级 | 已实现（build/vet/test 全绿） | 空范围拒绝（无默认范围）/符号链接逃逸/.env 永不读取/限额截断 |
| dify（Go） | 应用级（docker-compose 清单） | 已实现（build/vet/test 全绿） | 空 scope 拒绝；符号链接逃逸跳过；compose 文件仅 dify 相关行参与 content_hash，其余（尤其 environment 段密钥）绝不出内容；字节预算截断显式化 |
| piagent（Go） | 应用级（~/.piagent 目录） | 已实现（build/vet/test 全绿） | agents.json 只解码 id/name/model/workspace 白名单字段，apiKey/token 类字段不进结构体；.env/secrets/keys 目录只记 name+size 不读正文；符号链接逃逸跳过；字节预算耗尽即报错，不回退默认大小 |
| workbuddy（Go） | 应用级（~/.workbuddy 目录） | 已实现（build/vet/test 全绿） | buddies.json 白名单字段解码（同 docker 的无 Env struct 思路）；config.yaml 永不读正文（只探测存在性）；符号链接逃逸跳过；字节预算/文件数上限截断显式化 |
| mcp（Go） | 应用级（各 MCP 客户端众所周知配置） | 已实现（build/vet/test 全绿） | server 的 env 值绝不采集（只留 env_keys）；command/args 中与 env 值逐字相同的串替换为 `[REDACTED]`（防 `--token <值>` 夹带）；url 只保留 scheme://host；畸形 JSON 显式报错而非静默漏报 |
| docker（Go） | 运行级（容器） | 已实现（build/vet/test 全绿） | 容器环境变量值不出机（inspect 解码 struct 无 Env 字段）；`siq.agent=true` 标签仅为高置信提示/纳管标记，无标签的影子智能体容器仍按镜像/命令启发式信号纳入候选 |
| process（Go） | 运行级（主机进程） | 已实现（build/vet/test 全绿） | args 可能夹带 token：attributes 只保留 comm + 关键词 + args sha256 截断摘要，完整 args 绝不出进程；PID 不作为候选身份（用 comm+args 哈希）；`ps` 缺失/超预算均显式报错而非静默漏报 |
| systemd（Go） | 运行级（service unit） | 已实现（build/vet/test 全绿） | unit 名称关键词初筛 + ExecStart 可执行路径再确认（避免改名规避初筛的结构性漏报）；ExecStart 完整命令行脱敏截断后才入 attributes；`systemctl` 缺失/超时显式报错 |
| kubernetes（Go） | 运行级（集群 pod） | 已实现（build/vet/test 全绿；2026-08 修复 `NetworkAccess` 声明与超字节预算整批失败问题） | 容器 env 值不出机（解码 struct 无 env value 字段）；`siq.agent=true` 标签同样仅为提示而非前置条件；超字节预算走流式 JSON 解码优雅截断（`batch.Truncated`），不再整批失败 |
| siq | — | 待 Phase 1（依赖跨仓 Export Contract D3-D5） | — |

**已知遗留（诚实边界）**：
- `threat-obf-base64-blob` 等基于 240+ 字符连续 base64 的启发式规则，理论上可被跨行拆分绕过——静态规则的固有局限，非本轮范围。
- Connector 侧发现结果的最终风险研判仍由控制面 `app/threat_analysis.py` 静态规则引擎完成；Connector 自身只做证据采集与脱敏，不做风险判定。

## 版本兼容 CI（P2）

- `scripts/openshell_compat_matrix.json`：机器可读兼容矩阵，逐版本记录 `probe()`/读回可探测能力的期望值（`dynamic_network_update`、`static_filesystem`、`static_process`、`landlock`、`interceptor`、`provider_credential_injection`、`revision_support`、`sandbox_list_decodable`），取值来源为本文上文 2026-08-13 实测结论。
- `scripts/openshell_compat_check.py`：在 `apps/control-api` 下经 `uv run python ../../scripts/openshell_compat_check.py` 运行；按 `cli_backend` 相同环境变量约定（`SIQ_AS_OPENSHELL_CLI_BIN` + `SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT`，或 `SIQ_AS_OPENSHELL_ENV_SH`）连接真实网关，`OpenShellCliBackend().probe()` 取真实版本与能力后与矩阵比对，不一致项非零退出并逐项打印差异；未配置网关时打印 "SKIP: 未配置网关" 以 0 退出。`--live --sandbox <name>` 追加真实 policy set → 读回验证 → 回滚闭环 fixture。
- `.github/workflows/openshell-compat.yml`：每周一定时 + `workflow_dispatch`（可注入 gateway_endpoint / cli_bin / cli_bin_asset / live_sandbox）。真实网关需 self-hosted runner 或预置环境；未配置 secret 时检查步骤自动跳过，不会产生红色失败。
