# E168：研究业务本机预览部署与撤回验证

日期：2026-09-23。范围是原标杆任务的 API/Web 部署准备，不增加产品功能，不替换冻结客户端或企业端，不表示生产切换完成。

## 入口与实际验证

本机 Web：<http://127.0.0.1:15173>。E168 独立副本构建的页面，通过既有代理连接新 API `127.0.0.1:18084`。API 加载研究仓库当前源码，启动前核对源清单；并非不可变源码部署。

已完成的检查：

1. `npm run build` 的 TypeScript 检查及 Vite 构建成功，256 个产物按 SHA-256 记录。
2. 新 API 健康响应 200，OpenAPI 包含 `/api/analysis/chat/result/list`；原 API 的同一路径为 404，证明预览加载了新路由。
3. 直接请求 API，以及通过 Web 代理请求结果列表、元数据，未登录均返回 401 和 `Cache-Control: no-store`。
4. Playwright 实际打开 1440×900、390×844 页面，均跳转 `/login`，用户名、密码、登录、注册入口存在，无页面脚本异常或横向溢出；两张截图已检查。没有计为登录后业务验收。
5. 实际停止本批两个预览服务，两端口关闭；旧 API 仍健康且进程身份不变。随后重启预览，两端服务、代理及新路由检查再次通过。

原 API `127.0.0.1:18081` 的 PID、调用身份、重启计数与部署前一致。部署前实际库有 1 条标记 running 的历史行、0 条未过期租约；没有清理该行。未创建账号、伪造登录或放宽认证；环境副本和原始服务日志仅保存在私有运行目录。

## 明确限制

原恢复管理器的合同限定主 API 端口 18081。预览保留 `SIQ_OPENSHELL_POOL_RECOVERY_REQUIRED=1`，不持有恢复权限，健康响应为 `enabled=false, required=true, ready=false`。依赖该恢复器的 OpenShell 执行仍被拒绝；本批不是完整业务执行上线。预览只绑定回环地址，没有公网入口或开机自启。

下一步须用指定真实业务身份验收登录后结果读取，再协调主 API 恢复权限及受控运行身份的正式切换。原目标的生产 IAM/审批/事件、剩余故障窗口、原生 CI、发行签名及升级回滚仍待完成。

## 撤回与证据

以下命令仅撤回预览，保留旧 API：

```bash
systemctl --user stop siq-research-web-preview-e168.service siq-research-api-preview-e168.service
```

这不构成旧源码恢复或数据库降级验收。E167 私有备份保持原权限。

研究仓库 `var/ops/flagship-deploy-e168/` 保存源码清单、构建清单、截图、`delivery.sanitized.json` 和私有部署脚本。[脱敏运行证据](../evidence/flagship-optimization-20260921/business-preview-delivery-e168.json) 由本仓库 `var/flagship/e168-business-preview/candidate.json` 绑定报告、证据与研究仓库源清单摘要。8 项部署检查通过，不扩大其证明范围。
