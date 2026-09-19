# Edge Agent：受控采集与证据传输

Edge 是企业环境侧的 Go 命令行代理，连接 [Control API](../../apps/control-api/README.md)与 [Connectors](../../connectors/README.md)。它负责设备注册、签名任务核验、受限子进程采集、证据签名和回执，不承担模型规划或个人端工具授权。

## 协议与执行链

```text
控制面注册 → 固定设备身份/公钥 → 获取签名采集任务
Connector describe → validate_scope → plan_scan → collect → checkpoint
Edge 签名 → 上传候选/证据 → 任务回执 → 失败回执后续补交
```

Connector 通过 NDJSON 交换结构化消息，不能直接创建 managed 资产或 effective 权限。Edge 对任务和采集执行实施协议、期限与资源边界；控制面继续校验批次、租户、签名和证据引用。设备密钥和签名材料保存在私密状态中，不能连同运行目录上传作证据。

## 构建与使用入口

从仓库根构建；命令中的注册码由目标控制面实际签发：

```bash
mkdir -p .tmp/bin
go -C edge/agent build -o "$PWD/.tmp/bin/edge-agent" .
.tmp/bin/edge-agent --help
```

| 命令 | 行为 | 前提 |
| --- | --- | --- |
| `register --control-plane URL --enrollment-code CODE` | 注册设备并保存服务端凭据与本地签名身份 | 有效注册许可，目标 URL 明确；不把真实 code 写入共享脚本 |
| `heartbeat` | 30 秒心跳，失败退避 | 已注册状态；持续进程 |
| `tasks` | 获取待处理任务、执行扫描并提交回执 | 已注册且凭据有效；先补交本地 pending receipts |
| `run-once --connector NAME --scope JSON --connector-bin PATH` | 一次本地采集并输出 NDJSON | 可信 Connector 二进制与受控范围；不自动纳管或上传 |

实际可选模块见 [Connector 列表](../../connectors/README.md)，范围字段以 [protocol](protocol/)和各模块的验证器为准。不要对未知目录或整机根目录运行试探扫描。

## 实现与验证

[main.go](main.go) 是 CLI；[state.go](state.go) 管理本地状态；[protocol](protocol/)是 Connector 共享类型；完整线协议见 [connector-protocol.v1](../../packages/contracts/connector-protocol.v1.md)。开发检查：

```bash
go -C edge/agent vet ./...
go -C edge/agent test ./...
```

当前 `run-once` 可选择 11 种 Connector；注册请求的 capabilities 仍只声明 hermes、docker、directory、openclaw 四种。模块可构建不能证明所有 Connector 已通过远程任务调度或客户环境验收，部署者须核对实际能力声明。采集到配置/进程只证明对应证据存在，不证明宿主已经受运行时保护。
