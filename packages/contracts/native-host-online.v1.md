# 原生宿主在线接线 v1

ADR-056 的 Linux 显式启用路径。`serve --native-host` 从本状态目录的 `native-host/connection.json` 读取独立宿主连接配置；缺省不开启。配置精确字段为 `schema_version=native-host-connection/v1`、`credential`（`nhp-` 加 64 位小写十六进制随机数）和 `verification_socket`（宿主私有 Unix socket 的规范绝对路径）。目录须为当前用户私有，配置文件 0600；配置、路径和密钥不进入日志。此凭据只用于本协议，不是管理、配对或普通运行时凭据，不挂载进 Hermes。它由可信启动器与 daemon 共用；不借助环境变量传递。

## 宿主发布

`POST /v1/native-host/events` 仅接受独立宿主 Bearer 凭据，拒绝管理员会话、全局 decision token、普通运行时凭据和浏览器 Origin。请求最多 64 KiB，精确结构为 `schema_version=native-host-publish/v1`、`subject`、`event`；subject 精确包含 platform、instance_id、agent_id、session_id、task_id。要求 Linux Hermes 原生签名身份及真实有效会话。事件如下：

| kind | 其余精确字段 | 行为 |
| --- | --- | --- |
| task_begin | artifact_sha256 | 与身份策略及可信运行核验匹配后 Begin |
| skill_source | load_id、parent_load_id、source | parent 无父时为空串；source 为 native-skill-source/v1；由 Go 解析实际安装后 Load |
| call_prepare | tool、tool_call_id、request_binding、load_id | 无加载时 load_id 为空串；只发布最终调用元数据 |
| call_finish | tool_call_id、request_binding | 消耗原调用；不是副作用证明 |
| task_end | 无 | 即时失效 |

重复、未知字段、错误大小写、null、无效结构和超限请求拒绝，不把额外模型字段投影成 Authority。成功响应精确为 `schema_version=native-host-published/v1, accepted=true`，不返回 Grant、SEC 或执行许可。失败只返回固定类别。宿主须先通过原生内核凭据通道和 RuntimeGuard 验证实际进程，不能把普通 HTTP 客户端的声明转发为可信事实。

## 反向核验

daemon 仅连接启动时固定的私有 Unix socket，不接受事件指定 URL。使用同一独立宿主凭据调用 `POST /verify`，请求为 `schema_version=native-host-verification/v1`、随机 32 位十六进制 nonce、完整 subject 和 artifact_sha256。响应精确为 `schema_version=native-host-verified/v1`、原 nonce/subject/artifact_sha256、expires_at、install_mounts。数组最多 64 项，每项为 instance_id、install_id、claim_signature、host_root、runtime_root；无安装时为空数组。

可信宿主只为预先登记的真实实例/会话响应；每次响应前运行 RuntimeGuard.verify，并核对每个安装的实际只读映射。调用使用五秒有界等待、64 KiB 响应上限、无代理/重定向和独立 nonce。expires_at 是受控运行的最晚寿命，上限一小时，不是允许缓存运行事实的窗口；Go 每次必要的加载/调用/授权验证仍发起新核验。读取失败、nonce/subject/制品错配、到期或反向通道故障都拒绝，不复用上次成功值。

## 决策与初始化

构造 Engine 时注入原生查询器；server 初始化实际身份/安装 Store 后仅绑定一次同一查询器与 NativeHostBridge。不得在已运行 Engine 上替换权限依赖。未绑定、缺少核验服务或记录缺失均失败关闭。

实际工具参数继续通过 `/v1/decide`，使用既有请求级运行时凭据；认证完成后，必需原生身份先执行唯一 Bind，再进入原有 Engine 的 Agent/Skill/祖先交集。任何非 allow（包括 hold）或裁决异常都关闭该次在途调用，不宣称 handler 已执行；allow 后仅接受一次宿主 Finish。HTTP 响应丢失不会恢复原调用。无 Skill 只能从已登记任务的真实状态派生。

此次接线不自动开启新身份创建；须待真实启动器/业务接线完成后另行通过启用门禁。旧身份路径保持原行为。内存运行事实不跨 daemon 重启恢复，原签名证据继续保留。状态只写既有上下文/调用/审计目录；回查安装路径只用于核验，不授予读写权限。部署文档与组件联验须明确真实核验器、合成核验器以及 OpenShell 业务验收的区别。
