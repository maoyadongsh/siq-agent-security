# Trusted Intent V2：OpenClaw 完整 CLI 会话验收

- 时间：2026-09-07，Asia/Shanghai。
- SIQ 基线：`3d1a9b50b2e9429c183b4381a20f36e2cac2f735`；本轮增加验证脚本、IO 限制工具和证据文档，未修改产品授权或适配器实现。
- 原生环境：OpenClaw `2026.5.12`，Node `v22.22.1`，linux/arm64。
- 结论：完整嵌入式 CLI 会话、实际 pre/post hook、跨进程续聊和新会话拒绝继承权限通过。网关审批等未覆盖项仍待验收。

## 1. 验证路径

此前 OpenClaw 测试直接调用实际前置包装器和文件工具，并由测试手动触发后置 relay。这些结果能证明组件集成，不能证明完整 Agent 循环会正确调用 post hook。

本轮使用已安装产品的真实入口：

```text
node openclaw.mjs agent --local --agent <fixture-agent> --message <fixture> --json
  → OpenClaw 原生插件加载
  → 原生会话解析、创建和持久化
  → 原生嵌入式 Agent / Pi 模型协议与工具循环
  → SIQ before_tool_call → 实际临时 daemon /v1/decide
  → 允许时执行真实文件工具
  → OpenClaw 自行触发 after_tool_call → /v1/observe
  → 工具结果或阻断原因进入下一次模型请求
```

[validate-intent-v2-openclaw-conversation.py](../scripts/validate-intent-v2-openclaw-conversation.py) 提供本地 SSE 合成模型服务，实际 OpenClaw 负责解析响应和推进循环。测试没有手动调用插件钩子、替换 Agent 或改写平台工具实现。

模型响应是固定测试序列，不是付费模型调用或模型能力评估。临时管理端负责签发与绑定 Intent，管理 bearer 不传给 CLI/模型。CLI 只有读取临时 decision token 的配置。

## 2. 四次原生命令的结果

原始数据：[native-openclaw-conversation-20260907.json](evidence/intent-v2/native-openclaw-conversation-20260907.json)。

| 命令 | 会话与工具行为 | 验收结果 |
| --- | --- | --- |
| 第一次 | 不调用工具，由原生 CLI 创建会话、写入会话库并完成回答 | 从会话库读取实际 `sessionKey` 与 `sessionId`；没有意外工具回执 |
| 第二次 | 管理端绑定后，读取 company-a；尝试 company-b、company-a-evil 和写文件 | 合法读取执行；三次越权拒绝；结果返回模型时不含被拒绝的文件内容；禁止写入的文件不存在 |
| 第三次 | 独立 CLI 进程继续同一会话，再次读取 company-a | 原生历史含先前结果；会话 key/UUID 保持一致；任务序号连续，成功动作父节点没有被拒绝动作替换 |
| 第四次 | 通过显式新 `--session-id` 选择另一个会话并尝试读取 company-a | OpenClaw 生成不同路由 key；required 模式返回 `intent_binding_missing`，没有继承旧绑定或产生成功 observation |

合计四轮 CLI、十次 SSE completion 请求、六次工具调用；六条 decision 与两条 observation 共八条回执通过 HTTP 分页验签和停机后的 CLI verify。每条 observation 都引用原生 pre hook 对应的服务端 action_id/decision_receipt_id；task、principal、Intent digest 和 authority_revision 与决策一致。

报告包含构建二进制、适配器、两个共享测试工具、新脚本、IO guard，以及相关 OpenClaw CLI/Agent/协议模块的源码 SHA-256。模块哈希是相关实现的版本指纹，不是全进程模块加载追踪。归档是验证摘要，不包含完整签名回执文件、凭据或工具内容。

## 3. 两个必须区分的原生标识

### 会话路由 key 与 transcript UUID

当前适配器将 hook 的 `event.sessionKey` / `ctx.sessionKey` 映射到 SIQ 请求中的 `session_id`。因此管理端创建 OpenClaw Intent Binding 时应使用原生路由 key，例如 `agent:<agent-id>:main`，而不是仅凭字段名字使用会话库中的 transcript UUID。

第一次运行的 UUID 由 OpenClaw 生成。第四次的新 UUID 由测试管理端作为 `--session-id` 选择器提供，OpenClaw 根据它生成并持久化新的 explicit 路由 key；本报告不把后者称为平台自动生成的 UUID。

本轮覆盖不同 key 的隔离以及相同 key 的正常续聊，没有覆盖同一 key 下执行 reset、过期或轮换 transcript UUID 的生命周期。不能从“新 explicit key 拒绝继承”推导出“所有 reset 语义已经验收”。

### 模型历史中的调用 ID 规范化

实际会话路径会将部分历史 tool call ID 去掉连字符，例如 `foreign-company` → `foreigncompany`。本轮保留带连字符的输入，记录原始响应 ID 与历史 ID 的对应关系，并验证规范化后的 tool result 仍唯一对应同一工具名称和相同参数的 assistant tool call。

SIQ pre/post 回执则按真实执行事件的原始调用 ID 严格核对。没有修改适配器去猜测历史 ID，也没有放宽服务端的动作关联校验。模型消息规范化和授权回执关联是不同的验证对象。

## 4. 隔离测试配置与复测

临时目录内设置 `OPENCLAW_STATE_DIR`、`OPENCLAW_CONFIG_PATH`、`OPENCLAW_HOME`、Pi 状态目录和日志文件。只启用 SIQ 插件，工具 allowlist 仅 `read` / `write`，文件工具限制在测试 workspace。模型只配置一个 loopback provider 与固定合成 key，fallback 列表为空；命令没有 `--deliver`，没有配置消息渠道。

完整 CLI 会导入部分内置公共模块，因此不能使用 `OPENCLAW_DISABLE_BUNDLED_PLUGINS=1` 隐藏全部内置文件；插件激活仍受显式 allowlist 限制。脚本关闭 Node 编译缓存与 CLI 自动重启，方便超时回收。所有管理状态和私有日志随临时目录清理。

[openclaw-fixture-guard.mjs](../scripts/openclaw-fixture-guard.mjs) 在 CLI 前加载，限制 Node TCP 连接到本次两个临时服务。它只用于约束测试 IO，不是产品 OS 沙箱，不能据此声明阻止恶意同 UID 进程绕过平台。

```bash
python3 scripts/validate-intent-v2-openclaw-conversation.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --out /tmp/intent-v2-openclaw-conversation.json

uv run --project apps/control-api ruff check \
  scripts/validate-intent-v2-openclaw-conversation.py
node --check scripts/openclaw-fixture-guard.mjs
python3 scripts/check_capability_honesty.py
git diff --check
```

前提为已经安装 OpenClaw 和可用的 Go 工具链。脚本不自动安装运行时，失败以非零码退出；模型交互断言失败不会被当作平台成功。原始 stderr 不写入验收报告，失败诊断截断并脱敏。

## 5. 剩余验收

1. OpenClaw 网关模式、原生审批与本地 hold 管理批准的关联。当前平台批准不会自动成为 SIQ 管理批准，此安全边界保持不变。
2. 同一 OpenClaw 路由 key 的 reset/过期生命周期，以及更广的插件/运行时版本兼容性。
3. Hermes hold 阻断与管理端处理流程；CodeBuddy 原生运行时实机归档。
4. 更多系统故障验收和独立安全复核。

`3d1a9b5` 的完整远端 CI 已通过。本轮验证代码仍是该基线上的未提交增量，不能声称已运行新 SHA 的远端门禁。综合平台能力列保持 `unverified`，并链接本报告中已经取得的明确证据。
