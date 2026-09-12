# M53：升级与回退的历史程序摘要绑定

日期：2026-09-12。分支 codex/personal-client-upgrade-recovery，基于 main 69d9c59 的本地增量。未提交、未发布。

## 实现

首次产品升级写 local-service-switch/v2，源摘要取自当前 CLI 留存快照，目标摘要取自发行校验通过的暂存程序。复核当前 CLI 路径与 source unit 一致；持生命周期锁后停止前校验源/目标，取得主 Writer 后日志准备前再验，实际 start 前再验目标。既有候选发行验签不取消。

v2 恢复必须提供相同签名绑定并核对目标内容。产品回退要求原 v2 历史摘要，旧路径内容必须匹配原 source；新回退日志交换 source/target 摘要，不回滚状态台账。回退无需损坏的新程序仍完整。旧 v1 日志仍能前滚恢复，不被补写成可信历史程序记录；产品命令拒绝用其发起新回退。

## 验证

- `go vet ./...`、`go test ./...`、CLI/clientrelease 的 race 通过。
- 新正负向测试覆盖：源和目标替换在 stop 前拒绝、stop 后替换不发布 pending、不允许恢复时改摘要、同路径旧程序替换拒绝回退、损坏新程序可回退至完整旧程序、逆向日志保留交换后的绑定。
- Digest 使用已有限额普通文件读取，测试空文件、目录、超大文件、符号链接拒绝及固定 SHA-256 向量。
- `SIQ_TEST_UPGRADE_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m53-build/siq-linux-arm64 go test ./cmd/agentshield -run TestNativeUserServiceUpgrade -count=1 -v`：正常升级 2.01s；启动故障与恢复 2.19s；两项均执行原配置回退和隔离 runtime 注册清理，全部通过。
- 原生正向用同一开发程序的两个路径与测试内容 pin，经真实 systemd 与健康接口；不是正式发行签名正向测试，也不是跨版本验收。正式 CLI 拒绝非发行签名的原负向仍通过。
- 四目标构建通过，不代表 Windows/macOS 实机运行。

| 目标 | SHA-256 |
| --- | --- |
| linux/arm64 | 32acd4b9658b415c85dd7e5ca91bb1ac3f1c71e9cca58791dc61368e1a207ba7 |
| linux/amd64 | 48939178a45064f0ff71e74be33d136cd1e704b84c738f7b8b212215b7b2ce61 |
| darwin/arm64 | 1b847e92b8b67b8fde6b0ec6149e85bd39a5995f8c7967f86f776e109193d690 |
| windows/amd64 | b568a4d8236ff4ce03d4d592f5bbe650dab5b537f39fa9b7d4aa1e8efee317ff |

## 剩余

缺失原路径时尚不从快照自动恢复；正式发行清单与跨版本验证、三系统安装器仍待完成。摘要校验不证明进程内存映像，不抵抗同 UID 持续竞态改写；回退中的 source 摘要是历史绑定，不是损坏程序的新观测。UX-003/014 仍未闭环。
