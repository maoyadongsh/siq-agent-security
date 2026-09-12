# M66：macOS 显式加载

日期：2026-09-12。候选为 codex/personal-client-upgrade-recovery 基于 main 69d9c59 的本地 M48–M66 增量。规格 §3.11.28；代码 cmd/agentshield/launch_agent_load.go，CLI main.go 已接通。无新增持久合同。

## 行为

launch-agent-load --confirm-load 只加载既有签名源与用户目录精确注册链接。生命周期锁防止产品并发修改；已加载且 XML 归属一致时复用，不占运行服务主 Writer。目标缺席时获取主 Writer 后再查域、列表和源链接，bootstrap 单个精确实例并读回完整配置。命令失败、任务不出现、源/链接改变或异配置均返回错误，保留现场，不自动删除任务或配置。

GUI bootstrap 用法参考 [CircleCI 官方 macOS 安装文档](https://circleci.com/docs/guides/execution-runner/install-machine-runner-3-on-macos/)。这里只采用单个已注册配置的 GUI 域加载用法；未采用文档中的 enable、重启或特权操作。当前没有 macOS 环境，真实 list/list -x/bootstrap 兼容性仍未验证。模板不自动启动，加载命令不宣称保护就绪。

## 验证

- Go vet、全量测试和 CLI race 通过。
- 12 项模拟流程通过：初次加载、运行中复用、Writer 冲突、异配置、查询失败、bootstrap 失败、读回缺席、读回异配置、源内容漂移、链接被替换、加载前任务出现、错误用户域。
- bootstrap 时测试确认主 Writer 被持有；失败后可重新获取 Writer，未知文件保留；运行中复用已有 Writer 不触发 bootstrap。未确认及额外 CLI 参数拒绝。
- gofmt、git diff --check 通过；四目标交叉构建通过。不将模拟控制器和临时 home 验证计为 macOS 原生加载证据。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 924bf8ea57da2f2fb49b4d17874223963cdb970efd681640c180a4dbaaac1165 |
| linux/amd64 | 757c872beba8490d887944b738ce1525bafd41e799d6f58086124a20aad7b0c3 |
| darwin/arm64 | afb5ec4dc0991f832a9c6da6ce661aa4d325a17308b9adf90b820120310044cc |
| windows/amd64 | 5f404eb7652db18f289b5d5220bd7e503dba5928d24271324a2805be17f0835e |

加载成功仅是配置状态；启动、健康确认、退出、升级恢复及实机验收仍待推进。此批不构成 UX-003 完成，个人/LAN 总目标保持进行中。
