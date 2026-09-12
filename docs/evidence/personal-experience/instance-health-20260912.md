# M35 状态目录健康绑定验证

- 日期：2026-09-12，Asia/Shanghai。
- 基线：`a195faba41d128d21222f819ebf96a766fb9cd01` 加当前未提交 M35 增量；新开发构建，不属于历史发布快照。
- 实测环境：Linux arm64；测试在临时状态目录和随机 loopback 端口执行，不修改用户运行配置。
- 合同：`packages/contracts/local-service-instance-health.v1.schema.json`；Go 输出经规范化占位摘要回灌 `apps/agentshield/testdata/contracts/local-instance-health.json`，Python 校验必需字段、摘要边界及禁止额外路径字段。

## 验证命令与结果

在 `apps/agentshield` 执行，均通过：

```bash
gofmt -l .
go vet ./...
go test ./...
go test -race ./internal/state ./internal/server ./cmd/agentshield
```

最终 CLI 清理后重新执行全量/vet/CLI race；state/server 未再修改。四目标 `GOOS/GOARCH go build ./cmd/agentshield` 全部通过，输出在 `.tmp/personal-experience/instance-health/<os>-<arch>/siq-agent-security`。

在 `apps/control-api` 执行：

```bash
SIQ_TEST_BINARY=/home/maoyd/siq/siq-agent-security/.tmp/personal-experience/instance-health/linux-arm64/siq-agent-security uv run pytest app/tests/test_schema_contracts.py ../../scripts/personal-experience/test_start_local.py -q -o addopts=''
uv run ruff check app/tests/test_schema_contracts.py ../../scripts/personal-experience/start-local.py ../../scripts/personal-experience/test_start_local.py
```

157 项通过，Ruff 通过。已有 Starlette/httpx 弃用警告保留，不影响本批结果。

原生生命周期测试实际调用开发二进制和启动器，覆盖新启动、同目录复用、符号链接别名复用、错目录不复用且不创建第二 daemon、错目录配对失败及正确目录配对成功。测试不输出配对码/凭据，结束时回收自己创建的进程。其余启动器检查使用明确的进程测试替身，不算原生平台证据。

## 开发制品 SHA-256

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64（实测） | `b6415310d25d8b084999d91aff26a29cca06eff14682f55cbbbe691627ca3d93` |
| linux/amd64（交叉构建） | `116322e59e1ff60838f198385b3aa0f7b4ca5aa2460da7985bfd50ed16a66580` |
| darwin/arm64（交叉构建） | `9d55495fcc08920bebb2705c80f00fac757337d27c07c99a4e30f8e976e93762` |
| windows/amd64（交叉构建） | `9414cf67e943668096a8eef584ddec4e7054252a9d9f6b2cf681c6eda94c4d8e` |

目录摘要用于防止误连；不是秘密、稳定设备身份、恶意同 UID 隔离或跨请求原子认证。旧 daemon 需要升级才能被新 CLI 识别。未测试 Windows/macOS 原生运行、安装器、系统后台服务、浏览器旅程或智能体平台；这些门槛保持未完成。回退时恢复成套 CLI/daemon/启动器，不修改或重签历史事实记录。
