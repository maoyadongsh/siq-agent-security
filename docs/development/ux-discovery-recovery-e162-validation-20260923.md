# E162 发现故障修复与接入回归

已补齐既有首次接入旅程中的目录故障验收，修复“目录存在但不可读，预览仍接受并标为可扫描”的问题。E161 固定二进制在真实权限故障下复现；修复后同一浏览器流程通过。此项属于 UX-02/03/06 原有要求，不增加新功能。

## 交付

Linux ARM64 更新体验包（本机私有路径：`var/flagship/ux-e162/siq-agent-security-linux-arm64-preview-e162.tar.gz`），继承 E161 后台首次启动和 Hermes 重装修复。包内有中文启动/停止说明和许可证；未签名，不替换原安装，不等于正式发行。

```text
包 SHA-256: 13c9ae5a946252ee9d746f0f8b2e0b05cf7de3da9a5662406d5abe62c1b610e5
程序 SHA-256: 5ea51b1727bef963679340deb661585f3ba9db8640d13ccdbf78df95d1cf0720
```

解压后进入目录：

```bash
export SIQ_AGENT_SECURITY_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/siq-agent-security-preview-e162"
./siq-agent-security setup --confirm-setup --runtime --port 18171 --open-ui
./siq-agent-security pair
```

如端口已被 E161 实例占用，选择另一个空闲端口；不要停止未知服务。两者独立状态，不能称为已安装版本升级验收。退出步骤见包内说明。

## 修复与证据

扫描根预览现在实际只读打开文件/目录，目录最多读一个条目确认可枚举，空目录允许；不读取配置正文或递归扫描。沿用路径限制，检查打开前后对象身份。手动目录预览和提交共用 NormalizeDirectory，不可读时拒绝，页面保留输入供修正。默认不可读位置显示 unreadable，缺失可选配置仍为 missing。

这只说明检查当时的访问状态。扫描仍须逐项检查，不宣称解决同 UID 文件替换 TOCTOU，也没有修改文件权限或跟随符号链接。

| 验证 | 结果 |
| --- | --- |
| 真实后台浏览器故障与恢复 | **9 项通过**，另 **5 项** 服务隔离/清理检查；部分扫描保留可读取 Skill、中文错误、刷新不重复扫描、缺失/符号链接/不可读目录拒绝且保留输入、权限恢复后两项 Skill 可发现、无框架写入 |
| 双框架核心接入回归 | **53 项通过**，另 **7 项** 后台生命周期检查；实际页面/后端及权限撤销链路继续可用 |
| Go 定向 | inventory/server 的 TestPreview/TestDiscovery 通过；包含真实 POSIX 读权限、恢复、缺失配置、符号链接、对象变化与并发扫描拒绝 |
| Go 全量与构建 | **44 包通过**；vet、改动文件 gofmt、diff 检查、脚本 Ruff 通过；Linux ARM64 原生及其余三目标交叉构建通过 |
| 包体 | 93 个内容文件摘要核对，加摘要文件共 94 个；程序与浏览器验收摘要一致，解压程序新状态启动/配对/页面/停止通过 |

本轮真实浏览器无 HTTP mock、无模型调用；只修改本轮临时目录权限，最终恢复后注销自有 systemd runtime 单位并删除夹具，共享 manager 环境不变。E161 的原生框架专项仍为历史证据，本轮没有重复声称执行完整 Hermes/OpenClaw 模型会话。POSIX 权限测试不代替 Windows ACL 原生验收。

复现：

```bash
# 在 apps/agentshield 下：
go test ./internal/inventory ./internal/server -run 'TestPreview|TestDiscovery' -count=1
go test ./...
go vet ./...
# 在仓库根（要求非 root Linux 用户、systemd 用户服务、Playwright）：
python scripts/personal-experience/discovery-recovery-browser-smoke.py --binary /path/to/siq-agent-security --out-dir /new/output
```

## 当前剩余交付条件

正式安装和升级仍要求冻结可审查源码、走既有发行签发及安装验收流程；本轮没有提交、推送、读取发行私钥或发布。未用测试信任根冒充正式签名，也未将旧源码包当作当前变更。

UX-02 的目录权限/部分成功/恢复缺口有了直接证据，但不能因此将全部发现故障场景、完整 UX 任务或原标杆目标标为完成。原任务书中的生产 IAM、业务运行故障恢复、原生 CI、在线业务部署与 SEC-F01–F10 继续保留原顺序和未完成状态。

[规格](discovery-recovery-e162-spec.md) · [证据](../evidence/flagship-optimization-20260921/ux-discovery-recovery-e162.json)
