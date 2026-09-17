# Windows 集成候选回归

基线 main 8dea99b，受测合并源码 d9f7a309e8cd29e0c2478bb2bdcbdea14ddc2ed6。包含本任务 PR #48、#49、#56、#57、#73、#74、#76 的完整提交历史。不是最终验收候选，未并入其他协作者 PR #75。

唯一内容冲突位于 state.checkStateParents：保留 main 的 stateformat.CheckParents 调用；该函数已合入 PR #57 的 ValidatePath 首检查，兼顾原始路径拒绝和既有父目录检查。未放宽身份或权限。

fmt（输出为空）、vet、Windows 原生构建及 Linux amd64/arm64、Darwin arm64 构建均退出0；Windows CLI 30项顶层测试全部通过，无跳过。锁定环境 Schema 校验退出0。二进制摘要见 checks.json。仅交叉构建，不冒充对应 OS 实测。

七个受影响包测试命令退出1：顶层362通过、12失败、26跳过，3包通过、4包失败，详情见 tests.json。保留符号链接前置失败、旧锁恢复、迁移/提交恢复、Python/ shell验证等真实结果，不降低断言。此批不是全 Go 模块通过。

Python 制品获取失败诊断：PATH 原有 MSYS python3 的 sys.platform=win32、platform.machine()为空，产品无法选择 windows/ 制品。C:/Python313/python.exe 返回 AMD64。仅在子进程 PATH 前置私有固定 argv 转发程序，把 python3 转至该原生解释器，原始 TestPythonFetchArtifact 测试退出0（3.832秒）。没有修改产品、测试或全局 PATH；最初控制器相对路径错误发生在测试启动前，随后改用绝对路径。原始包失败结果保留。

旧锁恢复失败已最小复现于 #79；Windows processAlive 对其他正PID保守返回true。该问题尚未修复。#39/#42/#77仍是独立未解决的共享问题。固定验收台账68/303通过、4失败、8受阻、223未测，另3项系统中断按用户要求排除。不能将不同候选历史证据拼为本候选通过。

复现：固定本SHA、原生Go工具链和私有TEMP/TMP，执行 gofmt -l .、go vet ./...；go test -json -count=1 -timeout=20m 对 state/stateformat/adapterinstall/adapters/inventory/skillmanifest/receipt；另对 cmd/agentshield 执行 -run ^TestWindows -timeout=15m；随后四目标构建及锁定 Python Schema 校验。保留原始JSON测试事件与各命令退出码；本公开目录为脱敏摘要，私有完整日志位于本机 integration-results-r1 和 integration-supplement-r1。
