# OPT-15：重复回执 ID 的查询与绑定

日期：2026-10-08。基线提交：`e549b6b3`。状态：本子项完成，OPT-15 仍在实施。

## 1. 实际影响

审批路径已拒绝重复 ID。会话执行绑定、任务执行绑定、预留哈希读取和任务链定位仍把 `receipt_id` 当作唯一键：绑定取第一条，任务事实取最后一条。

修复前定向测试失败，实际结果是 `openshell_decision_missing`。两条签名决定共用同一 ID 时，函数采用第一条并因其没有 Grant 报告缺失，没有报告歧义。若第一条带有可匹配 Grant，后续执行会忽略第二条。

## 2. 修复行为

已验签链中同一 `receipt_id` 出现两次时：

- 会话与任务绑定返回 `openshell_receipt_ambiguous`，HTTP 409。
- 预留哈希读取返回空值，对账形状检查失败关闭。
- 任务状态、停止和对账不返回其中一条任务。

唯一旧决定且缺少 Grant 时，仍返回原来的 `openshell_decision_missing`。唯一预留仍返回其哈希和任务 ID。回滚授权遇到同一预留 ID 的不同哈希时，保持原有拒绝，本批没有改写该循环。对账回执和观察回执的末条覆盖语义未改。

## 3. 验证

| 验证 | 结果 |
| --- | --- |
| 修复前 `TestOpenShellLookupsRejectDuplicateReceiptIdentity` | 失败，会话绑定返回 `openshell_decision_missing` |
| 修复后同一测试及唯一 ID 对照 | 通过 |
| `go test -run OpenShell ./internal/server` | 通过 |
| `go vet ./internal/server` | 通过 |
| `CGO_ENABLED=0` 构建 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 | `./internal/server` 与 `./internal/receipt` 通过 |

四目标构建只证明可以编译，不是 Windows 或 macOS 原生安装、宿主执行或发行验收。

## 4. 仍未收口

线性扫描的性能上限、生产 assert、请求超限状态码、token 哈希和依赖锁定尚未在本子项处理。OPT-15 保持 implementing，总体仍为 11/16。
