# E170：沙箱已创建、监督尚未启动时的 API 崩溃验收

日期：2026-09-23。本批补齐原任务中一个具体启动早期窗口的实际 API 验收，没有改变生产恢复策略或增加产品功能。

## 故障位置与方法

使用独立 18083 API、临时 PostgreSQL 业务库、合成企业授权、独立 47811 身份服务和真实 OpenShell 沙箱。诊断启动器调用原沙箱创建函数；只有该函数成功返回并持久保存原实例绑定后，才保存私有故障观察记录并向自身发送 SIGKILL。正式 API 启动入口不包含此故障开关。

父诊断进程独立确认：API 返回码为 SIGKILL、原监听关闭、业务行仍 running；创建记录与实际沙箱及 Docker 容器身份一致。此时请求身份签发、监督 manifest/state、Hermes endpoint 及完整 endpoint 恢复描述均不存在，故障没有漂移到正常执行阶段。

随后启动相同测试库的普通 API，不再加载故障注入。等待原租约自然到期，不修改时间或运行终态，不手工调用清理器代替后台恢复。

## 结果

- 实际 HTTP 请求因 API 死亡中断，恢复器最初等待仍有效的原租约。
- 同库重启后约 **121.031 秒**观察到原执行变为 `authority_lost`。此耗时包含等待原租约到期，不是清理延迟或 SLA。
- API 自身的 startup finalizer 已持久记录 released，沙箱独立确认消失，转发监听不存在，恢复器重新就绪。
- 没有建立 Hermes endpoint 或监督状态，没有恢复业务执行，也没有发起模型推理。
- 临时业务库、API 和身份服务已清理。原主 API、模型及桥身份不变；E168 预览 API/Web 的 PID、invocation 和重启计数也未变。

正常、流式、取消、崩溃、撤权、退出清理重试及新增早期故障证明器共 **48 项测试通过**，涉及四个 Python 文件的 Ruff 检查通过。本批只扩展诊断进程工厂并复用业务准备/验收逻辑，没有修改生产 API 或恢复组件。

## 证据与剩余范围

研究仓库真实证明为 `artifacts/openshell/flagship/ml02-business-early-crash-e170-v1.sanitized.json`，SHA-256：`090a2d9a9c9cc27a3f0425e30c2742b8e4588300a82ffa58a8d03d1930fcb63d`。验证命令与源文件摘要保存在 `var/ops/flagship-early-crash-e170/validation.sanitized.json`。

[脱敏证据副本](../evidence/flagship-optimization-20260921/business-early-crash-e170.json) 由本仓库 `var/flagship/e170-business-early-crash/candidate.json` 绑定。私有日志、凭据、原始故障观察记录不进入公开证据。

本批只证明“已记录具体沙箱实例、身份和监督尚未启动”的自动恢复。创建结果未知、监督启动后未保存 invocation 等窗口仍须单独验证保留占位、禁止重放和不误清理他人资源；不得从本批推导所有早期窗口已完成。实际业务身份、生产集成、正式切换、原生 CI、发行签名及升级回滚等原任务仍未完成。
