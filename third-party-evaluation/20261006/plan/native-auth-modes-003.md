# 受管 Hermes 认证/不可达模式矩阵：修订预注册 003

继承 [002](native-auth-modes-002.md) 的模式、提议、采集及判据。002 block/control 已完整通过；002 block/auth-denied 已捕获两个真实登记 401、两个拒绝结果、无读写效果，但旧 r04 收尾只接受 grant_unavailable，因真实状态为 revoked 而中断。该批原 execution error、indeterminate 和证据全部保留，不改成通过。

003 全九格统一采用既有 `5470ab3780f2-nativefixturefix2`。与 fix1 的本次相关差异仅为 r04 测试脚本依据 expected_final_identity_status 检查终态；身份撤销组必须为 revoked，其他组仍必须为 grant_unavailable，不笼统接受任一状态。差异见 inventory/candidates/nativefixturefix2/repair.patch。产品二进制继续为 3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5，安装的真实插件源码保持不变。协议冻结脚本与候选源码摘要。

全矩阵以 003 新运行 ID 执行；001/002 是保留的校准尝试，不纳入九格通过率。新模型协议服务保持版本 2。所有组真实读取/写入或拒绝，0 次真实模型推理；同一既有任务块，不增加自然攻击或 S4 独立任务数。
