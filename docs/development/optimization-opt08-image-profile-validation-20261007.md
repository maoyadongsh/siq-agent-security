# OPT-08 D2h：实际 OpenShell 镜像保护与双向通道

日期：2026-10-07。状态：实际 OpenShell 组件联验通过，OPT-08 仍为 implementing。合同见 [native-runtime-image-profile/v1](../../packages/contracts/native-runtime-image-profile.v1.md)。

## 解决的问题

实际智能分析助手的 OpenShell 0.0.83 镜像以非 root 用户执行，代码和解释器由 root 拥有，文件不允许运行用户写入，但 Docker 根文件系统本身可写。原来的只读 bind-mount 核验不能直接代表这一部署。原业务挂载合同没有为任意安全模块挂载预留入口，本批没有扩大其可接受挂载范围。

新增显式 image profile：可信启动器固定后端沙箱归属、镜像、解释器、启动参数和代码清单；RuntimeGuard 从实际进程根目录逐级 NOFOLLOW 核对 root 所有权、不可由 group/other 写入、稳定 inode 和摘要。Skill 树必须与登记的文件集合一致；宿主安装根与镜像内副本的关联仍需后续真实签名安装校验，不能宣称二者同 inode。

运行进程必须非 root、NoNewPrivs 开启，effective/permitted/ambient capabilities 全零。原只读 bind profile 保持独立，新旧参数混用拒绝。镜像、后端、进程、文件或通道目录核验失败，旧 guard 不再恢复可用。

受信启动代码在容器 `/tmp` 创建独有 0700 目录。宿主从已核验进程根目录打开并固定目录 fd，以 fd 相对路径建立 socket，不额外引入业务挂载。发送方向由宿主逐包核对实际进程 PID/UID 和 pidfd；返回方向由容器核对宿主的内核凭据，当前已验证拓扑中宿主 PID 在容器内显示为 0。容器内同 UID 进程的响应具有非零 PID，因此即使能替换 socket 路径也不能冒充宿主。删除端点仍能造成拒绝服务。

这是当前 Linux 拓扑的显式模式，不能扩展为任意 PID namespace、Windows/macOS 或抵抗 root/内核、可信启动器及同进程代码控制的保证。

## 实际验证

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 双向通道定向测试 | 43 项通过 | 实际 Unix 包凭据、错误 PID/UID/GID、失效后不重试、目录 fd 固定及仅清理自己的 socket |
| 镜像边界定向测试 | 11 项通过 | 根所有权/权限、对象替换、实际符号链接和用户可写祖先拒绝；部分元数据使用明确合成夹具 |
| 新 profile 的真实 OpenShell 探针 | 11 项检查通过 | 独立网关、实际 supervisor/容器进程、代码与 Skill 文件核验、双向跨 namespace 通道、容器内真实伪造服务端拒绝、错误参数和混用 profile 拒绝 |
| 原只读 bind profile 回归 | 21 项检查通过 | 原实际 Docker 进程/挂载/通道正负检查，验证共享 guard 改动没有放宽旧边界 |

OpenShell 探针使用固定业务基础镜像派生的独有本地镜像，新增 root 拥有的探针 bootstrap、通道模块和一个合成 Skill。它运行真实 OpenShell 中的 Python 进程，**没有运行 Hermes 模型任务、真实 Go Authority 或两个业务 Skill**。11 项通过不能表述为日常业务端到端验收。原镜像、日常网关配置、CLI 元数据与 TLS 文件摘要保持不变；临时沙箱删除成功，独有网络确认空后清理。所有模型调用为零。

首次构建发现本机 Docker 旧构建器不支持 `COPY --chmod`，已改为兼容的独有镜像构建指令。失败尝试保留在本地 `opt08-openshell-image-profile-01`，不计为成功；修正后 `02` 为最终成功证据。原始日志和临时密钥仅保留在私有本地目录，不提交。结构化结果、检查列表和源码摘要见 [证据](evidence/optimization-20261007/native-openshell-image-profile.json)。

## 验证命令与剩余工作

```bash
var/mako117-20261006/worktree/apps/control-api/.venv/bin/python -m pytest adapters/runtime/hermes-agentshield/tests/test_native_channel.py -q
var/mako117-20261006/worktree/apps/control-api/.venv/bin/python -m pytest adapters/runtime/hermes-agentshield/tests/test_host_runtime_image.py -q
python patches/hermes/run_openshell_runtime_probe.py --image-profile --output var/optimization-20261007/opt08-openshell-image-profile-02
python patches/hermes/run_runtime_guard_probe.py --output var/optimization-20261007/opt08-image-bind-regression.json
```

修改的 Python 文件 Ruff 与 `git diff --check` 通过。本批未改 Go、前端或共享在线消息 Schema，按用户要求没有重跑这些无关全量测试。下一步把已验证的真实 OpenShell 运行进程、原生 Hermes 生命周期和宿主在线发布接成同一次运行，完成实际签名安装、两个 Skill、拒绝/撤权/漂移和合法业务效果的验收。新身份 HTTP 创建继续关闭；主任务完成数保持 9/16，不把组件检查数量换算成任务完成率。
