# E169：退出清理失败后的自动重试

日期：2026-09-23。本批关闭原标杆任务中的“失败 ExecStopPost 自动重试”缺口，不扩展客户端功能，也不表示生产集成全部完成。

## 问题与修复

研究业务的仅清理适配器原先在固定 systemd 单元的 ExecStopPost 失败后，只重新读取终止状态；即使外部依赖恢复，也不会再次执行清理。新增测试首先复现 `supervisor_service_recovery_unconfirmed`。

修复位于研究仓库 `scripts/openshell/qwen38_supervisor_service.py`。只有在原单元、原 invocation、manifest、运行摘要均匹配，MainPID/ControlPID 均为零且退出清理明确非零退出时，后续 API 扫描才可执行一次有界的固定 `recover` 子进程。它不调用 start/restart、不续租、不恢复智能体执行。失败继续保留占位及执行记录。

成功必须同时满足固定回包、contained 状态、原单元身份未变；随后新建私有重试证明，绑定 manifest、invocation、终止单元和状态摘要。磁盘重载核对证明后不重复清理。原 ExecStopPost 的失败保留，不改写为成功。损坏证明、符号链接、权限不符、活动子进程或身份替换均拒绝。

研究架构合同同步到 `docs/architecture/qwen38-request-runtime-v1.md`，既有诊断清理允许列表加入新证明文件。

## 实际故障验收

独立 18083 API、临时 PostgreSQL 业务库、独立 47811 身份服务、真实 Hermes/OpenShell 与本地 Qwen 模型参与；仅使用合成业务资料和授权。

1. 收到真实模型 delta 后，SIGKILL 本次测试 API，并停止本次自建身份服务。
2. 同库重启 API，等待原执行租约自然到期。没有手工改时间、运行终态或授权记录。
3. 独立确认原 ExecStopPost 非零退出，API 恢复扫描失败且未就绪，原执行仍为 running，没有成功重试证明。
4. 恢复相同状态目录的身份服务；诊断没有手工调用 finalizer，也没有创建新根授权或替换执行身份。
5. API 自动重试。身份服务恢复后的观察窗口约 **6.555 秒**，原执行变为 `authority_lost`，finalizer 持久记录 released；该时间不含模型等待及原租约到期等待，不是 SLA。
6. 原沙箱、监督和转发进程消失，子身份已撤销，旧子凭据返回 401；诊断根身份在清理前仍有效。磁盘重载独立确认重试证明，原失败 ExecStopPost 仍可读回。

模型桥首响应为 200，流中断后的终态为 502，仅证明真实输出后中断。没有把中断记成完整模型回答成功。

临时 API、身份服务及测试库均清理。原主 API、模型服务、模型桥身份不变；E168 预览 API/Web 的 PID、invocation、重启计数也未变。没有替换在线 API 进程或重新发布客户端。

## 验证与证据

- 清理、恢复、finalizer、启动恢复、systemd 适配器组合：**189 passed**（324 条既有弃用告警）。包含 19 项新增重试测试；首轮旧行为失败，扩展测试发现符号链接错误未归一，修复后最终通过。
- 新故障证明器及既有 API 崩溃证明器：**16 passed**。
- 六个涉及的 Python 文件 Ruff 检查通过；最终源文件摘要与验证记录匹配。

执行命令以研究仓库 `var/ops/flagship-cleanup-e169/validation.sanitized.json` 为准。真实证明：`artifacts/openshell/flagship/ml02-business-cleanup-retry-e169-v1.sanitized.json`，SHA-256 为 `710fcd10048f5b16b24db20b5c190f34398d083f22a28ac7c96c8f3f67e515f5`。

[本批脱敏证据](../evidence/flagship-optimization-20260921/business-cleanup-retry-e169.json) 由 `var/flagship/e169-business-cleanup-retry/candidate.json` 绑定。私有日志、凭据和合成业务原始输出不进入该证据。

## 剩余边界

该缺口已关闭。未知创建结果/缺失 invocation 等其他早期恢复窗口、其他宿主检索隔离、真实 IAM/审批/事件、正式服务切换、原生 CI 以及发行签名/升级回滚仍按原任务验收。合成账号的真实 HTTP 登录不能替代实际业务身份验收。整体目标仍未完成。
