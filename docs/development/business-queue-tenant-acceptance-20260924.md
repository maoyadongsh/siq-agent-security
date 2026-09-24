# 排队授权过期、第二租户及错误提示收尾

日期：2026-09-24。对应原研究运行时合同的排队过期、第二租户请求要求。两项真实 HTTP 验证通过，并修复验证中发现的通用 500 响应问题。

## 真实排队过期

独立候选 API 18083、临时 PostgreSQL、真实登录及管理员 HTTP 签发的 60 秒合成公司授权。诊断仅用正式 owner 组件保留独立候选网关的合成占位，不运行其他模型任务。真实业务请求进入原 API 队列，观察到原执行行及 pending 记录时授权仍有效；等待自然到期，没有修改时间、授权期限或执行租约。

v2 等待 **59.589 秒**后返回 **503**，固定中文说明、`request_start_unconfirmed`、`retryable=false`、`Cache-Control: no-store`。原执行 failed、pending released，仍为同一 provisional run；没有新的执行行、请求目录或沙箱，原网关占位保持不变。验证后按原绑定释放诊断占位、撤销诊断授权、删除临时数据库，监听关闭。

v1 已通过隔离/清理检查，但响应为通用 500；历史证据保留，不冒充新版错误响应验收。该用例证明实际排队和授权失效处理，不是两个模型同时运行或模型性能测试。

## 第二服务端租户

另一个独立候选与临时数据库先在 `default` 租户下完成真实 HTTP → Hermes/OpenShell/Qwen 请求，得到合成标记、模型桥 200、终态与释放证明。随后停止本次 API，以不同的服务端 `SIQ_DEFAULT_TENANT_ID` 启动同端口候选，数据库、认证密钥和用户编号保持一致。

两次 `/api/auth/me` 确认相同已登录用户编号，原租户 grant 尚未到期且未撤销；第二租户相同资料请求返回 **403**。数据库读回确认原 grant 和原执行行没有变化，未新增执行行或沙箱。最后恢复原候选租户，完成原 HTTP 撤销流程和临时资源清理。

v1 原租户业务成功，但第二租户接口返回 500，整轮判为失败并保留证据；修复后 v2 通过。此为两个服务端配置租户的顺序请求隔离，不声称生产 IAM、多租户并发或真实组织成员管理通过。原合同要求第二租户请求，不将此前矩阵中额外写入的“并发”扩充为新的结束条件。

## 实际修复与验证

`RequestSelectionError` 此前未注册 HTTP 处理器，拒绝和启动未确认异常冒泡为通用 500。现在访问校验拒绝返回 403，启动未确认/未知选择错误返回 503，只提供固定公共错误码和中文说明。未知启动不指示自动重试，不改变执行租约或清理规则。

流式启动异常发出一个同语义 error 事件，不发成功 done，不调用通用 provisional 释放。三个 HTTP 负向测试在旧代码均失败；修复后的注册处理器、内部异常脱敏和实际流式分支测试通过。

最终组合 **225 passed / 1 skipped / 547 warnings / 91.90 秒**。唯一跳过项因未设置 PostgreSQL 测试地址；随后在新建独立 PostgreSQL 数据库补跑该项，**1 passed / 5 warnings / 1.39 秒**，临时库删除。本批选定的 226 项不同用例均已执行通过，不将更早重叠回归累加。涉及 Python 文件 Ruff 和定向 diff 检查通过。

组合模块为 `test_qwen38_http_errors`、`test_qwen38_request_selector`、`test_qwen38_request_queue`、`test_qwen38_request_api`、`test_qwen38_request_finalizer`、`test_runtime_startup_guard`、`test_governed_analysis_entry`、`test_business_run_result_store` 及诊断模块 `test_prove_qwen38_{queue_expiry,tenant_boundary,business_api}`。补跑节点为 `test_business_run_result_store.py::test_postgres_migration_concurrent_insert_and_reauthorization`。命令均从研究仓根以 `PYTHONPATH=apps/api:. apps/api/.venv/bin/python -m pytest` 执行，附 `-q --disable-warnings --tb=short`。

## 预览部署及回退

修复已加载到 <http://127.0.0.1:15173> → **18088**。新 API 单元 `siq-research-api-preview-errors-20260924.service`，MainPID `2330015`、InvocationID `4ea91698d53a44e889d5350fe41e9736`；Web 单元 `siq-research-web-preview-errors-20260924.service`，MainPID `2330539`、InvocationID `455ec8fa80264fb1a8c7e19c4668686b`。

新建 971 项源码/安装包摘要清单，复用 282 项前端文件。七项部署检查通过，包含 Web 切回 18087、再恢复 18088 的实际演练，以及真实入口匿名拒绝和主服务/模型/桥进程身份不变。主 API 未部署本修复，预览仍保留必需恢复门禁，不因此开放正式 OpenShell 执行。

部署及回退脚本位于研究仓 `var/ops/flagship-preview-errors-20260924/`。回退前确认旧 API 18087 的 InvocationID 仍为 `c876d6724f204f3d8d0649148ca38401`，先停止本批 Web，再按 `verify_switch.py` 中原 Web 配置连接 18087，核验健康及匿名拒绝后才停止本批 API。该脚本会切换预览，不是只读检查。旧源码摘要不可用于变化后的代码冷启动；这不是数据库降级或生产回滚证明。

## 证据及剩余事项

[本批证据](../evidence/flagship-optimization-20260921/business-queue-tenant-acceptance-20260924.json)保存 v1/v2 结果、源码摘要、测试范围和部署身份，由候选清单（本机私有路径：`var/flagship/queue-tenant-acceptance-20260924/candidate.json`）绑定。原始响应、日志及环境留在私有目录，不复制到公开证据。

历史矩阵和候选摘要保持不变，其队列/第二租户“尚未核实”现由本报告补齐。已复核 E105/E106 原证据，明确是组件演练；正式 API 下监督退出、数据工具到正式报告发布/授权读回仍须完成。真实 IAM/审批/事件出口、固定模型质量/性能、原生 CI、生产部署与正式签发继续按原清单管理，整体目标未完成。
