# Trusted Intent V2：Hermes 原生工具链验收与审批修复

- 记录时间：2026-09-07 19:10:06，Asia/Shanghai。
- 开发基线：`main` / `60313a4`；此次修复与验收脚本运行于未提交工作树。
- 原始测量：[native-hermes-20260907.json](evidence/intent-v2/native-hermes-20260907.json)。包含脚本、适配器、服务端与构建二进制 SHA-256，以及 Hermes 版本和源文件摘要。
- 总体结论：Hermes 原生工具分发 → SIQ HTTP 决策 → 签名观察的隔离验收通过；V2 全部平台与发布验收仍未关闭。

## 1. 验收范围与可信边界

使用本机已安装 Hermes `42f0c8179e30cf6ba4cba0a8f2852e609f717773`，源码工作区干净，Python 3.11.15。脚本通过 Hermes 自身 `discover_plugins()` 加载仓库适配器，再调用真实 `model_tools.handle_function_call()` 执行内置 `read_file` / `write_file`；没有替换注册器、钩子或 HTTP 响应。

SIQ daemon 由当前 Go 源码构建，Go 1.26.5 / linux/arm64。配对、准入、Grant 编辑/审批、Intent 签发、会话绑定、决策和观察均走真实 loopback HTTP。所有状态、配对凭据、签名私钥、测试 Skill、Hermes 配置和业务文件位于自动清理的临时目录；只加载该临时实例显式启用的 SIQ 插件，不改变用户 Hermes 配置。

这是**原生工具分发器集成证据**。工具调用标识由脚本构造，并经真实前后置钩子传递；没有驱动 LLM 会话、GUI、真实用户审批或生产任务。测试 operator 和 Grant `deployed` 状态仅是隔离夹具，不证明真实平台策略配置已下发或形成 `effective` 权限。HTTP 负载使用合成结果，不计入原生工具执行证据。

原始 JSON 保存执行断言和测量摘要，不保存完整签名链或工具结果，不能拿摘要文件离线重新验签全部回执。脚本在临时实例存续期间通过管理 API 完整分页验证，并在退出 daemon 后调用 CLI `verify`；需要新的验签证据时运行脚本复测。

## 2. 实际通过的检查

| 检查 | 验证方式与结果 |
| --- | --- |
| 决策凭据不能访问授权管理 | Decision token 读取 `/v1/intents` 返回 403 |
| 允许的原生读操作 | company-a 文件真实读取，内容哨兵出现；恰有一条 decision 和一条 observation |
| 目录授权边界 | company-b、company-a-evil 都由 Intent 资源层拒绝；原生工具输出中没有文件内容 |
| 工具授权交集 | Grant 允许 write_file，但 Intent 只允许 read_file；返回 `intent_tool_not_allowed`，目标文件没有被创建 |
| required 缺绑定 | 实际原生钩子阻断，签名 decision 的 reason_code 为 `intent_binding_missing` |
| 可信元数据关联 | decision/observation 的 task、Intent ID/digest、authority revision、principal 一致，action_id 与 decision_receipt_id 正确对应 |
| 拒绝不能补成功观察 | 所有拒绝场景均没有 observation，尽管原生平台会触发 blocked 状态的 post hook |
| 强杀与失联 | 强杀实际 daemon 后调用原生工具，fail-closed 阻断，产生 unsigned pending 记录 |
| 重启恢复 | 新 daemon 恢复原绑定；工具再次成功执行；失联 pending 恰好提升为一条签名 deny |
| 观察重放 | 对重启前真实原生结果进行 HTTP 重试，复用原 observation；不同结果返回 409 |
| 并发重放 | 32 次重试、8 个客户端并发，全部返回相同回执，链上仍只有一条 observation |
| optional 兼容 | 未绑定会话在 optional 下读取成功；原已绑定会话仍拒绝 company-b，没有退回 Grant-only |
| 分页与签名链 | 最终 1,036 条回执，经多页读取、关联检查及退出 daemon 后 CLI 验签通过 |

## 3. 集成测试发现并修复的审批错误

触发方式：提交有效审批挑战，但 actor 缺失，或 Grant 的权限重叠仍未解决。

旧行为：`grant.Approve` 返回业务错误，HTTP 分支中的局部 `err` 遮蔽了公共错误处理使用的变量。接口继续返回 HTTP 200，追加一个仍为 `pending_approval` 的 Grant 版本，写入成功审批审计，并消费挑战。它没有把权限变成 approved，但会误导调用方并污染审批状态与审计。

新行为：先校验审批状态转换，错误立即返回 HTTP 400；不追加 Grant 版本、不写成功审批审计，也不消费挑战。通过校验后才消费挑战并进入既有提交协议。成功消费后若持久化失败，仍按既有恢复机制处理；本次没有引入跨文件事务承诺。

回归测试 `TestRejectedApprovalDoesNotCommitOrConsumeChallenge` 包含缺 actor 和未解决 overlap 两条负向案例，并验证补上 actor 后同一挑战可成功审批。两条负向测试在修复前均复现 HTTP 200，修复后通过；既有挑战重放与正文变更测试也通过。

## 4. HTTP 与落盘负载

512 对 decide/observe、32 并发客户端、同一可信绑定。包含 loopback HTTP、绑定读取/验签、签名及回执持久化，不包含模型或文件工具执行。负载阶段实际持续约 11.15 秒，约 45.90 对/秒。

| 请求 | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | ---: | ---: | ---: |
| Decide | 343.22 | 383.72 | 408.77 |
| Observe | 342.34 | 383.32 | 392.50 |

每个负载动作均检查唯一 decision/observation 及其授权关联。延迟包含并发排队，不与单次文件查找微基准直接比较；`thresholds=null`，没有预设 SLA。此轮补齐有限并发 HTTP 负载，**不是长期运行、断电或底层文件系统故障验收**。

## 5. 复测命令

在仓库根目录运行，需要已安装 Go 和可用的 Hermes Python 环境：

```bash
python3 scripts/validate-intent-v2-hermes.py \
  --hermes-root /home/maoyd/siq/hermes-agent \
  --hermes-python /home/maoyd/siq/hermes-agent/venv/bin/python \
  --load-samples 512 --concurrency 32 \
  --out /tmp/siq-intent-v2-native-hermes.json
```

Hermes 位于其他路径时替换对应参数。脚本不下载或修改 Hermes；缺失依赖、加载失败、HTTP 非预期或断言失败均非零退出，不能当作跳过后通过。默认负载是 200 对、8 并发；样本范围 1–4000，并发范围 1–32。认证信息和原始子进程日志不打印。

当前仓库的可复现检查：

```bash
cd apps/agentshield
go test ./internal/server -run 'TestRejectedApproval|TestApprovalChallenge' -count=1
go vet ./...
go test -race ./...
```

上述检查通过；Go 四目标构建 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 通过；脚本 Ruff 检查通过。此次没有修改 Python API、Web 或适配器生产源码，不将历史全仓测试数计作本轮重新执行结果。

## 6. CI 与下一步

基线 `60313a4` 的 [CI run 34113260319](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34113260319) 已检查为 `completed/success`。该事实关闭历史报告对这一基线的 CI 未确认项，**不覆盖本轮未提交的审批修复和验收脚本**。Go 回归测试会随现有 CI 执行；原生 Hermes 脚本需要外部平台安装，尚未成为托管 CI 的门禁。

后续仍需：

1. 补齐完整 Hermes 会话中标识生成、hold/审批以及用户重试路径；此次脚本调用标识来自夹具。
2. 验证 OpenClaw 原生工具链和 CodeBuddy 真实运行时，采集各自 V2 关联与失联证据。
3. 增加长期 daemon/多会话负载、平台重启期间重放，以及更全面的系统故障恢复测量。
4. 将本轮代码提交推送后检查对应新 SHA 的完整 CI；完成独立安全复核。

Provenance DAG、OS 强隔离、跨 Agent 委派和真实副作用证明仍属于后续阶段。能力矩阵中的平台 V2 综合验收列继续保留 `unverified`，原生分发器证据作为单独增量链接。
