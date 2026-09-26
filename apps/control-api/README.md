# Control API：企业安全控制面

本模块通过 FastAPI、SQLAlchemy 和版本化合同管理环境、Edge、资产、证据、风险与策略审批。它与个人 Go 客户端共享规则和合同，是独立的服务入口；部署企业端不会自动取得个人实例的管理权限。

[控制面设计与操作](../../docs/control-plane.md) · [生产运维模板](../../docs/enterprise-production-runbook-v1.md) · [合同](../../packages/contracts/README.md)

## 证据驱动的治理链

```text
环境/周期计划 → 已注册 Edge → 签名候选/证据批次 → 资产与框架/角色/Skill 观察
权限差异 → 策略草稿 → 人工审批 → 运行时绑定 → 执行后端部署 → 读回核验
状态变更 → 同事务审计 / outbox → 精确查询/OCSF 导出、漂移检查与到期复核
```

权限事实区分 declared、inferred、observed、effective、unknown。模型分类可以辅助提出候选，不能批准策略或将推断写成有效权限。部署请求成功也不等于 effective；后端读回与 authority revision 才能支持相应结论。这一分层为研究“声明与真实执行能力的差距”提供可追踪数据。

## 模块分工

| 实现 | 主要职责 |
| --- | --- |
| [routers](app/routers/) | 环境与周期计划、资产/框架/Skill、策略、风险、绑定、部署、审计与导出等 API |
| [main.py](app/main.py) | 应用启动、路由与服务配置 |
| [OpenShell adapter](app/adapters/openshell/) | 期望策略编译、后端交互与读回；能力不支持时显式拒绝 |
| [worker.py](app/worker.py) | outbox、规则评估、发现调度、漂移及到期状态处理 |
| [migrations](migrations/) | Alembic 数据库迁移；生产不自动建表 |
| [tests](app/tests/) | 租户/权限负向、合同与规则对等、状态机及后端契约测试 |

租户来自验证身份，不能由请求体覆盖。Secret 不以明文写入业务库、日志或 outbox；Edge 凭据吊销逐请求检查。高风险写操作若无法记录审计即失败。队列租约与重试属于至少一次处理，不宣称 exactly-once。

## 企业首次接入状态

`GET /api/v1/environments/access` 返回当前验证身份的接入操作权限；`GET /api/v1/environments/{id}/onboarding` 返回租户内设备心跳、扫描回执和证据计数，只读且有上限/截断标志。新建环境重名返回 409，复用现有唯一约束并回滚同事务审计。企业页按这些真实结果继续接入，不从注册码签发推断设备已在线。版本化合同和验收见 [E143](../../docs/development/ux-enterprise-onboarding-e143-validation-20260923.md)。

`GET /api/v1/inventory/access` 返回当前身份的候选处理、环境入口和策略创建权限。确认/驳回先定位租户对象再检查权限，驳回仅接受待处理候选；前端写后独立读回，未知结果先核对。详见 [E144 验收](../../docs/development/ux-enterprise-candidate-review-e144-validation-20260923.md)。

`GET /api/v1/console-context` 返回当前验证身份的组织、中文角色及有限访问/操作布尔值，未同步的组织名返回 null，GET 不创建记录。企业工作台与导航消费此合同。`/overview` 同时要求资产、环境和策略读取权限，在线设备仅按有效新鲜心跳计算。详见 [E145 验收](../../docs/development/ux-enterprise-workspace-e145-validation-20260923.md)。

当前主线还提供环境周期计划的创建、只读分页、撤销、Edge 待确认列表、显式确认与 tick 领取。设备端只读发现不会创建或确认计划；`active` 也不证明设备在线、采集成功或防护生效。框架实例/角色来源、Skill 安装观察和五态权限事实分别保留证据边界，缺少运行时加载证据时保持 unknown。审计支持精确条件查询与 OCSF NDJSON 导出；`X-SIQ-Export-Truncated` 仅说明本次响应是否截断，不代表完整归档。

## 本地开发

从仓库根进入模块；下列仅用于本机开发，API 监听 loopback：

```bash
cd apps/control-api
uv sync --dev
SIQ_AS_DEV=1 SIQ_AS_ALLOW_SQLITE=1 uv run uvicorn app.main:app --host 127.0.0.1 --port 8600
```

开发配置见 [.env.example](.env.example)，健康端点 `/health`。显式 dev 模式才接受 `X-Dev-*` 身份头和 SQLite。开发 worker 需另开进程，以相同配置执行 `uv run python -m app.worker --once`；持续运行可去掉 `--once`。生产必须关闭开发身份入口、使用 PostgreSQL、配置 OIDC/JWKS 与秘密注入，并先运行 Alembic 迁移。

需要隔离 PostgreSQL 时使用 [Compose 开发栈](../../deploy/compose/README.md)。Web 使用[企业构建](../web/README.md)，Edge 使用[注册与采集入口](../../edge/agent/README.md)；此开发栈不是生产拓扑或局域网团队交付验收。

## 验证与能力边界

```bash
# 在 apps/control-api 下
uv run ruff check app
uv run pytest
```

修改 schema 或共享规则时，须同步 Go 消费方和固定向量检查。真实 PostgreSQL + RS256/JWKS 的阶段记录见[测评目录](../../evaluations/README.md)，它不等同客户 IdP、HA、灾备或生产运维验收。OpenShell 的 fake backend、隔离网关验证和实际部署分别记录；不得用模拟读回宣称真实隔离已生效。

### 复用项目 OpenShell 的配置与证书目录

显式连接已有项目网关时，`SIQ_AS_OPENSHELL_CLI_BIN` 和
`SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT` 确定执行器与地址；同时继承该项目的
`XDG_CONFIG_HOME`、`XDG_STATE_HOME`、`XDG_DATA_HOME`、`XDG_CACHE_HOME`。
只传 config 目录可能找到网关登记，却找不到 state 目录内的客户端证书。
先核对目录上下文，不通过关闭 TLS、复制私钥或重建网关解决此类错误。
配置目录及用户目录变化会使旧连接指纹和部署预览失效，需要重新检查。

真实只读预览的复验脚本为
[`openshell-preview-live-check.py`](../../scripts/enterprise-experience/openshell-preview-live-check.py)：
使用 API 虚拟环境 Python，显式提供 `--cli`、HTTPS loopback `--endpoint`、
`--xdg-root`、已有 `--target` 和不存在的 `--out-dir`。脚本使用隔离开发数据库，
只允许运行网关信息/状态/版本和指定目标策略读取命令，拒绝任何 CLI 写操作。
不修改用户环境或沙箱；预览成功不代表部署或行为验证完成。

### 部署请求恢复（0017）

部署新入口为 `POST /api/v1/deployment-submissions`，使用
`deployment-submission-create/v1`（请求键 + 变更/环境/绑定 + 预览摘要）。
同键同内容只返回原记录，同键不同内容拒绝；每份变更仅保留一个部署请求。
`GET /api/v1/change-requests/{id}/deployment-submission` 可在刷新或进程重启后读取
准确的部署标识与状态。pending 表示正在处理或结果待核对，不允许自动超时重发。

`0017` 是持久部署请求首次引入的迁移，不是当前迁移头；当前主线版本目录已到
`0028_discovery_schedule`。上线前始终执行 Alembic `upgrade head` 并核对实际 head，
不能按历史部署记录停在 0017。表中有记录时，降级迁移会拒绝删除它。如果要回退到不理解持久请求的旧代码，必须先禁用部署写入口
（`SIQ_AS_ENFORCEMENT_BACKEND=none`）、保留 0017 表与审计并核对未决请求；不能
通过删除请求、改请求键或重启服务来重新执行。实际新一次操作需要重新审批变更。

隔离 PostgreSQL 复验：API 虚拟环境 Python 运行
[`deployment-postgres-check.py`](../../scripts/enterprise-experience/deployment-postgres-check.py)
并传入新输出目录。脚本只使用本机已有 `postgres:17-alpine` 镜像，在随机 loopback
端口启动自有临时容器，使用临时数据库和签名文件，最终删除自有容器。它验证数据库
事务和锁，不代替生产 IdP 或真实 OpenShell 行为验收。
