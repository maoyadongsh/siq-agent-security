# Trusted Intent V2：策略编辑导致逐次审批丢失的修复

- 时间：2026-09-07，Asia/Shanghai。
- 基线：`3d1a9b50b2e9429c183b4381a20f36e2cac2f735` 上的工作树增量。
- 状态：已复现、修复并通过本地门禁；尚未提交或取得此修复对应 SHA 的远端 CI。

## 1. 问题与影响

检查 OpenClaw hold 链路时发现，`grant.Build` 会根据 process、resource（package.install）和 credential 事实，将 `exec` 放入 `openclaw_tool_policy.require_approval`。执行引擎优先检查这份集合，因此即使工具同时在 allow 中，也应先产生 hold。

`grant.PatchDesired` 重新构建策略时，创建了空的 `ocReq` 集合，却没有从保留事实重新填充。结果是：编辑任一受支持的域后，事实仍存在，而审批集合变为空。

具体复现：一个含 `exec` 工具 allow 和 credential deny 的待审批 Grant，只修改模型配置，再正常批准、部署；旧实现对 `exec` 返回 `allow`，没有保留该工具原有的逐次审批要求。修改网络、文件系统或工具列表也有同类问题。此问题发生在 Grant 策略派生层，不能依赖 Intent 或前端来补偿。

## 2. 修复行为

[internal/grant/patch.go](../apps/agentshield/internal/grant/patch.go) 在遍历补丁后事实时，重新派生 `exec` 的审批集合：

- process 事实保留时，保留逐次审批；
- resource 或 credential 事实保留时，保留逐次审批；
- 没有这些来源事实时，不凭空新增审批要求。

修复采用与初始 Build 一致的规则，不直接复制旧策略中的审批条目。credential deny 事实继续保留，Grant 仍须经过批准才能部署；不会把部署状态声明为实际生效。

规格已同步到 [开发规格](agentshield-dev-spec-v1.md) 的 `patch-desired` 行为说明。本次没有变更 JSON Schema、签名格式、HTTP 权限划分或平台 hook 协议。

## 3. 负向复现与验证

### 策略派生回归

[patch_approval_test.go](../apps/agentshield/internal/grant/patch_approval_test.go) 覆盖三类来源事实 × 四类补丁，共 12 个场景。每个场景先确认初始 Grant 包含逐次审批，再确认修改其他域后仍然保留，并显式保留 `exec` allow，以测试审批对 allow 的优先级。

旧实现的这 12 个场景全部失败，错误为“来源事实仍在，但补丁移除了逐次审批”。修复后全部通过。另有正向对照，确认没有来源事实的 Grant 不会被无条件加上 exec 审批；credential 场景同时检查 deny 事实保留。

### 执行引擎回归

[receipt/patch_approval_test.go](../apps/agentshield/internal/receipt/patch_approval_test.go) 将修改后的 Grant 正常批准、部署并交给真实执行引擎：

1. 旧实现实际返回 `allow`，复现审批降级；
2. 修复后返回 `hold`；
3. 未经本地管理批准，关联 Observe 返回 `observation_action_not_authorized`；
4. `ResolveHold` 由管理主体批准后，同一动作的 Observe 才被接受。

这是 Grant/receipt 核心链路测试，不是 OpenClaw 网关审批 UI 或真实人类在场证明。测试的临时 Grant、审批主体和结果均为固定夹具。

### 提交前补充：HTTP 管理权限与恢复回归

[server/intent_hold_test.go](../apps/agentshield/internal/server/intent_hold_test.go) 直接发送原始 bearer，避免通用测试助手自动替换成管理会话。验证匿名请求返回 401、decision token 返回 403；伪造平台批准不能创建 observation。管理批准或拒绝后重建引擎，同一批准重放不增加回执，反向批准和冲突 observation 返回 409，最终回执链验签通过。

此测试使用 `optional` 下未绑定 Intent 的 exec 场景；绑定 Intent 的任意 shell 命令因副作用未知会提前拒绝，不能用它触发 hold。测试没有修改该生产约束，也不作为绑定 Intent 的完整审批或平台真人审批验收证据。

## 4. 门禁结果

| 验证 | 实际结果 |
| --- | --- |
| 新增策略与执行引擎回归 | 修复前 12 个策略场景和 1 个执行场景失败；修复后通过 |
| `apps/agentshield`: `go test -race ./...` | 全模块通过 |
| `apps/agentshield`: `go vet ./...` | 通过 |
| linux/amd64、linux/arm64、darwin/arm64、windows/amd64 构建 | 全部通过，输出在临时目录 |
| Control API 的 `test_intent_v2_contracts.py` 与 `test_schema_contracts.py` | 115 通过；一个既有 Starlette/httpx 弃用警告 |

复测命令：

```bash
cd apps/agentshield
go test ./internal/grant ./internal/receipt \
  -run 'TestPatchDesiredPreservesExecApproval|TestPatchDesiredDoesNotInventExecApproval|TestPatchedGrantCannotExecuteWithoutPerUseApproval' \
  -count=1
go test -race ./...
go vet ./...

cd ../control-api
uv run pytest -q -o addopts='' \
  app/tests/test_intent_v2_contracts.py app/tests/test_schema_contracts.py
```

## 5. 适用范围与后续工作

修复保护后续 `patch-desired` 的策略重建。它不会重写历史已签名 Grant，也不会自动修复此前已被错误派生并部署的策略。若实际环境曾对带上述事实的 OpenClaw Grant 做过编辑，应通过受信管理流程复核并重新生成授权；不可直接修改历史签名文件。本轮没有读取或操作真实部署状态。

OpenClaw 平台审批和 SIQ 本地 hold 批准仍是两个不同的状态。本轮证明本地审批门槛在策略编辑后继续存在，不宣称已经完成两者的网关联动。平台批准不得直接冒充 SIQ 管理批准；该完整流程以及同 key 的 reset 生命周期、CodeBuddy 实机与独立复核继续待验收。

此前 `3d1a9b5` 的远端 CI 成功仍是历史证据；新修复尚未获得新 SHA 的远端 CI。本报告不复用旧 SHA 的成功状态来宣布修复发布完成。
