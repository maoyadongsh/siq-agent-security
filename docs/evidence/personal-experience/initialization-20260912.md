# M36 初始化验证

- 日期：2026-09-12，Asia/Shanghai；Linux arm64，Go 1.26.5。
- 基线：`a195faba41d128d21222f819ebf96a766fb9cd01` 加未提交 M35/M36 增量，新开发制品；历史 M35 构建及其证据保留。
- 合同：`local-client-initialization.v1.schema.json`；Go 的实例记录与初始化响应经占位摘要规范化后，由 Python 校验同一组样例。

## 实际验证

`apps/agentshield`：`go vet ./...`、`go test ./...`、`go test -race ./internal/state ./internal/server ./cmd/agentshield` 通过；追加 64 KiB 正向边界、私有发布和独立安装身份测试后重新执行 state race，通过。`gofmt -l .` 无输出。

`apps/control-api`：

```bash
uv run pytest app/tests/test_schema_contracts.py ../../scripts/personal-experience/test_start_local.py -q -o addopts=''
SIQ_TEST_BINARY=/home/maoyd/siq/siq-agent-security/.tmp/personal-experience/initialization/linux-arm64/siq-agent-security uv run pytest ../../scripts/personal-experience/test_start_local.py -q -o addopts=''
uv run ruff check app/tests/test_schema_contracts.py ../../scripts/personal-experience/start-local.py ../../scripts/personal-experience/test_start_local.py
```

153 项合同通过；原生启动器最终 8 项检查通过，Ruff 通过。未指定 `SIQ_TEST_BINARY` 时原生测试明确跳过；不能把跳过算成通过。现有 Starlette/httpx 弃用警告未修改。

原生测试使用临时目录与随机 loopback 端口，覆盖：空目录初始化后启动、重复复用、状态目录别名、错目录拒绝、运行中 init 被锁拒绝、正确目录配对、正常停止后重启保留 ID、两个初始化子进程保持同一 ID。所有自建进程在测试结束回收，未重启用户服务。部分配置/身份文件缺失的恢复由 state 故障夹具验证，不声明真实断电恢复通过。

## 构建身份

四目标均通过 `GOOS/GOARCH go build`，输出在 `.tmp/personal-experience/initialization/<os>-<arch>/siq-agent-security`：

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64，实际运行 | `f33afe9c12056988e38733d7d01ef043dbe60527130ee173d7525f8af07b212a` |
| linux/amd64，交叉构建 | `410bf51b0401fdc3a2ff8174009bf01422ceb395c3fa8cf823f65711e13f0b69` |
| darwin/arm64，交叉构建 | `64f1f4cfee9a8f2f93528bf2a76c593acbbfb7724ef42ac574237c24f968252b` |
| windows/amd64，交叉构建 | `bf5a13c7c1fecd2bbe01037e632ee26b380a3addc6f725471a3d2b103788470d` |

本批不包含 UI 或适配器修改，未重复跑浏览器/宿主验收。系统后台注册、安装器、签名分发及 Windows/macOS 原生运行仍未完成。`local-instance.json` 不承载权限，回退客户端不应删除或改写此记录；移除客户端/状态数据需要后续独立卸载流程。
