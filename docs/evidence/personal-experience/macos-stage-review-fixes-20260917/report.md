# macOS 阶段合并：独立复核修复

授权日期：2026-09-17。原 PR #69 头为 `d122ab219bab91a065f3063de3e9a420f2b87149`，本次修复实现提交 `3e07e08cdb75906ea8f36e8a84640a3c195af6f1`。保留 Luke 的 31 个原提交（包含 #64/#66/#67）与历史实机证据，本批只追加修复，不重写作者历史。

## 修复

1. OpenClaw 卸载现在保留原始快照已有的空 allow、load、paths、entries、本插件空 entry 与 plugins 容器；仍清除本安装创建的空容器，保留安装后用户添加的其他插件和设置。新增 7 种显式空配置往返及用户新增配置回归。
2. 原本所有 OS 的根级目录 symlink 豁免收窄为 Darwin `/var`、`/tmp`、`/etc`，Readlink 解析目标须为对应 `/private/...` 且目标自身必须是真实目录。其他 OS 的路径边界保持原先拒绝规则，叶节点仍不接受 symlink。补固定目标、错误目标、未知别名、Linux 根级链接及真实 Darwin 检查。
3. 新增 macOS CI job `macOS path and config regressions (component only)`。它测试实际 Darwin 文件系统路径与隔离配置，不启动用户宿主/launchctl、不调用模型，不作为三宿主原生验收。
4. 同步规格与 Luke 待办；P18/P19 仍分别绑定旧候选，不能把历史原生通过项转贴到本次修复候选。

## 本机验证

- gofmt 无差异；`go vet ./...`、`go test ./...` 通过。
- `go test -race ./internal/adapterinstall ./internal/stateformat ./internal/state` 通过。
- Python Schema 校验 214 passed，1 项既有依赖弃用 warning。
- 以干净实现提交构建 CGO=0 的 linux/amd64、linux/arm64、darwin/arm64、windows/amd64，4/4 通过，摘要见 cross-builds.json。二进制仅存本机临时验证目录，未签名或发布。
- 本机 Linux 不执行 Darwin 专用测试，其结果为 skip；新增远端 macOS CI 必须通过后才进行阶段合并。
- 修复前的对照日志保留：原始空配置保留用例在 main 通过、PR 失败；Linux 原有根链接拒绝用例亦为 main 通过、PR 失败。路径项是收窄兼容设计，不声称已发现远程利用。
- 开发中新增“用户事后新增配置”测试曾假设 allow 必然存在而 panic；已改为同时覆盖字段缺省，最终全量及 race 均重新通过。该问题来自本次测试编写，不归因于 Luke 产品代码。

## 合并口径与剩余项

本批是代码与分阶段证据整合，**不是 Mac-P00–P05 / N09 整体验收或正式发布**。远端 PR CI、独立 code-owner review 通过后按正常规则合并，不使用 admin bypass。真实三宿主新候选复测、批准继续/换参终检、可信 Skill 来源、自动登录恢复、通知点击回跳、签名公证和历史兼容窗口等仍按 Luke 待办进行。

#64/#66/#67 均为 #69 祖先，整合合并后可关闭重复 PR；不删除协作者分支。Windows #49/#57 的代码冲突仍需单独整合验证。本批不将 GLM v6 未提交工作或其他脏工作树混入 main。

本报告在合并前形成；最终合并结果以 GitHub PR #69 与 main 提交图为准。测试与构建 JSON 记录实际退出码，SHA256SUMS 只证明本证据包完整性。
