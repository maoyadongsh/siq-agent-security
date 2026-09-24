# 结果保存修复的本机预览部署

日期：2026-09-24。预览地址仍为 <http://127.0.0.1:15173>，后端现为 loopback **18086**，已加载[结果提交顺序修复](business-result-commit-recovery-20260924.md)。本次没有更换主 API 18081、模型或企业端部署。

## 部署身份与验证

| 项目 | 当前值 |
| --- | --- |
| API unit | `siq-research-api-preview-result-20260924.service` |
| API MainPID / InvocationID | `2049646` / `8e80e725060d4cafa55eda5bf784eefb` |
| Web unit | `siq-research-web-preview-result-20260924.service` |
| Web MainPID / InvocationID | `2050065` / `7d1e3feefdda4c0f9a0649baafe8f09b` |
| 发布形态 | 本机 transient unit，`Restart=no`，没有新增开机自启 |
| 源码核验 | 新建 963 个 Python 源码/安装包文件摘要清单，启动前逐个核对；旧清单保留 |
| 前端 | 复用此前已验收的 282 项静态资源与服务器文件，无前端变更或重新构建 |

六项真实检查通过：新 API 健康且保留必需恢复门禁；前端切换新版；切回旧 API 18085；再恢复新版 18086；新 API 与前端代理的匿名结果读取均为 401/no-store；主 API 18081 与旧预览 API 18084/18085 的 PID、InvocationID、重启次数均不变。

恢复器仍配置为 `enabled=false / required=true / ready=false`。本预览不据此开放缺少恢复权限的 OpenShell 执行；真实模型和故障验收由独立候选完成。登录、真实组织角色、生产身份、正式执行和业务审批/事件出口没有因本次预览切换自动通过。

## 回退

本轮已实际执行 Web → 旧 API 18085 → 新 API 18086 的切换演练。保留运行中的旧 API 18085 作为该回退的前置条件。可停止本轮两个 unit，并以旧 API 启动独立 Web 单元：

```sh
systemctl --user stop siq-research-web-preview-result-20260924.service siq-research-api-preview-result-20260924.service
systemd-run --user --unit=siq-research-web-preview-result-rollback-20260924.service \
  --property=UMask=0077 --property=Restart=no \
  --property=WorkingDirectory=/home/maoyd/siq-research-engine/var/ops/flagship-deploy-e168/web \
  --setenv=TRIAL_HOST=127.0.0.1 --setenv=TRIAL_PORT=15173 \
  --setenv=SIQ_BACKEND_URL=http://127.0.0.1:18085 \
  "$(command -v node)" /home/maoyd/siq-research-engine/var/ops/flagship-deploy-e168/web/scripts/trial-server.mjs
```

实际演练使用此前 Web 单元名；上面独立 rollback 名用于人工撤回，执行前应确认它未被其他进程占用。回退后检查 `/api/health`、结果接口匿名拒绝及代理目标，不仅检查端口。

这不是旧源码冷启动、数据库降级或生产回滚证明。旧版本仍运行，但旧清单对应的源码已被后续修复改变，不能通过绕过摘要核验重启。新预览也是经过启动核验的当前工作区源码，不冒充不可变容器镜像；后续修改须建立新的发布清单。

## 证据

[部署证据](../evidence/flagship-optimization-20260921/business-preview-result-update-20260924.json)包含服务身份、六项检查及源码清单/部署脚本摘要，由候选清单（本机私有路径：`var/flagship/preview-result-update-20260924/candidate.json`）绑定。私有环境与日志留在研究仓 `var/ops/flagship-preview-result-20260924/`，不复制到公开证据。
