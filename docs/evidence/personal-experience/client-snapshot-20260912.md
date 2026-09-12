# M51：升级前当前程序副本留存

2026-09-12，当前 codex/personal-client-upgrade-recovery 未提交工作区，规格 §3.11.14。无新 JSON 合同，持久产物仅为按摘要定位的私有二进制文件。

首次 service-upgrade 在候选验证/暂存后、停止服务前调用 SnapshotCurrent。只复制当前 CLI 的规范化可执行文件，不接受外部快照源参数；流式复制、128 MiB 上限、二次源读取一致性核对、fsync 和排他发布。文件名包含摘要目录，0700；独立 client-snapshots Writer 允许运行中准备。恢复原事务不重新把调用者当作旧版本。

## 验证

- Go 全量/vet、clientrelease/CLI race、四目标构建通过，gofmt 无输出。
- 测试：实际 Go 测试可执行文件的完整副本 SHA-256 相等；原文件删除后副本保留；重复留存一致；主 Writer 持有时允许准备；被修改的既有副本拒绝覆盖；空文件/源 symlink 拒绝。
- client-snapshots 不创建 client-releases，不把本地复制提升为发行验证。本批未用正式发行签名候选执行完整 CLI 升级，因此不新增该范围原生通过声明；M50 的系统生命周期证据保留。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `1fac60e4eca4a835eecc4bfbd303c79bd42155ec2100a0cc6cf2d8832488fefe` |
| siq-linux-amd64 | `a7e696c2c43a6472e77add63f46a86e766738430a0395426322a78a17bd17502` |
| siq-linux-arm64 | `138d04d95ed34dc3d9bd740277219c8f6565f58f2594a08615954f142d78f1a2` |
| siq-windows-amd64 | `a936b9bef0f662360742fa7e924bc5520095a07478560f73110d3264f03cf9ee` |

## 后续边界

本地副本未绑定签名切换日志，不能据此自动推断历史构建或证明 daemon 内存映像与当前路径一致；它不替代回退所需发行清单。缺失原路径的自动恢复和签名历史摘要绑定仍待实现。完整个人/LAN 目标 active，本批未提交/推送。
