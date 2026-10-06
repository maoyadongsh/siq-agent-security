# SIQ API 聚合后端

## 模块定位

`apps/api` 是 SIQ Research Engine 的控制面后端。它不只是一个 CRUD API，而是整个系统的统一入口层：前面接 Web 工作台，后面连接 PDF 解析、通用文档解析、市场下载服务、多市场规则服务、Wiki 文件系统、PostgreSQL / Milvus 工作流和 Hermes 智能体。

它的职责不是“替代底层服务”，而是把这些能力包装成带鉴权、带归属、带状态、带审计的统一研究接口。

## 产品归属与业务边界

`apps/api` 同时服务三条产品面，但自身定位始终是控制面，不直接替代 parser、rules、Hermes 或模型服务。

| 产品面 | API 职责 | 关键价值 |
| --- | --- | --- |
| 二级市场投研分析智能体集群 | 统一暴露搜索下载、财报解析、market package、source access、分析/核查/跟踪/法务 Agent、PostgreSQL / Milvus 动作 | 让研究员从披露到报告复核的链路在同一鉴权和审计边界内发生 |
| 一级市场投研决策智能体集群 | 承载 Deal OS、材料中心、证据对象、专家任务、R0-R4 工作流、争议、决策和审计 | 把投委会过程从散落文档转成可回放状态机 |
| 应用中心 | 代理文档解析、会议转写、会议导入/导出、声纹/术语、向量入库和系统设置 | 让材料生产和知识沉淀能力被两大智能体集群复用 |

OpenShell 相关代码也位于 API 控制面边界内。API 负责运行面选择、公司上下文验证、范围自动创建、对话沙箱代际、资源池租约、隔离、重启恢复、空闲 TTL 清理和 Host 回退语义，但不会把 `NO_GO` 的 OpenShell 灰度链路当成默认生产运行面。正式切流必须由 OpenShell 完成度门禁、质量 A/B、人工架构/安全评审和正式生产门禁共同放行。

## 在系统中的位置

```text
apps/web / external client
  -> apps/api
     -> apps/pdf-parser
     -> apps/document-parser
     -> services/market-report-finder
     -> services/market-report-rules
     -> data/wiki / PostgreSQL / Milvus / Hermes
```

在这条链路中，API 后端承担三层责任：

- 统一入口：屏蔽下游服务的路径差异、端口差异和鉴权差异。
- 统一治理：对任务、artifact、下载文件、报告和 source 链接做用户归属与访问控制。
- 统一编排：把下载、解析、导入、Agent 会话、系统状态和设置管理串成同一套前端心智。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 鉴权与用户治理 | 登录、注册、用户审批、权限判断、审计入口 |
| 解析服务代理 | 对 PDF 解析和通用文档解析做统一鉴权代理与任务归属绑定 |
| 多市场入口 | 统一承接市场下载、evidence package 构建、后台 job 和导入动作 |
| 一级市场 Deal OS | 项目、材料、证据、专家工作流、争议、决策、审计与投后接口 |
| 会议智能化 | 会话、实时流、导入、说话人、术语/声纹、纪要、导出、回放与原生采集协议 |
| Wiki / 报告访问 | 读取分析、核查、跟踪、法务及市场 package 产物 |
| Agent 代理 | 对 Hermes 提供会话、附件、SSE 输出、停止与恢复能力 |
| 拟人化记忆控制 | 串联 Hermes 原生会话记忆、本地临时任务记忆、PostgreSQL 权威长期记忆、Milvus 语义索引和 reranker |
| OpenShell 运行面选择 | 对 `siq_analysis` 提供 Host / OpenShell 灰度路由、范围自动创建、对话代际、资源池租约/隔离/恢复、TTL 回收和失败关闭回退 |
| Source 访问控制 | 为 PDF 页图、source map、artifact、下载文件提供安全访问入口 |
| 工作流编排 | 驱动 Wiki、PostgreSQL、Milvus 等下游导入链路 |
| 系统设置与健康面板 | 汇总模型配置、下游健康和基础系统状态 |

## 当前最新状态

| 方向 | 状态 | 价值 |
| --- | --- | --- |
| Cookie 会话 | 支持 `SIQ_AUTH_COOKIE_MODE=1`，登录接口设置 HttpOnly cookie，前端请求自动 `credentials: include` | 生产路径禁止把 access token 写入 localStorage；本地 cookie=0 时令牌只留在内存 |
| Market package 动作 | `/api/market-reports/packages/*` 统一处理 build、import、vector dry-run 与后台 job | 把多市场 evidence package 做成可审计、可恢复的产品动作 |
| 质量门禁 | warning/fail package 未 force 时返回 409，并携带 `quality_gates` | 防止低质量解析静默污染 PostgreSQL 或语义索引 |
| Source 安全 | 下载文件、artifact、PDF 页图、source map 通过受控 API 访问 | 保留证据回跳能力，同时避免裸露本机路径 |
| 文档批次准入 | `/api/documents/tasks` 使用持久化幂等键、整批配额预留和原子任务发布 | 超时重试不重复创建任务或计费，任一文件失败时整批零可见 |
| Deal OS / IC 工作流 | `/api/deals/*`、会议室、agent runtime 与 readiness 接入 | 支撑一级市场 R1-R4 尽调、分歧和投委会决策链 |
| 记忆系统 | Hermes 原生会话记忆 + 本地临时任务记忆 + PostgreSQL 权威长期记忆 + Milvus 语义索引 + reranker | 支撑拟人化连续性、全量记忆、半衰期衰减、按需全量召回和用户/项目/系统隔离 |
| OpenShell 控制面 | `openshell_pool_adapter`、`openshell_scope_lifecycle`、运行协调、资源池恢复与运行路由接入 | 支撑 NVIDIA OpenShell + Hermes 演示/灰度链路：按公司范围自动建沙箱、同对话代际复用/隔离、请求级租约、API 重启恢复、原授权快照与机密 grant 的逐心跳复核、失权停止/写静默门禁、重启丢失原授权时只清理不续执行，以及空闲 TTL 删除；正式生产门禁仍为 `NO_GO` |

API 后端的商业价值在于把底层复杂能力包装成“可卖给研究组织的治理面”：权限、审计、质量阻断、任务状态、文件访问和智能体调用都在同一个控制面闭环中完成。

### 文档批次准入合同

`POST /api/documents/tasks` 的文件和 URL 准入都要求 `Idempotency-Key`。键必须是 1–128 个可见 ASCII 字符；缺失返回 `428`，格式无效返回 `400`。同一用户、租户、市场和操作下，只有相同键与相同规范化请求可以重放；内容不一致返回 `409`。

`202`、网络中断或 `unknown` 状态不是创建新请求的依据，客户端必须使用原键重试，或按响应中的 `Location` 调用 `GET /api/documents/batches/{batch_id}` 查询批次。API 确认解析器 task 批次已原子提交后，再以一个 PostgreSQL 终态事务结算 reservation、usage 和全部 artifact 归属；明确的 pre-send 失败会原子释放预留并返回 `retryable=true`。

上线前必须由 migration runner 应用 `migrations/011_create_document_parse_batches.sql`。旧版本应用回滚时保留该兼容表，不执行 drop；批次 reservation 采用长 TTL，避免旧版本的通用过期清理误释放仍在提交的配额。

## 高精度问答控制链

`apps/api` 是 SIQ “极致高精度”真正收口的地方。parser 和 rules 负责生产高质量事实，API 负责保证智能体最终使用的事实、计算与引用没有在最后一公里失真。

```text
用户问题 / 图片 / 文档 / 语音
  -> 会话、用户、profile、附件归属校验
  -> market/company/filing/parse run 身份解析
  -> LLM-Wiki logical route first / PostgreSQL fallback / independent Milvus semantic retrieval
  -> 主表与附注按问题类型分路
  -> Hermes 运行 + 记忆上下文 + 受控工具
  -> citation normalization / financial trace extraction
  -> trusted evidence 对齐 + Decimal 重算 + answer audit
  -> SSE 最终回答、source links、validation cards、runtime receipt
```

关键实现分工：

| 实现面 | 代表模块 | 保障内容 |
| --- | --- | --- |
| 问题与证据上下文 | `agent_runtime_context.py`、`agent_runtime_wiki_context.py`、`agent_runtime_statement_context.py` | 公司/市场/报告身份、三大表与附注路由、上下文预算 |
| 结构化事实兜底 | `agent_runtime_market_facts.py`、`agent_runtime_postgres_fallback.py` | Wiki 不足时从市场隔离 PostgreSQL agent view 补证，并保留真实 source type |
| 引用与来源 | `agent_runtime_citations.py`、`agent_runtime_financial_sources.py`、`citation_links.py` | evidence ID、PDF 页码、table/anchor/bbox、受控 source URL |
| 财务守卫 | `agent_runtime_financial_trace.py`、`agent_runtime_financial_claim_verifier.py`、`agent_runtime_financial_guard.py` | trace schema、证据绑定、单位/币种/期间检查、确定性重算、错误阻断 |
| 回答审计 | `agent_runtime_answer_audit.py`、`agent_runtime_financial_provenance.py` | 保存最终回答使用过的证据、计算回执、运行信息和失败原因 |

“高精度”在这里不等于强制输出数字。当权威事实、必要期间或计算 trace 不完整时，正确结果是降级、N/A、明确缺口或要求复核，而不是生成一个看似精确的值。

## 记忆控制与事实隔离

API 将长期记忆作为独立的可治理数据域，而不是把历史对话直接拼进 prompt：

- `agent_memory_service.py` 管理权威 PostgreSQL memory item、message、scope、来源、importance/confidence 和 ResearchIdentity。
- `agent_memory_milvus.py` 管理 Milvus 可重建索引；也保留 pgvector backend 选择，不让向量库成为唯一事实源。
- 默认召回在 rerank 后应用 30 天半衰期；显式“全量检索/完整历史”请求绕过时间衰减，但仍受 ACL、scope、数量上限和上下文预算保护。
- `user_private` 需要用户归属；`project_shared` 需要项目/Deal 范围；`system_shared` 仍按 agent group/profile 约束。一级市场缺少 project/deal context 时不创建项目共享记忆。
- 研究记忆可带完整 `market/company_id/filing_id/parse_run_id`，防止旧报告记忆污染当前报告事实。

记忆只回答“我们之前如何协作、曾经记录了什么”，evidence package 和当前数据库事实才回答“本期披露究竟是什么”。

## 本地多模态接入

| 输入 | API 处理 | 下游 |
| --- | --- | --- |
| 图片附件 | 白名单 MIME、大小与所有权校验，保存到受控 chat root；以 OpenAI vision `image_url` data URL 调用本机 `Nemotron 3 Nano Omni` | 返回文字/数字/表格/图表初步分析，随后交给 Hermes 结合问题与证据作答 |
| PDF/Office/文本附件 | PDF 等待 parser artifact，Office/文本做有界预览，保留本地 artifact 引用 | 文档解析、source map、Hermes 附件上下文 |
| 短语音 | WebM/OGG/M4A/MP3/WAV/AAC 白名单，FFmpeg 归一为 16 kHz mono WAV，限制 60 秒/10 MiB | FunASR 转写后进入普通聊天，同时保留音频附件归属 |
| 长会议音频 | 一次性 ticket、WebSocket gateway、持久 frame/segment/event、finalization worker | meeting-speech、Hermes 纪要/行动项、回放与导出 |

图片链路默认 `SIQ_IMAGE_MODEL_BASE_URL=http://127.0.0.1:8007/v1`，本机服务不可用时显式返回 fallback 状态并交给 Hermes，不会把失败吞成空分析。会议链路和普通短语音链路相互隔离，避免一个服务的延迟、权限或留存策略污染另一个入口。

## 双主模型与并发协调

云端 StepFun `step-3.7-flash` 与本地 Nemotron `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` 是当前双主模型，Step Plan 的 `step-5-preview` 作为 1M context 云端可选模型接入。`hermes_model_control.py` 负责把设置、用户显式切换、profile config 和 fallback 顺序解析成稳定 provider/model；运行回执保留实际来源。会议任务使用 immutable target snapshot，创建后不受全局设置变化影响。

问答请求可并发准备 LLM-Wiki 逻辑路由命中的精确事实、PostgreSQL 兜底事实、Milvus 向量候选、长期记忆、附件图片分析和文档 artifact；Qwen reranker 只作用于 Milvus/记忆等语义候选，不重排 Wiki 已按身份、主题、对象 ID 和附注关系确定的权威事实。各分支再按证据优先级裁剪和组装，并绑定 session/user/ResearchIdentity，晚到的旧 scope 结果不能覆盖当前请求。上游任一模型/数据服务失败时只降级相应能力，不应把整个请求静默切成无证据聊天。

LLM-Wiki 的 `semantic/retrieval_index.json` 是逻辑查询索引，不是 embedding 索引。API 依次通过公司/报告身份、topic alias、priority files、fact/claim/evidence IDs、`document_links`/`note_links` 和全文 source coordinates 跳转；这一主路径不调用 embedding、reranker 或 Milvus。这样可以避免传统 RAG 切片对跨页表格、报告期、单位和主表/附注关系的破坏。

API 不直接管理 GPU 显存，但通过输入上限、timeout、candidate limit、job/stream 状态、meeting backpressure 和模型 readiness 把 DGX Spark 的并发资源暴露为有界服务。实际容量仍由各独立 vLLM manager 的 context/sequence/token/memory budget 和整机压力测试决定。

## 技术难点

`apps/api` 的难点不在于定义几十个路由，而在于控制面如何在不破坏下游职责边界的前提下统一系统行为：

- 多下游服务并存：Flask、FastAPI、Wiki 文件、Hermes gateway、PostgreSQL、Milvus 同时存在，接口风格并不统一。
- 资产归属严格：artifact、聊天附件、报告产物、下载文件和 source 链接都必须和用户归属、权限和会话状态绑定。
- 长任务可观测：解析、下载、导入、Agent 运行都不是即时 RPC，需要统一 job / status / stream 语义。
- 证据访问受控：PDF 页图、source 表格、报告 HTML、结构化 JSON 都要可读，但不能裸露底层路径。
- 智能体接入复杂：API 要把多 profile、多端口、多种输出产物抽象成一致的前端体验。

## 关键接口或标准产物

### 关键路由分组

| 分组 | 前缀 | 用途 |
| --- | --- | --- |
| 健康检查 / 指标 | `/health` `/metrics` | 服务存活、基础状态与 Prometheus text 指标 |
| 鉴权 | `/api/auth/*` | 登录、注册、当前用户、管理员用户流程 |
| Wiki / 报告 | `/api/wiki/*` | 公司、报告、报告文件和管理动作 |
| 通用聊天 | `/api/chat/*` | 助手会话、附件、SSE 输出、运行控制 |
| 专业 Agent | `/api/analysis/*` `/api/factchecker/*` `/api/tracking/*` `/api/legal/*` | 专业 profile 代理 |
| PDF / Source | `/api/source/*` `/api/pdf_page/*` `/api/source_access/*` | 页面、表格、短期签名访问 |
| 通用文档 | `/api/documents/*` | 文档解析任务、artifact、抽取与来源访问 |
| 工作流 | `/api/workflow/*` | Wiki、PostgreSQL、Milvus 导入调度 |
| 市场报告 | `/api/market-reports/*` `/api/us-sec/*` `/api/jobs/*` | 多市场 package、后台 job、入库动作 |
| 一级市场 | `/api/deals/*` `/api/primary-market/*` | 材料、证据、R0-R4、争议、决策、审计与投后工作流 |
| 会议 | `/api/meetings/v1/*` | 会话、转写、说话人、词库、声纹、产物、任务、音频与导出 |
| 设置 / 状态 | `/api/settings/*` `/api/system/*` | 模型设置、系统状态、连通性测试 |

### 核心对接对象

| 对象 | 默认地址 / 目录 |
| --- | --- |
| PDF 解析服务 | `http://127.0.0.1:15000` |
| 通用文档解析服务 | `http://127.0.0.1:15010` |
| 市场公告下载服务 | `http://127.0.0.1:18000` |
| 多市场规则服务 | `http://127.0.0.1:18020` |
| Hermes home | `data/hermes/home` |
| Wiki 根目录 | `data/wiki` |
| 下载目录 | `data/market-report-finder/downloads` |

## 启动方式

以下命令均从仓库根目录执行。已有部署升级前请查看[应用数据库 migration](../../docs/operations/application-migrations.md)、[后台作业](../../docs/operations/durable-background-jobs.md)、[Agent Memory schema](../../docs/operations/agent-memory-schema-migration.md)和[密码哈希 Release A](../../docs/operations/password-hash-release-a.md)。

### 开发启动

```bash
cd apps/api
export SIQ_AUTH_SECRET_KEY="$(openssl rand -hex 32)"
./start.sh
```

### 手动启动

```bash
cd apps/api
uv sync --extra dev
export SIQ_AUTH_SECRET_KEY="$(openssl rand -hex 32)"
uv run python -m uvicorn main:app --host 0.0.0.0 --port 18081 --reload
```

### 常用健康检查

```bash
curl -s http://127.0.0.1:18081/health
curl -s http://127.0.0.1:18081/metrics | head
curl -s http://127.0.0.1:18081/api/system/status
```

## 关键环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `SIQ_BACKEND_PORT` | `18081` | API 监听端口 |
| `SIQ_AUTH_SECRET_KEY` | 无 | 鉴权密钥，必须设置 |
| `SIQ_SOURCE_TOKEN_SECRET` | 回退到 `SIQ_AUTH_SECRET_KEY` | source access token 签名密钥 |
| `SIQ_DATA_ROOT` | `$PROJECT_ROOT/data` | 历史兼容运行态根目录 |
| `SIQ_RUNTIME_ROOT` | `$PROJECT_ROOT/var` | 新增运行态推荐根目录 |
| `SIQ_WIKI_ROOT` | `$SIQ_DATA_ROOT/wiki` | 文件型事实层目录 |
| `SIQ_REPORT_DOWNLOADS_ROOT` | `$SIQ_DATA_ROOT/market-report-finder/downloads` | 官方披露文件目录 |
| `SIQ_PDF2MD_API_BASE` | `http://127.0.0.1:15000` | PDF 解析服务 |
| `SIQ_DOCUMENT_PARSER_API_BASE` | `http://127.0.0.1:15010` | 通用文档解析服务 |
| `SIQ_REPORT_FINDER_BASE` | `http://127.0.0.1:18000` | 市场下载服务 |
| `SIQ_MARKET_REPORT_RULES_BASE` | `http://127.0.0.1:18020` | market rules 服务 |
| `SIQ_HERMES_HOME` | `$SIQ_DATA_ROOT/hermes/home` | Hermes runtime 根目录 |
| `SIQ_AUTH_COOKIE_MODE` | `0` | 启用 HttpOnly cookie 兼容模式 |
| `SIQ_AUTH_ACCESS_COOKIE_NAME` | `siq_access_token` | access cookie 名称 |
| `SIQ_AUTH_COOKIE_SAMESITE` | `lax` | cookie SameSite 策略 |
| `SIQ_AUTH_COOKIE_SECURE` | `0` | HTTPS 公网部署应设为 `1` |
| `SIQ_PASSWORD_HASH_ITERATIONS` | `100000` | Release A legacy writer 的 PBKDF2-SHA256 迭代数；仅允许 `100000`～`1000000` |
| `SIQ_PASSWORD_LEGACY_ITERATION_CANDIDATES` | 空 | 仅填写环境审计确认过的旧迭代数，逗号分隔；连同当前值最多 4 个且每个不超过 `1000000` |
| `SIQ_IMAGE_MODEL_ENABLED` | `true` | 启用本地原生图片理解 |
| `SIQ_IMAGE_MODEL_BASE_URL` | `http://127.0.0.1:8007/v1` | Nemotron/OpenAI-compatible vision 地址 |
| `SIQ_IMAGE_MODEL` | 自动读取 `/models` | 图片模型名，规范部署为 `nemotron_3_nano_omni` |
| `SIQ_FUNASR_BASE_URL` | `http://127.0.0.1:8899/asr` | Chat 短语音转写服务 |
| `SIQ_AGENT_MEMORY_ENABLED` | `true` | 长期记忆总开关 |
| `SIQ_AGENT_MEMORY_TIME_DECAY_HALF_LIFE_DAYS` | `30` | 默认召回时间衰减半衰期 |
| `SIQ_AGENT_MEMORY_RERANK_ENABLED` | `true` | 记忆候选精排开关 |
| `SIQ_HERMES_RUNTIME` | `host` | Host/OpenShell 运行面选择；生产门禁前保持 Host |
| `SIQ_OPENSHELL_REQUEST_BACKEND` | `legacy` | `qwen38` 显式选择按请求创建的本地机密候选，仅限 `siq_analysis`；先核验主体/公司/授权并返回非执行计划，再于 create 阶段消费原 claim。不会退回 Host/旧 pool；真实 API 业务链验收前保持默认。 |
| `SIQ_OPENSHELL_REQUEST_DEPLOYMENT` | `host` | `isolated_candidate` 仅允许 local/development、127.0.0.1:18083、qwen38/confidential_local 及受限回环临时 PostgreSQL 库；固定使用隔离 47811 身份服务，启动请求恢复器，避免占用旧 pool 恢复锁。 |
| `SIQ_OPENSHELL_DATA_CLASSIFICATION` | `public_research` | `qwen38` 必须显式配置 `confidential_local`，并具备实时企业授权、预先许可的宿主根身份及就绪的恢复管理器。 |

运行面选择被权限拒绝时，普通 HTTP 返回 403 `runtime_access_denied`；缺少公司范围返回
400 `runtime_scope_required`；配置或可用性未确认返回 503 `runtime_selection_unavailable`。
SSE 在响应开始后发生选择失败时只发送终止 `error` 事件，不发送 `done`，不自动重试或改走 Host。
响应不回显底层异常、配置路径或凭据；这些分类不改变任何运行面授权规则。

`apps/api/start.sh` 与 `start_all.sh` 通过既有 `set -a` 加载私有 env 文件；Compose
显式转发上述开关。转发不代表容器具备宿主 OpenShell/systemd 运行权限，缺失
前置条件仍拒绝。请求构建与回滚见
[`qwen38-candidate-supervisor.md`](../../docs/runbooks/openshell/qwen38-candidate-supervisor.md)。

`siq_analysis` 的机密请求（或显式 qwen38 请求）还会在最外层调用建立宿主附属模型
出域约束。图片、记忆 embedding、rerank 只可访问
[`confidential-egress.v1.json`](../../infra/model-services/auxiliary/confidential-egress.v1.json)
登记的回环地址和模型，禁用环境代理/重定向；后台任务和线程继承该约束。该守卫
不替代业务授权，也不代表已验证 Milvus、文档解析等其他网络路径或模型进程身份。

上述受治理分析模式下，报告生成和模型控制请求统一进入聊天授权与沙箱执行路径，
不在 HTTP 路由中直接启动宿主报告流水线或改写宿主模型配置；机密请求拒绝 Host
及其隐式回退。目录快捷回答和消息 hash 回复缓存不用于此模式。显式 qwen38 在读取
附件包前核验原主体/企业授权；同会话已有活动任务时，新流式请求返回冲突。
公开 legacy 快捷分支保持兼容。该入口保护不代表宿主报告流水线已完成沙箱迁移，
也不替代实际 API 全链验收。

按请求恢复还要求私有 `origin-<nonce>.json` 来源记录：新队列在占用网关前绑定原
执行行与无凭据数据库目标摘要。不同库的请求计为 `foreign` 并保持不变；待清理
请求缺少或损坏来源记录时保留状态，恢复管理器不就绪。历史请求不自动补签来源，
须用原清理句柄明确处置；详见上述操作手册 E124。

E125 已用真实独立 FastAPI/临时 PostgreSQL 验证登录、未认证分析拒绝、管理员
授权创建/重试/撤销和分析师越权拒绝；不替代模型执行、生产 IAM 或业务审批验收。

本地候选授权管理 API 的撤销应答还包括已绑定 Qwen 请求的工具执行权限失效：业务
Grant 撤销提交后，从本 API 数据库筛选相同租户、用户、公司范围的运行记录，核对
原数据库、完整执行绑定与实际对象范围，通过 SIQ 自撤销端点撤销对应子运行身份。
不依赖当前 worker 的内存任务表，也不撤销共享根身份。无法核验或撤销时返回
`503 data_scope_execution_revocation_unconfirmed`，保留已经提交的业务撤权，允许幂等
重试；不会返回虚假的完成状态。沙箱停止和资源释放仍由原生命周期负责，已经派发的
操作不能由撤权回滚。该接入针对候选 Qwen 请求路径，不将其他未接入后端计为通过。
复现入口为 `python -m scripts.openshell.prove_qwen38_candidate_api --evidence-suffix vN`，
须使用 API 虚拟环境、仓库根工作目录和明确的 `PYTHONPATH=apps/api:.`，详见操作手册。

E126 已进一步通过真实非流式 `/api/analysis/chat`：管理员经 HTTP 发放合成企业授权，
分析师请求通过正式 selector/builder 调用沙箱 Hermes 与 Qwen，标记回复和模型桥 200
关联，原执行行 succeeded、API 自身 finalizer released 均在诊断清理前确认。
本轮发现并修复机密请求的宿主全局 PDF parse-only 兜底越范围问题：在目录枚举前拒绝
该兜底，不用文件名模糊匹配替代授权，事实核验规则保持不变。流式 HTTP、API 崩溃/
在途撤权、其他宿主检索路径、真实 IAM/审批和生产门禁仍须独立验收。

E127 已通过真实 `/api/analysis/chat/stream`：单个 run/done、无 error、完整模型标记与
桥 200 关联，SSE run/session 与原执行行一致。SSE done 表示模型完成，证明器另行等待
API 自身将执行行置为 completed 并写入 finalizer released，不用诊断清理冒充业务收尾。
流式与非流式正常路径均已有真机证据；在途撤权、API 崩溃和独立 active/history 授权仍待验证。

E128 v4 已通过首个模型输出后的真实 HTTP 取消：原执行 cancelled、API 自身回收、
旧子凭据 401，验证时诊断父身份仍有效。模型文本 delta 增加可选 `source: "model"`；
失败/超时提示没有该标记，客户端仍按 content 渲染，不能把来源标记当授权证明。
取消流无成功 done；本次收到两条 cancelled 通知，未宣称终态通知去重。

E129 已将受鉴权模型桥改为逐个校验 SSE 事件后转发，并对撤销等待准入锁设置有界
超时；错误模型/畸形事件拒绝，已开始的流不能追加伪造 DONE。候选桥受控切换及
批准 Docker 网络内真实模型探针通过，主 API/模型未重启。首帧 200 与完整结束回执
分离，取消导致的结束 502 不算回答成功。详见请求运行时架构及监督恢复操作手册。

E130 为独立 `/analysis/chat/active` 与 `/active/stream` 增加读取授权：返回前核对
同一 state/route、原服务端 scope 和当前企业 grant，重连逐事件复核，失权后只返回
分类错误。当前无本会话任务时返回空闲，不查询 profile 全局诊断。此检查不续执行
权限，已结束任务的输出仍可由当前有效 grant 读取。仅已通过隔离数据库及路由测试，
未加载到常驻 API；历史消息/session 摘要/audit trace 的持久化范围授权仍待完成。

## 基础环境与测试情况

API 后端建议在 Python `>=3.11` 环境运行，当前工作机采样为 Python `3.13.12`、uv `0.11.7`、Docker `29.1.3`。API 自身依赖 FastAPI、SQLModel、SSE、Redis/PostgreSQL/Milvus 相关客户端和多个下游 HTTP 服务；跨机器部署时以根 README 的环境表、`infra/env/local.example` 和各下游 README 为准。

| 测试面 | 命令 | 覆盖重点 |
| --- | --- | --- |
| API 单元/集成 | `uv run python -m pytest tests` | 鉴权、路由、Agent runtime、Deal OS、会议、market package、source access |
| Shell 入口 | `bash -n start.sh` | 启动脚本语法和基础环境变量 |
| FastAPI 导入 | `uv run python -c "import main; print(main.app.title)"` | 依赖解析、应用对象初始化 |
| OpenShell 控制面专项 | 见 `docs/siq-openshell-hermes-integration-status.md` | 最新记录 `78 passed`，覆盖运行面选择、资源池绑定、租约、范围自动创建、对话代际、TTL、恢复和 Host 回退 |

README 或文案变更通常只需要 Markdown 检查；如果改动 `services/openshell_*`、Agent stream、source access、Deal OS、会议或 package gate，应补跑对应测试并手动检查 `/health`、`/api/system/status` 和相关业务路由。

## 验证方式

```bash
cd apps/api
uv run python -m pytest tests
bash -n start.sh
uv run python -c "import main; print(main.app.title)"
```

若修改了代理、任务或路由聚合逻辑，至少补跑对应测试并手动检查 `/health` 与 `/api/system/status`。

## 维护原则

- API 负责统一入口，不负责把下游服务的全部业务逻辑重写一遍。
- 路径与运行态目录统一通过环境变量或 path config 解析，避免硬编码本机绝对路径。
- 与 artifact、source、下载文件相关的接口必须保留路径白名单与用户归属校验。
- 对 Hermes 的代理必须保持可停止、可恢复、可审计的流式语义。
- 新增 API 时优先补充 README、测试和前端调用方，避免出现“后端有能力但系统不可发现”的黑箱路径。

## 技术创新与商业价值

API 层不是传统 CRUD 网关，而是研究生产线的控制面。它把长任务、文件证据、模型流式输出、权限与人工确认组合为同一套可审计状态机。

| 创新点 | 工程实现 | 商业意义 |
| --- | --- | --- |
| 证据优先 API | 答案审计 trace、source token、artifact 路由与 package gate | 客户可以从结论回放到原文件、页码和结构化事实 |
| 多工作流统一编排 | PDF/文档 package、市场入库、Deal R0-R4、会议任务共用 job/status/event 模式 | 降低不同业务线重复建设控制面的成本 |
| 人机共治 | `force`、review、human confirmation、权限依赖与审计日志 | 高风险导入和投资决策不会被模型静默越权完成 |
| 本地模型解耦 | Hermes、解析器、语音与检索服务通过稳定 HTTP/文件合同连接 | 支持私有化部署及模型替换，降低供应商锁定 |

最难的部分是跨边界一致性：后台进程重启、流式连接中断、任务取消、重复请求和文件移动都不能破坏任务状态与证据引用。因此新增接口必须同时考虑幂等、路径白名单、鉴权、可恢复状态和产物可读性。
