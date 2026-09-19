# F04 / D05：E11 修复后候选真实服务复测（2026-09-17）

本批固定 Linux/arm64 二进制 SHA256 `0b16e5e09e6d807b5be732e390c373e6a4354d096b272eba827bddb84a6c8177`，源绑定 `ba8d266ef5ba861282f23a8576be8744d6023118f3f42efd8e1054632ffe06fc`（931 文件）。真实 OpenShell 0.0.83 gateway、独占沙箱 `siq-v6-f04-post-e11-local-20260917`、真实 SIQ daemon 与 E12 浏览器腿执行了 `openshell-o05v6-d05-acceptance.py`。驱动 exit 0；[机器可读矩阵](d05-acceptance-matrix.json)有 238 步：229 pass、8 partial、1 blocked、0 fail。E01–E13 汇总为 9 pass、4 partial（E04、E06、E08、E11），**不等于全部验收通过**。

本次把 E11 持久失败修复后的候选用于真实任务执行和浏览器路径；结果/审计写盘故障仍仅有[组件级故障注入](../v6-f04-e11-durability-20260917/report.md)，未在真实服务对已启动任务注入存储故障，故 E11 保持 partial。E04 的过期 SEC 与缺少必需 Authority、E06 的加载超时与不支持等待的旧 CLI、E08 的远端单任务停止确认仍缺独立实机条件。E12 在同一候选 12 个子检查通过，但不转移到其他 OS 或宿主。

沙箱系本批独占创建，性能复测完成后按精确名称删除；删除退出 0，随后只读列表确认名称消失。共享 gateway 未重启。本批私有 mTLS 副本和原始日志只在忽略的 `preflight-private/` 中，公开证据不含配对码或私钥。此结果只证明本机 Linux 与该固定候选，不替代平台矩阵或发行签名。
