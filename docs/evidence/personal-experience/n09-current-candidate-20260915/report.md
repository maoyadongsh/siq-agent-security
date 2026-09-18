# N09 当前候选逐行证据矩阵

日期：2026-09-15。六条 Linux/Hermes、Linux/OpenClaw 证据腿均使用候选二进制
`b6e7650f9ab35f6b259cbd64fe9be5a19347b3689ed3dab0be38874d4bda6708`。矩阵保留 3 平台 × 3 系统 × J1–J11 的完整结构，
只把报告实际执行的检查登记为 coverage，没有任何一行标记为 `complete_acceptance`。

候选从 `apps/agentshield` 以 `go build -trimpath -o <temporary-output> ./cmd/agentshield`
构建；同一源码复建得到相同 SHA256。各旧 runner 只记录完成时间，因此矩阵保守地将该时间同时登记为
leg 起止时间，不据此推导执行时长。

Linux/Hermes 已形成可信 Skill 归属、批准后签名预留执行及本地来源 V1→V2 更新的原生阶段证据。
Linux/OpenClaw 已形成会话级 SEC、配套检查点下的签名预留和真实桌面会话总线通知证据；
OpenClaw 检查点、执行器和操作者的限制仍保留。WorkBuddy、生产公网 Git、完整产品安装/卸载、
通知视觉确认及 Windows/macOS 实机均未由本批覆盖。

校验器通过只说明文件完整性、同一候选约束和声明的逐行 coverage 有效，不能据此宣布 N09 或个人版完成，
也不能提前启动 T01–T06。
