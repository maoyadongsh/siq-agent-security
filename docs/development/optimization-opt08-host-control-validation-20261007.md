# OPT-08 D3i：跨进程宿主控制与业务消费者

日期：2026-10-07。状态：本批实现与真实协议联验通过；日常业务 API／模型验收未完成，OPT-08 保持 implementing，总体 9/16。

## 实现与边界

按 [native-host-control/v1](../../packages/contracts/native-host-control.v1.md)，新增 HostControl 私有 Unix SOCK_SEQPACKET 控制服务和显式 host_service.py 入口。请求仅允许启动、续期、查询与停止固定会话；监管者 PID 由 SO_PEERCRED 与每包 SCM_CREDENTIALS 交叉核验，不接受 JSON 自报身份。配置、端点对象及凭据固定；fork 借用连接、参数漂移、错误凭据、额外描述符和坏包拒绝。

并发处理器上限4、未关闭会话上限16、历史句柄上限4096。已用句柄不能重新启动，客户端不自动重试启动/续期。业务进程退出或授权心跳过期由 BusinessGuard 拒绝；服务扫尾保留清理未确认状态。关闭共享 Verifier 前必须确认所属会话完成清理。该协议不隔离同 UID 恶意宿主，不批准业务权限，也不替代 Supervisor 的执行租约和容器回收。

业务仓库通过自己的独立客户端消费公开协议，不 import 安全仓库内部实现。四文件提交 `1f55682` 仅含客户端、驻留测评入口、定向测试和说明。既有用户改动保留。测评消费者的业务心跳为合成报告，后续必须改由日常 Supervisor 的真实授权复查产生。

## 验证

| 验证范围 | 结果 | 证明范围 |
| --- | --- | --- |
| HostControl／HostSession／HostLoop | 53 项通过，2 个预期 fork 警告 | 真实子进程、内核 PID、借用连接拒绝、生命周期与跨仓库消费者 |
| 新增配额负向 | 2 项通过 | 第5个并发处理器拒绝、4096个句柄达到上限后拒绝新启动 |
| 业务独立客户端 | 21 项通过 | 真实 Unix 传输配合夹具服务端；错误响应、配置替换、失联等拒绝 |
| 显式服务 CLI | 已包含在相关测试 | 实际子进程启动/终止、所属socket清理，不证明日常部署 |
| 真实 OpenShell 联验 | 18 项权限检查通过 | Reader/Writer、祖先交集、并发隔离、重放、结束后拒绝及三类撤权 |
| 回执与效果 | 18 条签名回执：14 allow、4 deny | 另5次在裁决前拒绝；宿主独立核对文件效果 |
| 跨进程业务控制 | 启动、4次续期、停止通过 | 内核监管者PID与独立业务消费者相同，消费者退出码0 |
| 清理 | 会话、沙箱、网络均通过 | 原网关配置/TLS摘要未变 |

实际运行目录：`var/optimization-20261007/opt08-native-host-control-01`。Go 联验通过，75.262秒。生产源代码在该次运行期间未修改；新增两个配额负向随后执行。运行采用测评宿主内嵌的 HostControl 实现，不能表述为独立服务 CLI 的完整业务部署验收。精确源码、业务提交、原始结果摘要及运行读回见[脱敏证据](evidence/optimization-20261007/native-host-control.json)。

本机 Python 缺少 os.pidfd_open 封装，业务消费者首轮失败后改用 libc 的同一 Linux pidfd 原语并通过21项测试；没有退化为数字PID判断。服务在读包前发现配置漂移可能导致Unix连接复位，负向测试同时接受固定错误或连接复位，并继续断言全部会话被封锁。

仅运行本批相关验证和 Ruff，未重复无关 Go／前端全量。增量配额检查命令为 `pytest -q adapters/runtime/hermes-agentshield/tests/test_host_control.py -k 'handler_budget or used_handle_budget'`。

## 剩余工作

本次模型调用为0，Skill内容与续期操作员为合成材料。下一步将控制客户端接入日常 builder／Supervisor：业务授权及租约复查先于宿主续期，受保护网关就绪及宿主确认先于开放请求，失败不回退未受管运行。真实 API＋模型任务、业务撤权、审批重试和其余验收场景仍需完成。
