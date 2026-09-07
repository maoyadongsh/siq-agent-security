# Trusted Intent V2：OpenClaw 空闲重置验收与原生历史保留问题

- 时间：2026-09-07，Asia/Shanghai。
- 环境：OpenClaw `2026.5.12` / Node `v22.22.1` / linux/arm64。
- SIQ：基线 `3d1a9b5` 的当前工作树，包含尚未提交的逐次审批修复。
- **整体测试未通过**：OpenClaw 的空闲重置轮换了 UUID，但保留了旧 transcript 文件及其历史内容。
- **SIQ 安全不变量通过**：相同路由 key 的固定授权、动作链及 PII 污点均未因原生 UUID 轮换而清空。

## 1. 实际复测方法

新增 [validate-intent-v2-openclaw-reset.py](../scripts/validate-intent-v2-openclaw-reset.py)，复用此前的完整 CLI 会话夹具。所有状态、模型响应和文件数据都是临时测试数据；没有修改 OpenClaw 安装文件或真实用户配置。

测试先运行既有的四轮 CLI 正负场景，再执行以下步骤：

1. 重启临时 SIQ daemon，恢复原有绑定和回执链。
2. 通过真实 OpenClaw 文件工具读取合成邮箱数据，确认 observation 已使 SIQ 会话带有 `pii` 污点。
3. 仅在临时 OpenClaw 配置启用 `session.reset = {mode: "idle", idleMinutes: 1}`。
4. 根据平台实际写入的 `lastInteractionAt` 等待空闲窗口结束。本次实际等待约 **60.77 秒**；没有修改会话时间戳，也没有替换时钟。
5. 重新执行真实 `agent --local` 命令；先尝试越权读取 company-b，再读取授权范围内的文件。
6. 分别检查原生 UUID/文件/模型历史以及 SIQ 的签名回执和授权状态。

## 2. 归档结果

原始报告：[native-openclaw-idle-reset-20260907.json](evidence/intent-v2/native-openclaw-idle-reset-20260907.json)。关键字段：

```json
{
  "passed": false,
  "siq_invariants_passed": true,
  "native_transcript_cleared": false,
  "native_reset_observations": {
    "tool_results_retained": 6,
    "pii_marker_retained": true,
    "uuid_rotated_before_model_request": true,
    "session_file_unchanged": true
  },
  "receipt_count": 13
}
```

| 检查 | 实际结果 |
| --- | --- |
| 原生空闲策略是否轮换 UUID | 是，模型请求前 UUID 已变化 |
| 原生会话是否换用新的 transcript 文件 | 否，`sessionFile` 与重置前相同 |
| 模型是否不再收到旧工具历史 | 否，保留六条旧工具结果，包含合成 PII 标记 |
| SIQ 固定 Intent 是否丢失 | 未丢失；相同 sessionKey 仍绑定原签名 Intent |
| 重置后越权资源访问是否放行 | 未放行；返回 `intent_resource_not_allowed` |
| 动作序号与父动作是否清空 | 未清空；种子读取和后续两次决策序号为 6、7、8，父动作保持关联 |
| 重置后、再次读取 PII 之前污点是否保留 | 保留；越权拒绝回执已有 `pii` |
| 回执完整性 | 共 13 条，HTTP 分页与停机 CLI 验签通过 |

原始报告嵌入本次重新运行的基础会话结果，并记录当前构建、脚本、共享夹具及相关原生代码的哈希。它没有用先前构建的会话结果代替新构建验证，也没有归档真实凭据或工具原文。

## 3. 原生问题的定位

本机已安装源码中可以看到以下调用顺序：

- `dist/model-fallback-*.js` 的 `resolveSession` 根据空闲策略生成新 UUID；
- `dist/agent-command-*.js` 随后把新 `sessionId` 写入原有会话条目，同时保留原有字段；
- `dist/session-file-*.js` 的 `resolveAndPersistSessionFile` 通过“条目的 sessionId 是否等于请求 sessionId”判断能否复用 `sessionFile`；
- 此时 ID 已被前一步更新，旧路径因而可能被继续使用。

这一解释来自源码分析，运行时归档则直接确认了 UUID 变化、文件未变化和历史继续进入模型。没有修改第三方安装包来让测试通过，也没有把脚本的预期放宽为通过。发现历史保留后，脚本继续收集 SIQ 检查结果，最后仍返回退出码 **1**。

该问题尚未验证到其他 OpenClaw 版本或网关手动 `sessions.reset` 路径，不能外推为所有重置方式均有相同行为。

## 4. 本项目的会话语义

当前 OpenClaw 适配器将原生 `sessionKey` 映射到 SIQ `session_id`。因此，同一个路由 key 下的 transcript UUID 轮换不会自动解除 Intent 绑定，也不会清除 SIQ 污点和动作链；这是本轮实际验证到的行为。

需要不同任务授权时，应使用新的原生会话 key 并由管理端签发、绑定相应 Intent。此前的 explicit 新会话测试已经证明它不会继承旧 key 的绑定。此操作不构成删除旧平台历史的保证。固定绑定的撤销/任务切换 API 仍是报告中明确的后续工作。

当前实例不能把“空闲后 UUID 已变化”作为旧模型历史已经清空的证据。对于需要上下文清除的部署验收，原生 transcript 保留问题仍须解决并重测。

## 5. 复测命令与状态

```bash
python3 scripts/validate-intent-v2-openclaw-reset.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --out /tmp/intent-v2-openclaw-idle-reset.json
```

总时长包含原生 CLI 启动和一分钟真实空闲等待。在本次安装版本上，此命令产生报告后返回 **1**。`passed=false` 的归档是失败证据，不能用作全平台通过记录；`siq_invariants_passed=true` 仅覆盖上表明确列出的 SIQ 检查。

脚本的 Ruff、格式检查和报告链接检查通过。没有因新增测试而重跑未变化的产品全套测试；逐次审批修复的 Go race/vet、四目标构建和 Python 合同门禁仍以其专门报告为准。

整体目标继续验收中：原生历史重置问题、网关审批联动、CodeBuddy 实机及独立复核尚未关闭。本轮新增脚本和文档未提交，现有 `3d1a9b5` 的 CI 成功不代表这些增量已获得远端门禁。
