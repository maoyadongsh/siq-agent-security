# E171：启动结果未保存时的保留与核对验收

日期：2026-09-23。本批验收两个指定持久化中断窗口，不改变生产恢复策略，也不把未知状态改成自动采用当前实例。

## 两个真实故障点

| 模式 | SIGKILL 位置 | 重启 API 所见的缺口 |
| --- | --- | --- |
| create | 原 OpenShell 创建与独立实例观察完成之后、写入 created 状态之前 | 沙箱实际存在，但持久状态仍为 creating，没有实例 ID |
| invocation | 原固定监督单元已经启动并返回 invocation、API 保存该 invocation 之前 | manifest 已保存，starting 记录的 invocation 仍为空 |

每轮使用独立 18083 API、临时 PostgreSQL 库、合成企业授权和独立 47811 身份服务。注入仅位于诊断启动入口；正式 API 不包含该开关。父诊断进程在重启前独立确认本次实际沙箱；第二轮还核对固定单元、原 invocation、活动 MainPID。

## 已验证的安全行为

普通 API 同库重启后，先等待仍有效的原租约。自然到期后，两轮均确认恢复扫描失败、ready=false，原执行行仍 running、原租约未延长、原 gateway owner 不变，缺失记录未被猜测补齐，也没有新 endpoint 或 released 证明。观察等待分别为 120.024 秒、120.062 秒，包含原租约到期，不是故障处理 SLA。

随后由诊断程序使用故障发生时独立保存的原始观察记录核对本次实例。第一轮重新核对实际沙箱/容器，第二轮使用原 invocation 确认监督已终止并完成其退出清理。持请求及 owner 锁复核原缺失记录未变化后，先新增私有诊断核对记录，再补入已捕获、已复核的原结果。

只有这一步完成后，API 才通过原 startup finalizer 自动释放资源，将原执行置为 `authority_lost`。两轮均确认 released 证明、沙箱消失、转发不存在、剩余 running 数量为零，临时库及进程全部清理。原主 API、模型/桥、E168 预览 API/Web 均保持原进程身份。

**本批证明的是“未知时保留并拒绝执行，独立核对后收敛”。不证明未知状态可自动恢复。** 诊断核对依赖本次测试控制器提前保存的观察；不能在生产故障中缺少该观察时，直接用当前任意实例填充原记录。未运行模型推理，也没有恢复旧业务执行。

## 代码、测试与证据

研究仓库新增 `scripts/openshell/prove_qwen38_unknown_startup.py` 及对应测试；候选证明器只增加两个允许的诊断标签。精确故障触发、非候选环境拒绝、未持久化原结果及相邻证明器共 **32 项测试通过**，三文件 Ruff 通过。生产恢复组件未修改。

真实证据及 SHA-256：

- `artifacts/openshell/flagship/ml02-business-unknown-create-e171-v1.sanitized.json`：`596efd77a06c1ba0a5a0242320d4c5afde348308a0b3270ee567605dc076d509`。
- `artifacts/openshell/flagship/ml02-business-unknown-invocation-e171-v1.sanitized.json`：`7da75b12b40c75f650c7b2b4f727385b25210cdfd005a7b73268c03adf55e408`。

每份证据均明确 `diagnostic_reconciliation_required=true`、`production_ready=false`。[本批脱敏证据](../evidence/flagship-optimization-20260921/business-unknown-startup-e171.json) 由 `var/flagship/e171-business-unknown-startup/candidate.json` 绑定；原始观察、凭据及私有日志不进入证据副本。

## 原目标边界

本批关闭上述两个具体窗口的真实保留/核对验收。它们与 Hermes 业务 run 创建响应未知、运行中的未知 child、业务结果提交故障不是同一个故障点，不能相互代替。其他宿主检索边界、实际业务身份与生产集成、正式切换、原生 CI、签名及升级回滚等原目标工作仍继续。
