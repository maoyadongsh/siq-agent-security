A04 在 Windows 宿主的 WSL2/Linux 中实际启动了 OpenClaw agent --local，但该次测评失败。Node、namespace 子进程及 Windows 传输均 exit 1；Node 和 namespace 子进程无 timeout，所有自有进程已 wait 回收。Windows 传输原件没有单独 timeout 字段，衍生 JSON 保留 null。

自有合成 provider 已启动，实际连接与请求均为 0，未观察到工具交换；agent_turn_invoked=null 保留未知。网络守卫仅记录 1 条 native-permissions 事件，没有 provider/decision 连接或网络拒绝事件。B 未运行，未观察到 SIQ block。本轮未启动/停止 Gateway，不推断既有 Gateway 的运行状态。

OpenClaw 目标前后均不存在，运行控制哨兵未改。namespace 自身的合成探针文件存在且内容正确，它不是 OpenClaw 工具产生的效果；私有树还保留状态/锁数据库制品，不能写成完全没有文件写入。

私有 /tmp bind、capability 清零及 Node 启动后的安全读回均通过；父 namespace、父 /tmp 元数据、固定源码/Node 摘要保持不变。四组被观察的 capability 均为零，NoNewPrivs 开启；这是读回时刻的证据，不外推整个多线程运行期间。provider 线程已 join，两个自有 socket 已关闭，夹具和原件保留。

CLI 只报告 generic restricted API。本次没有文件系统错误观察器，也没有具体致命 resource 或堆栈；不能套用旧 diag03 的 /tmp 原因。日志追加失败独立记为警告，尚不能确定它是致命原因。WSL 传输 stderr 非空、namespace 子进程 stderr 为空、Node stderr 非空，三个层次分别记录。

summary.derived.json 为白名单衍生件，列出原始 wrapper 字节 SHA、各层存储文本摘要及公开归一化源码标签。解码文本 SHA 不等于未解码进程字节流 SHA。未公开原始日志、完整命令/环境、私有路径、OS 身份、端口、签名或凭据。仅覆盖 A04，原始文件和旧五批公开材料均未改；本结果不构成 Windows 原生 OpenClaw、SIQ 授权链或完整平台旅程通过。
