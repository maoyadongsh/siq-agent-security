# 研究业务预览更新与切回验证（2026-09-24）

## 当前入口

**本机页面：<http://127.0.0.1:15173>，现连接新预览 API `127.0.0.1:18085`。**

本轮将近期已验证的研究业务源码更新到本地预览，包括宿主记忆主体、公司 Wiki/数据库范围、聊天附件归属和共享 Wiki 脚本检查。主 API 18081 和旧预览 API 18084 保持原进程；客户端、企业端冻结提交与发行包未变。本轮不宣称正式生产切换或登录后业务验收完成。

## 实际部署验证

新 API 启动前核验 957 个源码及已安装共享包文件的 SHA-256，启动后再次核验未变化。采用独立 systemd 用户临时服务，回环监听、`Restart=no`、私有环境和日志；没有开机自启或公网绑定。

以下六项检查全部通过：

1. 新 API 健康返回 200，新结果读取路由存在；必需恢复授权门禁保留。
2. 15173 页面代理成功切换到 18085，并核对实际 Web 进程的后端目标。
3. 实际停止新 Web，重新启用旧 Web 连接 18084，页面及代理健康通过。
4. 再次切换到新 Web/18085，页面和代理健康通过。
5. 直连新 API 和经页面代理读取结果列表/结果元数据，未登录均为 401 且 `Cache-Control: no-store`。
6. 主 API 和旧预览 API 的 PID、InvocationID、重启计数均与切换前相同；主 API 仍健康。

沿用 E168 的页面快照：原构建记录中的 256 个文件逐个哈希一致，24 个额外 gzip 缓存逐个解压与对应原文件一致。没有前端源码变更，未重复构建；旧批次登录页截图仅作为历史证据，本轮未声称重新完成浏览器或登录后验证。

## 运行状态与限制

| 服务 | 状态与职责 |
| --- | --- |
| `siq-research-api-candidate.service` | 主 API 18081，未切换 |
| `siq-research-api-preview-e168.service` | 旧预览 API 18084，保持运行，供切回 |
| `siq-research-web-preview-e168.service` | 切回演练后停止 |
| `siq-research-api-preview-20260924.service` | 新预览 API 18085，运行中 |
| `siq-research-web-preview-20260924.service` | 当前页面 15173 → 18085，运行中 |

新预览继续 `openshell_recovery={enabled:false, required:true, ready:false}`，不持有主 API 的恢复权限；依赖该恢复器的 OpenShell 执行仍被拒绝。预览更新不替代 Hermes 真实执行验收、生产 IAM、原生 CI、质量门禁或正式签名发行。真实业务账号入口仍待提供，没有创建替代账号或伪造身份。

源码按启动清单绑定，仍从当前仓库加载，**不是不可变源码镜像**。后续修改清单内文件后，不能直接重启并改写旧清单；须准备新的候选清单和对应验证。旧预览 API 保留的是运行中的旧代码，不代表它在当前源码上可直接冷启动回退。

## 撤回与切回

只撤回本轮服务、保留主 API 和旧预览 API：

```bash
systemctl --user stop siq-research-web-preview-20260924.service siq-research-api-preview-20260924.service
```

需将页面恢复到旧预览 API 时，在研究仓库根目录执行以下命令。它使用保留的 E168 页面快照，建立独立回退 Web 服务；不重启旧 API：

```bash
systemctl --user stop siq-research-web-preview-20260924.service
systemd-run --user --collect --unit=siq-research-web-preview-rollback-20260924.service \
  --property=UMask=0077 --property=Restart=no \
  --property="WorkingDirectory=$(pwd)/var/ops/flagship-deploy-e168/web" \
  --setenv=TRIAL_HOST=127.0.0.1 --setenv=TRIAL_PORT=15173 \
  --setenv=SIQ_BACKEND_URL=http://127.0.0.1:18084 \
  "$(command -v node)" "$(pwd)/var/ops/flagship-deploy-e168/web/scripts/trial-server.mjs"
```

上述独立回退服务命名用于人工操作；本轮实际自动演练使用原 E168 Web 服务名、相同启动程序和后端目标。切回验证是页面代理在两个存活 API 之间的切换，不扩大为数据库降级、旧依赖冷启动或主服务生产回滚证明。

## 证据

研究仓库私有 `var/ops/flagship-preview-refresh-20260924/` 保存准备/启动/切换脚本、源码及页面清单、环境副本和脱敏结果。环境与日志不导出。

[部署证据](../evidence/flagship-optimization-20260921/business-preview-refresh-20260924.json)由本仓库 `var/flagship/preview-refresh-20260924/candidate.json` 绑定本报告及清单摘要。原 E168 证据不覆盖或改写。
