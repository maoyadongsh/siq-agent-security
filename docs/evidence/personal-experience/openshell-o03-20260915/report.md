# OpenShell O03 子进程边界验收（2026-09-15）

结论：O03 的 Go/Python 传输实现与 Linux 组件验收完成；总体 P0 尚未完成。工作树 `kimi/personal-v4-r01-20260914`，HEAD `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 加未提交修改；未提交、未推送、未发布，未替换正在运行的服务。

## 改动与负向证据

- Go CLI 与 Docker 发现改走共享预算 writer。stdout/stderr 在读取时合计限额，默认 2 MiB，溢出立即取消直接子进程，超时与退出后的管道等待有界。
- Python 对非阻塞管道分块读取，统一字节预算，不使用无界 `capture_output`；无常驻读线程，退出后保留管道超过 200ms 即失败。只清理直接拥有的子进程及本地管道，不宣称全部后代终止。
- 两端仅继承精确基础环境键。CLI/endpoint 在父进程生成 argv，不透传任意 `SIQ_AS_*`/`OPENSHELL_*`，过滤 BASH_ENV、代理和动态加载器配置。用户显式 env.sh 仍是受信任可执行配置，可以自行设置环境；不是针对恶意启动脚本的隔离边界。
- 非零 CLI 错误不再包含参数或 stdout/stderr；保留稳定错误类别与 Go 的错误网关诊断。无法解析的 policy set 成功响应和 Python YAML 异常也不回显原文。
- 共用 `testdata/openshell-command-budget.v1.json` 测空输出、共享恰限/+1 和 UTF-8 字节边界；两端另有真实子进程持续输出、超时、继承管道、失败错误、合成秘密环境与诊断测试。实际使用本机测试可执行文件/Python 解释器，无模型、网关或第三方网络。
- 旧测试中依赖原始命令文字的断言改为稳定错误码；保留新版网关失败不走 Docker 回退的行为断言。首次 Go 共享向量测试暴露 helper 的参数分隔错误，修正为 `-- --emit` 后原断言通过，没有放宽字节边界。

## 验证

工作目录 `apps/agentshield`：

```bash
go vet ./...
go test ./...
go test -race ./internal/openshell
```

以上通过。四目标使用 `CGO_ENABLED=0 GOOS=<os> GOARCH=<arch> go build -trimpath -o <临时文件> ./cmd/agentshield`；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 全通过，摘要见 [cross-builds.json](cross-builds.json)。交叉构建不代表 OS 实机通过，临时二进制已清理。

工作目录 `apps/control-api`：

```bash
uv run pytest -q
uv run pytest app/tests/test_openshell_cli_backend.py app/tests/test_openshell_adapter.py app/tests/test_openshell_bounded_command.py -q
uv run ruff check app/adapters/openshell/bounded_command.py app/adapters/openshell/cli_backend.py app/tests/test_openshell_bounded_command.py ../../scripts/personal-experience/openshell-native-component-baseline.py
```

完整回归与 53 项定向检查通过；Ruff 通过。环境原有 Starlette/httpx 弃用提示不影响结果。Go 格式和 `git diff --check` 通过。Web 无本批改动，不重复生成其资源。

## 性能初始观察

[组件报告](../openshell-native-component-20260915-020537/report.json)由 `python3 scripts/personal-experience/openshell-native-component-baseline.py` 生成，复用已有 `TestRuntimeStageBaseline`，临时编译 `receipt.test`、5 次预热后采集 100 次决策以及各阶段原始样本。报告绑定测试二进制、脚本和 Go 源码摘要。

本次 `decision_total` P50/P95/P99 为 7.337589 / 8.371020 / 8.912913 ms。它是固定合成请求、真实本地密码学/状态的**组件观察**，没有启动宿主或沙箱，不覆盖完整 SEC/审批旅程，也不是 B1−B0 或 B3−B2 对照。尚未测量 CPU、真实 RSS、写入/网络/进程计数和端到端延迟，门槛未冻结；因此 O00/O04 保持未完成。

## 未关闭的风险与下一批

O01 完整策略保留、严格 revision、deny/L7 拒绝及静态差异规划仍待实现；O02 精确快照/授权回滚与漂移防护仍待实现；O04 当前能力探测与性能门槛仍待。不能用本报告宣布 `openshell-policy-safety/v2` 全部实现，也不能把当前读回当作真实隔离证明。

Go 的 WaitDelay 与 Python 非阻塞管道均不提供完整进程树停止保证。Windows/macOS 的真实超时/管道/环境行为由对应平台补验，Python 非阻塞管道不可用时失败关闭。当前没有可用 OpenShell 网关，O05/O06 不能借组件替身升级真实支持状态。

此次构建产生新二进制身份；旧 N09 六条原生腿继续是旧候选证据，未改写其摘要、未提升任何 complete_acceptance。下一批从 O01 开始，并继续独立的 Linux R04–R07 工作。
