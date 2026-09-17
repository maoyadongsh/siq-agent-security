# Hermes A9：已到真实 write_file，A 对照失败

A9 已通过控制器预检并进入正常 `-s -B -m hermes_cli.main chat`。这轮验证了新的 actual-PID 握手：实际 Python 与 launcher 不同，父持有同一 actual handle 核验当前 Job、预钉映像/guard SHA，并在摘要后复核存活，再发布当轮 actual PID。guard 记录一次安装、一次释放；保留的精确 `bash -c true` 例外真正获准一次。

11 次本地 provider 请求包括 7 GET、4 POST；其中两次有效 chat SSE 交换产生了唯一真实 `write_file` 工具结果：`private fixture guard denied subprocess.Popen`。最后被拒绝的是 ShellFileOperations 的写前目标文件探测复合 shell，不能称为已执行原子写入。目标从未预建，结束时仍不存在；Hermes 自己的 file-mutation verifier 也报告未修改。因此 **A fail，B not_run**；CLI 自然退出 0 和合成模型的完成文字都没有被当成写入成功。

同时保留 8 个合成 provider 错误：6 个不支持的 GET 元数据路径、2 个 `/api/show` POST 探测。它们没有阻止随后两次有效 chat 交换，不应被抹去或全部归因为宿主缺陷。58 个 guard 事件中，12 次 Popen 拒绝分别为 Git revision/tag 元数据 3、Python 版本探测 1、Bash health 2、只读 ASLR 查询 4、login 环境快照 1、写前文件探测 1；这些调用均未获准，ASLR 设置未修改。

actual/launcher 在 Job 关闭前均正常 exit 0，launcher 完成 wait，actual/launcher/Job 句柄关闭，Job active 0、terminated 0。Job total 6 仅是计数，未采集其余 4 个具名身份，不补造进程链。控制器约 38.789 秒、外层约 40.304 秒，无 native/outer 超时、强杀或输出 drain 超时；provider listener 已关闭、线程结束、剩余连接 0，原生栈文件为空。控制器 exit 1 准确保留 A 失败，harness_complete 单独为 true。

独立重算冻结清单 10 payload、33 个安装来源与本次 60 个运行文件；源与 guard、固定 profile、启动结构前后均一致。新根 protected 三 ACE、原父 ACL 不变，并有独立只读读回。原始文件在派生前后摘要不变。详见 [白名单摘要](summary.json) 与 [原始来源摘要索引](raw-source-index.json)。

这是诊断 guard 边界下的真实工具失败，不是 SIQ 离线拒绝或已证明的生产安全缺陷；没有 SIQ 插件/服务，完整 A 用户旅程仍未完成。r1 的 `-S` 显式身份探针保留独立证据，本轮不能重写 v7/v8 历史原因。Python audit hook 不等于 OS 沙箱。公开材料只保留白名单事实与 SHA，省略本机路径、数值 PID、用户名、SID/SDDL、nonce、session ID、私有栈和原始输出。
