# 业务结果独立读取边界（E156）

日期：2026-09-23。UX-11 业务结果接入第一段，总目标保持 active。

## 当前结果

已在研究 API 增加真实业务授权下的结果接口，并在安全项目定义三个跨仓合同。元数据 GET 不返回正文；正文 POST 需要明确确认、准确运行定位和预期结果快照。读取前后分别核对当前账户/精确数据授权、原 state/route/run_id 和正文摘要；撤权、同会话新运行、内容变化或子任务未结束均不能返回先前选中的正文。

接口只表示 `generated_reply`，`publication_status` 固定 `not_attested`。这解决业务源读取边界，没有把模型回复或工具成功当作已发布报告。**安全控制台尚未连接这两个接口，也未新增报告按钮；正式报告子项仍未完成。**

## 两个仓库的改动

| 仓库 | 改动 |
| --- | --- |
| siq-agent-security | `packages/contracts/siq-business-run-{result,read,content}.v1.schema.json`、研究 API 实际 HTTP 响应的合成样本、合同负向测试、规格与进度 |
| siq-research-engine | `services/business_run_results.py`、`routers/agent_business_results.py`、只在 siq_analysis 注册路由的增量、业务接口测试和 `docs/architecture/business-run-result-access-v1.md` |

没有跨仓导入模块或查业务数据库。业务侧使用原有 `get_current_user` 和独立业务数据授权服务，不接收调用者指定 tenant/owner，不创建或切换会话，不续租或启动执行。输入有界、严格确认布尔、未知字段/重复键拒绝；错误不回显输入。匹配路由响应含 no-store。

元数据区分运行/后处理/终态以及 pending/empty/too_large/ready；仅运行与子任务均确认终态的非空文本可读，限制为 1 MiB UTF-8，超过限额不截断冒充完整输出。内容保持原字符串，不执行或转义为 HTML。

## 验证

- 研究 API **108 项组合测试通过**，其中新增结果接口 **24 项**。真实 FastAPI 路由与临时 SQLite 账户/数据授权表；认证主体是测试身份，匿名路径使用原依赖拒绝。覆盖撤权、到期、禁用账户、令牌版本、公司范围变化、跨用户/错运行、运行替换、读取中撤权/正文变化/换 run_id、后处理与子任务未终态、空值、UTF-8 超限、恰好 1 MiB 边界、错误输入不回显、禁止创建/切换会话。
- 安全项目合同 **275 项通过**，新 3 项用研究 API 真实测试响应样本验证版本、必填、额外字段拒绝、确认、写静默一致性及不伪造已发布报告。
- 新 Python 模块/测试 Ruff 通过，两仓 `git diff --check` 通过。既有 datetime/Starlette 弃用提示保留。

命令：

```bash
# siq-research-engine/apps/api
PYTHONPATH=../..:. .venv/bin/python -m pytest \
  tests/test_business_run_results.py tests/test_agent_runtime_read_access.py \
  tests/test_siq_security_export.py tests/test_governed_analysis_entry.py \
  tests/test_qwen38_request_selector.py tests/test_agent_runtime_history.py -q

# siq-agent-security/apps/control-api
.venv/bin/python -m pytest app/tests/test_schema_contracts.py -o addopts='' -q
```

首次测试缺少研究项目根的 PYTHONPATH 导致导入失败，补齐后重跑；该失败不计通过。核对实际状态机后补齐 postprocessing，再完成上述最终组合测试。测试是进程内 HTTP 与临时数据库，不是在线业务 API、生产 IAM、真实模型或沙箱验收。本批未改 Web/Go 实现，没有重复运行其全量测试或构建。

## 限制、回退及下一段

这两个接口目前只读取业务运行缓冲。API 重启、缓冲清理或被同会话后一次运行替换时返回 404，不从聊天内容猜测归属。这是明确未完成项，不能视为历史结果访问已完成。

后续须继续：

1. 持久保存准确 run/tenant/user/session 与原业务 scope 的结果归属，跨进程后仍可独立重新授权；补齐终态写入和中断窗口。
2. 建立正式产物与运行的不可变绑定、发布核验、准确版本及业务授权下的目录/读取。当前发布工具主要有固定测试发布合同，不能按模型中的 URL 或 workspace 推断记录直接升级。
3. 接控制台显式业务连接、可信运行映射和结果导航；继承业务身份，不用本地管理员身份替代业务权限。
4. 真正完成业务 HTTP → Hermes/OpenShell → 产物发布 → 页面查看的验收后，再关闭 UX-11 正式报告子项。

[证据清单](../evidence/flagship-optimization-20260921/ux-business-result-access-e156.json) 固定两仓源码、合同样本及验证日志。源码候选未部署，未替换 E155 客户端或重启业务服务；无迁移、新依赖、模型调用或业务数据修改。回退本批新路由/模块及合同即可，保留既有用户改动。未提交、推送、发布；SEC-F01–F10 继续后续执行。
