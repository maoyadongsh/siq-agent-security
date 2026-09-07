# Trusted Intent V2：OpenClaw 重置候选补丁验收

- 日期：2026-09-07，Asia/Shanghai。
- 状态：候选补丁已落盘，并在独立临时运行时副本通过完整复测；本机原安装未更新。
- SIQ 基线：`3d1a9b5` 的当前工作树；OpenClaw 基线：`2026.5.12`。

## 1. 修复内容

此前 [原版空闲重置测试](trusted-intent-v2-openclaw-idle-reset-20260907-203600.md) 确认：UUID 已轮换，旧 `sessionFile` 和六条工具历史仍被复用。本轮没有删除或覆盖这份失败证据。

候选补丁位于 [patches/openclaw](../patches/openclaw/README.md)。它在 OpenClaw CLI 的两处会话状态更新中检查更新前的 UUID：

- UUID 变化时，清除旧 transcript 路径引用，并重设会话起始时间；
- UUID 不变时，保留正常续聊的文件和起始时间。

后续 transcript 解析继续由 OpenClaw 原生代码执行。补丁没有操作 SIQ 状态，没有更换路由 key，也没有通过删除 PII 污点或重建 Intent 来取得通过结果。

## 2. 与原版的实际对照

原始新结果：[openclaw-idle-reset-patched-20260907.json](evidence/intent-v2/openclaw-idle-reset-patched-20260907.json)。

| 检查 | 原版运行时 | 临时补丁副本 |
| --- | --- | --- |
| 一分钟真实空闲后 UUID 轮换 | 是 | 是 |
| 模型请求使用新的历史文件 | 否 | 是 |
| 重置后的请求保留旧工具结果 | 六条 | 零条 |
| 重置后的请求含旧合成 PII 标记 | 是 | 否 |
| SIQ 固定绑定、资源拒绝、动作链和 PII 污点 | 保留 | 保留 |
| 十三条最终回执验签 | 通过 | 通过 |
| 整体重置测试退出码 | 1 | 0 |

本轮空闲等待约 **60.83 秒**。测试没有修改平台时间戳或替换时钟；先执行正常续聊和新 key 隔离场景，再触发真实空闲轮换。因此，“修复重置”与“保持正常续聊”都有实际覆盖。

注意：新模型请求不再包含旧内容，不等于历史文件已从磁盘删除。SIQ 对同一路由 key 保留安全状态，也不等于为该 key 自动切换任务授权。

## 3. 版本与源码限制

[validate-openclaw-idle-patch.py](../scripts/validate-openclaw-idle-patch.py) 检查包名、版本、修改前 SHA-256、补丁 SHA-256 和修改后 SHA-256。目标仅限 `dist/agent-command-BQgTSh4F.js`。

原文件哈希为 `662d34784888289ecd133aec3ddb605de1f7076e9897e2e2e636ad246d6617f1`，补丁后为 `e6d7053a410162f1745b1a9608c233276ee8ac747e0d7cfeb8230a21a749425c`。报告包含完整固定元数据、运行器哈希及嵌套的原生测试证据。

运行器采用完整独立文件副本，不使用硬链接。本轮验证结束后，本机受补丁影响的原文件哈希仍与修改前一致；临时运行时、测试状态和日志均已清理。

另有两项前置负向检查：

1. 不支持的版本被拒绝，不生成成功报告、不修改输入文件。
2. 同版本但源码哈希不符被拒绝，不执行模糊应用、不修改输入文件。

## 4. 验证和复测

```bash
python3 scripts/validate-openclaw-idle-patch.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --out /tmp/openclaw-idle-reset-patched.json

uv run --project apps/control-api ruff check scripts/validate-openclaw-idle-patch.py
git diff --check
```

已通过补丁应用检查、JavaScript 语法检查、原生完整会话/空闲重置、Python Ruff 和证据哈希检查。本次没有修改 SIQ 产品实现；其逐次审批修复门禁沿用专门报告，不额外声明新的全仓 CI。

## 5. 当前验收边界

可开发的候选修复和复测工具已完成。该结果属于**带 SIQ 补丁的临时 OpenClaw 副本**，不代表原版已修复，不代表上游已接受，也不代表本机已经部署该修复。

原安装的失败记录仍有效，能力矩阵保持 `unverified`。网关手动 reset、平台审批与 SIQ hold 的联动、CodeBuddy 实机和独立复核仍待验收。本次未修改第三方实际安装，未发送上游 issue/PR，未提交或推送工作树增量。
