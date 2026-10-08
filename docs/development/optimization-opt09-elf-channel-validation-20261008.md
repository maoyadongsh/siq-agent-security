# OPT-09：静态 ELF 与有界回显观测通道

日期：2026-10-08。任务保持 `implementing`。本批实现真实探针程序与传输通道，但尚未证明真实 OpenShell 目标的程序路径归因，也未提升企业部署等级。

## 行为与边界

新增 [agent v1 合同](../../packages/contracts/openshell-behavior-agent.v1.schema.json)、[静态 Go 探针](../../scripts/enterprise-experience/probe/behavior_probe.go)和控制面 `behavior_channel.py`。两份探针文件内容相同，只改变绝对路径；程序实际读取 `/proc/self/exe` 路径与 ELF 摘要、运行 UID，供通道与独立可信预期比较。静态 ELF 不使用 Python／shell 脚本路径冒充实际执行程序。

探针单次进程只执行一次规范 IPv4 TCP 访问，超时 100–10000 毫秒覆盖建连、发送及读取。只发送带本次验证 ID／nonce 的固定合成标识，收到精确回显才记录 `connected`。单纯 connect 成功、错误回显和提前 EOF 均不能证明接收端可达。控制面主机对照使用相同协议。连接拒绝／重置／超时只是原始观测，最终是否构成策略差分仍由整体校验器判断。

固定命令经既有有界执行器发送，不拼接任意 shell，输出上限 4096 字节。通道拒绝重复 JSON 键、额外字段、错 ID／nonce／端点／路径／摘要／UID、异常退出、非法类型和过期挑战。错误输出不会被转换成阻断证明或写入观测。

**自报摘要不是独立信任根。** 本批仅提供一致性核对；受信任后端仍须核验目标、镜像、文件及父目录保护、实际身份，协调器仍须持有有效领取及实时授权。当前没有将新通道暴露为可由用户任意指定目标的 API。

## 实际验证

最终一次定向运行 **160 项通过、0 失败、0 错误、0 跳过**：39 项新 ELF／通道测试、58 项行为协议测试、63 项历史探针回归。首轮 38 项通过记录保留，与最终统计重叠。Ruff、Go vet、gofmt 和差异空白检查通过。

| 检查 | 实际证据 |
| --- | --- |
| 本机 Linux ARM64 静态 ELF | 使用本机 Go 1.26.5、CGO 关闭构建；解析 ELF 程序头确认无动态解释器；两个路径字节相同 |
| 实际 TCP 与原始身份 | 子进程访问回环受控接收端；精确回显成功，路径／摘要／UID与本地独立值一致；真实输出符合 agent v1 schema |
| 故障分类 | 错误回显、提前 EOF 为 probe_error；静默为 timeout；TCP reset／未监听端口分别记录 reset／refused |
| 输入与报告负向 | 非法 ID／nonce、DNS 名、IPv6、非规范端口和超时不建立连接；伪造报告、重复键、NaN、额外密钥字段和错误退出均拒绝 |
| 无拦截反例 | 三轮允许／拒绝／前后对照共 12 次实际 TCP 都成功；整体校验返回 `behavior_deny_not_observed`，不能记为防护有效 |

命令包装测试将 `sandbox exec` 参数映射成本地进程，明确属于传输夹具；它没有启动 OpenShell 沙箱。这里的允许／拒绝只是测试臂名称，不能把本地端口拒绝误标为真实 OpenShell 拦截。目标镜像和受保护文件、真实 OpenShell 三臂、持久协调 API 以及前端展示尚待完成。

## 复核与交付

```bash
cd apps/control-api
uv run --frozen pytest -q app/tests/test_openshell_behavior_channel.py \
  app/tests/test_openshell_behavior_protocol.py app/tests/test_enforcement_probe.py
```

构建与部署前提见 [探针说明](../../scripts/enterprise-experience/probe/README.md)。机器记录：[enterprise-behavior-elf-channel.json](evidence/optimization-20261007/enterprise-behavior-elf-channel.json)。本地日志／JUnit 位于 `var/optimization-20261007/opt09-elf-channel-{initial,final}.*`；测试产物仅保留本地，未混入源码提交。

本批没有调用模型、真实 OpenShell 或业务数据库，全部 TCP 接收端为本机回环临时服务，测试结束已关闭；未运行远端 CI、未推送或合并 main。总体完整验收仍为 9/16。
