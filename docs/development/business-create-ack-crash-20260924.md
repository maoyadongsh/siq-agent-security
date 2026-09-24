# Hermes 创建已确认、任务 ID 尚未入库时的 API 崩溃验收

日期：2026-09-24。原 ML-02 故障验收中的这一指定窗口已通过；没有修改生产实现、冻结客户端或企业端候选。

## 实际结果

隔离候选 API 经真实 HTTP 登录和业务授权创建 Hermes/OpenShell 任务。诊断包装器等待真实创建返回，并经 Hermes 状态接口确认任务仍处于活动状态后，只向自身 API 进程发送 SIGKILL。数据库保留原占位执行，尚未写入已观察到的 Hermes run ID。

同库重启后不修改租约、执行行或时钟，也不手工推进 finalizer。等待约 **134.009 秒**后，原执行进入 `authority_lost`，最终释放记录为 `released`，恢复器重新就绪。只有原执行行，没有重放或换绑。独立核验沙箱、监督进程和转发均消失，子身份已撤销、旧凭据返回 401；当时诊断父身份仍有效，排除了父身份清理代替恢复器完成回收的情况。

隔离数据库已删除，临时 API 与身份服务端口关闭；既有 API、模型、桥及预览服务身份保持一致。预览前端代理和 API 健康检查均返回 200。

## 验证与来源

研究仓库新增 `scripts/openshell/prove_qwen38_create_ack_crash.py` 及相邻测试，只允许在 `isolated_candidate` 和指定候选端口注入故障。负向测试覆盖环境不符、创建失败、状态查询失败和已终态任务不触发故障；创建、查询、保存观察、终止的顺序有断言。

定向验证 **21 passed**，两个新增文件 Ruff 通过：

```sh
PYTHONPATH=apps/api:. apps/api/.venv/bin/python -m pytest scripts/openshell/tests/test_prove_qwen38_create_ack_crash.py scripts/openshell/tests/test_prove_qwen38_crash_api.py scripts/openshell/tests/test_prove_qwen38_business_api.py -q --disable-warnings --tb=short
apps/api/.venv/bin/ruff check scripts/openshell/prove_qwen38_create_ack_crash.py scripts/openshell/tests/test_prove_qwen38_create_ack_crash.py
```

真实证明使用 E165 家族的独立 **v2** 证据；此前 v1 的“模型输出后崩溃”证据保留，二者不是同一故障时点。源码与结果摘要见[脱敏证据](../evidence/flagship-optimization-20260921/business-create-ack-crash-20260924.json)，由候选清单（本机私有路径：`var/flagship/create-ack-crash-20260924/candidate.json`）绑定。原始日志及观察中的任务身份只保存在私有运行目录。

## 限制

这是合成业务授权下的真实创建与回收验收，`production_ready=false`，不验证完整模型回答质量。尚未证明创建响应丢失、未知子任务、结果提交中断等其他窗口；真实业务 IAM、审批和事件出口、相关授权边界、生产部署回退、原生 CI 与签名发行仍按总清单完成。本结果不能使原总目标直接结项。
