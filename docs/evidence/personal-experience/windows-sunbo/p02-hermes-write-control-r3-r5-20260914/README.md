# Hermes Windows 写入对照后续证据（r3/r4/r5）

r5 的 Hermes 纯文本写入 A 正对照通过；r3/r4 仍保留 A=fail。r5 使用明确关闭可选 LSP 的新私有配置。三批 B 均未运行，SIQ 二进制与插件均未调用，不能据此记为完整 P02 或三宿主验收通过。

r1/r2 原件保留在相邻 p02-hermes-write-control-20260914 目录。后续批次使用新的目录、计划、清单和身份，不回写历史失败。

r3 三个环境拒绝的差异均为 missing=0、changed=0、extra=3。三个名称指纹与源码中的 SSL_CERT_FILE、_HERMES_GATEWAY、HERMES_TURN_LEASE_TIMEOUT 对应；gateway/run.py 含相应导入期赋值。普通 chat 的完整实际导入链尚未证明。

r4 在测试夹具中预测固定网关默认值，并向子进程显式传入已校验的安装证书文件；保留 TLS 校验和完整环境精确匹配。原匹配、命令顺序、真实工具与完整目标字节成功条件均未放宽。未知字段仍拒绝；环境原值不记录或公开。

参见 [实测报告与字节数勘误](report.md)、[机器可读摘要](summary.json)、[来源摘要索引](raw-source-index.json)和[归档校验](verification.json)。r4/r5 均有真实工具与完整 34 字节落盘证据；只有 r5 满足整组冻结判据。公开内容不含原始日志、私有路径、PID、nonce、session 或完整工具回执。

Python audit 不覆盖原生 Bash/coreutils 子进程的文件与网络行为；Job 仅管理生命周期。Job total 不能补造其余进程身份，CLI exit 0 或合成模型完成文字不能单独证明真实写入。SIQ B 组及其他平台依赖仍单独跟踪。
