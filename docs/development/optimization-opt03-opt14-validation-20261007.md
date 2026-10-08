# OPT-03 / OPT-14 扫描资源与隔离验证

日期：2026-10-07；机器 DGX Spark / Linux arm64；Python 3.13.12。分支 `codex/security-optimization-20261007`。

## 结果与任务状态

OPT-03 进程内资源准入已实现并通过本批验证。OPT-14 原生 Linux 扫描 worker 与故障恢复通过，但默认 Docker 安全配置拒绝创建 worker namespace，容器部署验收仍未关闭。不能将宿主验收等同于生产容器通过，也没有修改宿主内核配置或关闭 Docker 的安全限制。

| 实现 | 行为 |
| --- | --- |
| 已验证 tenant/actor 配额 | 默认每 60 秒 actor 20、tenant 60；原子检查，不因多身份绕过租户汇总 |
| 全局分析并发 | 每进程 2；无等待队列；超限 429 + Retry-After |
| 配额内存 | 最多 4,096 个键；过期回收，满时不淘汰活跃配额 |
| 请求与解码 | JSON 解析前累计 8 MiB，编码长度先检查，解码后 1 MiB；分块或错误 Content-Length 不能绕过 |
| worker 资源 | 256 MiB 地址空间、CPU 3 秒、墙钟 5 秒、输出 2 MiB；超限杀停并回收，不自动重试 |
| 结果绑定 | 任务 ID、作用域摘要、内容摘要、规则快照摘要和版本一致才允许入库 |
| 生产隔离 | 必须 Linux bubblewrap；最小只读挂载、独立 network/PID/user namespace；不可用则失败关闭 |
| 开发隔离 | 显式开发模式允许资源限制子进程；不宣称 OS 文件/网络隔离 |

## 资源实测

[原始摘要](evidence/optimization-20261007/static-scan-baseline.json)记录样本字节数、SHA-256、CPU、墙钟和峰值 RSS。每类仅一次受控观测，不能解释为吞吐 SLA、分位数或最佳配额。

| 样本 | 字节 | 原分析 CPU | 原分析峰值 RSS |
| --- | ---: | ---: | ---: |
| 普通 Python | 25 | 0.00014 秒 | 30,720 KiB |
| 4,000 层方括号 | 8,003 | 0.0026 秒 | 30,728 KiB |
| 长字符串 | 1,000,004 | 0.233 秒 | 33,544 KiB |
| `print(1)` 重复至内容上限 | 1,048,576 | 1.485 秒 | 448,536 KiB |

最后一个样本触发 OPT-14。新 worker 对该样本因内存预算返回 503；Finding、成功审计和 Outbox 均不增加，资产摘要不被半提交，下一次普通扫描成功。配额采用保守初始值，部署须按副本数与实际机器另行分配；不宣称集群共享配额。

## 验证记录

下列原始日志均在 `var/optimization-20261007/`，不提交运行态目录。

- 控制面全量：2,372 通过、1 跳过（既有 `SIQ_BATCH_WIRE_SAMPLE` 原生样例条件），`opt03-opt14-control-all.log`；本轮开启 `SIQ_TEST_NATIVE_BWRAP=1`，真实 bwrap 检查未跳过。
- 规则、旧分析器对等、配额与 worker 聚焦：142 项通过，`opt14-worker-final.log`；额外 CPU 密集期间治理可用性检查加入后 worker 单套 15 项通过，`opt14-worker-acceptance-002.log`。
- 正常/恶意/语法错误/二进制样本与既有分析器对等；已加载的替代规则快照正确传递，签名凭据不继承。
- 真实 CPU 超限、内存耗尽、墙钟超时、崩溃和输出超限均失败并回收。CPU 密集 worker 执行时健康请求在测试上限 1 秒内完成，第二扫描立即 429；不是多租户生产压力 SLA。
- 任务、scope、输入、规则摘要与版本错配被拒；未知/畸形结果不进入业务事务。
- 原生 bwrap 中宿主合成私有文件不可见，代码挂载不可写，宿主 loopback 接收端不可达；普通扫描仍成功。
- 原限流负向：旧路由返回 200，新要求 429，`opt03-negative-002.log`；原内存边界负向：旧路由对超出新预算样本返回 200，新要求 503，`opt14-baseline-negative.log`。失败来自行为差异，不是编译错误。
- 全量 Ruff 与差异检查通过。容器镜像构建成功，`opt14-docker-build.log`；默认容器运行负向见 `opt14-container-smoke.log`。

## 部署缺口与迁移要求

本机默认 Docker 的 seccomp/AppArmor 组合阻止非特权 namespace 创建，错误为 `No permissions to create new namespace`。安装 bubblewrap 包本身不能证明该运行时允许其工作。当前改动加入镜像依赖与原生 CI 门禁，但**不可在未通过 sandbox 预检的现有生产容器中直接升级启用扫描**。后续须验证有界的隔离部署配置或独立 worker 部署；不建议 `--privileged`、关闭整个 seccomp/AppArmor 或生产回退 process。

该缺口保持 OPT-14 `implementing`。其余治理功能不被扫描失败改写。历史成功记录不被回填为本轮隔离证明。
