# DGX Spark 原生 CI：启动修复与远端就绪检查

日期：2026-09-24。属于原任务 CI-01 的收尾，不增加新的生产门禁。

## 发现与修复

原工作流使用 `${{ toJSON(runner.labels) }}`。GitHub 的 [runner 上下文](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#runner-context)没有 `labels` 属性，不能据此取得调度标签。

新增 `scripts/dgx_spark_runner_labels.py`，通过 GitHub 的[当前运行尝试作业列表接口](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt)获取当前 `native-candidate` 作业。它核对运行 ID、尝试、提交 SHA、runner 名称及正在执行状态，标签来自接口返回，不使用固定标签替代现场证据。

工作流仅增加 `actions: read` 权限；短期 `github.token` 只作为该读取步骤的环境变量。请求固定到 GitHub HTTPS API，禁止重定向和环境代理，设置超时与响应大小限制；缺失、重复、不完整或不匹配的作业均拒绝。输出仅为校验后的标签环境变量；错误日志不输出令牌或接口正文。

工作流守卫同步拒绝旧 `runner.labels` 写法、静态预设标签、缺失只读权限或缺失实际读取步骤。原 DGX Spark/GB10、干净仓库、固定提交、实时 doctor、资源审计和四组回归要求不变。

## 验证

```bash
python3 -m unittest discover -s deploy/dgx-spark/tests -p 'test_*.py' -q
python3 scripts/check_dgx_spark_native_candidate_workflow.py
apps/control-api/.venv/bin/ruff check \
  scripts/dgx_spark_runner_labels.py \
  scripts/check_dgx_spark_native_candidate_workflow.py \
  deploy/dgx-spark/tests/test_runner_labels.py
```

门禁单测 **40 项通过**，包含新增 9 项测试及其负向子用例；工作流守卫、修改文件 Ruff 和差异空白检查通过。新接口读取的单测使用合成 GitHub 响应，不伪称当前已经存在实际 native-candidate 作业。

另通过现有受控 GitHub CLI 登录进行了真实只读查询，观察到：

- 仓库 runner 列表查询成功，`total_count=0`，没有符合所需标签的在线 runner。
- 仓库工作流列表查询成功，远端未出现 `.github/workflows/dgx-spark-native-candidate.yml`。

本轮未注册 runner、未创建注册令牌、未提交/推送工作流、未触发或伪造 CI 运行。没有改动 DGX 上运行的 API、模型或 OpenShell 服务。

## 结论与剩余依赖

原生 CI 的工作流启动缺陷已修复，但 **CI-01 尚未通过**。除锁定模型在线与三个仓库的固定干净源码外，远端确实还需要发布固定源码的工作流、接入具备规定标签的 DGX Spark runner，再取得同批次原生运行证据。普通本地单测不能替代该记录。

这些操作涉及当前尚未提供的受控 CI 接入与固定源码发布，不能通过给本机命令填入虚构的 GitHub 运行信息绕过。原任务其余工程工作可继续进行。

[远端查询脱敏证据](../evidence/flagship-optimization-20260921/native-ci-readiness-20260924.json)绑定本轮修改文件摘要；本仓库 `var/flagship/native-ci-preflight-20260924/candidate.json` 绑定报告与证据。客户端、企业端冻结候选和当前本地预览保持不变。
