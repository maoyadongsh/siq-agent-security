# Mac-P02/P04：OpenClaw 2026.9.4 原生 Skill 装前策略

**结论：本批修复了 OpenClaw 装前策略协议与接入，尚未完成 macOS 平台整体验收。** 受测干净实现候选为 `8fe579ad7ef916837f8656bfa9a4488060864038`，darwin/arm64、CGO=0、`-trimpath` 二进制 SHA256 为 `e86646f245225f0dce93658469df098f400a6193d71cb33ae1665944001201d3`。本机 macOS 26.6.2 / Apple Silicon，公开 OpenClaw 2026.9.4；测试仅用隔离 HOME/profile/状态及仓库内无害/恶意静态 Skill fixture，没有调用付费模型或触碰日常宿主实例。

## 本批实际行为

`adapter preview/install openclaw --enable-install-policy` 现在可显式配置宿主正式 `security.installPolicy`，默认安装仍不注入；未知既有策略拒绝覆盖。`policy-exec` 改为严格 OpenClaw 协议 v1：缺字段、未知目标、旧请求、软链接暂存根或准入持久化失败时 block。安装计划仍保留配置备份与外科卸载。

使用公开 `openclaw skills install` 原生 CLI 验证：恶意 Skill 被策略在目标发布前拒绝，目标不存在；条件准入的 Skill 未确认时不安装，显式 `--acknowledge-install-policy-warning` 后才安装；纯文档 Skill 允许安装。宿主 `config validate` 通过，随后产品钩子与策略卸载，配置恢复安装前原文。私有原始报告摘要及 13 条断言见 [脱敏原生证据](evidence/openclaw-native.json)；原始 CLI 输出、状态私钥、运行配置和配对信息没有归档。本证据只证明本地 Skill 安装路径，未将 Plugin 或所有网络来源标为通过。

同一候选的公开 `openclaw agent --local` 托管桥复测通过 17 条断言：受控本地模型的允许读到达模型，越界写在执行前拒绝，签名回执链通过。`service_unavailable_denial` 曾在 [P18](../p18-20260916-235000/report.md) 候选通过，但本批未重跑，故本批矩阵仍为 `not_run`，不跨 SHA 借用。

原生批准夹具按固定候选重跑，6 个 hold 决策、0 个宿主批准请求、0 次工具执行，exit 1；私有链 `verify` 为 12 回执、verified=true。以前的“worker 提前退出，可能插件未加载”诊断不准确；现在已查明是 OpenClaw 2026.9.4 没有本适配器所要求的等待式执行前复验检查点。公开 `onResolution` 是异步通知，不能作为原子预留前的可否决回调；适配器继续 fail-closed。不能把批准继续或批准后最终参数复验写成 pass。其公开 `before_tool_call` 也没有可信的逐调用 Skill 因果来源；管理员签发的 `controlled_session` SEC 只能证明受控会话范围，不能替代该事实。[官方安装策略](https://docs.openclaw.ai/tools/skills-config)、[官方工具钩子合同](https://docs.openclaw.ai/plugins/hooks/tool-policy)与本机分发物类型/实现已核对，规格已更新。

## 验证与尚缺门槛

[18 行矩阵](manifest.json)仅填写本机 OpenClaw macOS/arm64：本候选 discovery、normal_execution、pre_execution_denial、install_interception **4/8 pass**；service_unavailable_denial 本批未重跑；approval_resume、final_parameter_recheck、skill_attribution 因宿主能力缺失 blocked。Hermes、WorkBuddy 与其余 OS 行保持 `not_run`，不把 P18 的不同候选结果贴到本候选。[结构校验](structure-report.json)退出 0，[原生覆盖校验](native-report.json)退出 3，符合未完成现状。

Go 全量测试、vet、gofmt、四目标交叉构建及适配器 race 检查已执行；原生构建/安装/批准夹具与摘要见 [verification.json](verification.json)。本机只读查询显示 Developer ID Application 可用签名身份数为 **0**，没有发现发行/公证凭据环境变量；未尝试自签冒充正式发行，也未提交 Apple 公证或发布。PR 仍需与测试执行者不同的维护者审阅；CI 绿不等于独立审阅或本机原生验收。当前测试目录仅保存在忽略的 `.tmp`，没有上传密钥、账号、配对码、私有 prompt 或绝对用户路径；日常 OpenClaw 配置未写入。

后续依赖：OpenClaw 上游提供等待式、可否决的批准后执行前检查点，或产品实现并实测 N06 的安全重试；三个宿主若仍无逐调用 Skill 因果事实，必须维持 unknown/受控会话等级；正式 Apple 公证需要受授权的 Developer ID 身份与公证凭据；独立审阅需维护者实际完成。发布/合并不由本证据自动授权。
