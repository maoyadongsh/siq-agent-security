# B04 闭环证据：原始任务内容授权生命周期（采集→到期→清理）

## 1. 范围
- 任务：B04 —— 沿真实任务旅程验证 raw-task-content 授权生命周期：默认零采集 → 明确按任务授权 →
  原生参数/输出采集 → 授权到期或撤销后停止新采集 → 密文保留至保留期限 → 到期清理只删满足期限的密文。
- 被测二进制：`agentshield`（本地构建，sha256 `5361966882f7bbdc…`），隔离 state/HOME，loopback 端口。
- 授权期限（grant duration/授权撤销）与保留期限（retention，密文留存）分别验证，不混淆。
- 生产最低保留期（MinRetention=1h）未缩短；未修改系统时钟——到期等待为真实 wall-clock。

## 2. 关键事实
- 激活：retention_seconds=86400 budget_bytes=67108864 key_fingerprint=sha256:0a885942d…
- 三条腿（同一 identity，三个 task_id）：
  - task-exp-1: kind=parameters expect=purged record=raw-e6d9f6f27a87… expires_at=2026-09-16T00:27:06.771046816Z
  - task-keep-1: kind=output expect=survives record=raw-865c4e7ef275… expires_at=2026-09-16T23:27:06.791770053Z
  - task-rev-1: kind=parameters expect=purged_after_revocation record=raw-39a721aada7c… expires_at=2026-09-16T00:27:06.81914097Z
- 撤销腿：revoke 记录于 grant rawgrant-183b61c…（signature sha256 4b4480817691800d…）；
  撤销后再申请 permit 被 409 raw_task_content_authority_revoked 拒绝；密文按保留期仍在盘上（revoke ≠ 删除）。
- seed 阶段：runner 内部 require 断言把关，seed 进程 exit 0（SEED-OK 门）；本链路日志（tail 管道）仅保留末段，seed 4 项检查行见首轮日志（closure-b04 修复记录）。
- verify 阶段检查：19/19 通过；整体 passed=true。
- 到期清理（daemon 启动 PurgeExpiredRawContent + 15min tick 语义）：只删除已到期密文信封；
  未到期腿（task-keep-1）内容完整可读、密文保留；
  Grant、回执、活动、审计事实均未删除（verify_grants_not_deleted / receipts / activities 检查）。

## 3. 覆盖与遗漏
- 覆盖：默认关闭、按任务授权、参数/输出两类采集、到期前密文保留（daemon down 期间）、
  授权撤销即时停采（HTTP 409）、到期后清理范围（仅过期信封）、幸存腿完整性、导出腿（export）。
- 遗漏/限制：
  - verify 非幂等：verify 会触发启动清理从而消费 seed 状态（过期密文被删），同一 seed 目录第二次 verify
    必然失败 `verify_ciphertext_retained_while_daemon_down` —— 每次 verify 需重新 seed（harness 设计事实，非产品缺陷）。
  - 未覆盖主机端到端（B2/B3 仍 blocked，缺真实网关）。
  - 15min lifecycle tick 与显式 purge-expired 的竞态通过 PURGE_TICK_GUARD（13min）规避。
  - 本批 harness 修复（非产品缺陷）：首轮 verify 暴露 `verify_expiry_elapsed` 判定于在线等待之前记录，
    新鲜 seed→verify 链路必然 FAIL；同时 `expired_online=down<=0` 使整段等待路径的 expect_visible 退化为
    宽松分支。修复后判定移至真实墙钟跨过到期之后（checked_at 与 expires_at 差 1.09s），expect_visible=True
    采用严格分支（expired 且密文仍在盘上）——收紧断言，未放宽任何产品断言；产品行为两轮一致且正确
    （首轮 18/19 项实质检查亦全部通过，唯一 FAIL 为该 harness 检查点）。

## 4. 隔离与安全
- 隔离 run 目录 /tmp/siq-b04-run3（state/home/workspace/fixture-skill 自包含）；未触碰真实 ~/.openclaw 与
  ~/.config/siq-agent-security/；未改动系统时钟、全局网络、生产服务。
- 密文/凭据不落证据目录；grant signature 仅记录 sha256；日志只含检查名与状态字段。

## 5. 复现
```
python3 scripts/personal-experience/closure-b04-expiry-seed-runner.py seed \
  --binary /tmp/siq-b04-bin/agentshield --run-dir /tmp/siq-b04-run3 --out /tmp/siq-b04-bin/b04-seed3.json
python3 scripts/personal-experience/closure-b04-expiry-seed-runner.py verify \
  --binary /tmp/siq-b04-bin/agentshield --seed /tmp/siq-b04-bin/b04-seed3.json --out /tmp/siq-b04-bin/b04-verify3.json
```
- seed 用时与等待：到期腿 expires_at 为 grant 创建 +3600s（MinRetention=1h），verify 全程真实等待。

## 6. 证据文件
- checks.json —— seed+verify 全部检查（本目录）
- b04-seed3.json / b04-verify3.json —— runner 原始输出
- environment.json —— 环境与二进制摘要
- chain-log-redacted.log —— 后台链路日志节选（0600）
- SHA256SUMS
