# Trusted Intent V2：持续运行、到期边界与旧适配器验收

- 记录时间：2026-09-07 19:47:32，Asia/Shanghai。
- 工作树基线：`main` / `60313a4`，包含前序审批修复及 OpenClaw 安装修复，本轮尚未提交。
- 范围：真实 daemon 多会话持续负载和请求进行中的强杀恢复；24h 动作窗口边界；实际旧版 Hermes 适配器兼容性。

## 1. 持续运行验收方法

新增 [validate-intent-v2-soak.py](../scripts/validate-intent-v2-soak.py)，复用既有临时状态与受信管理 API 夹具。每个测试会话拥有独立签名 Intent、task_id、资源约束与绑定；交替授权 company-a / company-b 合成目录。

工作线程持续提交新决定和 Observe 重放。客户端只保存已收到服务端响应的 action_id/decision_receipt_id；Decide 响应丢失不被当作可以执行工具的授权。Observe 响应丢失后，用已知前置授权重试，验证幂等。约每十次操作生成一次新决策，其余操作重放已知观察；新动作数量另有预算，避免把缓存容量耗尽误算为重启故障。

控制线程在工作线程仍发送请求时强杀真实 daemon，保持约半秒不可用，再启动同一状态目录的新进程。只有跨越已记录重启代次或在重启窗口内开始的传输失败可被归为预期失联；其余传输失败、完整 HTTP 错误、拒绝结果或关联不一致均使验收失败。

结束后补录全部已知授权的观察，分页读取全部回执，检查：

- 每个已确认动作只有一条 observation；重复请求返回同一回执。
- 各 session 的 Intent/task/digest 保持一致，task_seq 连续，parent_action_id 正确恢复。
- 使用其他 session 引用已有动作返回拒绝；不同观察结果返回 409。
- 退出 daemon 后，CLI `verify` 对落盘链验签通过。

每 30 秒记录 daemon RSS、线程数、文件描述符数及近似状态目录大小。`--rate` 是操作速率上限：创建新动作含一对 HTTP 请求，重放仅含一次 Observe；不是保证达到的 HTTP QPS。延迟仅统计测量窗口内最后至多 10,000 次成功请求，排除初始化与最终补录。

这些是合成 HTTP 客户端，没有运行模型或真实业务工具，不产生用户业务副作用；所有凭据、回执及合成文件位于临时目录，验收摘要不包含完整签名链。

## 2. 原始记录与构建边界

- [600 秒持续运行记录](evidence/intent-v2/soak-20260907-600s.json)：在到期精度修复前构建的 daemon 上运行。二进制摘要见 JSON；没有通过测试期间修改磁盘源码来替换正在执行的构建。
- [到期修复后 60 秒恢复回归](evidence/intent-v2/soak-20260907-expiry-fix-60s.json)：新二进制的多会话/重启复验。与 600 秒记录分别计量，不拼成同一构建的运行时长。

两份记录的最终计数、重启恢复耗时与资源快照以 JSON 为准。该测试不宣称 24 小时 uptime、断电可靠性、生产 SLA 或所有文件系统故障覆盖。内存随动作关联与回执增长，不凭有限时长的 RSS 曲线宣称不存在泄漏。

| 实测 | 修复前持续运行 | 到期修复后恢复回归 |
| --- | ---: | ---: |
| 时长 | 600.18 秒 | 60.16 秒 |
| 会话 / 工作线程 | 32 / 8 | 32 / 8 |
| 强杀重启 | 6 次 | 2 次 |
| 新决策成功数（不含初始化） | 1,409 | 140 |
| Observe 成功请求数（含幂等重试，不含最终补录） | 14,088 | 1,400 |
| 重启窗口内的传输失败 | 109 | 26 |
| 最终 decision / observation | 1,441 / 1,441 | 172 / 172 |
| 验签回执总数 | 2,882 | 344 |
| 重启恢复耗时（含预设约 0.5 秒不可用） | 0.605–0.910 秒 | 0.555–0.556 秒 |
| 采样 daemon RSS | 16,488–27,260 KiB | 16,636–17,552 KiB |

两个实例的全部已确认动作均补齐且仅有一条 observation；没有通过忽略运行期 HTTP 拒绝或任意重试来获得通过。600 秒数据的 Decide P50/P95/P99 为 21.08/23.01/24.00 ms，Observe 为 1.02/12.06/19.69 ms。Observe 大量命中幂等返回，因此不与每次都写新回执的负载结果直接比较。

## 3. 24h 窗口不一致修复

原实现将 `issued_at` 按秒签入回执，但内存中的动作到期时间使用带小数秒的请求开始时间。恢复时则从回执按秒计算：同一个动作在 24h 边界附近，存活进程仍可能接受 Observe，重启后却拒绝，差异小于一秒。

新增 `TestActionWindowUsesSignedTimestampBeforeAndAfterRestart`，使用半秒时间戳创建动作，再分别验证边界前 1ns、边界时刻、边界后 1ns；覆盖存活与恢复后的引擎。修复前，存活引擎在边界及边界后两条负向断言失败。

现在两条路径都以签名 `issued_at` 的秒精度为准，到达边界即拒绝，没有改写旧回执或增加签名合同格式。另有 `TestExpiredActionAndRecentObservationDoNotEraseBoundTaint` 验证：靠近到期的 observation 不续期；清理旧动作不会丢失已绑定 Intent、PII 污点，也不能通过空闲回收为新会话让出安全状态槽；重启后规则相同。

这两项是可控时钟的边界测试，不能算作实际等待了 24 小时。

## 4. 实际旧版 Hermes 兼容性

新增 [validate-intent-v2-legacy-hermes.py](../scripts/validate-intent-v2-legacy-hermes.py)，从 Git 提交 `0360731f842e73bc5ec8cbdbb298075d43776c88` 提取 Hermes 的 `__init__.py` 和 `plugin.yaml`，原样写入临时插件目录。这是适配器新增 V2 action/receipt 关联字段之前的代码，不把当前代码切换 optional 当作旧版兼容证据。

该旧版 pre/post 已透传 `tool_call_id`，但 post 没有显式 action_id / decision_receipt_id，参数为空。它在当前 Hermes 原生加载器中执行合成文件工具，当前 Go 服务可根据稳定调用 ID 唯一关联观察。允许、目录/工具拒绝、required 缺绑定、失联阻断、重启恢复、optional 无绑定，以及并发观察重放全部通过。结果见 [旧版 Hermes 原始记录](evidence/intent-v2/legacy-hermes-pre-action-binding-20260907.json)。

这是指定提交的源代码兼容性，不等于发布制品兼容性或所有旧平台兼容。旧 OpenClaw post 不提供调用 ID、且参数为空时，仍不能通过猜测绑定观察；应升级适配器。完整平台会话与审批仍需要另外验收。

## 5. 复测命令

仓库根目录：

```bash
python3 scripts/validate-intent-v2-soak.py \
  --duration-seconds 600 --restart-every 90 \
  --sessions 32 --workers 8 --rate 24 \
  --out /tmp/siq-intent-v2-soak.json

python3 scripts/validate-intent-v2-legacy-hermes.py \
  --hermes-root /home/maoyd/siq/hermes-agent \
  --adapter-ref 0360731f842e73bc5ec8cbdbb298075d43776c88 \
  --out /tmp/siq-intent-v2-legacy-hermes.json
```

Soak 可配置 5–1800 秒、2–64 会话、1–32 工作线程，最大新动作预算不超过 4000。更长的验收需要同时设计授权有效期与关联容量，不直接无限提高现有参数。

Go 回归位于 `apps/agentshield/internal/receipt/action_expiry_test.go`。本轮 Go race/vet、四目标构建、Ruff 和 Python V2 合同测试均已执行；Python 合同测试 53 项通过，保留既有测试依赖弃用警告。

## 6. 尚未关闭的验收

- 完整 Hermes/OpenClaw Agent 会话、平台审批及用户重试路径。
- CodeBuddy 原生运行时；当前环境没有 `codebuddy` 可执行入口。
- 发布制品及跨 OS 实机验证、断电和更多文件系统故障恢复。
- 本轮新 SHA 的全仓远端 CI，以及独立安全复核。

本报告补充持续运行、恢复和指定旧适配器证据，不将 V2 总目标或平台支持矩阵标为完成。
