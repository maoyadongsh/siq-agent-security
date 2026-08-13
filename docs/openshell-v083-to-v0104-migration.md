# OpenShell v0.0.83 → v0.0.104 迁移 Runbook（canary 窗口期）

> 状态：待执行（2026-08-13 起草）。执行前提：所有验证结论已满足——
> ① 两补丁上游化（rebase 分析）；② v0.0.104 解码缺陷修复实测；③ 产品闭环在 v0.0.104 隔离网关实测通过（2026-08-13：sync 52 事实 + 部署 effective）。

## 0. 现状盘点

| 项 | v0.0.83（当前 canary） | v0.0.104（目标） |
| --- | --- | --- |
| 二进制 | research-engine `var/openshell/toolchains/v0.0.83/bin/`（网关为 patched 版） | 本机已构建：`/tmp/openshell-build/OpenShell-0.0.104/target/release/`（CLI/gateway/sandbox，gateway 需 `--features bundled-z3`） |
| 网关实例 | siq-openshell-dev @ 17671（TLS） | 已建独立实例：`var/openshell/gateway/siq-openshell-104/` @ 17673（当前 plaintext 开发配置，正式迁移需补 TLS） |
| 沙箱 | siq-as-live（策略 revision 7） | os104-live（Ready，revision 1） |
| 产品接入 | `SIQ_AS_OPENSHELL_ENV_SH` → env.sh（v0.0.83） | `SIQ_AS_OPENSHELL_CLI_BIN` + `GATEWAY_ENDPOINT` + `INSECURE` 直连（cli_backend 已支持） |

## 1. 窗口期执行步骤（在 canary 无流量时）

1. **备份**：`cp -a var/openshell/gateway/siq-openshell-dev /tmp/backup-gateway-v083-$(date +%s)`；备份 v0.0.83 三二进制与 env.sh；
2. **停网关**：先删活沙箱（`run_cli.sh sandbox delete <names>`），再 `bash scripts/openshell/stop_gateway.sh`；
3. **DB 迁移**：v0.0.104 gateway 启动时会跑自身 sqlx 迁移——**先对备份副本试跑**（新实例指向备份 DB 启动一次，确认迁移成功后再用原路径）；迁移失败则回退二进制；
4. **配置**：按 `var/openshell/gateway/siq-openshell-104/gateway.toml` 模板改 17671/正式 TLS 证书（generate-certs 或沿用 tls 目录格式对齐后再定）；provider inventory（siq-minimax-cn-pool 等）需重跑 `provision_siq_providers.py`（v0.0.104 用其 CLI 执行）；
5. **换二进制**：`var/openshell/toolchains/v0.0.104/bin/`（拷贝构建产物）+ env.sh 的 `SIQ_OPENSHELL_BIN` 指向更新；`OPENSHELL_GATEWAY` 保持 siq-openshell-dev；
6. **配套镜像**：supervisor 镜像 `localhost/openshell/supervisor:os104-eval`（已建）；BYOC 沙箱镜像需用 v0.0.104 supervisor 重打（research-engine 的 build_siq_analysis_image.sh 按新协议重跑）；
7. **回归**：`cd scripts/openshell && pytest control_tests -q`（基线 78 passed 对照）；补 bind-mount 契约正负样本（V2）；
8. **回滚预案**：任一步失败 → 恢复备份二进制/DB/镜像（v0.0.83 全部保留在备份目录与 toolchains 旧目录）。

## 2. 产品侧切换

```bash
SIQ_AS_ENFORCEMENT_BACKEND=openshell-cli \
SIQ_AS_OPENSHELL_CLI_BIN=/var/openshell/toolchains/v0.0.104/bin/openshell \
SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT=https://127.0.0.1:17671 \   # 正式迁移后 TLS
  uvicorn app.main:app
```

迁移完成后 `sync-openshell` + 部署闭环回归一遍（2026-08-13 已在隔离实例实测通过）。

## 3. 完成后

- ADR-009 定稿（方案 A 执行完成）；ADR-005 patch 治理表：0001/0002 → `upstreamed` 归档；
- cli_backend 的 docker 兜底路径退役评估（v0.0.104 无解码缺陷）；
- 兼容矩阵 v0.0.83 行标记"退役"。

## 4. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| DB 迁移失败 | 先对备份副本试跑；回退二进制即恢复 |
| BYOC 镜像重打成本 | 用现有 hermes-poc/siq-analysis 镜像清单批量重打（脚本化） |
| provider inventory 丢失 | provision 脚本重跑（幂等） |
| 回归新增失败 | 逐项归因；无法短期修复则回退（两代二进制并存） |
