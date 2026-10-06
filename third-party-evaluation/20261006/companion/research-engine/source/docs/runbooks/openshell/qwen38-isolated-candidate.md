# Qwen3.8 隔离本地模型候选审计与迁移

适用范围：DGX Spark 上的 `Qwen3.8-27B-NVFP4` + DFlash2 SGLang 8005 服务，作为 Hermes 0.21/OpenShell `siq_analysis` 的**独立备选候选**。本手册不改变已锁定的 Nemotron 8006 机密候选，也不改变当前 `siq_analysis` 活动 binding。

## 2026-10-06：请求输出目录与权限测评

Qwen逐请求运行的可写目录为`${SIQ_PROJECT_ROOT}/data/wiki/companies/<company>/analysis/runs/<run_id>/`（其他市场使用对应公司根目录）。公司级`analysis/`根目录和旧请求目录仍只读。SIQ允许某次工具调用，不意味着OpenShell会允许写入这些只读路径；报告应分别记录工具裁决与实际文件效果。

`hermes_client.create_run`现从已校验的请求route/plan中派生当前输出目录，附加到传给Hermes的instructions，并保留原业务说明。不使用用户文本提供的目录替代受信路径，不因此授予工具权限或改变挂载策略。伪造`pool_write_relative_path`在HTTP发送前被拒绝。默认运行服务不会因源码编辑自动切换；验收以专属API新进程为准。

测评入口为`scripts/openshell/prove_research_business_permissions.py`与`prove_research_agent_permissions.py`。配对固定Agent、公司输入及输出文件名，每次请求使用自己的run目录；不能把不同物理目录写成同一文件对照。运行租约数据库行可能被后续请求复用，测评关联使用`pool_binding_run_id`。运行前必须冻结二进制、镜像、插件及relay身份；隔离授权端点47811要求支持v4协议的relay，不应直接假定日常relay兼容。

本次53项聚焦回归通过：`PYTHONPATH=apps/api:. apps/api/.venv/bin/python -m pytest apps/api/tests/test_qwen38_request_http.py apps/api/tests/test_hermes_client.py -q`。真实模型复测、修复前失败及权限结论统一存放于安全项目的`third-party-evaluation/20261006/`；这些测试不改变下列历史批次的发布判断。

Skill 接入增量：`agentshield_runtime_binding`接受 SIQ 公开安装流程产生的完整 `grt-si-<64 hex>` 标识，继续校验运行身份、凭据、scope、relay及私有文件边界；畸形安装 Grant 标识仍拒绝。这是已有授权标识的格式兼容，不是把声明变成有效权限。

`research_permission_skills.py`执行两个合成 Skill 的公开安装和不同授权；`research_permission_skill_image.py`将真实安装文件按摘要交付到专属候选镜像，复用原镜像离线门禁，并通过 `SIQ_OPENSHELL_REQUEST_CANDIDATE_IMAGE_RECORD` 供独立验收 API 使用。不会替换日常镜像指针。安装器合法生成的只读硬链接使用稳定文件身份及完整内容摘要读取，不能套用普通镜像源码必须单硬链接的限制；符号链接和内容漂移仍拒绝。

`prove_research_skill_business.py`配合测评专用 `research_skill_sync.py`，由 Hermes 原生加载器读取固定技能，并向宿主报告真实 session/task，宿主再签发匹配 SEC。同步钩子只协调测评，不自行授权业务操作；原 SIQ 钩子继续裁决。只有实际工具回执含 verified Skill/SEC、真实文件效果及独立核验均满足时，才允许写运行权限通过。不能将这套显式受控任务选择推广为默认自动识别任意技能。相关前置回归85项通过；真实批次 `skill-business-002` 的两个 Skill 读写差异、SEC 归属、实际加载和文件效果已经独立核验，失败批次保留在上述独立测评目录。

## 当前结论

2026-09-22 受控切换后，活动 Qwen 容器仅发布在宿主 `127.0.0.1:8005`，SGLang 从私有文件装载密钥；运行 argv/environment 均无明文密钥，模型物料、参数和合成推理审计 `host_candidate_ready=true`。首次切换遇到固定镜像 `ServerArgs` 只读配置冲突，停止重试并修复为配置物化前注入后，服务冷启动成功且无自动重启。独立 OpenShell Provider 沙箱已通过错令牌 401、有效模型枚举 200；Hermes 0.21 真实合成 run 完成，与 bridge 200 单条摘要回执关联。同一合成企业 scope 沙箱的公司读写边界、候选 broker 身份续期/撤销和 Qwen 正向推理也通过。**整体 `candidate_ready=false`**：正式 Qwen 业务生命周期、SIQ IAM/生产 PostgreSQL、正式业务授权与原生 CI 仍待验收。以下保留切换前 502、LAN 发布和撤销失败现场作为历史记录，不能把它们解读为当前宿主状态。

切换前同机容量采样约为 121 GiB 统一内存、103 GiB 已用、18 GiB available，15 GiB swap 几乎耗尽；Qwen scheduler、embedding、reranker、MinerU 等推理进程持续占用内存。按原锁定 0.27 GPU fraction 启动 Nemotron 已在 CUDA 初始化阶段因内存不足退出。`mem_fraction_static=0.60` 与 vLLM 的 0.27 都是各自引擎预算参数，不能相加后就当成真实保留量；真实失败和 `MemAvailable` 才是当前不可同时启用的证据。不得为得到绿色探针而改小锁定候选参数，或静默替换模型身份。

## 只读候选审计

候选物料由 `infra/model-services/qwen3.8/candidate.v1.json` 锁定；该文件与 8006 的 `governed-model-routes.json` 完全分离。审计器只读取模型目录、Docker 状态与私有密钥文件，只发送模型枚举和合成标记推理，不读取企业资料，也不改路由、沙箱或容器。

```bash
cd /home/maoyd/siq-research-engine
python3 scripts/openshell/audit_qwen38_local_candidate.py \
  --probe \
  --out var/openshell/model-services/qwen38/candidate-audit.sanitized.json
```

当前预期退出码为 1；这是安全门禁正常阻断，不是审计器异常。退出码 2 表示审计器自身无法验证输入。公开脱敏投影见安全仓 `docs/evidence/flagship-optimization-20260921/ml-02-qwen38-isolated-candidate-audit.json`。输出只含摘要、布尔值和稳定错误码，不含模型响应、标记、凭据、容器地址或绝对路径。

## 受控迁移顺序

1. 盘点 8005 的真实调用方、既有非 loopback 发布地址及当前连接，并确定可接受的服务中断窗口。单机内存无法容纳两个完整 Qwen 实例，不能假设无损蓝绿切换。2026-09-22 一次 2 小时日志采样仍有 13 次请求，最近请求距采样不到 1 分钟；即使同时没有已建立 TCP 连接，也不能据此直接重启。
2. 窗口前使用 `infra/model-services/qwen3.8/preflight_locked_launch.py --full-artifacts` 复核完整主/MTP/draft 摘要、镜像 ID/RepoDigest、固定参数与私密密钥；再跑 `audit_qwen38_local_candidate.py --probe` 记录旧服务的合成模型枚举/推理。两项 2026-09-22 均通过静态物料和合成推理检查；审计整体仍按旧 LAN/argv 缺口返回 1。已准备 `infra/model-services/systemd-user/qwen38-27b-nvfp4-dflash2-sglang.service`，其启动器在删除旧容器前重复快速锁定检查，unit 不读取旧密钥环境文件，固定 `PUBLIC_HOST=127.0.0.1`。**该状态为 E72 切换前记录；安全 unit 现已安装并运行**。
3. 在确定的窗口内，将现有同名 systemd user unit 保存到 owner-only 的私有运行目录供审计，再安装上述安全 unit、`daemon-reload`、停止旧服务并启动新服务。该步骤预计存在模型冷启动中断，不能当作无损切换。先确认 loopback 模型枚举与最小推理，再检查 `/proc`/Docker 命令行和环境不含明文密钥、父进程及 spawn worker 的参数日志均已脱敏；然后从项目 Docker 网桥通过现有受鉴权 bridge 复验 200 与模型身份。运行态仍是旧容器时不得把静态修复记为通过。
4. bridge 已在网桥 8005 手动启动，宿主从 0600 文件读取上游密钥，沙箱不持有该密钥；迁移后仍要验证真实正向推理、连接超时、重启回收及网络撤销。不得把旧 LAN 发布端口直接加入机密沙箱 policy。
5. 复核并应用已新增的独立 Qwen 路由合同与策略编译分支，绑定候选锁中的镜像、权重、parser、推理参数、数据分类和 `cloud_fallback=forbidden`。现有 v1 Nemotron 清单和 `confidential_local/current-image.json` 指针不得被新构建覆盖；候选 ID、状态根、镜像与 ProfileManifest 必须分离。
6. 在独立 gateway/沙箱中跑 Hermes 0.21 原生推理、企业 scope 数据边界、AgentShield 决策、仅撤销模型路由后的失败关闭、策略恢复和干净 stop。随后生成新的候选 lock/doctor 与同批原生 CI 证据；不能复用 Nemotron 的 ML-01 推理或断路证据。

回滚边界：任何阶段失败都保持当前活动 `siq_analysis` binding 和 Nemotron 锁不变；已创建的 Qwen 独立沙箱先撤销租约并验证无 writer，再清理候选资源。模型服务重启若失败，先恢复原受审镜像、权重和参数及文件型密钥入口，不通过重新启用明文 argv 来制造健康状态。所有失败和跳过项保留在私有原始证据中，公开投影继续标记 `candidate_ready=false`。

安全 unit 和完整预检的脱敏材料见安全仓 `docs/evidence/flagship-optimization-20260921/ml-02-qwen38-secure-cutover-preparation.json`。完整预检命令需提供新 unit 所列的非密钥模型参数环境变量和 `SGLANG_API_KEY_FILE` **路径**，绝不能把文件中的密钥值放入命令行。安全启动器会在删除旧容器之前执行快速预检。E72 切换前，服务由 `/home/maoyd/modles_setup/` 旧脚本和旧 unit 托管，自动重启设置为 `always`；当时按 systemd 生命周期停止，未仅手工删除容器。当前运行的是本仓安全 unit。

## 8005 代理的离线实现边界

`scripts/openshell/authenticated_model_bridge.py` 和 `infra/systemd-user/siq-openshell-model-bridge-8005.service` 已落盘；user unit 已安装并手动启动，**未设为开机启用**。入口先验证 `siq-openshell-dev` Docker bridge 身份，只监听其网关 IP 的 8005，并固定上游为 `127.0.0.1:8005`。主机从两个独立的 0600 JSON 文件读取 `client_token` 与 `api_key`，每次请求重读，拒绝同值；只接受来自该 bridge 子网、携带正确 Bearer、Host 和固定模型名的 `GET /v1/models`、`POST /v1/chat/completions`。上游凭据只在宿主代理注入。请求上限 4 MiB、响应上限 16 MiB、并发上限 8；模型身份或上游状态异常时返回空体失败，不转发上游错误正文或敏感头。为完整响应校验，流式 SSE 在代理内有界缓冲后一次性交付，延迟须在真实 Hermes 探针中评估。

模型桥和令牌轮换共用 `%t/siq-qwen38-bridge/admission.lock`（0600，私有运行目录）。桥在请求准入到响应发送的整个窗口持共享锁；轮换持独占锁并等待已准入请求结束，锁不可用时返回空体 503，不能绕过撤权。运行目录在服务重启时保留锁 inode。轮换函数仅在持锁后读取旧令牌、原子替换私密文件和复读新令牌；撤权返回后旧代请求应为 401。该锁只解决**当前桥的单一共享客户端令牌**在途竞态；正式多沙箱并发必须先实现每沙箱独立模型代际或网关独占约束，不得对活动共享令牌直接做业务撤权。

systemd 用户服务的文件系统隔离会把宿主 root 所有者映射为 overflow UID。Docker 桥发现器现在只在 `uid_map` 精确为当前用户单 UID 映射时接受此身份；其他不可信二进制所有者继续失败关闭。真机服务保持 `active`，监听 `172.23.0.1:8005`，切换前旧 SGLang 监听 `192.168.2.121:8005`，E72 后已撤除。从 `siq-openshell-dev` Docker 网桥上的临时只读容器测试：无令牌与错令牌均为 401，正确令牌因 loopback 上游尚未迁移返回无正文 502；宿主自发请求经 NAT 显示为 LAN 来源并被来源限制拒绝。这证明桥的运行边界与失败关闭，**不证明真实模型通路**。对应脱敏证据见安全仓 `docs/evidence/flagship-optimization-20260921/ml-02-qwen38-live-bridge-negative.json`。

离线 HTTP 夹具覆盖正确转发、凭据替换与轮换、错令牌、越界路径/方法/Host、错误模型、上游失败、超大请求、符号链接和宽权限私密文件；这仅证明代理代码的边界，不证明 OpenShell 的网络、凭据下发或真实模型。已为**单一候选 generation**签发与上游不同的 `client_token` 并注册独立 Provider；令牌不进 CLI 参数、终端 passthrough、报告或仓库，在停止/撤销时轮换。上游密钥不得进入沙箱。unit 当前保持手动启动且对未迁移上游失败关闭；服务进程显示 active 不能充当模型在线证明。bridge 已启用 `--synthetic-trace`：仅当已认证且模型身份有效的 Chat 请求包含唯一高熵 `SIQ_QWEN38_TRACE_` 标记时，journal 才记录标记 SHA-256 和响应状态，不记录请求、凭据或模型响应。SGLang 迁至 loopback 后，要从独立沙箱分别验证 401、200、模型身份、合成推理和网络撤销，才可把审计里的 `authenticated_openshell_model_bridge_verified` 设为通过。

## 独立候选网关 Provider

2026-09-22 已在 `siq-openshell-scope-validation` 上启用 Provider v2，并安装 `siq-qwen38-bridge`。固定 profile 只允许 `host.openshell.internal:8005` 的模型枚举和 Chat Completions；候选令牌从宿主 0600 JSON 文件读取，通过 OpenShell 0.0.83 子进程环境传给 `provider create`，不在命令行、仓库或公开证据中出现。候选网关当时没有 sandbox；主网关的 Provider 清单未增添 Qwen。项目 CLI lint、32 项 provider 回归及实际网关导出通过。

OpenShell Provider 的固定凭据只适用于单个候选 generation：停止沙箱并撤销租约后，先轮换宿主 bridge token，再在空候选网关更新 Provider；旧 token 应即时失效。不能将其共享给主网关或当前活动 Hermes pool。

隔离协议探针使用已经锁定的 Hermes 0.21 镜像，仅运行 Python 标准库，不挂业务目录，也不启动 Hermes 网关；其目的只是在真实 OpenShell 沙箱中验证 Provider 挂载、环境占位符和网桥负向路径。执行前要求候选网关为空且只注册本候选 Provider，策略仅允许 Hermes Python 访问 `host.openshell.internal:8005`。资源租约固定 `siq_analysis_security_probe`（1 CPU、1 GiB、900 秒），探针 `--no-keep` 并按随机 nonce 标签二次确认删除；原始租约保留在 owner-only 本地状态目录。可重复执行：

```bash
python3 scripts/openshell/probe_qwen38_provider.py
```

2026-09-22 的真实运行中，沙箱内 `SIQ_QWEN38_BRIDGE_TOKEN` 仍是 OpenShell 占位符，错误 Bearer 请求得到 401，正确占位符请求得到 502；后者是旧 SGLang 尚未绑定宿主 loopback 时的预期失败。沙箱自动清理，候选网关复核为零沙箱，旧模型服务未重启。负向测试与资源治理测试共 **9 passed**，ruff 通过；公开脱敏证据在安全仓 `ml-02-qwen38-provider-sandbox-probe.json`。这尚未证明 SGLang 正向 200、Hermes Qwen 推理、企业 scope、AgentShield、撤销和回滚。

### 撤销顺序：先让桥接凭据失效

真实短命沙箱证明，**单独从基础 policy 移除 8005 不会撤销模型连接**：Provider 会组合出独立的 8005 endpoint。随后卸载 Provider 且有效 policy 显示零模型端点时，同一沙箱的最初两次请求仍到达桥接服务并得到 502；隔数秒后才变为 403。`policy set --wait` 和 Provider 清单已删除均不是即时撤销证据。因此仅凭 policy/Provider 修改不能满足机密候选的即时模型断路门禁；公开失败证据见安全仓 `ml-02-qwen38-route-revocation-gap.json`。

独立候选已验证一条失败关闭补偿路径：在旧沙箱仍存在时，先将宿主 0600 客户端令牌原子轮换。bridge 对每次请求重新读取该文件，旧 Provider 凭据的首次后续请求在此次实测中于 293 毫秒内得到桥接服务空体 401；之后清理旧沙箱，确认候选网关为空，再从新令牌文件更新 Provider，创建全新探针沙箱复验错令牌 401、有效占位符因上游离线 502。当前 Provider 已更新到 resource version 2，网关零沙箱。该 293 毫秒是单次观察，不是延迟 SLA；[候选轮换证明](../../../scripts/openshell/prove_qwen38_token_revocation.py)使用显式 `--apply --confirm-gateway siq-openshell-scope-validation`，结果见安全仓 `ml-02-qwen38-token-revocation-mitigation.json`。

正式 Qwen generation 的停机/撤销流程必须把**桥接客户端令牌先行轮换并验证旧代 401**纳入 lifecycle，然后停止并删除沙箱；只有候选网关无沙箱时才能向 Provider 登记新令牌。任何轮换或 Provider 更新失败均保持新令牌、旧 Provider 失配的失败关闭状态，不能恢复旧凭据制造健康假象。上述脚本只覆盖协议探针；下述持续 Hermes 网关候选证明将同一顺序提升到真实沙箱生命周期，但尚未覆盖正式企业业务沙箱、上游在线推理或业务 writer。

候选安装、验证和回滚命令见 [Provider 资产说明](../../../infra/openshell/providers/README.md)。Provider 与 bridge 现已上线，独立沙箱协议负向探针和令牌先行撤销实测通过；基础策略与 Provider 卸载的即时撤销门禁失败。该段是 E72 前的待办；SGLang loopback/文件密钥与合成沙箱 200/Hermes 推理现已在 E72/E73 通过。正式业务 stop/recover 与生产授权尚未验收，`candidate_ready` 仍为 false。

## 独立路由与机密策略编译

`infra/model-services/qwen3.8/governed-route.v1.json` 与 schema 单独存在，以字节 SHA-256 引用 `candidate.v1.json`；模型 ID、上下文、localhost 8005、`cloud_fallback=forbidden`、`confidential_local` 和 `SIQ_QWEN38_BRIDGE_TOKEN` 均严格校验。Hermes 配置编译器只有显式 `--qwen38-governed-route --require-security-plugin` 才允许 8005，并将所有模型、委派和辅助模型统一指向 Qwen；终端 passthrough 不含客户端令牌或云凭据，fallback 为空。快照入口只允许该路由生成 `--fresh --compile-config --require-security-plugin` 的新快照，不复制宿主会话。

上述严格入口已于 2026-09-22 生成独立命名的 `qwen38-v0210-20260922a` 运行快照：目录权限 `0700`，仅有编译配置和 manifest 两个文件；无 SQLite、会话或宿主运行记录，必需 AgentShield gate、`confidential_local`、Qwen 模型、空 fallback 与 `cloud_fallback=forbidden` 均通过检查。34 项快照/编译/路由回归及 mount scan 通过，Nemotron 的 `current-image.json` 指针未改变。安全仓证据为 `ml-02-qwen38-fresh-runtime-snapshot.json`。现有 `build_siq_analysis_image.sh` 会复用机密候选 `current-image.json`，并携带 MiniMax auth 模板，因此 Qwen 使用下述独立构建路径。

Qwen 专用镜像路径已加入：

```bash
python3 scripts/openshell/build_qwen38_current_hermes_base.py --dry-run
python3 scripts/openshell/build_qwen38_current_hermes_base.py
python3 scripts/openshell/build_qwen38_candidate_image.py --dry-run
python3 scripts/openshell/build_qwen38_candidate_image.py
```

现有 Nemotron Hermes 0.21 镜像的集成补丁摘要落后于当前五补丁源码，缺少 MCP watcher 生命周期修复，因此不能直接当作正式 Qwen 基础镜像。首个命令会准备、核验独立冻结上下文；第二个命令按 `base-image.lock.json` 在 Qwen 专用标签与状态目录构建当前五补丁基础镜像，绝不写 Nemotron 的 `current-image.json`。Qwen 衍生构建器再精确检查该基础镜像 ID、fresh 快照、当前源配置与受治理路由，只把编译配置和独立启动资产放入临时 Docker context；衍生层移除 MiniMax auth 模板。镜像标签按基础镜像 ID、快照 manifest 与实际构建文件摘要确定，专用状态写入 `var/openshell/qwen38/candidate-image/current-image.json`。镜像启动时重新检查配置摘要、唯一 8005 Qwen 路由、required security gate、空 fallback、OpenShell 客户端令牌占位符及空 auth 状态。构建后自动用 `--network none`、只读根文件系统和合成占位符启动 Hermes 网关；健康检查及启动后 auth 空状态通过才登记候选状态。失败时不更新候选状态；回滚时保留旧候选与原有模型服务，不将此独立镜像推广到活动池。

2026-09-22 的离线构建/网关启动均通过，安全仓证据见 `ml-02-qwen38-dedicated-hermes-image.json`。此证明**不含 OpenShell sandbox、真实 Qwen 推理、企业业务 scope 或撤销**。运行态上游仍未迁到 loopback；后续须以该专用镜像在候选网关完成正式沙箱与策略验证，再执行令牌先行撤销。不要用离线网关健康状态替代完整 ML-02 门禁。

专用镜像现已执行真实 OpenShell 短命沙箱探针：

```bash
python3 scripts/openshell/probe_qwen38_image_sandbox.py
```

它要求候选网关为空、Provider 清单精确、五补丁镜像状态锁匹配，使用 1 CPU/1 GiB/900 秒私有租约；策略仅给 Hermes Python 访问宿主 8005，并只读镜像内编译配置，不挂业务目录。初次探针发现 OpenShell 不继承镜像中的 `SIQ_PROJECT_ROOT`、`HERMES_HOME` 等运行身份环境，entrypoint 失败而 Provider 401/502 边界正常；失败的脱敏本地产物已保留。探针随后复用正式 lifecycle 的显式环境注入参数，entrypoint 配置摘要/空 auth 检查、Provider v2 占位符校验和 401/502 负向路径全部通过，`--no-keep` 后网关零沙箱。安全仓证据见 `ml-02-qwen38-dedicated-image-openshell-probe.json`。该探针只证明**专用镜像在 OpenShell 内的启动预检与协议负向边界**；尚未证明持续运行的 Hermes 网关、Qwen 正向推理、业务 scope 或令牌先行撤销。

持续 Hermes 网关和上游离线 run 的独立探针：

```bash
python3 scripts/openshell/probe_qwen38_gateway_bootstrap.py
```

该探针使用 `hermes_minimal_poc` 资源档位（1 CPU/2 GiB/1 小时），无宿主业务挂载，网络只允许 Hermes Python 到 8005；用合成 API 身份启动沙箱内 Hermes 网关，要求认证 `/health` 正常、Qwen 编译路由及空 auth 仍有效。初次合成 run 创建返回 202、终态 `failed` 且无成功标记；后续逐请求诊断证明该**初次失败发生在模型请求前**，不能再写成“上游离线 run”或推理尝试。根因是旧式 `custom_providers` 显示名与锁定路由身份不一致，以及基础镜像的私有运行态子目录由 root 持有。安全仓 E53 已补记重分析。Hermes API 的 `model` 字段报告网关别名 `siq_analysis`，不是底层 Qwen 模型 ID；模型路由身份由镜像编译配置摘要证明。修正后的逐请求证明见下文。

### 持续 Hermes 候选的令牌先行撤销

```bash
python3 scripts/openshell/prove_qwen38_hermes_generation.py \
  --apply --confirm-gateway siq-openshell-scope-validation
```

该证明要求独立候选网关为空、Provider 清单精确、五补丁镜像锁和私密客户端令牌有效；只使用短期 `hermes_minimal_poc` 租约、合成网关 API 身份、最小 8005 策略与零业务挂载。真实运行先使旧 Hermes 网关通过健康和路由检查，旧 Provider 占位符到桥返回 502；保持旧沙箱运行时原子轮换 bridge 客户端令牌，旧代首次后续请求由桥返回空体 401，随后提交 Hermes 合成 run 并确认失败终态。按 nonce 身份清理旧沙箱、复核候选网关为空后，才登记新令牌到 Provider；新建 Hermes 沙箱重新通过健康和桥 502 检查，最终两代沙箱均清理，网关零沙箱。凭据仅保存在宿主 0600 文件，证明输出不含凭据或模型原文。失败时保留轮换后的令牌使旧 Provider 失效，并在身份验证后清理；不得因单次负向探针成功就恢复旧令牌。安全仓脱敏证据见 `ml-02-qwen38-hermes-generation-revocation.json`。

这证明真实 Hermes/OpenShell **候选 generation** 的 token-first 顺序和失败关闭；502 表示桥认可凭据但 loopback 模型上游离线，绝不是 Qwen 正向推理。该合成 run 与单条桥请求尚未关联，企业数据 scope、AgentShield 工具授权、正式业务 writer 与生产停止/恢复仍须独立证明。旧 LAN SGLang 服务未重启，原活动 Hermes/Nemotron binding 未变。

### Hermes run 到模型桥的逐请求关联

当前候选镜像从独立 `qwen38-v0210-20260922d` fresh 快照构建。Qwen 路由现在登记在 Hermes v12+ `providers.<locked-id>`，显示名继续为 `SIQ Governed Qwen3.8 Local`；旧式 `custom_providers` 列表为空。这样运行时用固定 ID 解析模型，避免 legacy 兼容层丢弃 `provider_key`。衍生镜像把 `/sandbox/siq-analysis-runtime-state` 下的私有子目录归属交给 sandbox 用户，启动入口实测创建 `logs/curator`，构建器增加无网络的真实 Provider 解析检查。旧失败镜像和两次失败探针保留在独立私有状态，不作为当前镜像或成功推理证据。

```bash
python3 scripts/openshell/prove_qwen38_hermes_bridge_trace.py
```

该证明要求候选网关为空且 bridge 的合成回执开关在实际进程中生效，使用当前专用镜像、短期 `hermes_minimal_poc` 租约和仅到 8005 的策略。真实沙箱内 Hermes Provider 解析、运行态目录可写、网关认证健康均通过；一条带 128 位随机标记的合成 run 返回 202，终态 `failed`。bridge journal 中出现**同一标记 SHA-256 的一条 502 回执**，由此确认该 run 确实到达模型桥；标记原文、请求、响应和凭据均不进入公开证据。清理后网关零沙箱。使用新镜像重跑 token-first generation 演练也通过旧代 401、清理后登记新代、新沙箱 502。安全仓见 `ml-02-qwen38-hermes-bridge-trace.json` 与更新后的 `ml-02-qwen38-hermes-generation-revocation.json`。

此处 502 是 bridge 对离线 loopback SGLang 的失败关闭，仍不是 Qwen 模型正向推理。下一阶段在受控维护窗口切到私有 loopback 文件型密钥入口，再证明桥 200、Hermes 合成推理、企业数据 scope、AgentShield 授权与业务 writer 停止/恢复；当前活动服务和 Nemotron binding 未切换。

策略编译器只在显式 Qwen 路由下，把机密候选的 `siq_internal_services` 收紧为单独的 `host.openshell.internal:8005`；保留数据 broker 与 AgentShield relay，移除公开出网，其余 8004/8006/8007/8013 均不在该候选策略中。原始 `base.yaml` 和 Nemotron v1 清单未变。Qwen 策略输出必须位于 `var/openshell/qwen38/policies/`，旧 `current-image.json` 的候选镜像证明不能用于 Qwen；目前只支持宿主文件校验和真机 `--dry-run`，不代表候选镜像或沙箱已绑定。

```bash
cd /home/maoyd/siq-research-engine
python3 scripts/openshell/build_policy.py \
  --qwen38-governed-route infra/model-services/qwen3.8/governed-route.v1.json \
  --data-classification confidential_local --runtime-file-source host \
  --output var/openshell/qwen38/policies/candidate.yaml \
  --summary-output var/openshell/qwen38/policies/candidate.summary.json \
  --writable-path data/wiki/companies/600001-Test/analysis --dry-run
```

此命令只打印候选策略，不创建文件。真机结果的模型端口集合为 `[8005]`，无公网出口；业务写路径仅是合成示例，正式候选要换成该 run 的受授权 company/scope。当前独立镜像、令牌注入和真实沙箱负向断路已证明；仍须把此策略绑定企业业务沙箱，完成正向 Qwen 推理、数据 scope 和业务 writer 撤销。编译结果本身不足以把审计的正式路由门禁改为通过。

企业业务策略编译现支持 `--scope-ref` 指向宿主所有者持有、权限 `0600` 的授权 scope JSON。提供该参数时，策略仅接受 scope 中对应公司的**唯一直接 `analysis` 目录**作为任务写路径；跨公司、追加子目录、多个任务写路径、数据分类不匹配或缺少 `company_wiki` 权限均失败。策略摘要记录 `enterprise_scope_ref_sha256` 和授权快照摘要；正式 lifecycle 将它们与 scoped mount 摘要比对，避免挂载与策略分别绑定不同的公司。无 `--scope-ref` 的上述 dry-run 仅用于模型网络路由预检，不能作为企业 scope 验收。可复跑的合成边界证明为 `python3 scripts/openshell/prove_qwen38_policy_scope_binding.py`；它自动生成私有临时 scope、编译授权与跨公司策略并验证仅开放 8005、无公网出口，结束后清理临时文件，只留下 0600 脱敏证明。2026-09-22 该证明通过，聚焦及相邻回归共 170 项通过。公开投影见安全仓 `ml-02-qwen38-policy-scope-binding.json`。这仍是编译和生命周期合同证明，尚未把企业目录挂载到 Qwen 真实业务沙箱。

### 合成企业 scope 的真实沙箱挂载

```bash
python3 scripts/openshell/prove_qwen38_scoped_sandbox.py
```

该证明要求独立候选网关为空、Provider 和当前 Qwen 镜像身份有效；只在 `data/wiki/companies` 下创建两个唯一命名的**合成**公司目录，生成 Qwen fresh runtime 快照、私有 scope、8 项 scoped mount plan 和仅到 8005 的机密策略，并用 1 CPU/2 GiB `hermes_minimal_poc` 租约创建真实 OpenShell 沙箱。沙箱内 Hermes 网关健康；授权合成公司文件可读、`analysis` 可写并读回，另一合成公司不可读，公司根目录不可写；受鉴权模型桥返回 502（固定 loopback 上游尚未迁移）。清理前用 nonce 核对沙箱身份，用目录 inode 与内容核对合成源身份；清理后要求候选网关零沙箱，并删除本次合成目录、快照、策略和挂载计划。身份或目录内容异常时保留现场并失败关闭。真机证明及脱敏检查通过，见安全仓 `ml-02-qwen38-scoped-sandbox.json`。它不涉及真实企业资料、IAM 授权、AgentShield 决策或 Qwen 正向推理，不能替代正式业务生命周期验收。

### 沙箱内数据 broker 边界

同一证明现从真实 Qwen 候选沙箱以短时签名 v3 身份调用严格模式的数据 broker，仅用合成 scope 与公开 `SELECT 1`：同市场查询返回 200；跨市场、跨项目、无私有 scope 和不安全对象读取均返回 403；缺少身份返回 401。五条带身份请求均有规范审计回执，未保存令牌或查询正文；扩展后聚焦及相邻回归 136 项通过，公开脱敏投影为安全仓 `ml-02-qwen38-scoped-broker.json`。首次直连 socket 遭沙箱网络拒绝，改为遵循 OpenShell HTTP 代理的客户端后到达 broker；首次对象 scope 不足亦保留失败证据并修正合成授权对象集合。

E58 真实证明仍不等于即时撤销：运行中的 broker 只验签和业务 scope，测试令牌的 v3 gateway 声明为 `siq-openshell-dev`。后续源码已增加受限的候选 gateway 签名声明，以及候选 broker 的宿主私有在线准入表：候选令牌摘要、沙箱、策略、nonce 与 generation 登记后才可进入查询；每次请求持共享锁，撤销持独占锁并等待已准入查询完成；缺登记或状态损坏则失败关闭。HTTP 负向与并发回归通过，构成 E59 离线合同；它不回填 E58 的历史真机结果，也不能单靠 bearer 证明请求的网络来源。

E60 在独立 Qwen 候选网关上执行了真实 OpenShell/Hermes 沙箱演练：`python3 scripts/openshell/prove_qwen38_scoped_sandbox.py --online-admission`。候选策略只有同时绑定 Qwen route 和企业 scope 才能将数据 broker 路由固定到独立 `18794`；短时 broker 以合成 PostgreSQL 后端及合成审计响应公开 `SELECT 1`。候选专用模式要求签名身份和在线准入，开发网关身份访问 18794 返回 403。宿主先登记候选签名身份，沙箱内请求得到 200；在**同一沙箱未停止**时撤销登记，尝试重发旧 generation 被拒，再用同一令牌请求得到 `broker_admission_denied` 403。准入表 v2 持久保留每个沙箱的最高 generation，旧 v1 状态失败关闭；增加候选业务查询助手后，合成后端和审计各调用两次（原始 HTTP 与助手各一次）。身份交付已从创建命令中的令牌值改为 `--upload` 私有文件：沙箱内权限/归属为 `0600`/沙箱用户，启动 shell 读取同一身份摘要，宿主临时源删除，创建参数不含令牌值。随后候选沙箱、合成目录、准入状态和 18794 监听均清理，18793 活动 broker 未重启。扩展后相关 139 项测试、ruff、语法与脱敏检查通过，公开证据见安全仓 `ml-02-qwen38-broker-online-sandbox.json`。

E61 补齐了镜像到业务助手的一层：旧冻结 Qwen 镜像中的 `pg_query.py` 只接受 18793，真沙箱首次助手探针以 `broker_url_not_allowed` 失败，证据单独保存。现在助手只在 `host.openshell.internal:18794` 接受候选地址，并从固定上传文件读取所属用户 `0600` 的签名身份；其他 18794 主机、错权限、符号链接或身份不一致都失败。更新后的助手以 SHA-256 锁进**新的 Qwen 派生镜像**，构建器完成无网络文件摘要、Provider 解析和真实 Hermes 网关启动检查。新镜像的真实沙箱内，直接运行业务助手时登记后成功，撤销后以 `broker_admission_denied` 退出 2；合成后端只在撤销前执行。专项与相邻 139 项测试通过，见安全仓 `ml-02-qwen38-business-helper-candidate-broker.json`。Nemotron 镜像状态与 Qwen 候选状态仍分离；该助手是沙箱内进程直接调用，**尚未由 Hermes gateway 工具 dispatcher 调起**。

E62 在同一 Qwen 镜像的离线只读容器中，直接调用 Hermes 0.21 原生 `handle_function_call("terminal", ...)`。AgentShield 决策服务不可达时，分发器返回失败关闭错误，待执行命令的副作用文件不存在。构建器已将该负向检查固定为每次候选镜像物化的必需 smoke，状态记录 `offline_dispatcher_fail_closed=true`；36 项聚焦测试通过。该检查证明缺失决策服务不会放行工具，**不证明**网关 run 中带有效身份的正向工具调用、业务助手授权或模型推理；见安全仓 `ml-02-qwen38-native-dispatcher-offline-denial.json`。

E63 把候选沙箱启动证明中的数据身份改为**只从上传的 0600 文件读取**，不再导出 `SIQ_OPENSHELL_DATA_IDENTITY_TOKEN` 给启动 shell 的子进程；查询助手保持固定文件路径与权限校验。真实候选沙箱里，启动文件摘要校验通过、独立 `sandbox exec` 环境未见令牌值，助手在登记后读取成功。随后把新短时身份上传到私有目录，校验内容摘要及归属后在宿主登记 generation 2，再在沙箱内原子替换固定身份文件；旧令牌立即被注册表拒绝，新文件下查询助手仍成功，最终撤销后返回 `broker_admission_denied`。合成后端/审计各仅发生四次授权调用，候选网关最终零沙箱，临时 broker 监听和宿主上传源已清理；140 项专项及相邻回归通过。轮换仍只是隔离候选证明，**未接入正式 Qwen 生命周期的定时续期、恢复或故障重试**；也没有通过 `/proc` 独立证实 Hermes gateway 进程环境。见安全仓 `ml-02-qwen38-file-only-business-identity.json`。

E64 把续期顺序抽成 `scripts/openshell/qwen38_candidate_identity.py`，固定候选沙箱名、签名身份、注册表代际与文件上传边界；只有宿主私有文件承载令牌，OpenShell 命令参数只含路径和摘要。续期前读取注册表代际上限，要求严格下一代；上传到沙箱 0700 目录、校验后登记并原子替换固定身份文件。任何续期步骤失败都撤销该沙箱的 broker 准入，不能继续沿用旧令牌。真实候选沙箱连续完成 generation 2、3 两次续期，旧代逐次拒绝、两次续期后查询助手仍成功、最终撤销后拒绝；合成后端与审计各六次授权调用。故障注入还用真实注册表证明上传失败撤销旧授权、登记后文件安装失败撤销新旧授权。144 项相关测试通过，网关零沙箱、临时监听清理；见安全仓 `ml-02-qwen38-repeatable-identity-renewal.json`。这提供正式生命周期可调用的控制模块，**仍未实现定时调度、重启恢复或真实企业数据接入**。

E65 新增 `scripts/openshell/qwen38_candidate_lease.py`，把初次登记、续期、停止前撤销和恢复时先撤权串在宿主 0700 私有状态与独占锁下；状态只保存沙箱、代际、过期时间、策略与 scope 摘要，不保存令牌。真实候选沙箱中，该控制器登记 generation 1，连续完成 generation 2、3，第二次续期前重建控制器对象从私有状态继续，停止前将 lease 标记撤销且 broker 实际拒绝后续助手调用。故障测试验证状态写失败、状态损坏恢复、越权代际漂移均先撤 broker 准入；148 项相关测试通过，见安全仓 `ml-02-qwen38-candidate-data-lease.json`。重建对象不是实际 supervisor 崩溃演练；正式业务 start/stop、定时续期、崩溃恢复与真实 IAM/数据库还未接入。

E66 修正续期的运行身份合同：lease v2 固定原 `run_id`、`session_id`、run nonce 摘要和严格递增的 `issued_at`，防止通过换业务运行身份来制造新令牌。新增 `qwen38_candidate_renewal.py` 按到期窗口检查，每次 tick 都调用必需的授权复核回调；失权、scope 改变、状态损坏、签发时间未前进或运行身份漂移均失败关闭。真实候选沙箱里，generation 1→2→3 保持同一运行身份，合成授权回调调用两次，旧令牌逐次被拒，最后停止前撤权；154 项相关测试通过，见安全仓 `ml-02-qwen38-monotonic-lease-renewal.json`。**回调目前只有合成证明，不是真实 IAM 复核；tick 也尚未安装定时器/监督进程。**

该演练仍未把登记/撤销嵌入正式 Qwen 业务 lifecycle，未使用真实 IAM、企业资料或数据库，也未验证 AgentShield 工具决策和 writer 停止/恢复；该次历史演练时模型桥仍为 502，后续 E73 已另行证明合成沙箱正向推理。签名 gateway 声明及 bearer 登记不能独立证明网络来源。Hermes 进程环境的直接观察被沙箱 `/proc` 权限挡住，只能证明上传文件和启动 shell 读取，**不能宣称 Hermes 原生业务工具已继承身份**；失败观察的脱敏回执单独保留。下一步是将候选 broker 注册状态与正式 lifecycle 的创建和停机顺序原子绑定，并从 Hermes 原生工具验证身份，再完成真实授权和业务端到端门禁。

### E72/E73 安全宿主与合成正向链复验

当前安全 unit 的安装源为 `infra/model-services/systemd-user/qwen38-27b-nvfp4-dflash2-sglang.service`。首次切换前的旧 unit 仅保留在 `var/openshell/model-services/qwen38/cutover-20260922/old-unit.service`（0700 父目录、0600 文件）供审计，不得重新启用其明文 argv 启动方式。SGLang 镜像的只读 `ServerArgs` 要求文件密钥在配置物化前注入；`secure_launch_server.py` 已按固定镜像实际 API 修复，并禁止外部 `--config` 改写锁定启动参数。

```bash
cd /home/maoyd/siq-research-engine
python3 scripts/openshell/audit_qwen38_local_candidate.py --probe \
  --out var/openshell/model-services/qwen38/candidate-audit.sanitized.json
python3 scripts/openshell/probe_qwen38_provider.py --expect-positive
python3 scripts/openshell/prove_qwen38_hermes_bridge_trace.py --expect-positive
python3 scripts/openshell/prove_qwen38_scoped_sandbox.py --online-admission --expect-positive-model
```

审计器目前预期仍返回 1，因为它把正式 governed route、撤销和推广门禁保留为未通过；检查 `host_candidate_ready=true` 与各宿主检查项即可确认宿主层。后三个命令要求候选网关起始为空，只使用合成标记/公司目录并自动清理；真实执行已分别得到 Provider 401/200、Hermes run/bridge 单条 200 摘要回执，以及同沙箱企业 scope/broker/正向推理。令牌先行撤销的独立候选代际证明使用 `prove_qwen38_hermes_generation.py --apply --confirm-gateway siq-openshell-scope-validation`，会轮换当前候选 bridge 客户端凭据并重新登记 Provider；必须在候选网关为空且可验证清理时执行。上述证明均不接触真实企业资料，不能代替 SIQ IAM、生产 PostgreSQL、正式业务生命周期和 AgentShield 正向工具门禁。安全仓 E72/E73 证据保留本次摘要与失败恢复事实。

E75 新增 `qwen38_candidate_run_guard.py` 和 `qwen38_candidate_host_guard.py` 作为**尚未启用的正式业务监督合同**。它们要求候选网关独占一个已按 nonce 登记的业务沙箱；每 30 秒的默认 tick 需调用真实授权复核。失权、网关清单变化、状态损坏或停止/恢复时，控制顺序是 broker 撤权、通过 `qwen38_model_credential.py` 持 E74 锁轮换 8005 令牌、按 nonce 删除沙箱、复查整个候选网关为空。任一环节失败仍尝试余下切断，并报告处置不完整。`make_host_guard` 需要可信的已启动沙箱身份、业务授权回调、Broker 签名密钥与私有 lease；目前没有可信的 start 入口或常驻进程创建这些输入，**不能把此模块单独当作可启动的生产服务**。旧 Provider 在轮换后保持失效，直到旧沙箱清空并由新代重新登记。E75 的本地 grant 撤销测试使用真实 SQLModel 授权表、替身模型/沙箱回调；真实 Hermes 代际演练独立复验了抽离后的轮换函数，尚未把二者接成一个在线业务 run。


## E84：模型驱动报告发布与 HTTP 单次审批（2026-09-22）

真实 Qwen → Hermes `/v1/runs` → AgentShield → 不可信 MCP → HTTP 审批 →
Publisher → 独立读回已经在独立 OpenShell 沙箱验证。全部输入为合成资料，
Publisher 批准为非生产 fixture。拒绝 run 只有一个审批请求且没有发布副作用；
另一 run 单次批准后发布版本 1，再调用只读核验工具，宿主证明器独立读回摘要。
两条 publish 和一条 verify 的签名决策/observation 精确匹配 run、Grant 和参数摘要。

本次修复两处真实集成缺口：

- AgentShield 原先把报告 MCP 归为未知效果。新增固定工具/参数合同，发布显式需要
  `/sandbox/siq-business` 的读写 Grant，核验只需读；工具名允许或只有读权限均不足。
- Hermes 0.21 HTTP run 注册了审批回调，但 MCP consent 将 `api_server` 当无人值守
  路径处理。受审 0007 补丁将非 cron HTTP MCP consent 交给精确 run 的回调，
  缺回调拒绝；没有跳过审批、自动同意或更改终端无人值守策略。

候选镜像仍基于五补丁 Hermes 0.21 基础镜像，0006/0007 仅在 Qwen 派生层应用，
原文件/结果/patch 摘要写入 business MCP lock。离线真实审批队列验证缺回调、
回调异常、跨 run、错误 request ID、单次批准重放和取消；旧镜像同测失败。

### 复跑条件与入口

先构建并验证匹配当前源码/lock 的候选镜像，确保独立候选网关为空；不得复用
活动公司身份。构建安全仓 `apps/agentshield` 的 `cmd/agentshield` 和
`cmd/agentshield-decision-relay`，记录二进制 SHA-256。使用新建的空 0700
状态目录运行 `init --port 47811`，再以同一目录运行
`serve --state-dir <private-state> --port 47811 --mode block`；日志放在状态目录外
的私有文件。`SIQ_AGENT_SECURITY_STATE_DIR` 必须指向该目录。

确认仅 `127.0.0.1:47811/healthz` 健康后运行：

```bash
apps/api/.venv/bin/python scripts/openshell/prove_qwen38_gateway_business.py \
  --recovery-file <private-state>/admin-recovery.token \
  --relay-binary <reviewed-relay-binary> --relay-sha256 <exact-sha256> \
  --helper-image-ref <locked-helper-ref> --helper-image-id <locked-helper-id>
```

v4 relay 只接受候选 namespace/name 与固定 47811 上游；v2/v3 活动服务保持 47611。
证明器仅将新签发的 runtime credential 上传沙箱，管理凭据留宿主；结束时撤销
身份/Grant，按 nonce 删除沙箱，撤 broker、轮换模型令牌、复配 Provider 并验证
新代推理，然后释放网关占位。外层调用者必须在 finally 停止本次 47811 daemon。
清理后复核 18794/47710/47811 无监听及候选网关为空。

本轮公开证据为 `artifacts/openshell/flagship/ml02-qwen38-gateway-business-e84.sanitized.json`
和 `ml02-qwen38-gateway-business-sandbox-e84.sanitized.json`。E82/E83 原证据摘要未改。

### 回滚与范围

回滚时恢复匹配的源码、business MCP lock、snapshot 和已验证旧镜像，重新构建/验证
候选，不得只改 current-image 指针来掩盖输入不匹配。旧派生镜像状态备份在私有
`var/openshell/qwen38/candidate-image/pre-api-mcp-consent-image.json`；回退后模型驱动
MCP 审批能力应重新标记未验收。主 AgentShield daemon、公司 canary、模型与桥
均未重启。正式 IAM、生产发布审批、常驻监督及原生 CI 仍未完成，生产门禁不放行。

## 独立宿主监督进程（E86）

监督器、业务启动接口和恢复顺序见[Qwen 候选常驻监督与恢复](qwen38-candidate-supervisor.md)。
真实候选以独立进程复核 PostgreSQL grant，授权撤销后按 broker → 模型令牌 → 沙箱顺序清理；
这一验证仍使用合成授权和资料。正式业务入口、systemd 托管故障演练、同步即时撤权与生产 IAM
仍须独立验收，不改变整体候选或生产放行状态。
