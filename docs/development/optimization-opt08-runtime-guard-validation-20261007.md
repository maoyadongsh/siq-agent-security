# OPT-08 D2f：实际运行进程与只读挂载核验

日期：2026-10-07。状态：组件联验通过；OPT-08 仍为 implementing，主任务完成数仍为 9/16。

## 实现与作用

新增 `adapters/runtime/hermes-agentshield/host_runtime.py`，实现 [native-runtime-guard/v1](../../packages/contracts/native-runtime-guard.v1.md)。可信启动器提供固定进程、制品、解释器、启动参数和受保护挂载；模型或工具参数不能选择这些对象。

核验器持有 pidfd，逐次读取实际进程的身份、NoNewPrivs、capabilities、命名空间与启动参数摘要；通过进程的真实根目录逐级 NOFOLLOW 打开代码，核对摘要与宿主对象身份。挂载检查使用实际 mountinfo，必须存在精确只读挂载，且没有覆盖子挂载。代码目录的文件集合须与清单一致，拒绝额外文件、无清单文件的目录和符号链接；目录遍历也有条目总预算。任何失败使此核验器失效，即使随后恢复原文件也不能继续使用。

后端核验器仍为必需：它证明进程属于本次拥有的沙箱、运行镜像固定，以及底层解释器/库的保护。本组件只读取事实，不建立 OS 沙箱、不改变挂载、不授予权限，也不声称阻止同 UID 宿主进程。

## 实际验证

`patches/hermes/run_runtime_guard_probe.py` 创建并清理本次独有的离线 Docker 容器，使用固定业务镜像，网络关闭、根文件系统只读、非 root、删除 capabilities、开启 no-new-privileges。仅使用临时合成 Skill 和代码，不启动模型或业务请求。

解释器摘要从固定镜像预先提取；启动参数摘要来自明确的启动配置，不将待验证进程的自报值作为唯一基线。探针后端通过精确容器 ID 核对镜像、真实宿主 PID、用户及保护配置，不使用恒等允许回调。

21 项检查通过：

- 正向：真实进程、代码与只读挂载核验，以及同一进程通过内核凭据通道的实际请求/响应。
- 身份与来源负向：错误启动参数、解释器、组、制品、代码摘要，缺失后端，错误宿主对象和未登记 Skill 挂载均拒绝。
- 完整性负向：新增文件、新增无清单目录、符号链接、代码改变均拒绝；恢复后旧核验器仍拒绝。
- 执行边界负向：进程退出、可写代码挂载和覆盖子挂载均拒绝。最后两个检查刻意让后端不判断挂载属性，由内核事实检查直接拒绝，避免容器 API 的 RW 字段掩盖实现错误。

结构化结果及源码摘要见 [native-runtime-guard.json](evidence/optimization-20261007/native-runtime-guard.json)。探针本机产物位于 `var/optimization-20261007/opt08-runtime-guard.json`，原始运行产物不提交。

```bash
python patches/hermes/run_runtime_guard_probe.py \
  --output var/optimization-20261007/opt08-runtime-guard.json
```

新增两份 Python 文件 Ruff 通过。本批未改动 Go 和既有 Hermes 执行组件，因此不重复其全量测试；此前 D2e 的结果按原批次保留。初次探针准备中修正了临时代码文件的组写权限和覆盖挂载的目标目录，最终使用真实安全配置通过，不放宽核验规则。

## 剩余接线

此次后端为受控 Docker，不能替代 OpenShell 的沙箱归属、Landlock/挂载配置和实际 Hermes 子进程验证。下一步是认证宿主发布与 Go serve 接线，随后接入 OpenShell 启动和智能分析助手日常入口。当前新身份创建仍关闭，未推送，不宣称最终业务或跨平台验收完成。
