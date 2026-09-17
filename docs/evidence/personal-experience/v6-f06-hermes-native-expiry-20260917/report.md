# F06：Linux/Hermes 原文 Grant 自然到期后的原生新调用（2026-09-17）

## 结论与证据等级

本机真实 Hermes Agent v0.21.0 公共 `chat --oneshot`、真实 SIQ 插件钩子与文件工具，使用隔离 `HERMES_HOME`、本地确定性模型 fixture、真实 SIQ daemon 和同一 [E11 后候选](../v6-f06-hermes-post-e11-20260917/candidate.json) `0b16e5e09e6d807b5be732e390c373e6a4354d096b272eba827bddb84a6c8177`。最终到期腿 [17/17](expiry-result-final.json) 与默认 SEC 对照 [11/11](default-control-final.json) 均 `passed=true`、退出码 0；最终脚本 SHA256 `4b266bcc2ce48c6528d647f8b15b0baf6cc005a91ad2ac96e2968c7d03c2777b`，两份报告均绑定此脚本与同一二进制。

在一次原生 Hermes 任务中，先完成允许读取及禁止写入，再以服务端签名的原生会话绑定创建 60 秒、仅限该任务的原文 Grant。随后原生 `read_file` 产生参数和结果两条可经管理员读取核对的原文记录。真实墙钟到期后，运行时凭据请求新的 capture permit 得到 HTTP 410 `raw_task_content_authority_expired`；同一 Hermes 原生任务又完成一次允许的 `read_file`，签名决策仍为 allow，原文记录 ID 集合保持两条不变。四次受控工具调用的回执均与 Hermes 给出的同一 session/task 归属相符，跨任务借用 SEC 仍被拒绝，签名链通过。

公开结果记录了时间顺序：Grant 到期 `2026-09-17T11:47:32.626535+00:00`，过期许可拒绝 `11:47:32.636180+00:00`，到期后原生读取结果 `11:47:32.860640+00:00`。这些值来自同一次最终运行，满足严格的先后比较。Hermes 在同一会话重复读取未改变的文件时会返回 `unchanged` 摘要；脚本因此改用三份不同的合成文件，确保授权期内和到期后两次都真正经过原生读取。前两次失败诊断、一次较早通过但缺少时间/归属公开断言的结果及各轮 console 日志均保存在忽略的 `expiry-private/`，未计入最终通过分母，目录 0700、文件 0600。

验证还包括 `python3 -m py_compile`、`uv run ruff check` 对脚本 exit 0，以及最终默认 SEC 对照 11/11。公开 JSON 不含本机完整路径、凭据或原文；私有日志不进入 `SHA256SUMS`。本批只改测试脚本与证据，没有改产品源码或候选二进制。

## 尚未关闭

这关闭的是 **Linux/Hermes 原文自然到期后的原生新调用** 这一腿，不等于 F06 整体完成。可见桌面通知的人工视觉验收、完整跨功能产品旅程以及 Windows/macOS 各自原生腿仍独立待验。`0b16e5e0…` 未重跑真实 OpenShell 网关 D05、完整浏览器 E12 或排他性能；旧候选结果不能转移给它。测试模型为本地确定性 fixture，不证明付费模型行为或 OS 级隔离。
