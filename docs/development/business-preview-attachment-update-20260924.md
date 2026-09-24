# 项目附件权限修复已部署到本机预览

日期：2026-09-24。预览入口仍为 <http://127.0.0.1:15173>，后端已切换至 loopback **18087**，加载已通过 127 项回归的项目附件权限修复。主 API 18081、Qwen 模型和模型桥没有重启；客户端、企业端冻结候选未改变。

## 部署及实际检查

新 API：`siq-research-api-preview-attachment-20260924.service`，MainPID `2200486`，InvocationID `c876d6724f204f3d8d0649148ca38401`。

新 Web：`siq-research-web-preview-attachment-20260924.service`，MainPID `2201024`，InvocationID `c0cf4c4190f64821873f7f9d17ed1d11`。

新建源码清单包含 965 个 Python 源码及安装包文件，启动前核对；复用已验证的 282 项前端文件，无前端变更。两单元为手动 transient unit，`Restart=no`，没有新增开机自启。私有环境、日志和部署脚本保存在研究仓 `var/ops/flagship-preview-attachment-20260924/`。

七项部署检查通过：API 健康且保留恢复门禁；前端连接新 API；实际切回旧 API 18086；再恢复新版；结果接口匿名读取为 401/no-store；项目附件下载及历史接口匿名读取为 401；主 API、旧预览 API、模型及桥的 PID/InvocationID/重启次数均保持一致。

匿名检查验证真实部署入口的鉴权，没有代替 127 项临时文件/HTTP 测试中的项目授权正负向，也没有冒充真实业务账号验收。本预览继续保留 `enabled=false / required=true / ready=false` 的恢复门禁，不能据此宣称 OpenShell 生产执行已开放。

## 回退

已实际完成 Web → 18086 → 18087 切换。回退前确认保留的旧 API `siq-research-api-preview-result-20260924.service` 仍是 InvocationID `8e80e725060d4cafa55eda5bf784eefb`，并核验 18086 健康。停止新 Web 后，用既有 `flagship-deploy-e168/web/scripts/trial-server.mjs` 启动独立 Web，设置 `TRIAL_HOST=127.0.0.1`、`TRIAL_PORT=15173`、`SIQ_BACKEND_URL=http://127.0.0.1:18086`，然后检查代理健康及匿名拒绝；确认成功后方可停止新版 API。

部署脚本 `verify_switch.py` 保留本次实际执行的切换及失败撤回命令；其重新执行会切换预览，不是只读检查。旧 API 回退只在原进程仍存活时有效，不能拿已变化的工作区源码绕过旧摘要清单冷启动。当前新版同样为启动时核验的工作区源码，不是不可变镜像；后续源码变化必须创建新部署清单。

本次不执行数据库降级、不替换主 API、不宣称完成生产回滚。主服务部署、真实身份/组织联调及正式报告发布仍在原收尾清单中。

## 证据

[部署证据](../evidence/flagship-optimization-20260921/business-preview-attachment-update-20260924.json)记录七项检查、进程身份和部署脚本/清单摘要，由本批候选（本机私有路径：`var/flagship/preview-attachment-update-20260924/candidate.json`）引用。历史源码和部署证据没有改写。
