# 报告与导航功能的数据库及本机页面交付

日期：2026-09-24。本轮将此前完成的报告确认、报告发布/读取与事件导航研究端代码接入现有本机页面，同时完成实际数据库前置迁移。入口仍为 **http://127.0.0.1:15173**，后端现为 **127.0.0.1:18089**。

这不是完整生产切换：主 API 18081 未重启；企业安全控制端的新导航代码未在生产 IAM 环境部署；本机页面继续保留执行恢复门禁。真实业务身份授权、连续跨站登录及原发行签发仍待完成。

## 实际数据库迁移已完成

通过在线主 API 的自有进程树读取实际数据库连接，仅在内存及受控子进程环境中使用凭据。确认备份容器与 API 连接指向同一个 PostgreSQL cluster 后，完成以下操作：

1. 固定官方 runner、审计器、SQL 与 checksum 清单，核对唯一待应用项为 `024_create_business_report_publications.sql`。
2. 创建 0600 完整私有备份，实际恢复到新建独立数据库；恢复后的原迁移账本完全一致。
3. 在恢复库执行官方带锁/checksum runner，核对报告草稿、发布表存在且为空，审计为 current。
4. 再次确认实际库账本与主 API 身份未变后，应用同一份 024。001–023 的历史账本保持不变，重复运行无新增迁移。
5. 删除恢复演练库，保留私有备份，主 API 保持原进程。

备份大小 6,080,107 字节，SHA-256 `483f8719a4e66759de432be6e6405c72d4c4e0c913f4ae569af9b6699a06db3b`，位于研究仓 `var/ops/flagship-report-delivery-20260924/siq_app.before.private.dump`。包含业务数据，不提交、不公开。迁移前有 1 条 running 历史行、0 条未过期 running 租约；没有更改或删除该行，也没有以租约过期推断远端执行已停止。

本次仅增加草稿/发布表、约束、索引和迁移记录，不创建业务账号、不发放权限、不发布实际报告。回退应用代码时保留这些新增表及审计账本，不执行数据库降级。

## 当前实际部署

| 对象 | 当前值 |
| --- | --- |
| 页面 | `http://127.0.0.1:15173` |
| 新 API | `siq-research-api-delivery-20260924.service`，18089，InvocationID `86d6ba75967d42a7ad3681e86d9a781b` |
| 新 Web | `siq-research-web-delivery-20260924.service`，15173，InvocationID `0e8e6c405b9e41c9b6d0011331c86bce` |
| 上一版回退 API | `siq-research-api-preview-errors-20260924.service`，18088，保留原进程 |
| 交付目录 | 研究仓 `var/ops/flagship-report-delivery-20260924/` |
| 源码校验 | 994 项 Python/安装包源码启动前校验；仍在工作区运行，不冒充不可变 API 镜像 |
| 前端制品 | 263 项文件，复制到独立 `web/`，完整摘要校验；包含实际报告、审核与事件导航页面 |

新增接口已从实际 OpenAPI 读回：执行确认、由安全事件定位结果、报告发布、版本读取。实际 API 和页面代理均验证匿名 GET/POST 返回 401/no-store；不能由未登录请求读取结果或提交报告发布。实际页面导航到事件入口与报告目录均进入业务登录；375px 手机登录页面无横向溢出。没有用匿名登录页检查代替已授权业务操作验收。

执行状态仍是 `openshell_recovery={enabled:false, required:true, ready:false}`，Qwen request recovery 未启用。此部署提供新代码和页面入口，**不宣称依赖恢复器的新 OpenShell 业务执行已经开放**。不通过关闭 required 或伪造 ready 消除门禁。

## 回退与旧进程清理

本轮实际执行了“新 Web/API → 旧 Web/API 18088 → 新 Web/API 18089”，两次都检查页面代理和健康。主 API、模型及模型桥身份保持不变。两个新服务为手动 transient unit，`Restart=no`，没有新增开机自启。

若要回退，先确认 18088 原进程身份仍与本批 `deployment-before.sanitized.json` 一致，且健康；停止新 Web，恢复 `siq-research-web-preview-errors-20260924.service` 的原配置。若 transient unit 已被收集，须按本批 `deploy_web.py` 的旧 Web 分支重新建立：使用原 `flagship-deploy-e168/web` 摘要锁定目录、loopback 15173、代理 18088。检查成功后再考虑停止新版 API。`deploy_web.py` 是会切换服务的执行脚本，不是只读检查；不要重复执行并覆盖本批输出。

已停止四个本轮较早创建、身份与历史记录一致且没有 HTTP 连接的预览 API：E168、20260924 refresh、result、attachment（18084–18087）。未删除任何源码、日志或证据。保留主 API 18081、回退 API 18088、新 API 18089 和现有页面。历史文档中依赖 18084–18087 存活进程的回退步骤现在失效，以本报告的 18088 入口为准；不能用已变化的工作区源码冒充旧进程冷启动。

## 验证与剩余项

数据库七项实际检查、页面部署/回退七项检查、部署后浏览器三项检查通过；旧预览清理后，主 API、18088、新 API/Web 进程身份均未变化。前一批源码及行为测试仍有效，本轮没有重复运行无改动的模型生成测试。

当前还需：既有主执行服务的安全切换与实际恢复权限、真实业务/IAM/组织联调、企业控制台 origin 接入、连续跨站身份验收，以及发行候选更新、正式签发/安装升级和原任务平台门禁。本轮推进了实际数据库和现有页面交付，没有把这些待办改写为完成。

本批[脱敏证据](../evidence/flagship-optimization-20260921/business-report-deployment-20260924.json)由 `var/flagship/report-deployment-20260924/candidate.json` 引用；私有环境、日志、备份不进入证据正文。
