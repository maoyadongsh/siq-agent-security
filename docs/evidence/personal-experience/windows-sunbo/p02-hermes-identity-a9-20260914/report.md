# Windows Hermes 实际进程身份与工具调用诊断

本批确认了 Windows Hermes venv launcher 与执行 Python 的 PID 不同，并在常规公开 CLI 中重新核验当轮 actual handle、具体 Job、预先固定的映像及 guard 摘要后，成功完成实际 PID 握手。真实宿主随后进入本地合成模型对话，返回了一条 write_file 工具错误；目标文件没有创建。因此 A9 仍为 **fail**，B 未运行。这是测试 guard 拒绝复合 shell 的受控诊断结果，没有证明 SIQ 的拒绝能力或宿主产品缺陷。

| 子批 | 实际入口及结果 | 证据范围 |
| --- | --- | --- |
| identity-only r1 | 同一安装 venv Python，`-S -s -B -c` 显式导入 guard；身份诊断通过，约 12 秒正常退出。 | 未进入 Hermes main；A/B 均未运行。见[独立身份报告](identity-only-r1/report.md)。 |
| native A9 | 已安装 Hermes 公开 `-s -B -m hermes_cli.main chat`，正常 site/.pth 启动；当轮身份释放及一次精确 `bash -c true` 通过，真实工具返回测试 guard 拒绝，A 失败。 | 11 个 loopback 请求中有两次有效 chat SSE 交换；唯一工具结果为 error，目标前后不存在。见[A9 实测报告](native-a9/report.md)。 |

A9 另保留 8 项 provider 元数据探测不被夹具支持的错误，不能归为 SIQ 或 Hermes 生产缺陷。12 项 Popen 拒绝包括辅助版本/健康查询、login snapshot 和写前文件探测；未扩大原有 helper 许可，也未修改 ASLR 或其他系统防护。CLI exit 0 和合成回复文字没有被当作工具成功。两个进程均在 Job 关闭前自然 exit 0，Job active 0；实际句柄、launcher wait、provider 线程和 socket 均有独立收尾证据，未触发超时或强制终止。Job 总计数不用于补齐未单独观测的进程身份。

源码上下文分开记录：identity-only 准备时 checkout 为 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`；A9 使用新干净 main `b303c6f92392f3a44c306d81ad7323c6291ef4f2`，前后 clean，并核对 33 个选定安装源码/程序角色。两轮均未构建或调用 SIQ 二进制；不能把这些上下文改写为同一个安全产品受测候选。执行脚本、计划和来源各自固定 SHA，公开包仅作字段白名单派生，原私有日志与旧 v7/v8 失败未变。磁盘 SHA 不证明内存，选定启动清单不代表完整依赖闭包，Python audit hook 与 Job 也不是 OS 沙箱。

根执行者与独立代理分别重读原始结果、重算来源/输出摘要、握手和事件计数、文件效果及资源收尾；这属于独立证据审阅，并非第二台 Windows 重跑。两组公开包逐字节归档，内层清单、链接、Git 暂存字节与泄密检查另核对；当前 PR 最终 head 的 CI 状态见 PR。没有生产代码、适配器协议或矩阵变更，没有新增原生验收 pass，也不关闭 Windows/N09 或共享 Issue #39/#42/#43。

后续先评审本批已定位的测试限制，再决定受控 helper 和 provider 需要怎样的最小调整；不自动连续重跑 A，也不跳过正对照进入 B。WorkBuddy 独立桌面和共享核心的待办保持原状态。
