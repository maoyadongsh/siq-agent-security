# Hermes Windows 启动诊断交付包

本包汇总冻结的 v2–v6 r3 与 v7–v8 诊断材料，原子目录逐文件原字节复制。所有轮次 A 都没有完成真实文件写入，B 未运行，无 native pass，也不提升宿主验收矩阵。

- [v2–v6 r3 报告](hermes-startup-v2-v6-r3/report.md) 包含独立 review.json、空设备检查源码与结果。空设备检查使用独立工作区 Python，只证明设备类型，未重放 Hermes。
- [v7–v8 报告](hermes-startup-v7-v8/report.md) 包含严格 helper 候选、私有诊断和 Windows Job 收尾的公开派生；v7 的 Job 记录不能证明实际执行 guard 的 PID 已被识别或独立核实为该 Job 成员。v8 原生访问违例的根因仍 unknown。
- [verification.json](verification.json) 记录所有被复制文件及本报告的长度与 SHA256，并明确复核范围。

诊断时固定的干净 SIQ 检出是 `3cbbd1dcec7eae5691de465de0ea6fbc459243ae`。SIQ runtime candidate `ebc472f2e46aa7de837afe9d6a0ed422eef51cd0`、Windows 二进制 SHA256 `4bc3f5ae95fd00aab528363d5d91e64145e0fd75257904a9f898323de68b6f74` 都仅作身份核对（checked_only），本组没有执行 SIQ 二进制或安装、加载 SIQ 插件。实际运行的是已安装 Hermes 公共 CLI 和未替换的宿主 dispatcher；Hermes 0.21.2 是先前源码库存版本，不是本次 `--version` 输出。

请求数量是各 harness 成功追加的列表条数，不能当作完整 HTTP 流量；v4、v6、v7、v8 均记录了列表追加前可能发生的协议断言错误。计时与退出事实、原始日志摘要和选定宿主源码的前后校验见各子报告，不将正常退出、工具错误或 guard 拒绝换算成 SIQ 成功。

下一步仅为尚未执行的方案：在新独立私有诊断中记录 guard 实际 PID/ppid，由父使用本次具体 Job handle 和实际进程映像核实身份后再评估握手。保留严格 PID 约束，不向任意后代放行，不启用实际文件命令，不开展 B。本包组装期间未再运行宿主。

Python audit guard 是测试约束，Windows Job 用于生命周期管理，两者都不构成 OS 沙箱证明。私有绝对路径、argv、环境值、握手 nonce、原始调用栈与请求内容不进入此包。原始私有材料保持不变，公开派生不代替真实写入对照、服务失联阻断及完整宿主生命周期验收。
