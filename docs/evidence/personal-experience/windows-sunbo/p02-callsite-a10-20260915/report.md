# OpenClaw A10：调用点已关联，宿主 A 仍失败

2026-09-15 在 Windows 上的 WSL2/Linux 环境完成一次新的插桩宿主运行。诊断完成，原错误对象与 `@openclaw/fs-safe` 的 `node_fallback` / `staging` 分支中 `FileHandle.chmod` 表达式关联成立；目标文件仍不存在，原 A 判据未通过。结果见 [summary.json](summary.json)。

| 判定 | 实际结果 |
|---|---|
| 诊断完整 / 调用点关联 | 均为 true |
| 宿主 A / 完整 SIQ A/B | A 未通过；SIQ B 未执行，完整 A/B 未验收 |
| Node CLI、runtime、namespace、Windows wrapper | 均 exit 1；没有 timeout 或 kill |
| 耗时 | Node 命令及收尾 7.023 秒；runtime 7.383 秒；namespace 父控制器 7.936 秒 |
| 实际工具过程 | 暴露 read/write；固定下发一次 write；两次合成 provider 请求 |
| 第二次请求 | 携带失败的工具结果；夹具因预期效果缺席拒绝；未消费成功结果 |
| CLI 读回 | toolSummary：write 调用 1 次、失败 1 次；incomplete_turn / HTTP 400 夹具拒绝 |

cause 一帧 643 bytes，status 一帧 1188 bytes。两个精确源码 hook 各变换一次；最终 observed/matched/recorded 均为 1，无重复或歧义标志。`code=ERR_ACCESS_DENIED`；permission 是 **present 的空字符串**，name/syscall 缺席；resource **未采集**，stack 未读取。[cause.json](cause.json) 与 [status.json](status.json) 保留校验后的帧 JSON body，省略私有帧前缀和绑定值；帧 bytes/SHA 指原私有整帧，不是重排版后 JSON 文件的身份。

Windows 与 guest 的墙钟标签不一致，未建立同步关系；不据此跨钟推断时间顺序、运行耗时或精确时钟偏移。上述各层耗时分别来自本层单调计时，未改系统时钟。

本次采用新的内存插桩身份，保留原宿主参数、权限边界、严格 provider、错误传播和效果判据。没有加载 SIQ 插件或启动 SIQ 服务，没有经过 SIQ 裁决。因此本批归类为当前宿主/Node 与自建 permission 边界的兼容限制，不记为 SIQ 缺陷或产品拒绝；也不构成原生 Windows 或无插桩宿主验收。

独立核验覆盖同一冻结清单的成功 Plan 及退出 1 的 Run、16 条原始流、25 个自有文件及两处缺席路径。workspace 仅剩原 control 文件；22 个安装源码文件与 Node 前后身份一致。Node/namespace 已回收，provider 线程及两类 socket 关闭，Windows 证据根 ACL 未变。网络日志保留 2 条 `UND_ERR_INFO` connect-error，同时有 2 条 connect-success、无 guard-denied；三个 Windows transport stderr 保留原 132 bytes 及解码替换标记，不宣称全部日志无错误。[verification.json](verification.json) 列明核验范围、身份和预算；inventory 与主 transport 分别计时，不承诺同步 OS 调用硬抢占。

关联只证明这一新进程中的精确表达式与相同 Error 对象，不证明内核 syscall、被拒的资源路径或唯一 CALL_ID。A09 的结果支持上述兼容性分类，不能倒推 A08 的历史因果。原 18 项矩阵不变，本批不新增通过数。

停止同类诊断。下一步须先获得独立、干净的标准测试环境或已确认兼容的上游组合，再进行真实宿主 A/B；不得直接删除日常 WSL 的现有 permission 边界来取得通过。
