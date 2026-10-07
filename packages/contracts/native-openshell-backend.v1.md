# 原生 OpenShell 宿主归属核验 v1

本接口供可信宿主启动器构造 RuntimeGuard 使用，替代验收脚本中的临时后端回调。`OpenShellBackend` 只读取本机 rootful Docker 后端，不创建、执行、修改或删除容器，不授予 Agent/Skill 权限。

启动器必须提供完整 64 位容器 ID、固定镜像 digest、OpenShell namespace/sandbox 名、实际宿主运行 PID、容器 init PID、运行 UID/GID、制品 digest 和启动时观察的 cgroup。以上输入来自可信启动流程，不能由工具事件或模型选择。短 ID、布尔 PID、非法标识与超限输入在任何 Docker 调用前拒绝。

实现固定使用 root 拥有且不可由普通用户修改的 `/usr/bin/docker`，显式指定 `unix:///run/docker.sock`，清除继承的 Docker context/host、代理、插件及动态加载环境，工作目录固定为 `/`。本机 socket 必须由 root 拥有且不能 world-writable，其路径不得经符号链接或可写祖先替换。CLI/端点身份变更使已有后端永久失效，不能在新端点继续使用原核验结果。

仅执行固定格式的容器 inspect，单次最长两秒，输出最多 8 KiB，只投影核验字段，不读取容器环境、用户内容或 Provider 配置。核对完整容器 ID、镜像、运行状态、init PID、非 privileged、非 host PID/network 模式、精确 OpenShell namespace/name 和非空 sandbox ID；sandbox ID 在首次核验后固定。再次独立读取真实进程与 init 的 cgroup 和 PID namespace，必须与启动时 cgroup 及彼此一致。

所有失败返回固定类别，并永久使本次后端对象失效；无远端 Docker、rootless、环境覆盖或短 ID 回退。RuntimeGuard 继续负责 pidfd、运行 UID/GID、argv、解释器、代码/安装摘要和挂载边界；本接口不单独构成进程可信或业务授权证据。

部署目前限 Linux rootful Docker OpenShell。其他后端应另立显式合同并提供真实证据，不能放宽本合同来自动兼容。业务 Supervisor 仍负责授权、租约、精确回收和失败处理。
