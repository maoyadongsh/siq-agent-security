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

## 后续：真实 Windows 构建正向暂存

进一步定位旧 `TestResolveStagesVerifiedBinary`：固定查找无后缀仓库产物，且 Windows 上仍断言 POSIX 执行位。测试提交 ac28c0f 在 Windows 选择 `.exe`，保留非 Windows 执行位要求；两侧均断言普通文件并逐字节比较暂存前后内容。生产代码不变。

先用既有干净 de5 原生 exe 经实际 shell + 原生 Python 成功暂存，摘要一致、源未变、普通单链接 `.exe`；精确删除本批临时副本后暂存根为空。本地模式警告明确保留：它不是发布清单中的 pinned 制品，没有伪造正式发布验签。

随后在干净 ac28c0f 构建真实 `apps/agentshield/siq-agent-security.exe`（此前该路径不存在），再运行完整 skillmanifest 包。32项通过、1项符号链接权限失败、0跳过；正向暂存和错误哈希拒绝均通过。native build、vet、fmt均退出0，包退出1如实保留。构建信息确认 vcs.modified=false，摘要见 positive-verification.json。结束前核对本批构建文件摘要后删除，临时目录为空。没有覆盖原文件或运行该二进制。

此批测试变更没有生产行为变化；沿用原生产跨平台验证，未为已知未修的其他包失败重跑整仓。Windows固定验收分母和计数不变。
