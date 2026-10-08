# OPT-08 D3g：OpenShell 宿主归属核验产品化

日期：2026-10-07。状态：本批组件实现与真实联验完成，OPT-08 保持 implementing；本批不改变 9/16 的完整验收计数。

## 接入缺口与实现

此前真实 OpenShell 联验使用验收脚本中的局部 Docker 检查回调。日常业务监管器需要复用正式宿主组件，不能导入验收脚本作为产品依赖。

按 [原生 OpenShell 后端合同](../../packages/contracts/native-openshell-backend.v1.md)，新增 `host_openshell.OpenShellBackend`，供可信启动器传给 RuntimeGuard：

- 完整绑定容器 ID、镜像 digest、OpenShell namespace/name、实际运行 PID、init PID、UID/GID、制品及 cgroup；输入无效时不调用 Docker。
- 固定使用本机 rootful Docker socket 与 root 保护的 CLI；不继承 Docker context/host、代理和动态加载环境，不接受远端端点或任意命令。
- 每次读取固定的 inspect 字段与 `top -eo pid`；核对精确归属、非 privileged、非 host PID/network 模式、实际进程清单、内核 cgroup 和 NSpid 层级。结果不包含容器环境或业务内容。
- CLI/端点替换、镜像/实例变化、进程归属变化、输出异常及命令失败均永久使本次对象失效，不复用上次成功。

组件只核验后端归属。RuntimeGuard 继续逐次验证真实进程、解释器、argv、代码和安装来源，业务 Supervisor 继续负责业务授权与回收。

## 现场发现与修复

第一次联验在初始化阶段拒绝。第二次定向诊断仅采集异常类型和源码行号，定位为非 root 宿主无法读取 root init 的 `/proc/<pid>/ns/pid` inode。两轮均完成拥有的沙箱与网络清理。

调整后的合同明确采用 Docker 进程清单、真实 cgroup、NSpid 层级与运行进程 namespace 联合核对，不在不可读时推测 init namespace 相等。新增回归确认：root init 的 namespace inode 不可读不妨碍合法部署；仅 cgroup 相同、但进程不在 Docker 清单或层级错误时仍拒绝。

第三轮达到原测试夹具的 80 秒整批等待上限，没有形成完整运行通过结果。Go 独立检查通过不等于整批成功。新增逐次进程核验有实际开销，因此减少测试端重复健康轮询，并将该批 23 次工具尝试的总等待上限设为 110 秒；单命令两秒、既有请求超时和运行身份租约均不放宽。

## 验证

- 相关组件阶段检查 63 项通过；补充 root init 不可读回归后，最终后端专项 53 项通过，两批有重叠，不相加。
- 修改的五个 Python 文件 Ruff 与 `git diff --check` 通过。
- 第四轮真实 OpenShell 联验通过：18 项权限检查、18 条签名回执（14 allow、4 deny）、独立文件效果核验、服务线程退出及沙箱/网络清理均通过。另 5 次工具尝试在裁决前拒绝，不列为 deny 回执。原网关配置与 TLS 摘要不变。
- 业务客户端启动 8 项、撤权后取消 2 项 HTTP 检查通过；模型调用为零。Go 联验用时 76.769 秒，单次结果不构成性能基准；逐次 Docker CLI 核验有可见开销。
- 原始运行目录为 `var/optimization-20261007/opt08-native-openshell-backend-01` 至 `-04`，前三批失败记录保留。源码/运行摘要与脱敏结果见 [证据](evidence/optimization-20261007/native-openshell-backend.json)。

## 产品边界与下一步

本组件尚未接入智能分析助手日常 API/Supervisor。宿主 Verifier 当前通过进程内 API 登记，日常监管器跨进程接入仍需要受保护的生命周期交接，不能通过导入兄弟仓库内部代码或复用测试操作者解决。

接下来继续完成业务监管接线、真实 API 会话绑定和模型工具调用，再进行业务授权撤销、过期、升级/漂移及同候选效果验收。研究候选及其他平台不因本组件完成而改变状态。
