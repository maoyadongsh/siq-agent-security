# Windows Hermes 原生 CLI 接入入口补充证据

受测实现 `de5de5f72d5a9a5f60323334f038abbae6c80ad1`；go version -m 确认 Windows amd64、Go 1.27.1、vcs.modified=false。二进制及实际已安装 Hermes CLI 摘要见 verification.json。适配器取 PR #80 工作树，与 de5 的 adapters/runtime 无差异。本批没有生产代码变更。

## 实测与复现

使用权限受限的专用目录。HOME、USERPROFILE、APPDATA、LOCALAPPDATA、TEMP、TMP、SIQ_AGENT_SECURITY_STATE_DIR 全部指向隔离目录；不继承 HERMES_HOME。SIQ_AGENT_SECURITY_HERMES_CLI 指向实际已安装 hermes.exe，SIQ_AGENT_SECURITY_ADAPTERS_DIR 指向候选 adapters/runtime。仅继承系统运行所需环境，不继承模型密钥。建立 `.hermes/profiles/native-cli/config.yaml`，初始内容（Windows CRLF）见 verification.json 的 original_config。

1. 候选 `agent.exe init`，然后 `adapter instances hermes`。按 config_dir 精确匹配自建 profile，所有发现根必须在隔离 home 内。
2. `adapter preview hermes --instance <ID> --enable-native`：profile 全文件摘要不变。预览明确实例、插件/凭据引用、备份与配置变更，不授予内置工具覆盖权限。
3. 显式执行 `adapter install hermes --instance <ID> --enable-native`，再执行同实例 `adapter status`。实际 Hermes 配置命令成功、插件目录存在，status 返回 installed。
4. finally 执行 `adapter uninstall hermes --instance <ID> --enable-native`。插件目录移除，临时目录空；原始备份逐字节等于 CRLF 初始配置，摘要也等于预览的 before_sha256。恢复配置保留 custom_fixture，enabled 为空，disabled 恢复本插件；宿主规范化格式并增加 `_config_version: 44`。

六个命令和控制器均退出0；没有启动 SIQ daemon，没有模型调用或日常 profile 操作。只读进程核对没有 siq_adapter_document 的 Python/Hermes 子进程。私有状态、备份及日志保留追溯。

r1 控制器错误假定仅有一个发现根，在安装前断言退出1；r2 按精确路径选择，并确认全部根在隔离 home。原失败保留。另一次证据整理断言错误地按 LF 重建初始字节，在写出材料前失败；依据原始预览摘要核对 CRLF 后修正，不重跑或覆盖运行结果。

## 证明范围

真实 SIQ exe + 实际 Hermes CLI 配置接入与卸载，补足此前库测试采用未执行 placeholder SIQ Binary 的不足。保持 `runtime_verified=false`、`restart_required=true`；不证明实际会话加载、自检、工具执行或 OS 隔离。预览和 install 为两个命令，install 重新准备计划，本批不证明跨命令旧预览 digest 的批准绑定。既有漂移负向见 hermes-native-isolation-20260918。

本批不提升完整宿主条目通过数；最终候选未固定。
