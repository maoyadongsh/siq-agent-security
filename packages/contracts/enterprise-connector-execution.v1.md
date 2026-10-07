# 企业连接器可信启动 profile v1

此 profile 规定 Edge 本机启动条件，Connector 消息仍为 `connector-protocol.v1`，不修改既有签名文档的字段或字节。决策依据见 [ADR-057](../../docs/adr/0057-enterprise-connector-execution.md)。

1. 受管来源为已确认 Discovery Plan 与已验证签名的 `enterprise-release/v1` 暂存包。名称、版本、摘要、架构和路径必须相互绑定；不接受请求指定程序或 PATH 候选。每次启动最终读取实际程序并核对计划固定的 SHA-256。
2. Linux 程序逐级无符号链接；父目录当前 UID/root 所有且无组/其他写权限，root sticky 临时祖先例外。程序当前 UID 所有、0500、普通文件、单链接、ELF，1～256 MiB；读前后元数据不变。执行使用仍持有的已验证描述符，不再按原路径重开。
3. 受管环境为固定 PATH、当前 HOME 和 `SIQ_CONNECTOR_NAME`、`SIQ_CONNECTOR_VERSION`、`SIQ_CONNECTOR_TIMEOUT_MS`。不传设备身份、管理/模型凭据、LD_PRELOAD 等其他环境。此为环境最小化，不等于 OS 沙箱或禁止网络的独立证明。
4. 原子签名发行与计划验证失败仍拒绝；可信启动失败映射既有 `unsupported`，固定消息提示核验计划/发行及部署目录。不删除状态，不自动改权限/重新注册，不降级开发执行。
5. `run-once` 是明确的开发入口，须绝对 `--connector-bin` 或绝对 `SIQ_CONNECTOR_BIN_DIR`；目录项缺失即失败，禁止继续搜 PATH。开发配置不提升为已验证企业安装。
6. 每操作默认 60 秒、stdout 默认 8 MiB。没有换行的连续输出同样受限；超限停止子进程，后续调用返回 closed。诊断不透传任意 stderr 或 Connector 错误正文。
7. 本 profile 的受管实现仅 Linux。其他平台明确 unsupported，保持独立开发入口，不生成虚假的跨平台可信执行证据。无需迁移旧签名格式；旧设备缺少确认计划时需经原安装入口核验和确认后才能恢复受管扫描。
