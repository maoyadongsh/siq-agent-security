# M39 用户服务配置验证

基线 a195fab 加 M35–M39 工作区增量；Linux arm64。新增 `service-unit` 命令与规格 §3.11.4。本次不增加 HTTP/schema 合同。

- `go vet ./...`、`go test ./...`、`go test -race ./cmd/agentshield` 通过，部分未修改包使用缓存。
- 正负向测试涵盖固定路径、百分号/引号/空格转义、控制字符拒绝、相对路径拒绝、二进制美元符号拒绝、stdout/stderr 关闭、初始化缺失不创建状态、重复导出、null 配置拒绝以及不生成凭据。
- 在 mktemp 创建的独立目录执行本次二进制 `init`、`service-unit`，状态路径包含空格及百分号；输出临时 siq-test.service，经 `systemd-analyze --user verify` 退出 0、无诊断。没有 systemctl link/enable/start，没有动正式服务。
- 四目标 `GOOS/GOARCH go build` 通过，输出 `/tmp/siq-m39-build/siq-<os>-<arch>`。

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64 | cea0c1b114418f3303272d3d0f9a1830be1cc469ce2fd260085ca925eb329730 |
| linux/amd64 | 50c1eb24d6ca481d293d319081dcdcf92c2829d9d630f4af0706c6d08b552d0b |
| darwin/arm64 | 2d82a09d4c1e8fe9886d3857a2b4854fe2921997b43b6468967f3a193ee55487 |
| windows/amd64 | b536a9b3674cc7b156c9220477fbf1fe18f6f5af893c985bcd53bb21d46c34a6 |

非 Linux arm64 仅构建；未跑真实后台运行、重启/注销保活、Windows/macOS 服务注册、宿主或浏览器旅程。后续安装事务必须保护未知已有文件并在失败后可恢复；导出的单元文件尚不等于已安装服务。
