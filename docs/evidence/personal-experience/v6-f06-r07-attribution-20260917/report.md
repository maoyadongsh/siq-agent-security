# F06/R07：关联断言补强与失败诊断增强后的同候选复跑（2026-09-17）

按 [R07 复核](../v6-f06-r07-review-20260917/report.md) 的两项限制处方收口，候选、宿主、流程与上一批次完全同一：`0b16e5e0…6c8177`（linux/arm64，[候选身份](candidate.json)）× 真实 OpenClaw 2026.5.12 × 候选内嵌 UI × headless Chromium 145 × 本地确定性模型 fixture。产品 Go 源未改（源绑定 931 文件 `ba8d266e…` 前后复算不变），改动只在两个驱动脚本。

命令：`python3 scripts/personal-experience/r07-linux-user-journey-smoke.py --openclaw-root ~/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw --node ~/.nvm/versions/node/v22.22.1/bin/node --binary <本目录>/journey-private/siq-v6-hermes-post-e11-agent --out <本目录>/r07-journey.json`。

## 结果

**attempt3 通过**：退出码 0，`{"passed": true, "checks": 27}`；[机器可读结果](r07-journey.json) 27/27 全 pass，嵌套 r04 更新腿 31/31。相比上一批次（25+30）新增的 3 项检查全部真实触发：

- `r07_step4_attribution_correlates_grant_install_sec`：**relations=8/8** —— 由「Grant 相等 + 两摘要非空」升级为关系验证：grant_id 在回执/SEC/Grant 文档/安装 plan/runtime identity 五处同一；SEC install 钉住安装记录 claim_signature 与真实 subject（platform/instance_id/agent_id/session_id）；安装 plan 的 source.artifact_digest 与导入 artifact_digest 同域相等；回执 skill_attribution 逐字段复制 SEC（skill_id/content_hash/context_id/evidence_level=controlled_session）；SEC authority.grant_digest 由 python 侧复刻 `skillcontext.GrantDigest`（Go unmarshal 数字为 float64 + canon CPython float repr）对 live grant 文档重算相等。
- `r07_step4_attribution_digest_mismatch_detected`：**detections=4/4** —— 分别篡改 grant 文档字段、SEC install claim_signature、安装记录 claim_signature、回执 content_hash 后，同一关系校验全部检出（证明断言非恒真）。
- `r07_step4_tampered_sec_revoke_rejected`：**http=409 error=skill_context_changed 且 context_unchanged=true** —— 产品级负向：篡改 expected_context_signature 调 `/v1/skill-contexts/{id}/revoke` 被拒，签名上下文文件未变。
- 嵌套 r04 V1 同样升级：`v1_attribution_correlates_grant_install_sec` relations=8/8、新增 `v1_attribution_digest_mismatch_detected` detections=4/4。

## 三轮记录（失败轮原样保留，未重跑选优）

1. **attempt1**（r07 sha `6a35bfbb…`，新断言首跑）：RuntimeError 于 step4 新关系断言，前 10 检查 pass + 该检查 fail。新失败诊断首次实装即产出：`last_wait={journey_step: step5_receipts_deny_row, wait_target:{category: role:row, state: visible}}` 与 phase-a/checks_completed=11 落诊断文件。**操作失误如实记录**：该轮 failure.json（0600）在 attempt2 前被误删未归档；失败点由输出帧（r07 第 372 行）独立固定，并由 attempt2 完整复现定位。
2. **attempt2**（r07 sha `a9d91778…`，failure.json 增带截断 error）：同一确定性失败，`error` 明细 `failed=install_record_live` 归档于 [r07-journey.attempt2.failure.json](r07-journey.attempt2.failure.json)。**根因定位**：断言误用内部 Record 投影字段名（`local-skill-install-record/v1`/`recorded_status`），而公共 API 返回 View 投影（`local-skill-install-view/v1`/`status`，skillinstall operation.go 的 View 与 Record 同值域不同字段名）。属 harness 字段假设错误，产品行为正确，修正仅限脚本。两轮的 last_wait 停留在 step5 浏览器点是已知粒度语义：last_wait 只标注浏览器等待；API 段失败由 checks_completed 与 error 明细定位。
3. **attempt3**（r07 `a9d91778…` + r04 嵌套腿 `45223137…`）：字段名修正后 27/27 + 31/31 全绿。

## 失败诊断增强（复核限制 2 的收口）

`debug_dump` 与失败 JSON 现在记录固定 `journey_step` ID 与 `wait_target{category,state}`（locator 选择器类别如 role:row/role:heading/label:textbox 与等待状态 visible/editable/contains_text/enabled/count=0），phase-a/phase-c 的全部关键等待点已标注固定 ID；不包含任何输入值、配对码、grant ID 或页面文本。failure.json 另带截断至 240 字符的 `error` 明细。上一批次「phase-c 超时根因不可定位」的形态若重现，将直接给出阶段 ID 与等待目标类别。

## 宿主配置与清理

真实宿主 `~/.openclaw/openclaw.json` / `agentshield.json` / `exec-approvals.json` 前后 sha256 逐一相等（[resources.json](resources.json)）；旅程全程隔离 HOME；无本批进程/监听/临时目录残留；本批两个诊断目录核对内容后已删，9/15–16 历史目录与其他批次进程未动。

## 限制（仍不关闭）

headless 只证明传输/API/渲染 DOM，不关闭 GUI 视觉格；自动化操作员非人工验收；step1 为 fixture 复制二进制而非 R06 已装服务；step6 为 HTTP 决策+浏览器批准；step5 只覆盖缺 Authority 越权；会话级归属；其他 OS 与其他宿主各自独立验收。digest 重算复刻只覆盖 SEC authority 域；`canon` 与 CPython 的逐字节等价由产品既有测试锁定。

## 文件

- `r07-journey.json` — attempt3 机器可读结果（27 检查 + 嵌套 31 检查明细）
- `r07-journey.attempt2.failure.json` — 失败轮原样（含根因明细）
- `candidate.json` / `resources.json` / `SHA256SUMS`
- `journey-private/`（0700，gitignore 命中）— 候选执行副本（0700）与前置核对（0600）
