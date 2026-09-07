# Trusted Intent V2：OpenClaw 安装修复与原生工具链验收

- 时间：2026-09-07 19:25:39，Asia/Shanghai。
- 基线：`main` / `60313a4`，本轮在包含前一批审批修复的未提交工作树上开发。
- 平台：本机 OpenClaw **2026.5.12**，Node **v22.22.1**，linux/arm64；不以设计文档日期推断已安装平台版本。
- 原始结果：[OpenClaw 原生验收 JSON](evidence/intent-v2/native-openclaw-20260907.json)。脚本、适配器、Go 服务端、构建产物及主要原生调用模块的摘要随结果保存。

## 1. 发现的问题与最终修改

### 插件资产缺少原生加载清单

旧适配器目录只有 `package.json` 和 `index.ts`。使用本机真实 `loadOpenClawPlugins()` 做 manifest-only 加载时，插件列表为空，诊断为 `plugin manifest not found`。已有模拟钩子测试绕过了加载过程，因此无法发现这一问题。

现已新增 `openclaw.plugin.json`，包含固定插件 ID 和不接受额外字段的空配置 schema；package 增加 `openclaw.extensions: ["./index.ts"]`。源码资产与 Go 内嵌安装资产同步，并由对等测试约束。Endpoint/tokenPath 仍来自适配器本地配置，不放入插件清单。

### 安装完成不等于插件已被加载

旧安装器写入插件文件和 L1 安装策略，但未给原生运行时登记插件加载路径与启用 entry。

现在安装器将本插件绝对目录追加到 `plugins.load.paths`，设置本插件 entry 的 `enabled=true`；已有 `plugins.allow` 时仅追加本插件。保留其他插件、slots 和已有路径；不主动创建全局 allow 列表以免改变其他插件的加载范围。全局插件明确禁用、本插件出现在 deny 列表或相关配置类型错误时，在改写平台文件前拒绝安装。

卸载同步移除本插件的 path/entry/allow 项，保留其他插件配置。增加 `OPENCLAW_STATE_DIR` 的适配器配置读取支持，让原生隔离实例读取自己的配置，而非用户默认 `~/.openclaw`。

### 重装丢失卸载归属

新测试复现：连续安装两次后，最新安装记录不再记得哪些插件文件由首次安装创建，卸载后仍残留清单及插件文件。

修复后重装保留既有记录中属于当前 OpenClaw 插件目录及产品配置的 Created 归属；已有记录损坏时拒绝重装。文件首次备份策略保持不变，卸载不覆盖用户新增的其他插件配置。

## 2. 两层真实平台验证

| 验证层 | 实际运行内容 | 边界 |
| --- | --- | --- |
| Go 安装器 → 原生加载器 | `TestOpenClawInstalledPluginLoadsNatively` 在临时 Home/State 中调用真实 Install，再让安装版 OpenClaw 加载其输出清单、入口与配置 | 验证加载，不调用 L1 安装策略命令，不证明真实用户运行时已启用 |
| 原生工具路径 → Go HTTP | 原生插件加载器、`wrapToolWithBeforeToolCallHook`、安装版 Pi 内置 read/write 工具和 `runAgentHarnessAfterToolCallHook`，连接临时 SIQ daemon | 工具调用和 session/run ID 由夹具提供；后置 relay 由脚本调用，不是完整 Agent 会话 |

没有替换 SDK、Plugin API、原生前置钩子或 HTTP 返回值。所用内部模块由实际导出函数定位，并记录文件摘要；安装版不具备预期导出时失败，不回退模拟实现。合成测试结果经过真实前后置映射与签名链保存。

全部操作在临时状态中进行。没有改写用户 OpenClaw 配置、连接现有网关、调用模型或使用真实业务审批。Go 安装器的 `Home` 测试参数和 OpenClaw 的状态目录环境变量用于隔离测试，不覆盖进程的 `HOME`。

## 3. 通过的行为检查

- 管理权限分离：Decision token 读取 Intent 管理 API 返回 403。
- 原生 read 读取 company-a 合成文件；decision 与 observation 唯一关联，携带一致的 Intent/task/principal/revision。
- company-b 与 company-a-evil 路径由 Intent 资源约束拒绝，工具未泄露文件内容。
- Grant 允许 write、Intent 只允许 read 时，原生 write 被拒，目标文件未创建。
- required 无绑定拒绝；optional 无绑定可执行；既有绑定不会因切换 optional 而降级。
- 强杀 daemon 后，原生工具 fail-closed，产生 pending；重启恢复绑定并恰好提升一条 pending deny。
- 重启前结果重放幂等；不同结果返回 409；32 次并发重放仍只有一条观察回执。
- 512 对 HTTP 请求、32 并发客户端，每个动作的 decision/observation 关联正确。最终 1,036 条回执通过完整分页读取和退出 daemon 后 CLI 验签。

原始 JSON 是验证摘要，不是完整签名链副本；不能独立对摘要文件重新验签所有回执。新证据应通过复测采集，不把版本号或脚本的存在当作通过证据。

## 4. 负载测量

负载阶段约 10.93 秒、46.84 对请求/秒，包含 loopback HTTP、绑定验签、签名和回执持久化。负载请求与观察结果为合成 HTTP 夹具，排除原生文件工具和模型执行。

| 请求 | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | ---: | ---: | ---: |
| Decide | 338.53 | 368.54 | 380.74 |
| Observe | 341.05 | 353.81 | 384.55 |

延迟包括并发排队，`thresholds=null`，不是 SLA 或长期 soak 结论。

## 5. 复测与开发检查

仓库根目录，按本机安装路径调整两个参数：

```bash
python3 scripts/validate-intent-v2-openclaw.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --load-samples 512 --concurrency 32 \
  --out /tmp/siq-intent-v2-native-openclaw.json

node scripts/test-openclaw-adapter.cjs
```

验证 **Go 安装器实际输出**，在 `apps/agentshield` 中运行：

```bash
SIQ_OPENCLAW_NATIVE_ROOT=/home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
SIQ_OPENCLAW_NATIVE_NODE=/home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
go test ./internal/adapterinstall -count=1
```

没有设置两个环境变量时，该原生加载测试明确 skip；其他安装、重装、卸载、全局禁用/deny、格式错误与坏记录测试仍会执行。不能把托管 CI 上的 skip 当作平台验收通过。

本轮执行通过：Go 全模块 race/vet、安装器聚焦回归（启用实际 OpenClaw 加载）、四目标交叉构建、OpenClaw mock hook/隔离配置回归、两个 Python 脚本 Ruff。共享 HTTP 夹具复测 Hermes 的结果另存 [shared-harness JSON](evidence/intent-v2/native-hermes-20260907-shared-harness.json)，前一批历史 JSON 保留。

## 6. 剩余任务

1. 完整 Hermes/OpenClaw Agent 会话的稳定标识生成、事件投递和用户重试路径。
2. 原生平台 hold/审批与本地批准的完整验收；当前不因平台弹窗而假定已有本地授权。
3. CodeBuddy 原生运行时 V2 验收；当前仅有 Go hook 与合同测试证据。
4. 多会话长期运行、平台进程重启期间重放，以及更全面的故障恢复验证。
5. 当前修改提交推送后，对应新 SHA 的全仓 CI 和独立安全复核。

两平台的原生组件链路已有新增证据，但能力矩阵中的完整平台 V2 综合验收仍保留 `unverified`；不由本报告升级为生产支持或 OS 隔离能力。
