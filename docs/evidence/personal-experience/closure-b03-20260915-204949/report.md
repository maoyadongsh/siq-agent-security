# B03 证据报告 — UP05 并发 + UP07 状态兼容 (2026-09-15)

## 1. 范围
- UP05 并发: skillinstall 组件层 7 测试 (plain + -race) + HTTP 层 2 测试。
- UP07 状态兼容: 未来格式 / 破损标记 / 破损存储签名 / 陈旧 revision / 真实二进制 五条腿,
  全部走真实 HTTP/CLI 写入口; 核心不变量 = 拒绝时零变更 (不建目录、不迁移、不加隔离锁、
  不改写历史、不"修复"为当前版本、不推进 revision)。
- 写入口枚举: write-entrypoints.json (路由 110 条来自 server.go mux 表; CLI 57 命令来自
  main.go switch + state_compatibility.go 豁免表)。

## 2. 关键事实
- 请求时闸门 (server.go ~L316) 对每条 /v1 请求执行 RequireStateCompatibility,
  失败 -> 503 {"error":"state_incompatible"}; 未来格式与破损标记均落入该路径。
- store 层闸门 (state.Open -> stateformat.Check + CheckStateCompatibility) 是所有 HTTP/CLI 写的公共咽喉。
- CLI 闸门 checkCommandState 在命令 switch 之前运行, 豁免表之外全部覆盖;
  失败输出 stateformat.RecoveryMessage 并 exit 1。
- 拒绝路径零变更由字节级快照 (全目录 walk + sha256) 证明, 基线取篡改后状态。
- 陈旧 revision: stale expected_revision -> 409, 随后正确 revision 的请求 200,
  证明拒绝不消费 revision。
- 破损存储签名: analysis.json 单字节翻转后, 读取与重放导入均非 2xx, 磁盘字节保持篡改态 (禁止修复)。
- 真实二进制: go build ./cmd/agentshield, SIQ_AGENT_SECURITY_STATE_DIR 指向未来格式状态目录
  + 一次性 HOME; admit exit 1 + RecoveryMessage + 状态目录零变更; state-status (诊断豁免) exit 0 且只读。

## 3. 覆盖与遗漏
- 直测写入口 6 条 (skill-imports, intents, intent-bindings, admit, raw-task-content/activation,
  grants/{id} action); 其余写路由依赖 central-gate 结构论证 + store 咽喉 + 真实二进制腿, 见 gaps。
- 遗漏 2 项 (not_exercised) 及解除条件见 checks.json。

## 4. 隔离与安全
- 全部负例 fixture 仅篡改 t.TempDir 所属状态目录与导入 blob; 未触碰真实
  ~/.config/siq-agent-security 与 ~/.openclaw; 无 bypass、无断言放宽、无时钟改动。

## 5. 复现
```
cd apps/agentshield
go vet ./...
go test ./internal/server/ -run 'TestUP0[57]' -count=1 -v -timeout 600s
go test ./internal/skillinstall/ ./internal/server/ ./internal/state/ ./cmd/agentshield/ -count=1 -timeout 900s
```
