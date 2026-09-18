# OpenClaw WSL2 实机探索证据

本组证据保留 5 项预检成功、3 次未观察到工具调用的旧尝试、1 次纯 namespace 探针成功，以及 1 次新的 A04 失败正对照。没有取得真实 OpenClaw write 工具成功效果；B 未运行，不能登记为 SIQ 断服拒绝或宿主验收通过。受测环境为已有 WSL2 中的 Linux 安装，不是 Windows 原生 OpenClaw。

详细结果分别见 [历史预检与诊断](history/SUMMARY.md) 和 [A04 唯一运行](a04/report.md)。历史目录 5 个公开文件按原字节复制，保留其原清单；新 A04 使用独立原始输出和派生清单，没有改写旧失败。

| 证据范围 | 观察结果 | 可支持的结论 |
| --- | --- | --- |
| 预检 | 5 项退出成功，无 agent turn | 本机安装的 CLI 与指定合成配置预检可执行 |
| 旧 A、diag02、diag03 | 均 exit 1，provider 请求为 0，目标不存在 | 没有观察到真实工具交换；仅 diag03 实际捕获 `fs.existsSync('/tmp')` 拒绝 |
| 纯 namespace 探针 | 新私有 tmp 映射、清能力与合成写入检查成功 | 该单线程探针的隔离准备可用，不代表 OpenClaw 工具成功 |
| A04 | 新 namespace 准备通过；Node exit 1，provider 请求为 0，目标仍不存在 | 正对照未通过；具体受限 API / resource 未记录，不能套用旧诊断归因 |

A04 的网络日志有 1 条守卫初始化权限记录，provider 实际连接和请求为 0。记录显示父 namespace 和原 `/tmp` 元数据不变，自有进程已 wait 回收、provider 线程已 join、套接字已关闭，受测安装文件的收尾摘要一致。本组未加载 SIQ 插件或运行 SIQ 服务，未发送真实模型请求，未启动或停止现有 Gateway。JS 网络守卫仅覆盖指定公开 Node API，不是完整 OS 网络沙箱。

本公开包只包含白名单派生信息；原始包装输出、完整 argv / env、私有路径、身份、PID、namespace ID、inode 与日志仍私有保存。各派生 JSON 标注原始文件 SHA256 和转换方式；已解码文本摘要不冒充原始 stdout 字节摘要。没有改写或重签原始对象。根清单仅对公开文件建立摘要索引，不替代原始证据。
