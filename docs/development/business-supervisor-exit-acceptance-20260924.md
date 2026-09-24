# 监督退出终态核对与实际验收

日期：2026-09-24。结论：v4 实际业务 HTTP 故障验收通过，关闭收尾清单中的监督退出终态缺口。生产代码未修改，固定客户端和企业端候选未变；整体标杆目标尚未完成。

## 结果与原合同

真实业务 HTTP → Hermes/OpenShell/Qwen 产生模型正文后，诊断通过 pidfd 终止原请求固定监督进程。原业务 API 保持同一进程，无重启；SSE 一个 run、两个 delta、一个 error，没有成功 done。流式错误和执行资源记录承担不同职责：业务流报告失败，执行资源由恢复器在原租约自然到期后记为 `authority_lost`。

运行状态的各次观察中，原租约未续期；恢复终态发生在原截止时间之后。原绑定及同一 run 保持一致，持久 finalizer 已在诊断清理前进入 released，监督进程、沙箱和 forward 均消失。子身份在父身份仍有效时已撤销，旧子凭据 HTTP 401。随后才撤销诊断父身份和业务授权、删除临时 PostgreSQL 数据库并关闭隔离 18083/47811 服务。既有主服务、模型、桥及预览身份未变。

模型桥开始状态 200，故障后终端状态 502，符合执行被终止的场景，不记作正常生成成功。这里使用实际业务入口和真实运行组件，但身份、公司及消息为隔离合成资料，不替代生产 IAM 和真实企业资料验收。

## 诊断修正及失败历史

原恢复合同与实现已经规定：原租约过期且资源确认回收后写 `authority_lost`。v2 只接受 `failed`，而且没有保存实际数据库终态，因此历史证明保持失败。

v3 保存了实际 `authority_lost`，但把终态 `lease_until` 与运行截止时间直接比较。生产 `release_active_run_sync` 会将该字段改为关闭时间，这不是续租。对此增加了同一执行的独立只读观察：395 次读取确认运行租约未变，原截止时间后记录终态；观察产物单独保留，不把它改写成 v3 整轮通过。

最终诊断在 running 时检查截止时间不变，在终态检查关闭时间与更新时间、当前时间的关系；失权恢复还必须晚于原截止时间。成功终态、未来关闭时间、提前失权和运行中续租均拒绝。v4 用该诊断重新执行全链路，全部检查通过；v1–v3 失败历史不改写。

## 定向验证与交付

研究仓执行：

```sh
PYTHONPATH=apps/api:. apps/api/.venv/bin/python -m pytest scripts/openshell/tests/test_prove_qwen38_supervisor_exit.py -q --disable-warnings --tb=short
PYTHONPATH=apps/api:. apps/api/.venv/bin/python -m pytest apps/api/tests/test_qwen38_request_recovery.py::test_scan_defers_valid_original_lease_without_renewing_or_stopping apps/api/tests/test_qwen38_request_recovery.py::test_expired_scan_releases_exact_request_and_records_authority_lost -q --disable-warnings --tb=short
apps/api/.venv/bin/ruff check scripts/openshell/prove_qwen38_supervisor_exit.py scripts/openshell/tests/test_prove_qwen38_supervisor_exit.py
```

分别为 **20 passed**、**2 passed / 6 warnings**，Ruff 通过。未重跑无关全量回归。修改只涉及诊断、诊断测试和终态说明，不需要部署新生产服务。

v4 原始脱敏证明摘要：`f46534a18b9cc5e9385936f26e0377d200d99a369f9e71a5e93809c1bc06edf9`。实际启动器、失败历史、只读观察及源码摘要见[本批证据](../evidence/flagship-optimization-20260921/business-supervisor-exit-acceptance-20260924.json)，由候选清单（本机私有路径：`var/flagship/supervisor-exit-acceptance-20260924/candidate.json`）绑定。私有日志、模型正文及凭据不进入报告。

接下来的工程工作是正式报告发布、归属和当前授权下读取；真实企业集成、模型/平台门禁及签名发行仍按[收尾清单](flagship-closeout-20260924.md)管理。未知状态的保留与诊断补偿边界未放宽。
