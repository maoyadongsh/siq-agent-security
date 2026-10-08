# OPT-15：矛盾的对账与观察不得按末条采信

日期：2026-10-08。前置提交：`8150cf13`。状态：本子项完成，OPT-15 仍在实施。

## 1. 实际影响

任务状态从已验签链投影对账和观察，不经过引擎的内存去重。修复前向同一预留追加两条签名对账：第一条 `deny`（未发生），第二条 `allow`（已发生）。`taskChainFacts` 返回空错误，并采用后一条 `allow`。观察摘要同样会被后一条覆盖。状态、停止和对账都会沿用这个投影。

引擎在 24 小时动作窗口内重启时会拒绝第二条对账，因此这个错误投影主要出现在链上已经存在两条闭合记录、而当前进程仍按原文读取的时候。本批不把引擎重启失败改写成状态成功。

## 2. 修复行为

同一预留出现第二条 `hold_reconciliation`，或第二条匹配的 `observation`，返回 `openshell_receipt_ambiguous`。既有 HTTP 映射为 409。恰好一条对账或一条观察仍按原投影。规格 §3.8 已同步。

## 3. 验证

| 验证 | 结果 |
| --- | --- |
| 修复前 `TestTaskChainFactsRejectsContradictoryClosure` | 失败，选中后写入的 `allow` |
| 修复后该测试，以及唯一预留加单条 `deny` 对账 | 通过 |
| `go test -run OpenShell ./internal/server` | 通过 |
| `go vet ./internal/server` | 通过 |
| `CGO_ENABLED=0` 构建 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 | `./internal/server` 通过 |

四目标构建不是 Windows 或 macOS 原生验收。

## 4. 仍未收口

线性扫描性能、生产 assert、请求超限状态码、token 哈希、依赖锁定和原生平台验收未在本子项处理。OPT-15 保持 implementing，总体仍为 11/16。
