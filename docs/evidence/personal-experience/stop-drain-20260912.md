# M38 停止排空验证

- 基线：a195fab 加工作区 M35–M38 增量，未提交开发候选。
- 修复范围：`cmd/agentshield/main.go`、`serve_lifecycle.go` 和测试；规格 §3.11.3。
- 原因：`http.Server.Serve` 在 Shutdown 开始后就可返回，原主 goroutine 随即释放 Writer，不能用 Serve 返回证明请求内状态操作完成。
- 现在先停止接纳业务请求，等待 HTTP handler 完成，再让 cmdServe 返回；默认 3 秒连接排空超时后 Close 取消请求上下文，继续等 handler。未响应取消的 handler 会延长退出，不提前交出写锁。定时刷新协程同样在释放锁之前结束。该保证不包含外部强杀或所有任意后台任务，既有 runtime-check 关闭逻辑保持。

## 已执行验证

`apps/agentshield`：

```bash
go test -race ./cmd/agentshield -run 'TestHTTPStop|TestDrain' -count=10
go vet ./...
go test ./...
go test -race ./cmd/agentshield ./internal/state ./internal/server
```

全部通过，未变包可使用 Go 测试缓存。专项验证包含真实 TCP 请求；测试在 request context 取消后仍阻塞 handler，确认服务尚未返回，释放后获得超时诊断。新请求在 drain 期间为 503 且无业务调用；无请求停止正常返回。并发等待采用事件通道，超时只作为失败边界。

`apps/control-api`：`SIQ_TEST_BINARY=/tmp/siq-m38-build/siq-linux-arm64 uv run pytest ../../scripts/personal-experience/test_start_local.py -q -o addopts=''`，9 passed。临时状态/随机端口的真实二进制启动、停止、复用、错目录拒绝和实例保留全部通过，自建子进程已清理。未操作用户 daemon。

## 本批构建

四目标 `go build` 成功，输出在 `/tmp/siq-m38-build/siq-<os>-<arch>`：

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64（实际运行） | `c99f985ed627061dd5642ff4a22fb9695eeb25f46c0a425cc052ffc718a382e2` |
| linux/amd64 | `ec43695d1a26eac8427a6cb44f8789996078c98a41758c70605d3424bfa385c0` |
| darwin/arm64 | `e951c47034244736f176fbb4333084d3686a39c9ba6e6a4600147ff26e296cf2` |
| windows/amd64 | `8b76803690ac4511b60659d8967d0cbacb530cd9a8faa666fc9c2b72bbcfa886` |

非 Linux arm64 仅交叉构建。未改 UI/平台适配器/合同，未复跑浏览器、真实智能体旅程或 Python schema。系统服务注册与签名制品仍未完成。停止超时返回错误供诊断，不将强制关闭连接算作正常排空；回退不会修改历史状态，但旧程序仍有该退出窗口，不建议在活跃写入时换回旧版本。
