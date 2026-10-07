# OPT-08 D2b：Linux 可信宿主元数据通道

日期：2026-10-07。范围：原生 Skill 管控所需的进程传输组件与离线容器探针。OPT-08 仍为 implementing。本批不代表 Hermes、OpenShell 或日常业务验收完成。

## 设计依据

真实业务镜像的现有 bootstrap 将普通运行凭据放入沙箱文件；这类凭据适合受限决策接口，不能进一步赋予其声明任意 Skill 加载或无 Skill 上下文的能力。本批选择独立的无管理密钥通道：由可信启动器固定真实宿主进程，接收其元数据，再由后续应用协议验证安装、加载与调用事实。

本机内核探针验证了一个关键差别：子进程继承已建立的 Unix socket 后，`SO_PEERCRED` 仍可指向原连接建立者；`SO_PASSCRED` / `SCM_CREDENTIALS` 的逐包凭据则能识别实际发送的子进程。因此接收端必须逐包核对固定 PID/UID，不能只在连接时认证一次。

`ProcessPin` 持有 pidfd，进程退出即失效，不将相同数字 PID 的后来进程视为原宿主。本机 Python 3.13.12 没有 `os.pidfd_open` 包装，但 libc 提供同名函数；按 ADR-056 使用标准库 ctypes 调用，不降级到不可靠的 PID 存在检查。能力缺失或非 Linux 平台明确拒绝。

## 实现

薄传输模块：[native_channel.py](../../adapters/runtime/hermes-agentshield/native_channel.py)。它没有规则、Grant、签名私钥、管理 token 或执行接口，也没有被旧插件自动加载或安装。

- 接收端只创建本用户 0700 私密目录中的精确 socket，不覆盖已有对象；只清理由本次创建且 inode 一致的 socket。
- 每包核验实际 PID/UID 和 pidfd 存活，拒绝截断、额外描述符、非法 JSON、重复字段、非有限数值、错误版本和序号；额外收到的文件描述符立即关闭。
- 每包最多 64 KiB，事件/结果最多 32 个字段。最终工具参数应通过精确摘要绑定，不能把大参数原文当作此元数据协议的默认负载。
- 服务与客户端串行维护序号，进入处理器前消耗序号；响应失败后客户端停止，不自动重试。处理器负责后续应用合同和自身执行期限，socket 超时不冒充处理器取消。
- 客户端路径必须来自可信启动器的受保护挂载。固定 PID 也必须由启动器提供；模型或工具自报 PID、Skill 名称不能注册为可信源。

## 验证证据

| 验证 | 结果与边界 |
| --- | --- |
| Linux 传输最终定向测试 | 31 项通过，在系统 Python 与 API venv 分别运行；真实 socket、内核凭据与进程句柄，非凭据模拟 |
| 权限反例 | 继承已连接描述符的实际工具子进程被拒绝；错误 UID、退出宿主、缺 OS 能力、不安全路径、重复/乱序/超限消息、附加描述符等拒绝 |
| 正常效用 | 合法进程可连续交换；并发回调保持独立响应；恰好 64 KiB 通过、超一字节拒绝；公开响应样例来自实际服务处理 |
| Hermes 适配器回归 | 本批全套 182 项通过；之后细化通道内部串行锁并补充一个并发用例，最终定向 31 项与容器探针再次通过。未将此数字记成已完整运行的 183 项 |
| 合同 | Python 相关合同 292 项通过，包括两个新传输合同及既有合同回归 |
| 固定业务镜像离线容器 | 六项检查全部通过，详见下文；无网络、无模型、无业务资产 |
| 格式 | 定向 Ruff 与 `git diff --check` 通过；本批未改 Go 或前端，不重复声明新的跨 OS 原生通过 |

离线容器使用实际缓存业务镜像 `sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02`，以当前非 root UID 启动其中 Python，关闭网络、移除 capabilities、开启 no-new-privileges 和只读根文件系统，仅挂载本次 socket 目录且只读。宿主固定 Docker 读回的实际进程 PID；普通容器 PID 命名空间中的父进程通过，继承连接的子进程不能冒用父进程身份，挂载不可写，容器退出后 pidfd 失效。

该探针运行的是合成 Python 传输程序，不运行 Hermes 会话或 OpenShell。`hermes_execution=false`、`openshell_execution=false`、`model_calls=0` 明确保存在证据中；不能因此宣称日常 Skill 权限链已生效。探针只删除本次创建并精确记录 ID 的容器。

可复查脚本：[native-host-container-probe.py](../../scripts/personal-experience/native-host-container-probe.py)。脱敏证据和源码摘要：[native-host-channel.json](evidence/optimization-20261007/native-host-channel.json)。原始日志位于本机 `var/optimization-20261007/opt08-channel-*`、`opt08-native-*-probe.*`，不提交。最初探针发现 Python 缺少 pidfd 包装并失败，随后采用 libc 同名接口重新验证；没有将首次失败计为成功。

## 未完成条件

启动器仍须验证准确的业务进程、制品、只读代码和安装，落实 OpenShell 下的精确挂载及生命周期；接入版本化的任务、首次/缓存加载、最终调用事件并连接现有签名上下文/调用存储，再完成 `serve` 与真实业务验收。当前没有开放新的管理创建或执行接口。

此传输不防御 root、具有相关 capabilities、可替换可信代码或注入宿主进程的攻击者；它也不能证明 Skill 加载内容本身可信、业务操作已获授权或已执行。通道验证只是后续 Authority 校验的输入来源约束，不是 Authority 本身。全部适用任务及门禁完成后按用户授权推送远端。
