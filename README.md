# SIQ Agent Security

智能体安全管控平台（独立产品）：发现、解释、审批并持续验证智能体的权限状态。SIQ 是首个接入方，不是代码宿主。

> 状态：**Phase 0–2 可运行基线，持续安全加固中**。设计文档与评审意见见工作区根目录
> [`SIQ_AGENT_SECURITY_DESIGN.md`](../SIQ_AGENT_SECURITY_DESIGN.md)（v0.2）、
> [`SIQ_AGENT_SECURITY_DESIGN_REVIEW.md`](../SIQ_AGENT_SECURITY_DESIGN_REVIEW.md)（v1.0）、
> 开发计划 [`SIQ_AGENT_SECURITY_DEVELOPMENT_PLAN.md`](../SIQ_AGENT_SECURITY_DEVELOPMENT_PLAN.md)（v1.0）。

## 仓库结构

```text
packages/contracts/   合同事实源：JSON Schema + Connector 子进程协议 v1
apps/control-api/     Control Plane API（Python/FastAPI/SQLAlchemy/Alembic）
apps/web/             Web 控制台骨架（React/Vite/TS）
edge/agent/           Edge Agent（Go）+ 共享 protocol 包
connectors/hermes/    Hermes Profile Connector（Go）
connectors/docker/    Docker Connector（Go）
docs/                 ADR、威胁模型、兼容矩阵
deploy/compose/       本地开发部署
```

## 快速开始

### Control API（dev 模式）

```bash
cd apps/control-api
uv sync --dev
SIQ_AS_DEV=1 SIQ_AS_ALLOW_SQLITE=1 uv run uvicorn app.main:app --port 8600
# dev 身份头：X-Dev-Tenant-Id / X-Dev-User-Id / X-Dev-Roles（仅 dev 模式生效）
```

### 测试与质量

```bash
cd apps/control-api
uv run ruff check app          # 静态检查
uv run pytest                  # 含跨租户/职责分离/注册生命周期负向测试
uv run alembic upgrade head    # 在干净数据库回放全部迁移
```

### Web

```bash
cd apps/web
npm ci && npm run build        # 构建已验证
VITE_DEV_MODE=true npm run dev # 仅本地；API 默认走同源 /api/v1 代理
```

### Edge Agent

```bash
cd edge/agent
go build ./... && go vet ./... && go test ./...
```

## 安全不变量（代码级强制）

- 租户上下文永远从验证身份派生，客户端不可覆盖；
- 对象级端点"先租户定位（404）再权限（403）"，跨租户 ID 猜测与不存在不可区分；
- Edge 注册码一次性 + 15 分钟 TTL + 只存哈希；device secret 只返回一次；吊销即时生效；
- Edge 连接非回环控制面时强制 HTTPS，拒绝 URL 内凭据、查询串和路径混入；
- 审计与状态变化同事务（Transactional Outbox）；审计摘要只存标识/数量/哈希；
- 策略：提出者≠批准者（SoD）、幂等键、未批准不可部署、回滚同权审计；
- Secret 只存引用；每批 evidence 必须被本批 candidate 引用（孤儿证据 422）；
- 生产强制 PostgreSQL + OIDC/JWKS + Secret Manager 注入任务签名私钥（启动即校验，fail-closed）。

## 已知待办（不隐藏风险，详见 docs/threat-model.md 末表）

- 部署回执的独立可信验证器与完整性证明仍待 Phase 4 评估；
- SIQ Export Contract（D3-D5）与 OpenShell 版本路径（ADR-009/D1 spike）为 SIQ 侧跨仓依赖；
- 许可证待定（评审会决策 #1），暂未添加 LICENSE 文件。
