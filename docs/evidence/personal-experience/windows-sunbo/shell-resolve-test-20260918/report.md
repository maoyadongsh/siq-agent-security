# Windows shell 哈希拒绝测试夹具修正

问题来自集成回归 `TestAdapterAndBootstrapShareVerifiedResolve`，不是新的生产哈希绕过。本机默认 PATH 无 sh，exec 启动错误被旧断言隐藏为空输出；此前显式 shell 对照也失败，但原因是测试写出的无后缀文本 fake-bin 在 Git/MSYS sh 的 `-x` 检查阶段被过滤，尚未到达哈希校验。

## 定位与修正

同一生产 resolve_verified_bin.sh、同一 not-a-release-binary 内容，三个专用目录对照：原文件名退出1并报告 binary not found；仅加 .exe 后退出1并明确报告 binary sha256 does not match skill-manifest.json；再改正斜杠结果相同。三组均无 stdout、暂存目录空。脚本从不执行候选文件。

提交将测试文件名改为 fake-bin.exe（Unix 仍按0755写入），收紧到明确二进制摘要不匹配，并断言没有暂存产物。运行启动失败现在会显示实际 error 与 shell PATH 提示，不自动跳过，不接受任意 staging failed 作为哈希校验证据。没有修改生产脚本、校验器或权限策略，因此无需修改运行合同。

## 原生验证

干净测试候选及精确退出码见 verification.json。仅对测试子进程 PATH 前置已安装 Git bin/usr/bin 与此前验证的固定原生 Python argv 转发器；不修改全局环境、不安装工具、不提权。Go 1.27.1、Windows amd64、CGO_ENABLED=0，TEMP/TMP 使用本批私有目录。

- `go test -json -count=1 -run '^TestAdapterAndBootstrapShareVerifiedResolve$' ./internal/skillmanifest`：退出0。
- `go test -json -count=1 -timeout=5m ./internal/skillmanifest`：退出1；31顶层pass、1fail、1skip。符号链接创建缺少权限的失败保留；仓库二进制缺席的旧跳过保留。
- `go vet ./internal/skillmanifest` 与修改文件 `gofmt -l`：退出0，格式输出为空。测试临时目录清空。

本批只改测试；生产二进制、宿主配置和模型调用均未改变。不声称全Go回归通过，不提高303项验收计数。原d9整组失败仍有效，不用本批局部成功覆盖旧结果。
