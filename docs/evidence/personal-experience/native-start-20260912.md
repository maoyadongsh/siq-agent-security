# M37 原生启动验证

- 基线：`a195faba41d128d21222f819ebf96a766fb9cd01` 加保留的 M35/M36 和本次 M37 未提交增量。
- 环境：Linux arm64；本批复用现有健康、初始化合同，无新增 HTTP 端点或权限规则。
- `start` 使用同一个 Go 进程执行初始化和服务，不依赖 Python；Python 仅作为本次子进程验证驱动。

## 执行结果

在 `apps/agentshield`：`go vet ./...`、`go test ./...`、`go test -race ./cmd/agentshield ./internal/state ./internal/server` 均通过（部分未变包使用 Go 缓存）。新测试覆盖初始化先于 serve、配置保留、默认端口继承、占用端口不创建状态、匹配目录复用、错目录拒绝、无效参数与活跃 writer 拒绝。

在 `apps/control-api`：`uv run pytest app/tests/test_schema_contracts.py ../../scripts/personal-experience/test_start_local.py -q -o addopts=''` 在新增原生 start 测试前为 159 passed、2 skipped；跳过为未指定二进制的原生测试，不算平台通过。随后添加原生 start 用例，执行 `SIQ_TEST_BINARY=/tmp/siq-m37-build/siq-linux-arm64 uv run pytest ../../scripts/personal-experience/test_start_local.py -q -o addopts=''`：9 passed、无跳过。该测试实际启动本次二进制，在临时状态目录/随机 loopback 端口验证初始化、健康、重复复用、错目录拒绝及终止后身份保留；所有自建子进程已回收。既有 Python 启动器的原生生命周期与并发初始化同时回归通过。`uv run ruff check ../../scripts/personal-experience/test_start_local.py` 通过。

## 开发构建 SHA-256

由 `GOOS/GOARCH go build -o /tmp/siq-m37-build/siq-<os>-<arch> ./cmd/agentshield` 生成：

| 目标 | SHA-256 | 验证强度 |
| --- | --- | --- |
| linux/arm64 | `660a5766131c3d061ff007b84dabc8a7113b25330c94f47cb75d2b80b0930a02` | 实际运行 |
| linux/amd64 | `919a658eedb6c25f3306fde209e4336d999e67eed2dba9e0bdbfbf1c3a4b7845` | 交叉构建 |
| darwin/arm64 | `52e90a029ebb25648f6660e33619278c94aa8fe08393141bf8dbb221eb949c88` | 交叉构建 |
| windows/amd64 | `f8ea4a7645a88164c39f5b5a99958ea2cfef8a00be472619661684230c37e205` | 交叉构建 |

本批没有 UI/适配器改动，未重跑浏览器与智能体宿主旅程。Windows/macOS 原生运行、系统后台注册、签名安装包、注销保活仍未完成。健康目录摘要不是认证或同 UID 隔离。回退为成套旧 CLI/daemon 时保留配置、稳定实例和签名事实，不删除状态数据。本记录不声明提交、远端 CI 或正式发布完成。
