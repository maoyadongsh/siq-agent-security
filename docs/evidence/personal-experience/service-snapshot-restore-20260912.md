# M54：回退时明确恢复缺失程序

日期：2026-09-12。分支 codex/personal-client-upgrade-recovery；main 69d9c59 上的本地开发增量。

## 实现与范围

`service-rollback ... --confirm-rollback --restore-missing-binary` 可从当前实例快照恢复缺失的旧程序。原事务须 v2 验签有效，原路径渲染必须匹配 source unit，快照须同时匹配历史摘要和正式发行清单校验。生命周期锁内复验并复制到目标同目录临时文件，fsync/0700 后排他 link 发布，同步父目录。已有文件、符号链接、缺失父目录均不覆盖或自动创建。发布后仍由原回退流程核对身份和健康。

没有新增状态合同；使用 M51 快照目录和 M52 v2 切换日志。原路径文件是已授权恢复例外，范围登记于规格 §3.11.16 与模块 AGENTS.md。临时失败清理，已发布旧程序保留供回退重试；不回滚权限和台账。

## 验证

- Go 全量测试、vet、CLI/clientrelease race 通过；新增负向覆盖无明确恢复选择、错误路径、发行验证失败、损坏快照、已有用户内容、符号链接、缺失父目录及非法摘要。恢复前后内容和 0700 模式验证通过。
- 四目标交叉构建通过。
- `SIQ_TEST_UPGRADE_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m54-build/siq-linux-arm64 go test ./cmd/agentshield -run TestNativeUserServiceUpgrade -count=1 -v`：正常升级与回退 1.96s；故障启动、前滚恢复、删除旧程序、快照恢复、回退启动 2.35s；全部通过，隔离 runtime 单位完成清理。
- 原生正向使用同一开发构建两份路径、合成快照与测试 pin 验证器；正式 CLI 发行根未替换。不能视为正式发行签名正向、跨版本升级或 Windows/macOS 实机验收。

| 开发目标 | SHA-256 |
| --- | --- |
| linux/arm64 | bf24f26cc3f6526c9d9cb57a020873dbef4b41c2c9e53bfacc9301d1e92e1c90 |
| linux/amd64 | 46b1cde2dacb38460881a3dcc8d49f7dd24f411a9258386fc07c34a595bf2463 |
| darwin/arm64 | 3151c2c5534e5627c84032297a66a0d8809f65d92ef62ae24022cabb2808cbab |
| windows/amd64 | 7e7690ae709d1337fd34aea2cb10090bafb250df920b5de921526095dad40cbe |

## 尚未完成

正式发行清单留存/分发、真实不同版本验收、三系统安装与后台生命周期仍未完成。恢复要求原父目录可写且支持硬链接，不提升权限；不声称抵抗同 UID 持续竞态。UX-003/014 保持进行中。
