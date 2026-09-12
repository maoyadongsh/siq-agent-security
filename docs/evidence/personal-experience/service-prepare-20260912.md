# M41：用户服务配置归属与恢复验证

日期：2026-09-12。工作分支 `codex/personal-k002-platform-readiness`，候选为当前未提交工作区，继承 M35–M40；不是远端发布制品。

新增 `service-prepare`：先要求已初始化配置，再获取单写者，使用本地签名身份发布 `user-service.json` 和实例专属 unit 文件。签名绑定实例、规范化目录摘要、unit 名与内容摘要。记录仅代表发布意图，不证明 systemd 注册、服务运行或权限生效。

## 验证

- `go test ./...`、`go vet ./...` 通过，`gofmt -l .` 无输出。
- `go test -race ./internal/state ./cmd/agentshield` 通过。
- Python `uv run pytest app/tests/test_schema_contracts.py -q` 154 项通过；Ruff 通过。既有 Starlette/httpx 弃用提示保留。
- 新 Go 生产路径样例规范化随机实例与本地目录后重新签名；Python JSON Schema 校验必需字段、未知字段/越界路径拒绝，并独立验证 Ed25519 签名。
- 负向测试：未知同内容文件不能认领、配置漂移不覆盖、损坏记录/不同签名身份拒绝、缺少 writer 拒绝；恢复测试删除已归属 unit 后只补齐该文件。
- Linux arm64 实际二进制隔离临时目录：未初始化拒绝、初始化后准备、重复输出一致、文件摘要/0600 权限、缺失 unit 恢复、漂移拒绝且保留文件。未调用系统管理器，临时目录已回收。
- 四目标交叉构建通过；Windows/macOS 未原生执行。

## 候选构建

| 文件 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `44b42a4d57fd263e93fa115de9d785c5293bf81291728324c419fc5554910c5d` |
| siq-linux-amd64 | `55766dbb9bac5319c1fc0e3035cf509975c1cb64c165099ccf82fda23f647170` |
| siq-linux-arm64 | `c632110dd0dbd56a19b00e1108f168611f06809143ce006cfd3a3b3087b9efaa` |
| siq-windows-amd64 | `8ce1e66c042afaa69ddb95752ddde78a4abb984310a9b6a7ddc57c47610fec97` |

## 未完成边界

本批没有系统用户服务注册、自动启动、升级迁移或卸载。二进制路径/配置变化当前明确拒绝，后续需要显式迁移事务。签名归属不能对抗恶意同 UID；恢复为可控文件缺失故障测试，不是断电实验。下一步将归属验证接入注册、状态查询与清理流程，随后完成个人任务书其他项；完整目标仍 active。
