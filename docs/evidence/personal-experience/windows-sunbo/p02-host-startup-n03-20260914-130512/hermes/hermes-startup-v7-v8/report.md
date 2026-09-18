# Hermes Windows 公共 CLI 启动诊断 v7–v8

两轮均未完成无 SIQ 的真实写文件对照 A，B 未运行。v7 的真实文件工具错误已回传给本地合成 provider；v8 在到达精确 Bash 回退探针前发生原生访问冲突。两轮目标文件均不存在，不能提升正常执行或 SIQ 服务失联拒绝的验收结论。

入口为已安装 venv 的 `python -m hermes_cli.main chat`，使用未修改的宿主 dispatcher、独立私有 profile 与本地合成 provider。Hermes 0.21.2 来自先前源码库存，不是本次运行 `--version` 的输出。SIQ candidate 和二进制仅核对身份，没有执行 SIQ 二进制、安装插件或运行 B。

## 逐轮结果

| 轮次 | 观测上限 / case 耗时 | 退出与工具结果 | 许可及拒绝 |
|---|---|---|---|
| v7 | 180 秒 / 39.750 秒 | 自然 exit 0；真实工具错误回传；目标不存在 | 精确空设备许可 16 次；Popen 拒绝 19 次；精确 Bash `-c true` 许可 0 次 |
| v8 | 180 秒 / 38.023 秒 | 非超时异常退出 `3221225477`（`0xC0000005`）；没有已记录的 chat POST 或工具结果；目标不存在 | 精确空设备许可 7 次；Popen 拒绝 10 次；精确 Bash `-c true` 许可 0 次 |

case 耗时从 Popen 前开始，包含通信、provider 与 Job 收尾及原始日志处理，不是精确进程生存时间。父 harness 总耗时在 [summary.json](summary.json) 单列。原始报告和 harness SHA 均逐轮保留，旧记录没有覆盖。

v7 已记录的请求列表为 10 个 metadata GET 和 2 个 chat POST；第二个 chat POST 含宿主实际工具错误。v8 列表只有 10 个 metadata GET。两轮均另有 2 个 `AssertionError` 协议错误；harness 的断言可能发生在列表追加前，因此列表不是完整 HTTP 请求总量，也不能用它推导模型调用总数。

v7 新增的唯一子进程许可候选是固定 Git 安装路径的非登录 `bash -c true`，仍要求精确 cwd、隔离环境路径、无 shell 注入变量和本次 Job 握手。实际没有发生许可。v7 三个早退分支和握手条件为 false 的分支没有详细枚举；旧日志对字节类型会做显示转换，并不记录环境，因此不能仅凭显示后的 argv/cwd 判定所有条件均相同。

v8 只增加私有原始 audit 类型及条件匹配布尔，没有放宽许可。其 10 条门槛诊断均止于 command/executable 不匹配，没有到达精确 `true`，未能解释 v7 的不匹配原因。私有 faulthandler 日志记录了 `Windows fatal exception: access violation`，以及 importlib 导入、模型流式调用等待相关栈；具体根因未知，不能归因于 Hermes 产品缺陷、许可规则失败或 SIQ。没有因异常自动重跑。

## 进程收尾及身份边界

两轮都建立了本次独立、无名称的 Windows Job，仅设置 `KILL_ON_JOB_CLOSE` 以管理生命周期。父进程成功分配 Popen 入口进程并用该具体 Job handle 验证成员关系，Job handle 不可继承。两轮查询在清理前和关闭 handle 前均为 active 0、total 3、terminated 0；handle 已关闭。两次主入口 PID 均由 harness wait/reap，随后独立精确 PID 查询未发现它。

Job 的三个进程总数不能证明三个进程的身份，也不能代替逐个后代映像与退出核验。本轮握手 PID 是父 `Popen.pid`；实际执行 Python guard 的 `os.getpid()` 未记录，其是否与入口 PID 相同尚未证明。不能据此断言存在 launcher 转交链，也不能删除 PID 限制或向任意 Job 后代放行。后续诊断需要先记录实际 guard PID/ppid，再由父查询其成员关系和映像。

[summary.json](summary.json) 保留 Git 安装中的 `bin/bash.exe` 与 `usr/bin/bash.exe` 静态摘要和可用的文件版本。`bin/bash.exe` 文件版本为 `2.51.0.windows.1`；`usr/bin/bash.exe` 的 PE 版本字段为空。它们区别于 Hermes Python 入口；静态身份不证明本轮实际启动过 Bash。

## 证据与隐私

公开 JSON 是明确白名单派生：原始报告与 harness SHA、六个选定安装源码文件的前后摘要、进程与 Job 状态、许可计数、协议错误类别、请求列表计数和目标副作用。stdout/stderr 即使为空也保留字节数与 SHA。私有原始路径、完整 argv、调用栈、环境值、握手 nonce、provider 请求内容和源码片段均未直接公开。原始日志仍在 ignored 私有目录，未修改。

主检出保持干净 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`；六个选定宿主源码文件摘要不变。源安装 `.env` 和恢复标记仅查存在性，未读内容。配置审计只证明尝试读取精确新 profile 文件，不证明解析成功或有效值已经应用。

Python audit guard 是测试约束，不是 OS 沙箱；Windows Job 是生命周期管理，不是隔离证明。A 和 B 仍需后续独立证据完成，当前不提升原生验收矩阵。
