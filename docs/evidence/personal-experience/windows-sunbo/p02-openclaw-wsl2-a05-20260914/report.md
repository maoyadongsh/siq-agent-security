# A05：A 失败，诊断完成

这次单次实际运行取得终端 stack。Node 约 5.468 秒后 exit 1；namespace child 和 WSL 传输也 exit 1，Windows 外层保留失败码。A=false、diagnostic_completed=true、terminal_stack_marker_observed=true 是三个独立结果，诊断完成没有改写 A 结论。

本批使用上游明确支持的 `OPENCLAW_DEBUG=1` 开关，保留原 Node 权限、网络守卫和合成模型行为。Windows 控制器补充有界输入/进程等待、原始字节捕获和独立 guest 清理确认；其合成子进程测试验证了退出码 7 保留、二进制流一致、进程与输入阻塞超时回收及旧证据拒绝覆盖。

原始 Node stderr 记录 `ERR_ACCESS_DENIED`、`lstatSync`，源码帧为 `dist/openclaw-agent-db-registry-CQNE3K5p.mjs:392:17`。该帧足以定位本次观察到的 API，不能补造其参数。两份运行后源码身份单独收录；不据此宣布缺失目录、具体拒绝路径、修复或新的通过结果，也不倒推 A04。

provider 虽已启动，但请求 0；目标前后不存在，真实工具交换未观察到。namespace setup 的合成写入是环境检查，不是 OpenClaw 工具成功。本批未启动 SIQ 插件/服务或 Gateway、未调用真实模型，B 未运行。

实际读回确认 Node 已回收、provider socket 关闭、provider thread 已 join、未监听的 decision socket 关闭；namespace 已 wait/reap。Windows 传输与 stdin 完整，已 wait/dispose，所有层均无超时或强制终止。Linux 清理由 guest 的精确布尔记录确认，不由 Windows 退出码推断。

19 个冻结文件摘要全部相符。9 项已固定安装源码及 Node/unshare 的收尾摘要一致；control、namespace 哨兵、父 namespace 和父 tmp 元数据保持。这里核对的是固定清单及已保留的运行记录，不声称全安装审计。

WSL 盘点、WSL 主传输、namespace 与 Node 共八条流仅公开长度/SHA。WSL 主传输 stderr 是 132 字节 UTF-16LE，driver 的 UTF-8 replacement 标记被保留；它不同于 2032 字节的 Node stderr。namespace/Node 内嵌原始字节的 base64、长度、SHA、解码及嵌套记录已独立核对，原始正文不进入本目录。

任务背景为干净的 main `b303c6f92392f3a44c306d81ad7323c6291ef4f2`，不冒充已安装 OpenClaw 身份。本批仍为 WSL2/Linux 失败正对照及完成的诊断，不是 Windows 原生平台或 SIQ 通过证据。原 A04 失败、18 行矩阵和分母不变，未包含产品 runtime 修改。

公开文件完整性与交付前敏感信息检查另见 verification.json；检查通过不代表平台验收通过。
