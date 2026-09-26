# Connectors：有范围、可解释的资产发现

本目录有 12 个独立 Go 模块，经 [Edge Agent](../edge/agent/README.md)子进程协议采集候选与证据。Connector 是发现入口；工具调用的执行前检查由 [runtime adapters](../adapters/runtime/README.md)承担。发现到某种宿主不等于支持其运行时拦截。

## 已有模块

| 模块 | 采集对象 | 解释与部署边界 |
| --- | --- | --- |
| [hermes](hermes/) | Hermes 配置与工具集 | 声明的 toolsets 不能冒充 effective 权限 |
| [openclaw](openclaw/) | OpenClaw agent 配置、模型与 workspace 声明 | 配置可发现不等于插件加载；不读取 auth-profiles 密钥正文 |
| [directory](directory/) | 显式目录内的 Skill/配置线索 | 必须给受控范围；目录发现不执行其中代码 |
| [dify](dify/) | Dify 应用配置线索 | 依具体配置证据生成候选，不跨产品查数据库 |
| [siq](siq/) | SIQ 业务智能体身份、授权摘要与 run 生命周期事件 | 只读 API 产生的 owner-only v1 安全投影；无凭据、无网络、无跨库访问、无提示词或结果正文 |
| [piagent](piagent/) | Pi Agent 配置线索 | 配置身份与运行保护分别确认 |
| [workbuddy](workbuddy/) | WorkBuddy 配置线索 | 不赋予已退出范围的 Linux 新接入能力 |
| [mcp](mcp/) | MCP 客户端配置与服务器声明 | 不证明远端工具内容可信或调用已获授权 |
| [docker](docker/) | 容器名称、镜像、标签等运行线索 | 标签/启发式只形成候选；环境变量值不作为输出 |
| [process](process/) | 进程级运行线索 | 依赖目标 OS 可见性，不保证全机发现完整率 |
| [systemd](systemd/) | systemd 服务线索 | Linux 服务可见性与扫描 scope 限定 |
| [kubernetes](kubernetes/) | Kubernetes 工作负载线索 | 受命名空间与访问凭据约束，不扩大集群权限 |

详细输入、平台限制和既有验证见[兼容说明](../docs/compatibility.md)与各模块源码。各模块均有本地测试；Hermes 与 OpenClaw 另有从当前工作树构建临时二进制、经 `--serve` 驱动 NDJSON 的 Linux 原生合同测试，覆盖范围拒绝、秘密边界、符号链接与预算/截断等场景。该证据不自动迁移到 macOS/Windows、正式安装包或真实用户目录。Docker 已有候选分类测试，也不能据此宣称恶意输出/超时等负向全部闭合。

## 数据链与安全要求

协议依次提供 `describe`、`validate_scope`、`plan_scan`、`collect`、`checkpoint` 与 `health`。输出为 candidate/evidence，Edge 统一签名；每条 evidence 必须被同批 candidate 引用，控制面拒绝孤儿证据。范围、输出限额、取消、超时、脱敏和游标语义见 [协议 v1](../packages/contracts/connector-protocol.v1.md)。

配置里的名称、模型和路径只构成声明或观察。候选需经确认才进入治理；所有推断保留 evidence_ids，模型或启发式分类不能创建有效权限。这种发现与执行分层支持研究“影子智能体”和配置漂移，同时避免把发现率误写成保护率。

## 开发与测试

从仓库根选择一个模块构建、测试；例如目录 Connector：

```bash
mkdir -p .tmp/bin
go -C connectors/directory build -o "$PWD/.tmp/bin/directory-connector" .
go -C connectors/directory vet ./...
go -C connectors/directory test ./...
```

其他模块替换对应目录即可。模块通过 Go `replace` 引用仓内 `edge/agent/protocol`，不要复制协议类型或移动路径后留下失效引用。新增/修改 Connector 必须检查空范围、根路径、符号链接逃逸、超大输入、秘密字段和错误响应；再验证 Edge 消费及控制面 schema，不能只检查自身构建。

远程注册能力声明目前仍为早期四种 Connector，详见 [Edge 限制](../edge/agent/README.md)。新的采集实验须记录源码、OS、实际范围、排除项与失败，不继承其他 Connector 的验收结论。
