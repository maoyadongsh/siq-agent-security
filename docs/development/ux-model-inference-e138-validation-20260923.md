# E138：模型回答测试按钮与真实 Step 5 验收

日期：2026-09-23。属于 UX-03 模型发现/验证的接续，不代表 UX-03、全部用户旅程或标杆总目标完成。按用户最新排序，外部检查项目已登记为任务书 SEC-F01–SEC-F10，后续排期，本批继续原模型验证开发。

## 交付结果

首页及运行环境页的“测试模型回答”已接通真实后端。用户选择已发现的 Hermes 或 OpenClaw 模型配置后，按钮提交固定公开文本测试；服务端只调用该配置的 OpenAI Chat Completions 地址一次，不切换默认模型或尝试备用模型。仅当返回精确模型名、唯一 assistant 回答、正常结束且内容匹配随机标记、没有工具调用时显示通过。

“检查模型服务”仍只读取模型列表，两个按钮的意义和额度影响分别说明。凭据只在后端解析已有配置引用，不进入浏览器。实际 Step Plan `step-5-preview` 固定公开文本测试通过；使用既有 OpenClaw Step 配置的 file SecretRef，没有修改原配置，没有发送业务数据。

当前候选：`var/flagship/ux-e138/siq-agent-security-v2`。

SHA-256：`97539c364f29af3b2b535dae3cd01b642f13d79bc7d0e2739d1aef246fd78374`。

## 请求、状态与恢复

- 新增管理接口 `POST /v1/model-inference-tests` 和 `GET /v1/model-inference-tests?model_id=...`，普通决策凭据不可调用。请求只接受精确字段、明确确认和已发现配置 ID/指纹，拒绝重复字段、额外 URL/提示词、超大请求和失效选择。
- 服务端先记录请求，再异步调用；当前服务会话同时只允许一个测试。同一请求 ID、相同参数重发返回已有记录；参数改变拒绝。最多保留 1024 条去重记录，不为接受新任务驱逐旧记录。
- 输出最多请求 512 token，单次调用上限 45 秒；不跟随重定向、不读取环境代理、不绕过 TLS 或元数据地址防护。网络不确定结果不自动重试，避免重复消耗额度。
- 页面刷新恢复进行中/完成状态；关闭页面不取消已提交测试。提交回包丢失时读取后端状态，不重新发起推理。认证失败、限流、服务失败、回答不匹配、连接中断各有明确反馈。
- 调用前后复验配置和凭据。配置变化后结果失效，重新发现后才能使用新配置显式发起测试；未找到凭据时按钮禁用。
- 记录保存在当前服务进程内，不跨服务重启保留，页面明确说明。完成结果 5 分钟后显示过期；它只证明此次固定文本回答，不证明原生 Agent 工具、完整业务运行或授权生效。

## 验证结果

| 检查 | 结果与证据范围 |
| --- | --- |
| 回答测试真实后端浏览器 | **22 项通过**；包含刷新恢复、相同请求去重、不同请求并发拒绝、提交回包丢失、读取失败恢复、401/429/503、错回答、断连、配置漂移、重新发现、凭据缺失、Hermes/OpenClaw 配置选择及手机尺寸操作 |
| 真实 Step 5 回答 | **passed**；浏览器发起，真实候选后端读取现有 SecretRef 后调用 Step Plan，严格核对模型和随机标记；未使用替代响应或仅模型列表作为证明 |
| 原模型列表浏览器回归 | **15 项通过**；同一最终候选，真实 Step 列表为 listed；回答测试未破坏原列表检查 |
| Web | **40 文件、255 项通过**；类型检查及本地 UI 构建通过；嵌入上述候选 |
| Go | `go test ./...` **44 个有测试包通过**，其余包无测试文件；`go vet ./...` 通过，产品源码 gofmt 检查通过 |
| Go 定向竞态检查 | modelconfig/server 的回答测试 **两包 `-race` 通过**；覆盖同请求重放、不同请求拒绝、历史保留和配置漂移 |
| Python | 完整 API/合同套件 **970 项通过、1 个既有 Starlette/httpx 弃用 warning**；其中新增回答合同样例与模型发现合同聚焦 **2 项通过** |
| Ruff | `ruff check app` 通过；顺带修正原开发的两处测试行超长，未处理复核中迁移目录的独立整理项 |
| 交叉构建 | 最终嵌入 UI 的 Linux amd64/arm64、macOS arm64、Windows amd64 均通过；不视为对应系统的原生运行验收 |

浏览器使用真实候选进程、管理配对和隔离 HOME。Hermes/OpenClaw 通用错误场景使用本机合成 HTTP 模型服务，Step 5 正向使用真实云服务。这次没有执行 Hermes/OpenClaw 原生工具或企业业务任务；不可借用上述按钮证明整个 Agent 运行链路。

本批没有实等 5 分钟或强杀本地服务来额外证明过期/重启语义，不将这些作为浏览器 22 项之一；TTL 展示及服务会话范围由当前实现/合同和说明限定。API 单测使用独立 SQLite、开发身份及 fake enforcement，不代表生产 PostgreSQL/OIDC 部署验收。

## 保留的失败及修复

1. 首次 Go 聚焦测试使用了缺少明确模型协议的夹具，以及非 loopback 的 httptest 默认地址，分别被配置与访问守卫拒绝；修正夹具后通过，没有放宽产品守卫。原失败日志保留。
2. 浏览器 v1 在配置漂移后的重新发现场景失败：先前被拒绝提交的 pending ID 留在 sessionStorage，使前端隐藏了本应展示的历史失效说明。修复为优先显示配置已变化的历史结果，同时仍禁止把不同待确认请求的旧成功当作本次成功；v2 完整复测 22 项通过。
3. 新测试开始时终止旧状态读取，提交期间禁用手动刷新，避免旧读取覆盖新提交状态；读取失败隐藏成功提示，恢复后以真实读回重新展示。

## 文件与复验入口

- 实现：`internal/modelconfig/inference.go`、`internal/server/model_inference.go`、`ModelInferenceTest.tsx`、`modelInference.ts`，以及既有模型发现 API/组件的接续。
- 合同：`local-model-inference-create.v1.schema.json`、`local-model-inference-record.v1.schema.json`、`local-model-inference-latest.v1.schema.json`；三个 Go 输出样例供 Python 与前端验证。
- 浏览器证明器：`scripts/personal-experience/model-inference-browser-smoke.py`。
- 脱敏证据：[E138 JSON](../evidence/flagship-optimization-20260921/ux-model-inference-e138.json)。完整检查输出与截图在 `var/flagship/ux-e138/`；v1 失败与 v2 成功独立保留。

```bash
python3 scripts/personal-experience/model-inference-browser-smoke.py \
  --binary var/flagship/ux-e138/siq-agent-security-v2 \
  --hermes-cli /home/maoyd/siq/hermes-agent/.venv/bin/hermes \
  --step-config /home/maoyd/.openclaw/openclaw.json \
  --out-dir var/flagship/ux-e138/browser-recheck
```

上述命令显式选择真实 Step 测试；省略 `--step-config` 仅执行隔离合成模型场景。重复运行会产生新的固定公开云端请求，不能将旧证据当作当前服务可用性。

## 接续与回退边界

未替换已安装发行版、未改默认模型、未修改 Hermes 0.21 基线、未更新 OpenShell 网关，也未提交或推送。浏览器证明器退出时停止并清理自建候选环境；故障恢复使用已存在测试记录，不能撤销已经送达模型服务的请求或已消耗额度。

继续 UX-03 的多网关/项目配置接续与原生凭据继承、UX-04/05 的权限流程简化、UX-11 的业务结果产物、企业向导和发行验收。外部检查的后续清单保留独立状态；不因本批模型按钮通过把 SEC-F 项或总目标改成完成。
