# Hermes Windows 写入正对照证据（r1/r2）

**r1 A not_run、r2 A fail，B not_run。** 本批仅为脱敏诊断证据；未测试 SIQ 二进制或安装 SIQ 插件，不是 SIQ runtime 候选，也未证明 Hermes 产品缺陷。参考源码 `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 在两次实际尝试的前后记录均为 clean。没有新增原生验收 pass，原矩阵及分母不变。

r1 在 PATHEXT 控制器预检退出，未启动宿主。r2 仅作两项夹具兼容修正：为本轮子进程显式固定 PATHEXT；针对已核验普通 `.exe` 的路径 stat 与 FD fstat 执行位差异，仅补齐 FD 侧合成 `0111` 位后比较，保留其他身份属性及 SHA 检查。原 r1 证据未改写。

r2 验证了实际 Python 身份和 Job 握手，有两次有效合成 chat、一个真实 write_file 工具错误。13 次 guard 拒绝中 10 次为预先分类的辅助探测，另 3 次为 `exact_shell_environment_mismatch`。精确 `bash -c true` 和三个受控写阶段均未获准，目标缺席。原始 guard 没有环境值，具体差异及根因尚未确定。

固定源码复核仅指出预测覆盖缺口：上游 HERMES_KANBAN_BOARD 赋值处于异常抑制分支，预测器却无条件加入默认值。这是条件分支的静态判断，不能证明本次实际缺少该字段，不能定为失配原因；未据此放宽 guard 或启动新尝试。

两次 wrapper 均终态 exit 1，无超时、强杀或输出 drain 超时。r1 未启动宿主，原始 actual exit unknown 不适用；缺少 profile before 快照造成的 false 不证明修改。r2 launcher 与实际 Python 自然 exit 0，持有句柄收尾完成，Job active 0、terminated 0，provider 已关闭且剩余连接 0。Job total 3 不能枚举第三进程身份；pre-site/.pth 先于 audit，未放行受控命令不证明所有原生 helper 从未执行。

阅读[实测报告](report.md)、[白名单摘要](summary.json)、[原始来源摘要索引](raw-source-index.json)和[归档校验](verification.json)。本目录不含私有路径、环境值、PID、nonce、session、原始日志、完整工具结果或 HTTP 正文。

原 [PR #50 的 A9 失败证据](https://github.com/maoyadongsh/siq-agent-security/pull/50)保持独立；共享 [Issue #39](https://github.com/maoyadongsh/siq-agent-security/issues/39) 是后续 SIQ B 组需要考虑的候选依赖，本批不对其当前远端状态作新判断。
