# 企业控制面本地开发栈

[compose.yaml](compose.yaml)提供 PostgreSQL 16 与 Control API，显式启用开发模式，仅绑定本机端口。它用于独立开发与迁移验证；个人客户端无需启动此栈。

## 启动与检查

在仓库根目录执行，需要 Docker Compose：

```bash
docker compose -f deploy/compose/compose.yaml up --build
```

PostgreSQL 映射 `127.0.0.1:55433`，API 映射 `127.0.0.1:8600`。容器等待数据库健康，再执行 `alembic upgrade head` 后启动 API；健康检查为 `http://127.0.0.1:8600/health`。数据库保存在命名卷 `siq_as_pg_data`。

```bash
docker compose -f deploy/compose/compose.yaml ps
docker compose -f deploy/compose/compose.yaml logs control-api
docker compose -f deploy/compose/compose.yaml down
```

普通 `down` 保留数据卷。该配置使用公开开发口令与 `SIQ_AS_DEV=1`，不得原样暴露到外网或用作生产配置。Web、Edge 和后台 worker 不在此 Compose 中，分别按 [Web](../../apps/web/README.md)、[Edge](../../edge/agent/README.md)和 [Control API](../../apps/control-api/README.md)配置；不要将“容器已启动”记为完整策略闭环通过。

## 生产与验收边界

生产须关闭开发身份头，注入数据库/任务签名秘密，配置 OIDC/JWKS、迁移、备份与恢复；实际缺口见[运维模板](../../docs/enterprise-production-runbook-v1.md)。仓库已有隔离 PostgreSQL/JWKS 记录，见[测评索引](../../evaluations/README.md)，不代表 HA、客户 IdP、长期运维或便捷 LAN 多设备流程已验收。
