# OPT-08 D3f：宿主持续服务循环与真实 OpenShell 联验

日期：2026-10-07。状态：本批实现和联验完成，OPT-08 保持 implementing；总体完整验收仍为 9/16。

## 问题与实现

此前宿主通道将尚未收到连接的 accept 超时与已连接请求失败统一报告为 ChannelError。日常模型运行可能长时间没有工具请求，监管器必须区分正常空闲与通道故障，不能靠固定工具次数驱动服务。

按 [native-host-loop/v1](../../packages/contracts/native-host-loop.v1.md)，新增 ChannelIdle 子类，仅用于未接受连接时的超时；不消耗调用序号。已连接后的接收超时、坏包、错误凭据和重放仍拒绝。

`host_online.HostLoop` 在已授权的固定 UTC 租约内持续转发已有 DecisionRelay，并以单调时钟再次限制寿命。启动一次、失败不可重启；fork 后控制在取得任何继承锁之前拒绝。每次等待和转发检查实际 RuntimeGuard；转发返回时若已观察到停止、过期或 guard 失效，则返回固定拒绝。普通应用层 deny 不会禁用后续合法请求。

关闭先停止接收，再有界等待线程退出，未退出不得宣称清理成功。循环借用 guard，由所属启动器退出 namespace 目录上下文后关闭，避免资源关闭顺序导致误报。业务 Supervisor 仍须自行执行业务授权检查、租约管理及精确沙箱回收。

## 验证结果

| 层次 | 结果 | 证明范围 |
| --- | --- | --- |
| Python 相关定向 | 88 项通过 | 循环、内核凭据通道、HTTP 转发及在线核验相关行为 |
| 最终循环定向 | 15 项通过 | 在上述基础上新增已连接无包超时、普通拒绝后允许两项；与 88 项有重叠，不相加 |
| 静态检查 | 修改的五个 Python 文件 Ruff 通过 | 本批文件；没有重跑无关 Go/前端全量 |
| 真实 OpenShell | 18 项权限检查通过 | 原生 Hermes 工具、宿主持续循环、真实 Go HTTP 裁决、签名安装来源及文件效果 |
| 回执 | 18 条签名回执：14 allow、4 deny | 另有 5 次尝试在裁决前拒绝，不伪称 deny 回执 |
| 业务身份 HTTP 客户端 | 启动 8 项、撤销后取消 2 项通过 | 业务独立客户端协议调用，尚非日常业务路由 |
| 清理 | 工作线程退出；沙箱删除和网络清理成功 | 原网关配置与 TLS 材料摘要不变 |

fork 负向测试在已持有控制锁、另有 HTTP 夹具线程的情况下创建子进程，Python 发出预期的多线程 fork 警告。子进程在两秒 alarm 保护下完成 start/close/assert_running 三个拒绝检查，正常退出；没有屏蔽警告或跳过测试。

真实联验命令：

```bash
SIQ_NATIVE_BUSINESS_CLIENT_PROBE=1 python3 patches/hermes/run_openshell_runtime_probe.py \
  --online --output var/optimization-20261007/opt08-native-host-loop-01
```

联验已用产品 HostLoop 替换原逐请求线程池。固定测试操作员仅负责在原有指定调用前触发真实撤权及记录事件，实际请求仍经过原 DecisionRelay。Go 联验通过，用时 30.759 秒。脱敏摘要、代码与原始结果摘要见 [证据](evidence/optimization-20261007/native-host-loop.json)；私有运行文件不提交。

## 边界与后续

本批实际运行进程、OpenShell、原生工具、HTTP Authority 和签名 Store 均为真实组件；Skill 内容、请求参数和测试操作员为合成材料。没有模型调用，也未执行智能分析助手日常 API 请求，不能标为完整业务验收。

下一步将同一宿主生命周期能力接入业务 builder/Supervisor，绑定真实执行租约与实际 API 会话，随后验证业务撤权、取消及模型工具调用。已开始动作不因关闭循环而被宣称回滚；完整 OPT-08、后续同候选对照和跨平台任务仍未完成。
