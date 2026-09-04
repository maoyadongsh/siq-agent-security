# AgentShield 本地控制台（embed）

`embedded/` 由 `apps/web` 的本地模式构建写入，再由本包 `go:embed` 进 `agentshield` 二进制。

```bash
make -C apps/agentshield ui
# 或：cd apps/web && npm ci && npm run build:local
```

未构建时保留占位 `index.html`，`agentshield serve` 的 `GET /` 仍可响应，Go 测试不依赖 npm。
