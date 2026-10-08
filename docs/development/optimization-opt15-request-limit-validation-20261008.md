# OPT-15：决策与审批正文超限状态

日期：2026-10-08。前置提交：`6cfb9789`。状态：本子项完成，OPT-15 仍在实施。

## 1. 实际影响

`POST /v1/decide` 与 `POST /v1/observe` 在进入处理函数前读取正文。全局决策凭据上限 4 MiB。修复前超过上限时，认证层返回 400 `invalid decision request`，与畸形正文使用同一状态，且不会把正文交给后续处理。`POST /v1/hold/{id}` 超过 64 KiB 同样返回 400。两条路径都不会改链，但调用方无法把超限和格式错误分开。

## 2. 修复行为

决策与观察超限返回 413 `decision_request_too_large`，不恢复正文、不调用引擎。畸形或身份不完整仍返回 400。审批正文超限返回 413，格式错误仍返回 400。规格 §3.8 已同步。资产动作等已经单独返回 413 的入口未改。

## 3. 验证

| 验证 | 结果 |
| --- | --- |
| 修复前 `TestDecisionPathsRejectOversizedBodiesBeforeMutation` | 失败，超限 decide 为 400 `invalid decision request` |
| 修复后该测试 | 通过：decide/observe 为 413，畸形 decide 为 400，超限 hold 为 413，链头不变 |
| `go test -run 'TestDecisionPathsRejectOversizedBodiesBeforeMutation\|TestHoldHTTP\|OpenShell' ./internal/server` | 通过 |
| `go vet ./internal/server` | 通过 |
| `CGO_ENABLED=0` 构建 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 | `./internal/server` 通过 |

四目标构建不是 Windows 或 macOS 原生验收。

## 4. 仍未收口

线性扫描性能、生产 assert、token 哈希、依赖锁定和原生平台验收未在本子项处理。已查看的三处 panic 分别位于规范编码失败和启动时随机源失败，本次没有复现由请求触发的错误失败方式，因此未改。OPT-15 保持 implementing，总体仍为 11/16。
